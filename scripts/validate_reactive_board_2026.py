"""
scripts/validate_reactive_board_2026.py — Draft Mode schema validation (2026)

Non-destructive validation checks for the Draft Mode event layer.
Equivalent to doctor.py checks but scoped to Migration 0055 deliverables.

Checks:
  1. drafted_picks_2026 table exists
  2. v_draft_targets_remaining_2026 view exists
  3. No duplicate prospect_id rows in drafted_picks_2026 for season_id=1
  4. No duplicate pick_number rows in drafted_picks_2026 for season_id=1
  5. v_draft_targets_remaining_2026 is a strict subset of v_draft_targets_2026
     (remaining rows <= total rows)
  6. All rows in drafted_picks_2026 reference a valid prospect_id in prospects
  7. All picks in drafted_picks_2026 have a valid drafting_team in team_draft_context

Usage:
    python -m scripts.validate_reactive_board_2026
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.db.connect import connect


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  OK: {msg}")


def main() -> None:
    print("=" * 60)
    print("VALIDATE REACTIVE BOARD — 2026 (Draft Mode schema checks)")
    print("=" * 60)

    with connect() as conn:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        views = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view';"
            ).fetchall()
        }

        # ── Check 1: drafted_picks_2026 table ────────────────────────────────
        if "drafted_picks_2026" not in tables:
            _fail("drafted_picks_2026 table does not exist. Run: python -m draftos.db.migrate")
        _ok("drafted_picks_2026 table exists")

        # ── Check 2: v_draft_targets_remaining_2026 view ─────────────────────
        if "v_draft_targets_remaining_2026" not in views:
            _fail("v_draft_targets_remaining_2026 view does not exist. Run: python -m draftos.db.migrate")
        _ok("v_draft_targets_remaining_2026 view exists")

        # ── Check 3: No duplicate prospect_id for season_id=1 ────────────────
        dup_pid = conn.execute(
            """
            SELECT prospect_id, COUNT(*) AS n
            FROM drafted_picks_2026
            WHERE season_id = 1
            GROUP BY prospect_id
            HAVING COUNT(*) > 1
            """,
        ).fetchall()
        if dup_pid:
            detail = ", ".join(f"pid={r['prospect_id']} ({r['n']}x)" for r in dup_pid)
            _fail(f"Duplicate prospect_id rows in drafted_picks_2026: {detail}")
        _ok("No duplicate prospect_id rows in drafted_picks_2026 (season_id=1)")

        # ── Check 4: No duplicate pick_number for season_id=1 ────────────────
        dup_pick = conn.execute(
            """
            SELECT pick_number, COUNT(*) AS n
            FROM drafted_picks_2026
            WHERE season_id = 1
            GROUP BY pick_number
            HAVING COUNT(*) > 1
            """,
        ).fetchall()
        if dup_pick:
            detail = ", ".join(f"pick#{r['pick_number']} ({r['n']}x)" for r in dup_pick)
            _fail(f"Duplicate pick_number rows in drafted_picks_2026: {detail}")
        _ok("No duplicate pick_number rows in drafted_picks_2026 (season_id=1)")

        # ── Check 5: Remaining view is a subset of target view ────────────────
        total_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM v_draft_targets_2026;"
        ).fetchone()["n"]
        remaining_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM v_draft_targets_remaining_2026;"
        ).fetchone()["n"]
        drafted_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM drafted_picks_2026 WHERE season_id=1;"
        ).fetchone()["n"]

        if remaining_rows > total_rows:
            _fail(
                f"v_draft_targets_remaining_2026 ({remaining_rows} rows) > "
                f"v_draft_targets_2026 ({total_rows} rows). View logic error."
            )
        _ok(
            f"Remaining view is subset of target view: "
            f"{remaining_rows} remaining / {total_rows} total "
            f"({drafted_rows} prospect(s) drafted)"
        )

        # ── Check 6: All drafted prospect_ids exist in prospects ──────────────
        orphan_pids = conn.execute(
            """
            SELECT dp.prospect_id
            FROM drafted_picks_2026 dp
            LEFT JOIN prospects p ON p.prospect_id = dp.prospect_id
            WHERE dp.season_id = 1
              AND p.prospect_id IS NULL
            """,
        ).fetchall()
        if orphan_pids:
            detail = ", ".join(str(r["prospect_id"]) for r in orphan_pids)
            _fail(f"drafted_picks_2026 references prospect_id(s) not in prospects: {detail}")
        _ok("All drafted prospect_ids reference valid prospects rows")

        # ── Check 7: All drafted teams exist in team_draft_context ────────────
        orphan_teams = conn.execute(
            """
            SELECT DISTINCT dp.drafting_team
            FROM drafted_picks_2026 dp
            LEFT JOIN team_draft_context tdc ON tdc.team_id = dp.drafting_team
            WHERE dp.season_id = 1
              AND tdc.team_id  IS NULL
            """,
        ).fetchall()
        if orphan_teams:
            detail = ", ".join(r["drafting_team"] for r in orphan_teams)
            _fail(f"drafted_picks_2026 references team(s) not in team_draft_context: {detail}")
        _ok("All drafting_team values reference valid team_draft_context rows")

    print()
    print(f"drafted_picks_2026 rows (season_id=1) : {drafted_rows}")
    print(f"v_draft_targets_2026 rows             : {total_rows}")
    print(f"v_draft_targets_remaining_2026 rows   : {remaining_rows}")
    print()
    print("OK: all reactive board checks passed")


if __name__ == "__main__":
    main()
