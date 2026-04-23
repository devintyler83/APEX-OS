"""
global_ghost_pid_cleanup.py

Identity-hygiene pass: enforce one active prospect_id per (display_name, position_group).

Ghost PIDs are duplicate bootstrap entries created when early pipeline ingests recorded
the same player under multiple ingest runs. The canonical PID is selected using this
priority rule:

  1. Has apex_scores for season_id=1 (scored first — preserve our work)
  2. Among ties, LOWEST prospect_id (original bootstrap entry, most likely to have
     consensus data and source_player_map coverage)

All other active pids for the same (display_name, position_group) become ghosts:
  - SET is_active = 0
  - DELETE season_id=1 apex_scores rows

Usage:
    python -m scripts.global_ghost_pid_cleanup --apply 0   # dry run (default)
    python -m scripts.global_ghost_pid_cleanup --apply 1   # execute
    python -m scripts.global_ghost_pid_cleanup --apply 0 --show-all   # show every group
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
# Canonical PID selection CTE
# ---------------------------------------------------------------------------
GHOST_CTE = """
WITH scored AS (
  SELECT DISTINCT prospect_id FROM apex_scores WHERE season_id = 1
),
ranked AS (
  SELECT
    p.prospect_id,
    p.display_name,
    p.position_group,
    p.school_canonical,
    CASE WHEN s.prospect_id IS NOT NULL THEN 1 ELSE 0 END AS has_score,
    ROW_NUMBER() OVER (
      PARTITION BY LOWER(p.display_name), p.position_group
      ORDER BY
        CASE WHEN s.prospect_id IS NOT NULL THEN 0 ELSE 1 END,
        p.prospect_id ASC
    ) AS rn
  FROM prospects p
  LEFT JOIN scored s ON s.prospect_id = p.prospect_id
  WHERE p.is_active = 1
)
SELECT * FROM ranked WHERE rn > 1
"""

GROUPS_CTE = """
WITH scored AS (
  SELECT DISTINCT prospect_id FROM apex_scores WHERE season_id = 1
)
SELECT
  LOWER(p.display_name) AS name_key,
  p.display_name,
  p.position_group,
  COUNT(*) AS active_count,
  SUM(CASE WHEN s.prospect_id IS NOT NULL THEN 1 ELSE 0 END) AS scored_count
