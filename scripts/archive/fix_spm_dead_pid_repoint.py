"""
fix_spm_dead_pid_repoint.py

Finds source_player_map entries pointing to is_active=0
prospects and re-points them to the correct is_active=1
canonical prospect_id.

Resolution logic (in priority order):
  Rule A: Dead pid has exactly one is_active=1 prospect
          sharing the same name_key + school_canonical
          -> unambiguous, safe to re-point

  Rule B: Dead pid has exactly one is_active=1 prospect
          sharing name_key only (school mismatch or missing)
          -> unambiguous if name_key is sufficiently unique
            (no other is_active=1 prospect shares name_key)

  Rule C: Multiple is_active=1 candidates found
          -> AMBIGUOUS -- log for manual review, do not apply

  Rule D: Zero is_active=1 candidates found
          -> NO CANDIDATE -- log for manual review

Usage:
  python scripts/fix_spm_dead_pid_repoint.py --apply 0
  python scripts/fix_spm_dead_pid_repoint.py --apply 1
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH    = Path(r"C:\DraftOS\data\edge\draftos.sqlite")
BACKUP_DIR = Path(r"C:\DraftOS\data\edge\backups")


def backup_db() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = BACKUP_DIR / f"draftos_pre_spm_repoint_{ts}.sqlite"
    shutil.copy2(DB_PATH, dest)
    return dest


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    apply = bool(args.apply)

    print(f"\n{'='*60}")
    print(f"  fix_spm_dead_pid_repoint.py  |  apply={apply}")
    print(f"{'='*60}\n")

    with connect() as conn:

        # -- Step 1: Find all orphaned mappings ----------------------
        orphans = conn.execute(
            """
            SELECT DISTINCT
                spm.prospect_id          AS dead_pid,
                p.display_name,
                p.name_key,
                p.school_canonical,
                p.position_group         AS dead_pos,
                COUNT(spm.source_player_id) AS spm_count
            FROM source_player_map spm
            JOIN prospects p ON p.prospect_id = spm.prospect_id
            WHERE p.is_active = 0
              AND p.season_id = 1
            GROUP BY spm.prospect_id
            ORDER BY p.display_name
            """
        ).fetchall()

        print(f"  ORPHANED DEAD PIDS: {len(orphans)}")
        if not orphans:
            print("  Nothing to fix. All source_player_map entries point to active prospects.")
            return

        unambiguous  = []   # (dead_pid, canonical_pid, display_name, spm_count, rule)
        ambiguous    = []   # (dead_pid, display_name, spm_count, candidates)
        no_candidate = []   # (dead_pid, display_name, spm_count, reason)

        for row in orphans:
            dead_pid  = int(row["dead_pid"])
            name_key  = row["name_key"] or ""
            school    = row["school_canonical"] or ""
            display   = row["display_name"] or f"pid={dead_pid}"
            spm_count = int(row["spm_count"])

            if not name_key:
                no_candidate.append((dead_pid, display, spm_count, "no_name_key"))
                continue

            # Rule A: name_key + school -> unique active prospect
            if school:
                cands_a = conn.execute(
                    """
                    SELECT prospect_id, display_name, position_group
                    FROM prospects
                    WHERE name_key = ?
                      AND school_canonical = ?
                      AND is_active = 1
                      AND season_id = 1
                    """,
                    (name_key, school),
                ).fetchall()
                if len(cands_a) == 1:
                    unambiguous.append((
                        dead_pid, int(cands_a[0]["prospect_id"]),
                        display, spm_count, "Rule A (name+school)"
                    ))
                    continue
                if len(cands_a) > 1:
                    ambiguous.append((dead_pid, display, spm_count,
                                      [(r["prospect_id"], r["position_group"])
                                       for r in cands_a]))
                    continue

            # Rule B: name_key only -> unique active prospect
            cands_b = conn.execute(
                """
                SELECT prospect_id, display_name, position_group
                FROM prospects
                WHERE name_key = ?
                  AND is_active = 1
                  AND season_id = 1
                """,
                (name_key,),
            ).fetchall()
            if len(cands_b) == 1:
                unambiguous.append((
                    dead_pid, int(cands_b[0]["prospect_id"]),
                    display, spm_count, "Rule B (name only)"
                ))
                continue
            if len(cands_b) > 1:
                ambiguous.append((dead_pid, display, spm_count,
                                  [(r["prospect_id"], r["position_group"])
                                   for r in cands_b]))
                continue

            no_candidate.append((dead_pid, display, spm_count, "no_active_match"))

        # -- Step 2: Report ------------------------------------------
        print(f"\n  UNAMBIGUOUS (safe to re-point): {len(unambiguous)}")
        for dead_pid, canon_pid, name, n, rule in unambiguous:
            print(f"    pid={dead_pid} -> pid={canon_pid}  "
                  f"'{name}'  spm_rows={n}  [{rule}]")

        print(f"\n  AMBIGUOUS (manual review required): {len(ambiguous)}")
        for dead_pid, name, n, cands in ambiguous:
            print(f"    pid={dead_pid}  '{name}'  spm_rows={n}  "
                  f"candidates={cands}")

        print(f"\n  NO CANDIDATE FOUND: {len(no_candidate)}")
        for dead_pid, name, n, reason in no_candidate:
            print(f"    pid={dead_pid}  '{name}'  spm_rows={n}  [{reason}]")

        if not apply:
            print(f"\n  [DRY RUN] No changes made.")
            print(f"  Run --apply 1 to re-point {len(unambiguous)} "
                  f"unambiguous mappings.")
            return

        # -- Step 3: Apply unambiguous re-points ---------------------
        if not unambiguous:
            print("\n  No unambiguous re-points to apply.")
            return

        backup = backup_db()
        print(f"\n  OK: backup created: {backup}")

        repointed = 0
        for dead_pid, canon_pid, name, n, rule in unambiguous:
            rows_to_move = conn.execute(
                """
                SELECT spm.source_player_id
                FROM source_player_map spm
                WHERE spm.prospect_id = ?
                """,
                (dead_pid,),
            ).fetchall()

            for r in rows_to_move:
                spid = int(r["source_player_id"])
                # Check if this source_player_id is already mapped to canon_pid
                existing = conn.execute(
                    """
                    SELECT 1 FROM source_player_map
                    WHERE source_player_id = ? AND prospect_id = ?
                    """,
                    (spid, canon_pid),
                ).fetchone()
                if existing:
                    # Already mapped to canonical — delete the dead duplicate
                    conn.execute(
                        "DELETE FROM source_player_map "
                        "WHERE source_player_id = ? AND prospect_id = ?",
                        (spid, dead_pid),
                    )
                    print(f"    DEDUP-DELETE: spid={spid} already mapped "
                          f"to pid={canon_pid}, removed dead duplicate")
                else:
                    conn.execute(
                        "UPDATE source_player_map SET prospect_id = ? "
                        "WHERE source_player_id = ? AND prospect_id = ?",
                        (canon_pid, spid, dead_pid),
                    )
                repointed += 1

        conn.commit()
        print(f"\n  APPLIED: {repointed} source_player_map rows re-pointed")
        print(f"  SKIPPED AMBIGUOUS: {len(ambiguous)}")
        print(f"  SKIPPED NO CANDIDATE: {len(no_candidate)}")

        # -- Step 4: Final verification -------------------------------
        remaining = conn.execute(
            """
            SELECT COUNT(*) as n
            FROM source_player_map spm
            JOIN prospects p ON p.prospect_id = spm.prospect_id
            WHERE p.is_active = 0
            """
        ).fetchone()["n"]

        print(f"\n  VERIFICATION: orphaned mappings remaining = {remaining}")
        if remaining == 0:
            print("  OK: All source_player_map entries now point to active prospects")
        elif remaining == len(ambiguous) + len(no_candidate):
            print("  OK: Only ambiguous/no-candidate rows remain -- "
                  "manual review required for those")
        else:
            print("  WARNING: Unexpected remaining count -- investigate before "
                  "rebuilding consensus")

    print(f"\n{'='*60}")
    print(f"  {'DONE' if apply else 'DRY RUN COMPLETE'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
