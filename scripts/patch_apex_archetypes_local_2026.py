"""
patch_apex_archetypes_local_2026.py

Re-matches GEN-* archetype labels in apex_scores to positional archetypes
using the local APEX v2.2 weight tables from prompts.py.

The raw_score, apex_composite, and apex_tier are NOT changed — those were
correctly computed from the trait vectors. Only the archetype classification
fields are updated:
  - matched_archetype
  - archetype_gap
  - gap_label

Algorithm:
  1. Fetch all apex_scores rows where matched_archetype LIKE 'GEN-%'
  2. For each row, load the 8 trait vector scores from the DB
  3. Map position_group -> archetype library (weight tables + archetype names)
  4. For each candidate archetype, compute fit_score using position weights + bumps
  5. Assign highest-scoring archetype; compute gap between rank-1 and rank-2
  6. Compute gap_label per APEX spec
  7. UPDATE only matched_archetype, archetype_gap, gap_label (--apply 1) or report (--apply 0)

No API calls. No network. Fully deterministic.

Usage:
  python -m scripts.patch_apex_archetypes_local_2026 --apply 0   # dry run
  python -m scripts.patch_apex_archetypes_local_2026 --apply 1   # write
"""
from __future__ import annotations

import argparse
import sqlite3
from typing import NamedTuple

from draftos.config import PATHS

SEASON_ID = 1

# ---------------------------------------------------------------------------
# Trait vector order (must match apex_scores column order used in fit scoring)
# Index: 0=processing 1=athleticism 2=scheme_vers 3=comp_tough
#        4=character 5=dev_traj 6=production 7=injury
# ---------------------------------------------------------------------------
TRAIT_COLS = [
    "v_processing",   # 0
    "v_athleticism",  # 1
    "v_scheme_vers",  # 2
    "v_comp_tough",   # 3
    "v_character",    # 4
    "v_dev_traj",     # 5
    "v_production",   # 6
    "v_injury",       # 7
]


# ---------------------------------------------------------------------------
# Weight tables (indexed same as TRAIT_COLS)
# proc / ath / sv / ct / char / dt / prod / inj
# ---------------------------------------------------------------------------

_QB_BASE    = [0.28, 0.10, 0.18, 0.14, 0.08, 0.12, 0.08, 0.02]
_EDGE_BASE  = [0.20, 0.18, 0.13, 0.14, 0.08, 0.12, 0.11, 0.04]
_CB_BASE    = [0.22, 0.20, 0.16, 0.14, 0.08, 0.10, 0.07, 0.03]
_OT_BASE    = [0.20, 0.25, 0.12, 0.18, 0.06, 0.15, 0.03, 0.01]
_S_BASE     = [0.25, 0.18, 0.15, 0.13, 0.10, 0.12, 0.05, 0.02]
_IDL_A      = [0.20, 0.22, 0.12, 0.16, 0.05, 0.08, 0.14, 0.03]  # Disruptor
_IDL_B      = [0.18, 0.16, 0.14, 0.24, 0.05, 0.08, 0.12, 0.03]  # Anchor
_TE_BASE    = [0.22, 0.18, 0.16, 0.13, 0.10, 0.12, 0.07, 0.02]
_ILB_BASE   = [0.25, 0.15, 0.15, 0.13, 0.12, 0.10, 0.08, 0.02]
_OG_BASE    = [0.20, 0.15, 0.14, 0.22, 0.10, 0.12, 0.05, 0.02]
_C_BASE     = [0.28, 0.18, 0.14, 0.16, 0.08, 0.10, 0.04, 0.02]
_OLB_BASE   = [0.20, 0.22, 0.18, 0.15, 0.08, 0.12, 0.03, 0.02]
_RB_BASE    = [0.20, 0.20, 0.06, 0.15, 0.10, 0.12, 0.15, 0.02]
_WR_BASE    = [0.22, 0.18, 0.14, 0.12, 0.07, 0.10, 0.16, 0.01]


