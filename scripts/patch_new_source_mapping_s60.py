from __future__ import annotations

# --- sys.path bootstrap ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

"""
patch_new_source_mapping_s60.py
Session 60 — Map unmapped source_players from fantasypros_2026 and drafttek_2026
to canonical prospect IDs.

Problem: conservative patch_name_normalization_2026.py refuses to map when multiple
active prospects share the same name_key (duplicate bootstrap artifacts with __dedup__
school_canonical). Resolution: prefer the prospect with the most existing SPM entries
(i.e., the one other sources already reference). If there's a unique winner with
spm_count > 0, map it. If there are ties at spm_count > 0, skip (ambiguous).
If all candidates have spm_count = 0, use the smallest prospect_id (oldest row).

Source names: fantasypros_2026, drafttek_2026
Idempotent: INSERT OR IGNORE on source_player_map.

Usage:
    python scripts/patch_new_source_mapping_s60.py --apply 0   # dry run
    python scripts/patch_new_source_mapping_s60.py --apply 1   # write
"""

import argparse
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect

SEASON_ID = 1
TARGET_SOURCES = ("fantasypros_2026", "drafttek_2026")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pick_canonical_prospect(
    conn,
    name_key: str,
    source_school: str,
) -> Optional[int]:
    """
    Given a name_key and source school, find the canonical prospect_id.

    Strategy (deterministic):
    1. Get all active (is_active=1) prospects with this name_key.
    2. Score each:
       - spm_count: number of existing source_player_map entries pointing to this pid
       - school_match: 1 if school_canonical matches source_school (case-insensitive), else 0
       - is_dedup: 1 if school_canonical starts with '__dedup_', else 0
    3. Rank: exclude dedup rows first, then sort by spm_count DESC, prospect_id ASC.
    4. If there's a unique winner at the top rank with spm_count > 0, return it.
    5. If all tied at spm_count = 0, return the smallest prospect_id among non-dedup rows
       if there's exactly one school match, else return the smallest pid overall.
    6. If top spm_count > 0 is shared by multiple pids, return None (ambiguous).
    """
    rows = conn.execute("""
        SELECT p.prospect_id, p.school_canonical, p.is_active,
               COUNT(m.source_player_id) AS spm_count
        FROM prospects p
        LEFT JOIN source_player_map m ON m.prospect_id = p.prospect_id
        WHERE p.name_key = ? AND p.is_active = 1
        GROUP BY p.prospect_id
        ORDER BY spm_count DESC, p.prospect_id ASC
    """, (name_key,)).fetchall()

    if not rows:
        return None

    # Separate dedup from real rows
    non_dedup = [r for r in rows if not (r["school_canonical"] or "").startswith("__dedup_")]
    if not non_dedup:
        # All are dedup — just pick smallest pid
        return rows[0]["prospect_id"]

    # Best non-dedup candidate = highest spm_count, then smallest pid
    best = sorted(non_dedup, key=lambda r: (-r["spm_count"], r["prospect_id"]))[0]
    top_spm = best["spm_count"]

    if top_spm > 0:
        # Check if uniquely the best
        tied = [r for r in non_dedup if r["spm_count"] == top_spm]
        if len(tied) == 1:
            return best["prospect_id"]
        else:
            # Multiple non-dedup pids share the top spm_count
            # Try to break tie by school match
            src_school_lower = (source_school or "").strip().lower()
            school_matched = [r for r in tied if (r["school_canonical"] or "").lower() == src_school_lower]
            if len(school_matched) == 1:
                return school_matched[0]["prospect_id"]
            return None  # genuinely ambiguous

    # All non-dedup have spm_count=0 — use school match to prefer, else smallest pid
    src_school_lower = (source_school or "").strip().lower()
    school_matched = [r for r in non_dedup if (r["school_canonical"] or "").lower() == src_school_lower]
    if len(school_matched) == 1:
        return school_matched[0]["prospect_id"]
    elif len(school_matched) > 1:
        # Multiple school matches, pick smallest pid
        return min(r["prospect_id"] for r in school_matched)
    else:
        # No school match — pick smallest pid among all non-dedup
        return min(r["prospect_id"] for r in non_dedup)


