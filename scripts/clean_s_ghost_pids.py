"""
clean_s_ghost_pids.py

Deactivate S-position ghost PIDs (duplicate bootstrap entries for the same player)
and delete any season_id=1 apex_scores rows they carry.

Ghost PIDs are stale bootstrap rows created when early pipeline runs ingested players
under multiple position labels (LB/S/CB) before canonical position was established.
The canonical PID is the is_active=1 row with the correct position_group and higher
consensus coverage. Ghost PIDs are is_active=1 duplicates that must be deactivated.

Categories:
  SCORED_GHOSTS  — ghost pids that have season_id=1 apex_scores: deactivate + delete scores
  UNSCORED_GHOSTS — ghost pids with no apex_scores: deactivate only

Usage:
    python -m scripts.clean_s_ghost_pids --apply 0   # dry run (default)
    python -m scripts.clean_s_ghost_pids --apply 1   # execute
"""

from __future__ import annotations
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.db.connect import connect
from draftos.config import PATHS

import sqlite3 as _sqlite3

# ---------------------------------------------------------------------------
# Ghost PID catalog
# ---------------------------------------------------------------------------
# Format: ghost_pid -> (canonical_pid, display_name, note)
#
# SCORED_GHOSTS: have season_id=1 apex_scores rows — delete scores + deactivate
SCORED_GHOSTS: dict[int, tuple[int, str, str]] = {
    3567: (148,  "Kamari Ramsey",    "S ghost: LB bootstrap duplicate; canonical S pid=148 scored S-3"),
    3570: (182,  "VJ Payne",         "S ghost: LB bootstrap duplicate; canonical S pid=182"),
    3694: (306,  "Bishop Fitzgerald","S ghost: LB bootstrap duplicate; canonical S pid=306"),
    239:  (338,  "Keionte Scott",    "S-5 ghost scored off wrong pid; canonical CB pid=338 (CB-4)"),
}