def _apply_bump(base: list[float], idx: int, new_val: float) -> list[float]:
    """
    Override base[idx] with new_val and redistribute remaining budget
    proportionally across all other indices so sum stays 1.0.
    """
    old_val = base[idx]
    remaining_budget = 1.0 - new_val
    old_remaining = 1.0 - old_val
    result = list(base)
    result[idx] = new_val
    if old_remaining > 1e-9:
        scale = remaining_budget / old_remaining
        for i in range(len(result)):
            if i != idx:
                result[i] = base[i] * scale
    return result


# Trait column indices for bump targets
_I_PROC = 0
_I_ATH  = 1
_I_CT   = 3
_I_CHAR = 4


def _fit(traits: list[float], weights: list[float]) -> float:
    """raw fit score (0-100 scale) = sum(t*w) * 10"""
    return round(sum(t * w for t, w in zip(traits, weights)) * 10, 4)


# ---------------------------------------------------------------------------
# Archetype library per position
# Each entry: (archetype_label, weight_vector)
# Weight vectors are pre-computed with any archetype-specific bumps applied.
# ---------------------------------------------------------------------------

def _build_qb_library() -> list[tuple[str, list[float]]]:
    # No bumps defined in prompts.py for QB archetypes — all use base
    return [
        ("QB-1 Elite Field General",       _QB_BASE[:]),
        ("QB-2 Dual-Threat Architect",      _QB_BASE[:]),
        ("QB-3 Gunslinger",                 _QB_BASE[:]),
        ("QB-4 Game Manager",               _QB_BASE[:]),
        ("QB-5 Raw Projection",             _QB_BASE[:]),
        ("QB-6 System-Elevated Starter",    _QB_BASE[:]),
    ]


def _build_edge_library() -> list[tuple[str, list[float]]]:
    # No archetype bumps for EDGE
    return [
        ("EDGE-1 Every-Down Disruptor",     _EDGE_BASE[:]),
        ("EDGE-2 Speed-Bend Specialist",    _EDGE_BASE[:]),
        ("EDGE-3 Power-Counter Technician", _EDGE_BASE[:]),
        ("EDGE-4 Athletic Dominator",       _EDGE_BASE[:]),
    ]


def _build_cb_library() -> list[tuple[str, list[float]]]:
    # CB-1/CB-2: Processing bumps to 26%
    _cb12 = _apply_bump(_CB_BASE, _I_PROC, 0.26)
    # CB-3: Athleticism bumps to 28%
    _cb3  = _apply_bump(_CB_BASE, _I_ATH, 0.28)
    # CB-4: base
    # CB-5: Character bumps to 14%
    _cb5  = _apply_bump(_CB_BASE, _I_CHAR, 0.14)
    return [
        ("CB-1 Press-Man Shutdown",  _cb12),
        ("CB-2 Zone Technician",     _cb12),
        ("CB-3 Athletic Freak",      _cb3),
        ("CB-4 Slot Specialist",     _CB_BASE[:]),
        ("CB-5 Raw Projection",      _cb5),
    ]


def _build_ot_library() -> list[tuple[str, list[float]]]:
    # OT-3: Athleticism drops to 20% (from 25%)
    _ot3 = _apply_bump(_OT_BASE, _I_ATH, 0.20)
    return [
        ("OT-1 Elite Athletic Anchor",  _OT_BASE[:]),
        ("OT-2 Technician",             _OT_BASE[:]),
        ("OT-3 Power Mauler",           _ot3),
        ("OT-4 Developmental Athlete",  _OT_BASE[:]),
        ("OT-5 Raw Projection",         _OT_BASE[:]),
    ]


def _build_s_library() -> list[tuple[str, list[float]]]:
    # No bumps for S archetypes
    return [
        ("S-1 Centerfielder",     _S_BASE[:]),
        ("S-2 Box Enforcer",      _S_BASE[:]),
        ("S-3 Multiplier Safety", _S_BASE[:]),
        ("S-4 Coverage Safety",   _S_BASE[:]),
        ("S-5 Raw Projection",    _S_BASE[:]),
    ]