def run(apply: bool) -> None:
    conn_ctx = connect()
    conn = conn_ctx.__enter__()
    now = utcnow_iso()

    # Get target source IDs
    source_ids: List[Tuple[str, int]] = []
    for sname in TARGET_SOURCES:
        row = conn.execute("SELECT source_id FROM sources WHERE source_name=?", (sname,)).fetchone()
        if not row:
            print(f"WARN: source not found: {sname}")
            continue
        source_ids.append((sname, int(row["source_id"])))

    if not source_ids:
        print("ERROR: no target sources found. Aborting.")
        conn_ctx.__exit__(None, None, None)
        return

    print(f"Target sources: {[(s, sid) for s, sid in source_ids]}")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN'}\n")

    mapped_new = 0
    already_mapped = 0
    skipped_no_prospect = 0
    skipped_ambiguous = 0
    per_source: dict = {sname: {"new": 0, "existing": 0, "skip": 0} for sname, _ in source_ids}

    for sname, sid in source_ids:
        # Get unmapped source_players for this source
        unmapped = conn.execute("""
            SELECT sp.source_player_id, sp.raw_full_name, sp.raw_school, sp.name_key
            FROM source_players sp
            LEFT JOIN source_player_map m ON m.source_player_id = sp.source_player_id
            WHERE sp.source_id = ? AND sp.season_id = ? AND m.source_player_id IS NULL
              AND sp.name_key IS NOT NULL AND TRIM(sp.name_key) <> ''
        """, (sid, SEASON_ID)).fetchall()

        print(f"{sname}: {len(unmapped)} unmapped source_players to resolve")

        for sp in unmapped:
            sp_id = int(sp["source_player_id"])
            name_key = sp["name_key"]
            school = (sp["raw_school"] or "").strip()

            # Check if already mapped (idempotency)
            existing = conn.execute(
                "SELECT 1 FROM source_player_map WHERE source_player_id=?", (sp_id,)
            ).fetchone()
            if existing:
                already_mapped += 1
                per_source[sname]["existing"] += 1
                continue

            pid = pick_canonical_prospect(conn, name_key, school)

            if pid is None:
                # Check if there are any prospects at all
                any_prospects = conn.execute(
                    "SELECT COUNT(*) FROM prospects WHERE name_key=? AND is_active=1", (name_key,)
                ).fetchone()[0]
                if any_prospects == 0:
                    skipped_no_prospect += 1
                else:
                    skipped_ambiguous += 1
                per_source[sname]["skip"] += 1
                continue

            if apply:
                conn.execute("""
                    INSERT OR IGNORE INTO source_player_map
                        (source_player_id, prospect_id, match_method, match_score, match_notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (sp_id, pid, "patch_new_source_mapping_s60", 0.85, f"auto-mapped Session 60 to canonical pid={pid}"))

            mapped_new += 1
            per_source[sname]["new"] += 1

    if apply:
        conn.commit()

    print()
    print(f"=== PATCH NEW SOURCE MAPPING S60 {'— DRY RUN' if not apply else '— APPLIED'} ===")
    print()
    for sname, _ in source_ids:
        s = per_source[sname]
        print(f"  {sname}: {s['new']} new | {s['existing']} already mapped | {s['skip']} skipped")
    print()
    print(f"  Total new mappings: {mapped_new}")
    print(f"  Already mapped: {already_mapped}")
    print(f"  Skipped (no prospect): {skipped_no_prospect}")
    print(f"  Skipped (ambiguous): {skipped_ambiguous}")

    if not apply:
        print("\nDRY RUN complete. Rerun with --apply 1 to write.")
    else:
        print("\nAPPLY complete.")

    conn_ctx.__exit__(None, None, None)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Map unmapped fantasypros_2026 and drafttek_2026 source_players to canonical prospects."
    )
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
