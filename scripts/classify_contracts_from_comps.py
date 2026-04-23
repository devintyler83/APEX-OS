"""
Populate archetype_code, archetype_confidence, and classification_source
in contract_history for all players with confirmed entries in historical_comps.

Matching:
  1. Normalize both sides (lowercase, strip punctuation/parens/suffixes)
  2. Position-aware (historical_comps.position -> contract_history.position_group)
  3. Exact normalized match -> HIGH confidence
  4. Fuzzy SequenceMatcher >= 0.88 -> HIGH confidence (logged)
  5. WHERE archetype_code IS NULL guard — never overwrites existing classifications

Usage:
    python -m scripts.classify_contracts_from_comps --apply 0   # dry run
    python -m scripts.classify_contracts_from_comps --apply 1   # execute

EXCLUSION_LIST: add bad fuzzy match pairs here after dry run review.
Format: ("historical_comps_normalized_name", "contract_history_normalized_name")
"""

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from draftos.config import PATHS

SEASON_ID = 1
FUZZY_THRESHOLD = 0.88
LOG_PATH = Path("data/exports/classification_unmatched.txt")

# Add bad fuzzy match pairs here after reviewing dry run output.
# Format: ("normalized_comps_name", "normalized_ch_name")
EXCLUSION_LIST: list[tuple[str, str]] = []

# historical_comps.position -> contract_history.position_group(s)
# ILB and OLB both map to LB in contract_history (OTC uses LB umbrella).
# EDGE maps directly. All others are 1:1.
POSITION_MAP: dict[str, list[str]] = {
    "QB":   ["QB"],
    "CB":   ["CB"],
    "EDGE": ["EDGE"],
    "WR":   ["WR"],
    "S":    ["S"],
    "ILB":  ["LB"],
    "OLB":  ["LB"],
    "LB":   ["LB"],
    "IDL":  ["IDL"],
    "OT":   ["OT"],
    "OG":   ["OG"],
    "C":    ["C"],
    "RB":   ["RB"],
    "TE":   ["TE"],
}

_SUFFIX_RE = re.compile(
    r"\b(jr|sr|ii|iii|iv)\b\.?$",
    re.IGNORECASE,
)
_PAREN_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Normalize a player name for comparison."""
    s = name.strip()
    # Strip parenthetical annotations first (e.g., "(CB-5 entry)", "(NFL)")
    s = _PAREN_RE.sub("", s)
    # Lowercase
    s = s.lower()
    # Strip punctuation (periods, apostrophes, hyphens, commas, etc.)
    s = _PUNCT_RE.sub("", s)
    # Strip name suffixes
    s = _SUFFIX_RE.sub("", s).strip()
    # Collapse whitespace
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def is_excluded(norm_comps: str, norm_ch: str) -> bool:
    return (norm_comps, norm_ch) in EXCLUSION_LIST


def load_comps(conn: sqlite3.Connection) -> list[dict]:
    """
    Load all rows from historical_comps ordered by comp_id (ascending).
    Deduplication is handled by the WHERE archetype_code IS NULL guard —
    for a given (player, position_group), the first comp_id match wins.
    """
    rows = conn.execute(
        "SELECT comp_id, player_name, archetype_code, position "
        "FROM historical_comps "
        "ORDER BY comp_id ASC"
    ).fetchall()
    return [
        {
            "comp_id":       r[0],
            "player_name":   r[1],
            "archetype_code": r[2],
            "position":      r[3],
            "norm_name":     normalize(r[1]),
        }
        for r in rows
        if r[1] and r[2] and r[3]  # skip rows with NULL player_name/archetype/position
    ]


def load_ch_players(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """
    Build a lookup: position_group -> list of {norm_name, player, position_group}.
    Only unclassified rows (archetype_code IS NULL) are candidates.
    We also load classified rows so we can report total coverage.
    """
    rows = conn.execute(
        "SELECT DISTINCT player, position_group "
        "FROM contract_history"
    ).fetchall()
    by_pos: dict[str, list[dict]] = defaultdict(list)
    for player, pg in rows:
        by_pos[pg].append({
            "player":         player,
            "norm_name":      normalize(player),
            "position_group": pg,
        })
    return by_pos


def find_match(
    comp: dict,
    ch_by_pos: dict[str, list[dict]],
) -> tuple[str | None, str | None, float | None, str | None]:
    """
    Returns (matched_player, match_type, ratio_or_None, position_group)
    match_type: 'exact' | 'fuzzy' | None
    """
    comp_norm = comp["norm_name"]
    comp_pos  = comp["position"]
    target_pgs = POSITION_MAP.get(comp_pos, [])

    candidates: list[dict] = []
    for pg in target_pgs:
        candidates.extend(ch_by_pos.get(pg, []))

    if not candidates:
        return None, None, None, None

    # Pass 1: exact normalized match
    for cand in candidates:
        if cand["norm_name"] == comp_norm:
            if is_excluded(comp_norm, cand["norm_name"]):
                continue
            return cand["player"], "exact", 1.0, cand["position_group"]

    # Pass 2: fuzzy match
    best_ratio = 0.0
    best_cand  = None
    for cand in candidates:
        r = fuzzy_ratio(comp_norm, cand["norm_name"])
        if r > best_ratio:
            best_ratio = r
            best_cand  = cand
    if best_ratio >= FUZZY_THRESHOLD and best_cand is not None:
        if not is_excluded(comp_norm, best_cand["norm_name"]):
            return best_cand["player"], "fuzzy", best_ratio, best_cand["position_group"]

    return None, None, None, None


UPDATE_SQL = """
UPDATE contract_history
SET archetype_code        = ?,
    archetype_confidence  = 'HIGH',
    classification_source = 'historical_comps'