def _build_idl_library(traits: list[float]) -> list[tuple[str, list[float]]]:
    """
    IDL uses two tables (Disruptor A vs. Anchor B).
    Determine family from trait profile: athleticism > comp_tough -> Disruptor.
    """
    ath  = traits[_I_ATH]
    ct   = traits[_I_CT]
    # Disruptor family: DT-1, DT-2, DT-5
    # Anchor family: DT-3, DT-4
    # Note: IDL archetype prefix is DT-
    return [
        ("DT-1 Interior Wrecker",    _IDL_A[:]),
        ("DT-2 Versatile Disruptor", _IDL_A[:]),
        ("DT-3 Two-Gap Anchor",      _IDL_B[:]),
        ("DT-4 Hybrid Disruptor",    _IDL_B[:]),
        ("DT-5 Pass Rush Specialist", _IDL_A[:]),
    ]


def _build_te_library() -> list[tuple[str, list[float]]]:
    # TE-1 Seam Anticipator: Processing bumps to 28%
    _te1 = _apply_bump(_TE_BASE, _I_PROC, 0.28)
    # TE-2 Mismatch Creator: Athleticism bumps to 24%
    _te2 = _apply_bump(_TE_BASE, _I_ATH, 0.24)
    # TE-3/TE-4: CompTough bumps to 16% and 20% respectively
    _te3 = _apply_bump(_TE_BASE, _I_CT, 0.16)
    _te4 = _apply_bump(_TE_BASE, _I_CT, 0.20)
    return [
        ("TE-1 Seam Anticipator",     _te1),
        ("TE-2 Mismatch Creator",     _te2),
        ("TE-3 Dual-Threat Complete", _te3),
        ("TE-4 After-Contact Weapon", _te4),
        ("TE-5 Raw Projection",       _TE_BASE[:]),
    ]


def _build_ilb_library() -> list[tuple[str, list[float]]]:
    # ILB-1 Green Dot: Processing bumps to 28%
    _ilb1 = _apply_bump(_ILB_BASE, _I_PROC, 0.28)
    # ILB-5 Raw Projection: Character bumps to 18%, Processing drops to 20%
    _ilb5 = _apply_bump(_ILB_BASE, _I_CHAR, 0.18)
    _ilb5 = _apply_bump(_ilb5, _I_PROC, 0.20)  # apply second bump on already-adjusted vector
    return [
        ("ILB-1 Green Dot Anchor",   _ilb1),
        ("ILB-2 Coverage Eraser",    _ILB_BASE[:]),
        ("ILB-3 Run-First Enforcer", _ILB_BASE[:]),
        ("ILB-4 Hybrid Chess Piece", _ILB_BASE[:]),
        ("ILB-5 Raw Projection",     _ilb5),
    ]


def _build_og_library() -> list[tuple[str, list[float]]]:
    # OG-1: Processing bumps to 24%
    _og1 = _apply_bump(_OG_BASE, _I_PROC, 0.24)
    return [
        ("OG-1 Complete Interior Anchor", _og1),
        ("OG-2 Power Mauler",             _OG_BASE[:]),
        ("OG-3 Athletic Zone Mauler",     _OG_BASE[:]),
        ("OG-4 Positional Specialist",    _OG_BASE[:]),
        ("OG-5 Raw Projection",           _OG_BASE[:]),
    ]


def _build_c_library() -> list[tuple[str, list[float]]]:
    # No bumps for C archetypes
    return [
        ("C-1 Cerebral Anchor",   _C_BASE[:]),
        ("C-2 Complete Center",   _C_BASE[:]),
        ("C-3 Power Center",      _C_BASE[:]),
        ("C-4 Zone Center",       _C_BASE[:]),
        ("C-5 Projection Center", _C_BASE[:]),
        ("C-6 Guard Convert",     _C_BASE[:]),
    ]


def _build_olb_library() -> list[tuple[str, list[float]]]:
    # No bumps for OLB archetypes
    return [
        ("OLB-1 Speed-Bend Specialist",      _OLB_BASE[:]),
        ("OLB-2 Hand Fighter",               _OLB_BASE[:]),
        ("OLB-3 Hybrid Pass Rush/Coverage",  _OLB_BASE[:]),
        ("OLB-4 Power Bull",                 _OLB_BASE[:]),
        ("OLB-5 Raw Projection",             _OLB_BASE[:]),
    ]