FROM prospects p
LEFT JOIN scored s ON s.prospect_id = p.prospect_id
WHERE p.is_active = 1
GROUP BY LOWER(p.display_name), p.position_group
HAVING active_count > 1
ORDER BY active_count DESC, p.display_name, p.position_group
"""


def _backup() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src = PATHS.db
    dst = src.parent / f"draftos_pre_global_ghost_cleanup_{ts}.sqlite"
    shutil.copy2(src, dst)
    print(f"  Backup: {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Global ghost PID identity-hygiene cleanup")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1])
    parser.add_argument("--show-all", action="store_true", help="Print every (name, pos) group detail")
    args = parser.parse_args()
    apply = bool(args.apply)

    print("=" * 70)
    print("GLOBAL GHOST PID CLEANUP — one active pid per (display_name, position_group)")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 70)

    with connect() as conn:
        conn.row_factory = _sqlite3.Row

        # ------------------------------------------------------------------
        # Step A: ghost audit summary
        # ------------------------------------------------------------------
        print("\n[A] Ghost audit (active_count > 1 groups) ...")
        groups = conn.execute(GROUPS_CTE).fetchall()
        print(f"  Violating (display_name, position_group) pairs: {len(groups)}")
        total_active_in_violation = sum(g["active_count"] for g in groups)
        total_scored_in_violation = sum(g["scored_count"] for g in groups)
        print(f"  Total active pids in violation:  {total_active_in_violation}")
        print(f"  Of those with apex_scores:        {total_scored_in_violation}")

        if args.show_all:
            print()
            print(f"  {'display_name':<35} {'pos':<6} {'active':>6} {'scored':>7}")
            print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*7}")
            for g in groups:
                print(f"  {g['display_name']:<35} {g['position_group']:<6} {g['active_count']:>6} {g['scored_count']:>7}")

        # ------------------------------------------------------------------
        # Step B: compute ghost pids using corrected canonical rule
        # ------------------------------------------------------------------
        print("\n[B] Computing ghost pids (lowest scored pid -> else lowest pid = canonical) ...")
        ghost_rows = conn.execute(GHOST_CTE).fetchall()
        ghost_pids = tuple(r["prospect_id"] for r in ghost_rows)
        n_ghosts = len(ghost_pids)
        print(f"  Ghost pids to deactivate: {n_ghosts}")

        # How many have apex_scores?
        scored_ghosts: list[dict] = []
        total_score_rows = 0
        if ghost_pids:
            ph = ",".join("?" * len(ghost_pids))
            score_counts = {
                r["prospect_id"]: r["n_rows"]
                for r in conn.execute(
                    f"SELECT prospect_id, COUNT(*) AS n_rows FROM apex_scores "
                    f"WHERE season_id=1 AND prospect_id IN ({ph}) GROUP BY prospect_id",
                    ghost_pids,
                ).fetchall()
            }
            total_score_rows = sum(score_counts.values())
            for gr in ghost_rows:
                if gr["prospect_id"] in score_counts:
                    # find canonical pid for this ghost
                    canonical = conn.execute("""
                        WITH scored AS (
                          SELECT DISTINCT prospect_id FROM apex_scores WHERE season_id=1
                        )
                        SELECT p.prospect_id AS canonical_pid
                        FROM prospects p
                        LEFT JOIN scored s ON s.prospect_id = p.prospect_id
                        WHERE LOWER(p.display_name) = LOWER(?) AND p.position_group = ?
                          AND p.is_active = 1
                        ORDER BY
                          CASE WHEN s.prospect_id IS NOT NULL THEN 0 ELSE 1 END,
                          p.prospect_id ASC
                        LIMIT 1
                    """, (gr["display_name"], gr["position_group"])).fetchone()
                    scored_ghosts.append({
                        "ghost_pid": gr["prospect_id"],
                        "display_name": gr["display_name"],
                        "position_group": gr["position_group"],
                        "score_rows": score_counts[gr["prospect_id"]],
                        "canonical_pid": canonical["canonical_pid"] if canonical else "?",
                    })

        print(f"  Ghost pids with apex_scores:     {len(scored_ghosts)} distinct pids")
        print(f"  apex_scores rows to delete:       {total_score_rows}")

        if scored_ghosts:
            print()
            print(f"  Scored ghosts (scores will be deleted, canonical is scored counterpart):")
            print(f"  {'ghost_pid':<10} {'canonical_pid':<14} {'display_name':<35} {'pos':<6} {'rows'}")
            for sg in scored_ghosts:
                print(f"  {sg['ghost_pid']:<10} {sg['canonical_pid']:<14} {sg['display_name']:<35} {sg['position_group']:<6} {sg['score_rows']}")

        if not ghost_pids:
            print("\n  Nothing to clean — DB is already identity-clean.")
            return

        if not apply:
            print(f"\n[DRY RUN] Would deactivate {n_ghosts} ghost pids and delete {total_score_rows} apex_scores rows.")
            print("Re-run with --apply 1 to execute.")
            return

        # ------------------------------------------------------------------
        # Step C: execute in a single transaction
        # ------------------------------------------------------------------
        print("\n[C] Executing cleanup ...")
        _backup()

        ph = ",".join("?" * len(ghost_pids))

        # Delete apex_scores first (FK safety)
        del_result = conn.execute(
            f"DELETE FROM apex_scores WHERE season_id=1 AND prospect_id IN ({ph})",
            ghost_pids,
        )
        rows_deleted = del_result.rowcount

        # Deactivate ghost prospects
        upd_result = conn.execute(
            f"UPDATE prospects SET is_active=0 WHERE prospect_id IN ({ph})",
            ghost_pids,
        )
        pids_deactivated = upd_result.rowcount

        conn.commit()

        print(f"  Deactivated:          {pids_deactivated} ghost prospect rows")
        print(f"  apex_scores deleted:  {rows_deleted} rows")

        # ------------------------------------------------------------------
        # Step D: verify
        # ------------------------------------------------------------------
        print("\n[D] Verification ...")

        remaining_violations = conn.execute("""
            SELECT COUNT(*) AS n FROM (
              SELECT LOWER(display_name) AS name_key, position_group
              FROM prospects WHERE is_active=1
              GROUP BY name_key, position_group
              HAVING COUNT(*) > 1
            )
        """).fetchone()["n"]

        if remaining_violations == 0:
            print("  VERIFY OK: 0 (display_name, position_group) pairs with multiple active pids.")
        else:
            print(f"  VERIFY PARTIAL: {remaining_violations} pairs still have multiple active pids — investigate manually.")

        remaining_score_rows = conn.execute(
            f"SELECT COUNT(*) AS n FROM apex_scores WHERE season_id=1 AND prospect_id IN ({ph})",
            ghost_pids,
        ).fetchone()["n"]
        if remaining_score_rows == 0:
            print("  VERIFY OK: 0 apex_scores rows remain for deactivated pids.")
        else:
            print(f"  VERIFY FAIL: {remaining_score_rows} apex_scores rows still present for deactivated pids.")

        total_s1 = conn.execute(
            "SELECT COUNT(*) AS n FROM apex_scores WHERE season_id=1"
        ).fetchone()["n"]
        total_active = conn.execute(
            "SELECT COUNT(*) AS n FROM prospects WHERE is_active=1"
        ).fetchone()["n"]
        print(f"\n  Total season_id=1 apex_scores remaining: {total_s1}")
        print(f"  Total active prospects remaining:         {total_active}")

    print("\n[DONE]")


if __name__ == "__main__":
    main()