WHERE player = ?
  AND position_group = ?
  AND archetype_code IS NULL
"""


def count_classified(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM contract_history WHERE archetype_code IS NOT NULL"
    ).fetchone()[0]


def count_total(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM contract_history").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], default=0,
                        help="0=dry run, 1=execute writes")
    args = parser.parse_args()
    apply = bool(args.apply)

    db_path = PATHS.db
    if not db_path.exists():
        print(f"[ERROR] DB not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    comps     = load_comps(conn)
    ch_by_pos = load_ch_players(conn)

    pre_classified = count_classified(conn)
    pre_total      = count_total(conn)

    print(f"[INFO] historical_comps rows loaded : {len(comps)}")
    print(f"[INFO] contract_history total rows  : {pre_total}")
    print(f"[INFO] already classified           : {pre_classified}")
    print()

    exact_matches:   list[dict] = []
    fuzzy_matches:   list[dict] = []
    unmatched:       list[dict] = []
    updates_planned: int        = 0

    for comp in comps:
        matched_player, match_type, ratio, matched_pg = find_match(comp, ch_by_pos)

        if match_type == "exact":
            # Count how many rows would be updated
            n = conn.execute(
                "SELECT COUNT(*) FROM contract_history "
                "WHERE player = ? AND position_group = ? AND archetype_code IS NULL",
                (matched_player, matched_pg),
            ).fetchone()[0]
            exact_matches.append({
                "comp_name":    comp["player_name"],
                "ch_player":    matched_player,
                "archetype":    comp["archetype_code"],
                "position_group": matched_pg,
                "rows":         n,
            })
            updates_planned += n

        elif match_type == "fuzzy":
            n = conn.execute(
                "SELECT COUNT(*) FROM contract_history "
                "WHERE player = ? AND position_group = ? AND archetype_code IS NULL",
                (matched_player, matched_pg),
            ).fetchone()[0]
            fuzzy_matches.append({
                "comp_name":    comp["player_name"],
                "ch_player":    matched_player,
                "archetype":    comp["archetype_code"],
                "position_group": matched_pg,
                "ratio":        ratio,
                "rows":         n,
            })
            updates_planned += n

        else:
            unmatched.append({
                "comp_name":  comp["player_name"],
                "archetype":  comp["archetype_code"],
                "position":   comp["position"],
                "comp_id":    comp["comp_id"],
            })

    # --- Print match plan ---
    print("=== EXACT MATCHES ===")
    for m in exact_matches:
        print(f"  [{m['archetype']:8s}] {m['comp_name']!s:35s} -> {m['ch_player']!s:35s}"
              f" ({m['position_group']}, {m['rows']} rows)")

    print(f"\n=== FUZZY MATCHES (threshold={FUZZY_THRESHOLD}) ===")
    for m in fuzzy_matches:
        print(f"  [{m['archetype']:8s}] {m['comp_name']!s:35s} ~> {m['ch_player']!s:35s}"
              f" ({m['position_group']}, ratio={m['ratio']:.3f}, {m['rows']} rows)")

    print(f"\n=== UNMATCHED ({len(unmatched)}) ===")
    for u in unmatched:
        print(f"  [{u['archetype']:8s}] {u['comp_name']!s:40s} (pos={u['position']}, comp_id={u['comp_id']})")

    # --- Summary table ---
    print("\n" + "=" * 55)
    print(f"  Players attempted              : {len(comps)}")
    print(f"  Exact matches                  : {len(exact_matches)}")
    print(f"  Fuzzy matches                  : {len(fuzzy_matches)}")
    print(f"  Unmatched                      : {len(unmatched)}")
    print(f"  contract_history rows to update: {updates_planned}")
    print("=" * 55)

    # --- Write unmatched log ---
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("CLASSIFICATION UNMATCHED LOG\n")
        f.write(f"historical_comps rows attempted : {len(comps)}\n")
        f.write(f"Exact matches                   : {len(exact_matches)}\n")
        f.write(f"Fuzzy matches                   : {len(fuzzy_matches)}\n")
        f.write(f"Unmatched                       : {len(unmatched)}\n\n")
        f.write("=== UNMATCHED ===\n")
        for u in unmatched:
            f.write(f"[{u['archetype']:8s}] {u['comp_name']:40s} "
                    f"pos={u['position']} comp_id={u['comp_id']}\n")
        f.write("\n=== FUZZY MATCHES (review for false positives) ===\n")
        for m in fuzzy_matches:
            f.write(f"[{m['archetype']:8s}] {m['comp_name']:35s} ~> "
                    f"{m['ch_player']:35s} ratio={m['ratio']:.3f} "
                    f"({m['position_group']}, {m['rows']} rows)\n")
    print(f"\n[LOG] Written to {LOG_PATH}")

    if not apply:
        print("\n[DRY RUN] No writes performed. Re-run with --apply 1 to execute.")
        conn.close()
        return

    # --- Execute updates ---
    rows_updated = 0
    for m in exact_matches + fuzzy_matches:
        conn.execute(UPDATE_SQL, (m["archetype"], m["ch_player"], m["position_group"]))
        rows_updated += conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    conn.close()

    # Re-open to report final state
    conn = sqlite3.connect(db_path)
    post_classified = count_classified(conn)
    conn.close()

    print(f"\n[OK] Rows updated         : {rows_updated}")
    print(f"[OK] Classified before    : {pre_classified}")
    print(f"[OK] Classified after     : {post_classified}")
    print("\n[DONE] Classification pass complete.")


if __name__ == "__main__":
    main()
