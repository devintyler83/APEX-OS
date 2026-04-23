"""
purge_non2026_apex_scores.py

Remove season_id=1 apex_scores rows tied to non-2026 draft prospects.

Two categories of violating rows:
  A) Stale "wrong-pid" garbage — scores written to incorrect proxy pids
     before the Session 26 CALIBRATION_OVERRIDES pid corrections were applied.
     These pids were never 2026 prospects; they were placeholder rows that
     happened to exist in the DB when the calibration batch first ran.

  B) Non-2026 calibration artifacts — 2025/2024 draftees that were
     deliberately scored as reference anchors but must not appear in the
     2026 scoring universe per the S110 hard boundary rule.

All 16 target prospects are already is_active=0; no deactivation step needed.
Group D (2026 calibration artifacts: Schwesinger, Ratledge, Membou, Emmanwori,
Ezeiruaku, Wilson, Paul, Stukes) are 2026 class and are NOT touched.

Usage:
    python -m scripts.purge_non2026_apex_scores --apply 0   # dry run (default)
    python -m scripts.purge_non2026_apex_scores --apply 1   # execute
"""

from __future__ import annotations
import argparse
import sys
import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.db.connect import connect
from draftos.config import PATHS

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

# Group A — stale wrong-pid rows (scores written to placeholder pids before
# Session 26 CALIBRATION_OVERRIDES corrections).  These pids are real DB rows
# for NFL veterans or other non-2026 people who happened to collide in the
# bootstrap ingest.
GROUP_A: dict[int, str] = {
    813:  "Tyler Allgeier (was wrong pid for Shedeur Sanders)",
    885:  "Travis Kelce (was wrong pid for Travis Hunter)",
    838:  "Kaimi Fairbairn (was wrong pid for Trevor Etienne)",
    1717: "Danny Striggow (was wrong pid for Armand Membou)",
    1254: "Logan Webb (was wrong pid for Tate Ratledge)",
    838:  "Kaimi Fairbairn (was wrong pid for Trevor Etienne)",
    1591: "Jordan Clark (was wrong pid for Nick Emmanwori)",
    1405: "Tj Sanders (was wrong pid for Tyleik Williams)",
    916:  "Demario Douglas (was wrong pid for Chris Paul Jr.)",
    1736: "Ethan Downs (was wrong pid for Jared Wilson)",
    450:  "Jason Marshall ghost (pre-S26 residual)",
    842:  "Younghoe Koo / Helm ghost (pre-S26 residual)",
}

# Group B — non-2026 draftees scored as calibration reference anchors.
# Gunnar Helm (pid=313) was already removed from CALIBRATION_OVERRIDES in a
# prior session but the apex_scores row was never cleaned up.
GROUP_B: dict[int, str] = {
    455:  "Travis Hunter (2025 draftee, CB/WR, Colorado)",
    230:  "Shedeur Sanders (2025 draftee, QB, Colorado)",
    304:  "Trevor Etienne (2024 draftee, RB, Georgia)",
    1050: "Tyleik Williams (2025 draftee, IDL, Ohio State)",
    313:  "Gunnar Helm (2025 draftee ghost, TE — already removed from CALIBRATION_OVERRIDES)",
}

ALL_TARGET_PIDS: frozenset[int] = frozenset(GROUP_A) | frozenset(GROUP_B)


def _backup(apply: bool) -> None:
    if not apply:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src = PATHS.db
    dst = src.parent / f"draftos_pre_purge_non2026_{ts}.sqlite"
    shutil.copy2(src, dst)
    print(f"  Backup: {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge non-2026 apex_scores rows")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = parser.parse_args()
    apply = bool(args.apply)

    import sqlite3 as _sqlite3

    print("=" * 60)
    print("NON-2026 APEX_SCORES PURGE")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 60)

    with connect() as conn:
        conn.row_factory = _sqlite3.Row

        # ------------------------------------------------------------------
        # Step 1: verify all target pids are is_active=0
        # ------------------------------------------------------------------
        print("\n[1] Verifying target prospects are inactive ...")
        rows = conn.execute(
            f"SELECT prospect_id, display_name, is_active FROM prospects "
            f"WHERE prospect_id IN ({','.join('?' for _ in ALL_TARGET_PIDS)})",
            tuple(ALL_TARGET_PIDS),
        ).fetchall()

        active_found = [r for r in rows if r["is_active"] == 1]
        if active_found:
            print("  ERROR: these target pids are still is_active=1:")
            for r in active_found:
                print(f"    pid={r['prospect_id']}  {r['display_name']}")
            print("  Aborting — deactivate these rows first.")
            sys.exit(1)

        print(f"  OK: all {len(ALL_TARGET_PIDS)} target pids are is_active=0")

        # ------------------------------------------------------------------
        # Step 2: count apex_scores rows to be deleted
        # ------------------------------------------------------------------
        print("\n[2] Counting season_id=1 apex_scores rows to delete ...")

        pid_list = tuple(ALL_TARGET_PIDS)
        placeholders = ",".join("?" for _ in pid_list)

        score_rows = conn.execute(
            f"""
            SELECT s.prospect_id, p.display_name, s.is_calibration_artifact,
                   s.matched_archetype, s.scored_at
            FROM apex_scores s
            JOIN prospects p ON p.prospect_id = s.prospect_id
            WHERE s.season_id = 1
              AND s.prospect_id IN ({placeholders})
            ORDER BY s.prospect_id, s.scored_at
            """,
            pid_list,
        ).fetchall()

        print(f"\n  apex_scores rows to delete: {len(score_rows)}")
        print()
        print(f"  {'pid':<6} {'display_name':<30} {'cal':<4} {'archetype':<40} {'scored_at'}")
        print(f"  {'-'*6} {'-'*30} {'-'*4} {'-'*40} {'-'*24}")
        for r in score_rows:
            group = "B" if r["prospect_id"] in GROUP_B else "A"
            print(
                f"  [{group}] "
                f"{r['prospect_id']:<6} {r['display_name']:<30} "
                f"{'Y' if r['is_calibration_artifact'] else 'N':<4} "
                f"{(r['matched_archetype'] or ''):<40} {r['scored_at']}"
            )

        if not score_rows:
            print("  Nothing to delete — already clean.")
            return

        # ------------------------------------------------------------------
        # Step 3: execute (or show dry-run)
        # ------------------------------------------------------------------
        if not apply:
            print(f"\n[DRY RUN] Would delete {len(score_rows)} apex_scores rows.")
            print("Re-run with --apply 1 to execute.")
            return

        _backup(apply)

        conn.execute(
            f"DELETE FROM apex_scores WHERE season_id = 1 AND prospect_id IN ({placeholders})",
            pid_list,
        )
        conn.commit()
        print(f"\n  Deleted {len(score_rows)} apex_scores rows.")

        # ------------------------------------------------------------------
        # Step 4: verify
        # ------------------------------------------------------------------
        remaining = conn.execute(
            f"SELECT COUNT(*) AS n FROM apex_scores WHERE season_id = 1 AND prospect_id IN ({placeholders})",
            pid_list,
        ).fetchone()["n"]

        if remaining == 0:
            print("  VERIFY OK: 0 season_id=1 apex_scores rows remain for target pids.")
        else:
            print(f"  VERIFY FAIL: {remaining} rows still present — check manually.")
            sys.exit(1)

        total_remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM apex_scores WHERE season_id = 1"
        ).fetchone()["n"]
        print(f"\n  Total season_id=1 apex_scores remaining: {total_remaining}")

    print("\n[DONE]")


if __name__ == "__main__":
    main()