# UNSCORED_GHOSTS: no apex_scores — deactivate only
# These are LB-label ghost rows for players whose canonical S/CB/EDGE pid was already active.
UNSCORED_GHOSTS: dict[int, tuple[int, str, str]] = {
    2334: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    4559: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    1854: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    2346: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    3792: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    3964: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    4184: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    4331: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    3276: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    3831: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    3997: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    1579: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    1600: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    2395: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    1581: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    1628: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    520:  (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    2742: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    2209: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    492:  (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
    2123: (None, "S ghost (LB label)",  "LB bootstrap ghost — no apex_scores"),
}

ALL_GHOST_PIDS: frozenset[int] = frozenset(SCORED_GHOSTS) | frozenset(UNSCORED_GHOSTS)


def _backup() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src = PATHS.db
    dst = src.parent / f"draftos_pre_clean_s_ghosts_{ts}.sqlite"
    shutil.copy2(src, dst)
    print(f"  Backup: {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean S-position ghost PIDs")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = parser.parse_args()
    apply = bool(args.apply)

    print("=" * 65)
    print("S-POSITION GHOST PID CLEANUP")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 65)

    with connect() as conn:
        conn.row_factory = _sqlite3.Row

        # ------------------------------------------------------------------
        # Step 1: inventory current DB state for all ghost pids
        # ------------------------------------------------------------------
        print("\n[1] Inventorying ghost PIDs ...")

        all_pids = tuple(ALL_GHOST_PIDS)
        placeholders = ",".join("?" * len(all_pids))

        prospect_rows = {
            r["prospect_id"]: r
            for r in conn.execute(
                f"SELECT prospect_id, display_name, position_group, is_active "
                f"FROM prospects WHERE prospect_id IN ({placeholders})",
                all_pids,
            ).fetchall()
        }

        score_rows = {
            r["prospect_id"]: r["cnt"]
            for r in conn.execute(
                f"SELECT prospect_id, COUNT(*) AS cnt FROM apex_scores "
                f"WHERE season_id = 1 AND prospect_id IN ({placeholders}) "
                f"GROUP BY prospect_id",
                all_pids,
            ).fetchall()
        }

        missing_pids = [p for p in ALL_GHOST_PIDS if p not in prospect_rows]
        if missing_pids:
            print(f"  NOTE: {len(missing_pids)} ghost pid(s) not found in prospects table "
                  f"(already cleaned or never existed): {sorted(missing_pids)}")

        print(f"\n  {'pid':<6} {'display_name':<30} {'pos':<6} {'active':<8} {'scores':<8} {'category'}")
        print(f"  {'-'*6} {'-'*30} {'-'*6} {'-'*8} {'-'*8} {'-'*20}")
        for pid in sorted(ALL_GHOST_PIDS):
            if pid not in prospect_rows:
                print(f"  {pid:<6} {'(not in DB)':<30}")
                continue
            r = prospect_rows[pid]
            sc = score_rows.get(pid, 0)
            cat = "SCORED" if pid in SCORED_GHOSTS else "UNSCORED"
            print(
                f"  {pid:<6} {r['display_name']:<30} {r['position_group']:<6} "
                f"{r['is_active']:<8} {sc:<8} {cat}"
            )

        # ------------------------------------------------------------------
        # Step 2: validate — scored ghosts that shouldn't have scores in DB
        # ------------------------------------------------------------------
        print("\n[2] Validating scored ghost apex_scores ...")
        unexpected_scores = {
            pid: cnt for pid, cnt in score_rows.items()
            if pid in UNSCORED_GHOSTS and cnt > 0
        }
        if unexpected_scores:
            print(f"  WARNING: {len(unexpected_scores)} UNSCORED ghost(s) have apex_scores in DB:")
            for pid, cnt in unexpected_scores.items():
                print(f"    pid={pid}  {cnt} rows — should be in SCORED_GHOSTS")
            print("  Continuing — will delete these rows as part of cleanup.")

        # ------------------------------------------------------------------
        # Step 3: count rows to delete / deactivate
        # ------------------------------------------------------------------
        pids_with_scores = set(score_rows.keys())
        pids_to_deactivate = {
            p for p in ALL_GHOST_PIDS
            if p in prospect_rows and prospect_rows[p]["is_active"] == 1
        }
        pids_already_inactive = {
            p for p in ALL_GHOST_PIDS
            if p in prospect_rows and prospect_rows[p]["is_active"] == 0
        }
        total_score_rows = sum(score_rows.values())

        print(f"\n  Pids to deactivate (currently is_active=1): {len(pids_to_deactivate)}")
        print(f"  Pids already inactive (is_active=0):         {len(pids_already_inactive)}")
        print(f"  Pids not found in DB:                        {len(missing_pids)}")
        print(f"  apex_scores rows to delete:                  {total_score_rows}")

        if not pids_to_deactivate and total_score_rows == 0:
            print("\n  Nothing to do — already clean.")
            return

        if not apply:
            print(f"\n[DRY RUN] Would deactivate {len(pids_to_deactivate)} pids and delete {total_score_rows} apex_scores rows.")
            print("Re-run with --apply 1 to execute.")
            return

        # ------------------------------------------------------------------
        # Step 4: backup + execute
        # ------------------------------------------------------------------
        _backup()

        # Delete apex_scores for all ghost pids (scored and any unexpected unscored)
        if pids_with_scores:
            scored_tuple = tuple(pids_with_scores)
            scored_ph = ",".join("?" * len(scored_tuple))
            conn.execute(
                f"DELETE FROM apex_scores WHERE season_id = 1 AND prospect_id IN ({scored_ph})",
                scored_tuple,
            )
            print(f"\n  Deleted {total_score_rows} apex_scores rows for ghost pids.")

        # Deactivate ghost pids
        if pids_to_deactivate:
            deact_tuple = tuple(pids_to_deactivate)
            deact_ph = ",".join("?" * len(deact_tuple))
            conn.execute(
                f"UPDATE prospects SET is_active = 0 WHERE prospect_id IN ({deact_ph})",
                deact_tuple,
            )
            print(f"  Deactivated {len(pids_to_deactivate)} ghost prospect rows.")

        conn.commit()

        # ------------------------------------------------------------------
        # Step 5: verify
        # ------------------------------------------------------------------
        remaining_scores = conn.execute(
            f"SELECT COUNT(*) AS n FROM apex_scores WHERE season_id = 1 AND prospect_id IN ({placeholders})",
            all_pids,
        ).fetchone()["n"]

        still_active = conn.execute(
            f"SELECT COUNT(*) AS n FROM prospects WHERE is_active = 1 AND prospect_id IN ({placeholders})",
            all_pids,
        ).fetchone()["n"]

        ok = remaining_scores == 0 and still_active == 0
        if ok:
            print(f"\n  VERIFY OK: 0 apex_scores rows + 0 active prospects remain for ghost pids.")
        else:
            print(f"\n  VERIFY PARTIAL:")
            if remaining_scores:
                print(f"    apex_scores still present: {remaining_scores} rows")
            if still_active:
                print(f"    prospects still active: {still_active} rows")

        total_s1 = conn.execute(
            "SELECT COUNT(*) AS n FROM apex_scores WHERE season_id = 1"
        ).fetchone()["n"]
        print(f"\n  Total season_id=1 apex_scores remaining: {total_s1}")

    print("\n[DONE]")


if __name__ == "__main__":
    main()