def _build_rb_library() -> list[tuple[str, list[float]]]:
    # RB-1 Elite Workhorse / RB-3 Explosive Playmaker: Athleticism bumps to 25%
    _rb13 = _apply_bump(_RB_BASE, _I_ATH, 0.25)
    # RB-4 Chess Piece: Processing bumps to 25%
    _rb4  = _apply_bump(_RB_BASE, _I_PROC, 0.25)
    return [
        ("RB-1 Elite Workhorse",      _rb13),
        ("RB-2 Receiving Specialist", _RB_BASE[:]),
        ("RB-3 Explosive Playmaker",  _rb13),
        ("RB-4 Chess Piece",          _rb4),
        ("RB-5 Raw Projection",       _RB_BASE[:]),
    ]


def _build_wr_library() -> list[tuple[str, list[float]]]:
    # No bumps for WR archetypes
    return [
        ("WR-1 Route Technician",    _WR_BASE[:]),
        ("WR-2 Vertical Separator",  _WR_BASE[:]),
        ("WR-3 YAC Creator",         _WR_BASE[:]),
        ("WR-4 Jump Ball Specialist", _WR_BASE[:]),
        ("WR-5 Raw Projection",      _WR_BASE[:]),
    ]


def get_library(position_group: str, traits: list[float]) -> list[tuple[str, list[float]]] | None:
    """
    Return archetype library for the given position_group.
    Returns None for positions with no defined library (e.g. ST).
    Falls back:
      LB     -> ILB library
      OL     -> OT library
      DT/IDL -> IDL library
      DE     -> EDGE library
      FS/SS  -> S library
    """
    pos = (position_group or "").upper().strip()
    if pos == "QB":
        return _build_qb_library()
    elif pos in ("EDGE", "DE"):
        return _build_edge_library()
    elif pos == "CB":
        return _build_cb_library()
    elif pos in ("OT", "OL"):
        return _build_ot_library()
    elif pos in ("S", "FS", "SS"):
        return _build_s_library()
    elif pos in ("IDL", "DT", "NT"):
        return _build_idl_library(traits)
    elif pos == "TE":
        return _build_te_library()
    elif pos in ("ILB", "MLB", "LB"):
        return _build_ilb_library()
    elif pos in ("OG", "G"):
        return _build_og_library()
    elif pos in ("C",):
        return _build_c_library()
    elif pos == "OLB":
        return _build_olb_library()
    elif pos == "RB":
        return _build_rb_library()
    elif pos == "WR":
        return _build_wr_library()
    else:
        # No library for position (ST, K, P, etc.)
        return None


def compute_gap_label(gap: float, traits: list[float]) -> str:
    """APEX spec gap flag logic."""
    if gap > 15.0:
        return "CLEAN"
    elif gap >= 8.0:
        return "SOLID"
    elif gap >= 3.0:
        return "TWEENER"
    elif gap >= 1.0 and all(t >= 7.0 for t in traits):
        return "COMPRESSION"
    elif gap >= 1.0:
        return "TWEENER"
    else:
        return "NO_FIT"


