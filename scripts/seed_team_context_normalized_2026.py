"""
scripts/seed_team_context_normalized_2026.py

Seed all five normalized team context tables (Migration 0054) for all 32 NFL teams,
season_id=1 (2026 draft year).

Source of truth
---------------
Reads from team_draft_context (populated by build_team_context_2026.py --apply 1),
which contains 32 rows at context_version='v2.0'.  This script does NOT re-derive
or override any sourced data — it expands the existing JSON-blob columns into the
normalized schema.

Tables written (all idempotent via INSERT OR REPLACE)
------------------------------------------------------
  team_context_snapshots      — one row per team (scheme, capital, FM bias, provenance)
  team_needs_2026             — PREMIUM + SECONDARY needs as ordered rows
  team_depth_pressure_2026    — depth pressure per position group
  team_deployment_traits_2026 — controlled-vocab traits derived from scheme context
  team_context_sources_2026   — source provenance log

Constraints
-----------
- season_id = 1 only.
- Idempotent: re-running is safe (INSERT OR REPLACE throughout).
- Backup before any DB write.
- --apply 0 (dry run, default) / --apply 1 (write).

Usage
-----
    python -m scripts.seed_team_context_normalized_2026 --apply 0   # dry run
    python -m scripts.seed_team_context_normalized_2026 --apply 1   # write

After running, rebuild_team_fit_2026.py --apply 1 will consume v_team_fit_context_2026.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from draftos.config import PATHS
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEASON_ID        = 1
SNAPSHOT_VERSION = "2026.v1"
SOURCE_DATE      = "2026-04-21"
SOURCE_NAME      = "build_team_context_2026.py"
SOURCE_URL       = "nfl.com/news/2026-nfl-draft-every-teams-full-set-of-picks"

# Pressure label → numeric score + starter_quality
_PRESSURE_MAP = {
    "high":   (80, "REPLACEABLE"),
    "medium": (60, "SOLID"),
    "low":    (30, "BLUE"),
}

# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

def _loads(v: str | None, fallback):
    if not v:
        return fallback
    try:
        return json.loads(v)
    except Exception:
        return fallback


def _capital_profile(draft_capital: dict) -> str:
    """Produce a short text summary of pick capital."""
    if not draft_capital:
        return "No early capital"
    parts = []
    for k in sorted(draft_capital.keys()):
        parts.append(f"{k}=#{draft_capital[k]}")
    return ", ".join(parts)


def _fm_bias(fm_sensitivity: dict) -> str | None:
    """Summarize failure_mode_sensitivity as a text field."""
    if not fm_sensitivity:
        return None
    return "; ".join(f"{k}: {v}" for k, v in list(fm_sensitivity.items())[:3])


def _derive_traits(team: dict) -> list[tuple[str, str, str, str | None]]:
    """
    Derive team_deployment_traits_2026 rows from scheme context columns.

    Returns a list of (position_group, trait_code, trait_value, rationale) tuples.
    All derivations are deterministic from the existing team_draft_context columns.

    Trait_code vocabulary:
      EDGE_HAS_WIDE9_ROLE    YES / NO
      EDGE_BASE_FRONT        ODD / EVEN / MULTIPLE
      CB_PRIMARY_COVERAGE    MAN / ZONE / MIXED
      S_SPLIT_FIELD_USAGE    TWO_HIGH_HEAVY / ROTATION_HEAVY
      RB_RUN_SCHEME          WIDE_ZONE / GAP / MIXED
      WR_PRIMARY_USAGE       X_ISOLATION / MOTION_SLOT_HEAVY / VERTICAL_OUTSIDE
      OT_PROTECTION_STYLE    PLAY_ACTION_HEAVY / PURE_DROPBACK_HEAVY
    """
    cov       = (team["coverage_bias"]           or "").lower()
    def_fam   = (team["primary_defense_family"]  or "").lower()
    off_fam   = (team["primary_offense_family"]  or "").lower()
    def_struc = (team["defense_structure"]        or "").lower()
    off_style = (team["offense_style"]            or "").lower()

    traits: list[tuple[str, str, str, str | None]] = []

    # ── CB_PRIMARY_COVERAGE ───────────────────────────────────────────────────
    has_man  = "man" in cov
    has_zone = "zone" in cov
    if has_man and not has_zone:
        cb_cov = "MAN"
    elif has_zone and not has_man:
        cb_cov = "ZONE"
    else:
        cb_cov = "MIXED"
    traits.append(("CB", "CB_PRIMARY_COVERAGE", cb_cov,
                   f"Derived from coverage_bias='{team['coverage_bias']}'"))

    # ── EDGE_BASE_FRONT ───────────────────────────────────────────────────────
    if "3-4" in def_fam or "3-4" in def_struc:
        front = "ODD"
    elif "multiple" in def_fam:
        front = "MULTIPLE"
    else:
        front = "EVEN"
    traits.append(("EDGE", "EDGE_BASE_FRONT", front,
                   f"Derived from primary_defense_family='{team['primary_defense_family']}'"))

    # ── EDGE_HAS_WIDE9_ROLE ───────────────────────────────────────────────────
    # Wide-9 is characteristic of aggressive 4-3 pressure fronts
    wide9 = "YES" if ("pressure" in def_fam and "4-3" in def_struc) else "NO"
    traits.append(("EDGE", "EDGE_HAS_WIDE9_ROLE", wide9,
                   f"Derived from primary_defense_family + defense_structure"))

    # ── S_SPLIT_FIELD_USAGE ───────────────────────────────────────────────────
    if "quarters" in cov or "robber" in cov:
        s_split = "TWO_HIGH_HEAVY"
    else:
        s_split = "ROTATION_HEAVY"
    traits.append(("S", "S_SPLIT_FIELD_USAGE", s_split,
                   f"Derived from coverage_bias='{team['coverage_bias']}'"))

    # ── RB_RUN_SCHEME ─────────────────────────────────────────────────────────
    combined = off_fam + " " + off_style
    if ("gap" in combined or "power" in combined) and "zone" not in combined:
        rb_scheme = "GAP"
    elif "zone" in combined or "rpo" in combined:
        rb_scheme = "WIDE_ZONE"
    else:
        rb_scheme = "MIXED"
    traits.append(("RB", "RB_RUN_SCHEME", rb_scheme,
                   f"Derived from primary_offense_family + offense_style"))

    # ── WR_PRIMARY_USAGE ──────────────────────────────────────────────────────
    if "air_raid" in combined or "spread" in combined:
        wr_usage = "X_ISOLATION" if "air_raid" in combined else "MOTION_SLOT_HEAVY"
    else:
        wr_usage = "MOTION_SLOT_HEAVY"
    traits.append(("WR", "WR_PRIMARY_USAGE", wr_usage,
                   f"Derived from primary_offense_family"))

    # ── OT_PROTECTION_STYLE ───────────────────────────────────────────────────
    if "air_raid" in combined:
        ot_style = "PURE_DROPBACK_HEAVY"
    else:
        ot_style = "PLAY_ACTION_HEAVY"
    traits.append(("OT", "OT_PROTECTION_STYLE", ot_style,
                   f"Derived from primary_offense_family + offense_style"))

    return traits


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def _build_snapshot_row(team: dict, ts: str) -> tuple:
    fm_sens = _loads(team["failure_mode_sensitivity_json"], {})
    cap_dict = _loads(team["draft_capital_json"], {})
    return (
        team["team_id"],
        SEASON_ID,
        SNAPSHOT_VERSION,
        team["scheme_family"],
        None,                          # offensive_coord — not in team_draft_context
        None,                          # defensive_coord — not in team_draft_context
        None,                          # base_personnel — not in team_draft_context
        team["notes"],
        _capital_profile(cap_dict),
        _fm_bias(fm_sens),
        team["source_provenance"],
        ts,
    )


def _build_needs_rows(team: dict) -> list[tuple]:
    team_id = team["team_id"]
    premium   = _loads(team["premium_needs_json"], [])
    secondary = _loads(team["secondary_needs_json"], [])
    rows = []
    for rank, pos in enumerate(premium, start=1):
        rows.append((team_id, SEASON_ID, rank, pos, "PREMIUM", "B", None, None, SOURCE_DATE))
    for rank, pos in enumerate(secondary, start=1):
        rows.append((team_id, SEASON_ID, rank, pos, "SECONDARY", "B", None, None, SOURCE_DATE))
    return rows


def _build_depth_rows(team: dict) -> list[tuple]:
    team_id = team["team_id"]
    pressure_dict = _loads(team["depth_chart_pressure_json"], {})
    rows = []
    for pos_group, label in pressure_dict.items():
        score, quality = _PRESSURE_MAP.get(label.lower(), (30, "UNKNOWN"))
        rows.append((team_id, SEASON_ID, pos_group, score, quality, 0, None, None, SOURCE_DATE))
    return rows


def _build_trait_rows(team: dict) -> list[tuple]:
    team_id = team["team_id"]
    traits = _derive_traits(team)
    return [
        (team_id, SEASON_ID, pos_group, trait_code, trait_value, rationale, None, SOURCE_DATE)
        for pos_group, trait_code, trait_value, rationale in traits
    ]


def _build_source_rows(team: dict, ts: str) -> list[tuple]:
    team_id = team["team_id"]
    return [
        (
            team_id, SEASON_ID,
            SOURCE_NAME, "NEEDS_ARTICLE",
            SOURCE_URL, ts,
            f"build_team_context_2026.py --apply 1; context_version={team['context_version']}",
        ),
    ]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def backup_db() -> Path:
    src     = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst     = out_dir / f"draftos_{ts}_seed_team_normalized.sqlite"
    shutil.copy2(src, dst)
    return dst


def _load_source_teams(conn) -> list[dict]:
    """Read all 32 active rows from team_draft_context (must be populated first)."""
    rows = conn.execute(
        """
        SELECT
            team_id, season_id, team_name,
            primary_offense_family, primary_defense_family,
            coverage_bias, man_rate_tolerance,
            scheme_family, offense_style, defense_structure,
            premium_needs_json, secondary_needs_json,
            depth_chart_pressure_json, draft_capital_json,
            failure_mode_sensitivity_json,
            notes, source_provenance, context_version
        FROM team_draft_context
        WHERE season_id = ? AND is_active = 1
        ORDER BY team_id
        """,
        (SEASON_ID,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _run(apply: bool) -> None:
    with connect() as conn:
        # Verify prerequisites
        source_teams = _load_source_teams(conn)
        if not source_teams:
            print("ERROR: team_draft_context has no active rows for season_id=1.")
            print("Run: python -m scripts.build_team_context_2026 --apply 1")
            sys.exit(1)

        # Verify migration 0054 tables exist
        for tbl in ("team_context_snapshots", "team_needs_2026",
                    "team_depth_pressure_2026", "team_deployment_traits_2026",
                    "team_context_sources_2026"):
            exists = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
            ).fetchone()[0]
            if not exists:
                print(f"ERROR: table '{tbl}' does not exist. "
                      "Run migration 0054_team_context_normalized.sql first.")
                sys.exit(1)

        ts = datetime.now(timezone.utc).isoformat()
        print(f"Mode             : {'APPLY' if apply else 'DRY RUN'}")
        print(f"Season           : season_id={SEASON_ID}")
        print(f"Teams to process : {len(source_teams)}")
        print()

        # Build all rows in memory
        snapshot_rows: list[tuple] = []
        needs_rows:    list[tuple] = []
        depth_rows:    list[tuple] = []
        trait_rows:    list[tuple] = []
        source_rows:   list[tuple] = []

        trait_stats: dict[str, int] = {}

        for team in source_teams:
            tid = team["team_id"]
            snap  = _build_snapshot_row(team, ts)
            needs = _build_needs_rows(team)
            depth = _build_depth_rows(team)
            traits = _build_trait_rows(team)
            srcs  = _build_source_rows(team, ts)

            snapshot_rows.append(snap)
            needs_rows.extend(needs)
            depth_rows.extend(depth)
            trait_rows.extend(traits)
            source_rows.extend(srcs)

            premium = [n[3] for n in needs if n[4] == "PREMIUM"]
            secondary = [n[3] for n in needs if n[4] == "SECONDARY"]
            print(f"  {tid:<4}  premium={premium}  secondary={secondary}"
                  f"  depth_positions={len(depth)}  traits={len(traits)}")

            for _, _, pos, code, val, *_ in traits:
                trait_stats[f"{code}={val}"] = trait_stats.get(f"{code}={val}", 0) + 1

        print()
        print(f"Snapshot rows    : {len(snapshot_rows)}")
        print(f"Needs rows       : {len(needs_rows)}")
        print(f"Depth rows       : {len(depth_rows)}")
        print(f"Trait rows       : {len(trait_rows)}")
        print(f"Source rows      : {len(source_rows)}")
        print()

        # Trait distribution summary
        print("Trait distribution:")
        for code_val, count in sorted(trait_stats.items()):
            print(f"  {code_val:<45} : {count:>2} teams")
        print()

        if not apply:
            print("Dry run complete. No changes written.")
            return

        # Apply
        backup_path = backup_db()
        print(f"Backup : {backup_path}")

        # team_context_snapshots
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_context_snapshots (
                team_id, season_id, snapshot_version, scheme_family,
                offensive_coord, defensive_coord, base_personnel, play_style_notes,
                capital_profile, failure_mode_bias, provenance_note, last_updated_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            snapshot_rows,
        )

        # team_needs_2026
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_needs_2026 (
                team_id, season_id, need_rank, position_code, need_tier,
                confidence, rationale, source_url, source_date
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            needs_rows,
        )

        # team_depth_pressure_2026
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_depth_pressure_2026 (
                team_id, season_id, position_group, pressure_score, starter_quality,
                snaps_blocker_flag, rationale, source_url, source_date
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            depth_rows,
        )

        # team_deployment_traits_2026
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_deployment_traits_2026 (
                team_id, season_id, position_group, trait_code, trait_value,
                rationale, source_url, source_date
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            trait_rows,
        )

        # team_context_sources_2026
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_context_sources_2026 (
                team_id, season_id, source_name, source_type,
                url, fetched_at_utc, notes
            ) VALUES (?,?,?,?,?,?,?)
            """,
            source_rows,
        )

        conn.commit()

        # Verify
        counts = {
            tbl: conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE season_id=?", (SEASON_ID,)
            ).fetchone()[0]
            for tbl in (
                "team_context_snapshots", "team_needs_2026",
                "team_depth_pressure_2026", "team_deployment_traits_2026",
                "team_context_sources_2026",
            )
        }
        for tbl, n in counts.items():
            print(f"  {tbl:<35} : {n} rows")

        # Verify view is accessible
        view_rows = conn.execute(
            "SELECT COUNT(*) FROM v_team_fit_context_2026 WHERE season_id=?", (SEASON_ID,)
        ).fetchone()[0]
        non_null_needs = conn.execute(
            "SELECT COUNT(*) FROM v_team_fit_context_2026 WHERE season_id=? AND needs_json IS NOT NULL",
            (SEASON_ID,)
        ).fetchone()[0]
        non_null_depth = conn.execute(
            "SELECT COUNT(*) FROM v_team_fit_context_2026 WHERE season_id=? AND depth_pressure_json IS NOT NULL",
            (SEASON_ID,)
        ).fetchone()[0]
        print()
        print(f"  v_team_fit_context_2026 rows     : {view_rows}")
        print(f"  Teams with non-null needs_json   : {non_null_needs}")
        print(f"  Teams with non-null depth_json   : {non_null_depth}")
        print()
        print("Apply complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seed normalized team context tables (Migration 0054) "
            "from team_draft_context for season_id=1."
        )
    )
    parser.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="0 = dry run (default), 1 = write to DB",
    )
    args = parser.parse_args()
    _run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