def match_archetype(
    traits: list[float],
    position_group: str,
) -> tuple[str, float, str]:
    """
    Run local archetype matching against the position library.

    Returns:
      (matched_archetype, archetype_gap, gap_label)

    Falls back to GEN-0 Unknown if no library is defined.
    """
    library = get_library(position_group, traits)
    if library is None:
        return ("GEN-0 No Library", 0.0, "NO_FIT")

    # Score every archetype.
    # Tiebreaker: prefer first-defined archetype (lower index) when scores are equal.
    # Negative score + index as secondary sort key achieves: highest score, then lowest index.
    scored: list[tuple[float, int, str]] = []
    for i, (arch_name, weights) in enumerate(library):
        s = _fit(traits, weights)
        scored.append((-s, i, arch_name))  # negate score for ascending sort

    scored.sort()  # ascending: highest score first, then earliest-defined wins ties
    best_score  = -scored[0][0]
    best_arch   = scored[0][2]
    second_score = -scored[1][0] if len(scored) > 1 else best_score

    gap = round(best_score - second_score, 4)
    label = compute_gap_label(gap, traits)

    return (best_arch, gap, label)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    db_path = str(PATHS.db)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch all GEN-* rows with trait vectors and position
    cur.execute(f"""
        SELECT
            a.apex_id,
            a.prospect_id,
            p.full_name,
            p.position_group,
            a.matched_archetype,
            a.apex_composite,
            {', '.join('a.' + c for c in TRAIT_COLS)}
        FROM apex_scores a
        JOIN prospects p ON a.prospect_id = p.prospect_id
        WHERE a.matched_archetype LIKE 'GEN-%'
          AND a.season_id = ?
        ORDER BY a.apex_composite DESC
    """, (SEASON_ID,))
    rows = cur.fetchall()
    print(f"GEN-* rows to re-match: {len(rows)}")

    updates: list[tuple[int, str, str, str, float, str]] = []
    # (apex_id, full_name, position, old_arch, gap, gap_label)

    no_library: list[tuple[int, str, str, str]] = []

    for row in rows:
        apex_id    = row["apex_id"]
        full_name  = row["full_name"]
        pos        = row["position_group"] or ""
        old_arch   = row["matched_archetype"]
        traits     = [float(row[c] or 0.0) for c in TRAIT_COLS]

        new_arch, gap, gap_label = match_archetype(traits, pos)

        if new_arch.startswith("GEN-"):
            no_library.append((apex_id, full_name, pos, old_arch))
            continue

        updates.append((apex_id, full_name, pos, old_arch, new_arch, gap, gap_label))

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print(f"\n[ARCHETYPE UPDATES] {len(updates)} prospects will be re-classified")
    for apex_id, name, pos, old, new, gap, label in updates:
        print(f"  apex_id={apex_id:4d}  {name:<35s}  {pos:<5s}  '{old}' -> '{new}'  gap={gap:.1f}  [{label}]")

    if no_library:
        print(f"\n[NO LIBRARY] {len(no_library)} prospects skipped (no positional library):")
        for apex_id, name, pos, old in no_library:
            print(f"  apex_id={apex_id:4d}  {name:<35s}  {pos:<5s}  '{old}' (kept)")

    if not apply:
        print("\n[DRY RUN] No changes written. Pass --apply 1 to commit.")
        conn.close()
        return

    # -----------------------------------------------------------------------
    # Apply
    # -----------------------------------------------------------------------
    updated = 0
    for apex_id, name, pos, old, new_arch, gap, gap_label in updates:
        cur.execute("""
            UPDATE apex_scores
               SET matched_archetype = ?,
                   archetype_gap     = ?,
                   gap_label         = ?
             WHERE apex_id  = ?
               AND season_id = ?
        """, (new_arch, gap, gap_label, apex_id, SEASON_ID))
        updated += cur.rowcount

    conn.commit()
    conn.close()
    print(f"\n[APPLIED] {updated} rows updated.")

    # -----------------------------------------------------------------------
    # Verification
    # -----------------------------------------------------------------------
    print("\n--- Verification ---")
    conn2 = sqlite3.connect(db_path)
    cur2 = conn2.cursor()

    cur2.execute("SELECT COUNT(*) FROM apex_scores WHERE matched_archetype LIKE 'GEN-%'")
    remaining = cur2.fetchone()[0]
    print(f"Remaining GEN-* archetypes: {remaining}")

    cur2.execute("""
        SELECT matched_archetype, COUNT(*) as cnt
        FROM apex_scores
        GROUP BY matched_archetype
        ORDER BY cnt DESC
    """)
    print("\nArchetype distribution:")
    for r in cur2.fetchall():
        print(f"  {r[0]:<40s}  {r[1]}")

    print("\nSpot check — known top prospects:")
    cur2.execute("""
        SELECT p.full_name, p.position_group, a.matched_archetype, a.apex_composite
        FROM apex_scores a
        JOIN prospects p ON a.prospect_id = p.prospect_id
        WHERE p.full_name IN (
            'Caleb Downs', 'Rueben Bain', 'David Bailey',
            'Mansoor Delane', 'Carnell Tate', 'Travis Hunter',
            'Fernando Mendoza', 'Carson Schwesinger'
        )
        ORDER BY a.apex_composite DESC
    """)
    for r in cur2.fetchall():
        print(f"  {r[0]:<35s}  {r[1]:<5s}  {r[2]:<40s}  comp={r[3]}")

    conn2.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-match GEN-* APEX archetypes locally")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1],
                        help="0=dry run, 1=write (default: 0)")
    args = parser.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
