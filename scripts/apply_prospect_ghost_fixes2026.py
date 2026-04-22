"""
apply_prospect_ghost_fixes2026.py
Write-side fixer for prospect ghost / duplicate PIDs — season_id=1 (2026).

Usage:
    python -m scripts.apply_prospect_ghost_fixes2026 --apply 0   # dry run (default)
    python -m scripts.apply_prospect_ghost_fixes2026 --apply 1   # execute writes

Safety gates (BOTH must be satisfied before any write executes on --apply 1):
    1. Run the DB backup manually BEFORE invoking --apply 1:
           copy data\\edge\\draftos.sqlite data\\edge\\draftos_ghostfix_backup.sqlite
    2. Flip the constant below from False → True:
           ALLOW_WRITES = True

Leaving ALLOW_WRITES = False guarantees that even accidental --apply 1 invocations
produce only a plan printout and never touch the database.

Actions performed (DEDUP_GHOST and INACTIVE_SNAPSHOT categories only):
    - deactivate_prospect  : UPDATE prospects SET is_active=0, updated_at=<now>
                              WHERE season_id=1 AND prospect_id=? AND is_active=1
    - delete_snapshot_row  : DELETE FROM prospect_board_snapshot_rows
                              WHERE snapshot_id=? AND prospect_id=?

MULTI_ACTIVE clusters are printed but never auto-fixed — they require manual review.

Audit log written to:
    prospect_ghost_fixes2026 (created in-DB if absent)
    Columns: fix_id, season_id, prospect_id, snapshot_id, action, reason, created_at

Idempotency:
    - deactivate_prospect only fires when is_active=1 (guarded in SQL WHERE clause).
    - delete_snapshot_row is idempotent (DELETE on missing row is a no-op).
    - Audit rows are append-only; duplicate runs append more rows (additive, acceptable).
"""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# SAFETY GATE — flip to True only after running the backup command below
# ---------------------------------------------------------------------------
ALLOW_WRITES: bool = True

BACKUP_COMMAND = (
    r"copy data\edge\draftos.sqlite data\edge\draftos_ghostfix_backup.sqlite"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = Path("data/edge/draftos.sqlite")
SEASON_ID = 1

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS prospect_ghost_fixes2026 (
    fix_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id   INTEGER NOT NULL,
    prospect_id INTEGER,
    snapshot_id INTEGER,
    action      TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Import shared classification logic
# ---------------------------------------------------------------------------
# The classify_all() function and helpers live in fix_prospect_ghosts2026;
# import them rather than duplicating to keep both scripts in strict parity.
from scripts.fix_prospect_ghosts2026 import classify_all  # noqa: E402


# ---------------------------------------------------------------------------
# Dry-run printer
# ---------------------------------------------------------------------------

def _print_plan(classification: dict) -> None:
    dg = classification["dedup_ghost"]
    ins = classification["inactive_snapshot"]
    ma = classification["multi_active"]

    print()
    print("=" * 70)
    print("  PLAN — DEDUP_GHOST (deactivate + remove from snapshots)")
    print("=" * 70)
    for e in dg:
        status = "ACTIVE" if e["is_active"] else "already-inactive"
        print(
            f"  pid={e['prospect_id']:>6} | {e['display_name']:<30} | "
            f"{e['school_canonical']:<28} | pos={e['position_group']:<8} | {status}"
        )
        for act in e["planned_actions"]:
            if act["action"] == "deactivate_prospect":
                print(f"             -> DEACTIVATE")
            elif act["action"] == "delete_snapshot_row":
                print(
                    f"             -> DEL_SNAPSHOT  snap={act['snapshot_id']}  "
                    f"rank={act['rank_overall']}"
                )

    print()
    print("=" * 70)
    print("  PLAN — INACTIVE_SNAPSHOT (remove from snapshots only)")
    print("=" * 70)
    for e in ins:
        print(
            f"  pid={e['prospect_id']:>6} | {e['display_name']:<30} | "
            f"{e['school_canonical']:<28} | pos={e['position_group']:<8} | inactive"
        )
        for act in e["planned_actions"]:
            print(
                f"             -> DEL_SNAPSHOT  snap={act['snapshot_id']}  "
                f"rank={act['rank_overall']}"
            )

    print()
    print("=" * 70)
    print("  PLAN — MULTI_ACTIVE (no auto-fix; manual review required)")
    print("=" * 70)
    print(f"  Total clusters : {len(ma)}")
    for c in ma:
        print(
            f"  {c['display_name']:<30} | school={c['school_canonical']:<28} | "
            f"suggested_canonical=pid {c['suggested_canonical_pid']}"
        )
        for m in c["members"]:
            marker = "<-- suggested canonical" if m["prospect_id"] == c["suggested_canonical_pid"] else ""
            print(f"       pid={m['prospect_id']:>6}  pos={m['position_group']:<6}  {marker}")

    dg_deactivate = sum(1 for e in dg if e["is_active"] == 1)
    dg_snap = sum(
        sum(1 for a in e["planned_actions"] if a["action"] == "delete_snapshot_row")
        for e in dg
    )
    ins_snap = sum(len(e["planned_actions"]) for e in ins)

    print()
    print("=" * 70)
    print("  TOTALS")
    print("=" * 70)
    print(f"  Prospect deactivations : {dg_deactivate}")
    print(f"  Snapshot row deletes   : {dg_snap + ins_snap}")
    print(f"  Multi-active clusters  : {len(ma)}  (skipped — manual review)")


# ---------------------------------------------------------------------------
# Write executor
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_audit_table(cur: sqlite3.Cursor) -> None:
    cur.executescript(AUDIT_DDL)


def _audit(cur: sqlite3.Cursor, *, season_id: int, prospect_id: int | None,
           snapshot_id: int | None, action: str, reason: str) -> None:
    cur.execute(
        """
        INSERT INTO prospect_ghost_fixes2026
            (season_id, prospect_id, snapshot_id, action, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (season_id, prospect_id, snapshot_id, action, reason, _now_utc()),
    )


def _execute_fixes(classification: dict, db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    _ensure_audit_table(cur)

    deactivations = 0
    snap_deletes = 0

    # -----------------------------------------------------------------------
    # DEDUP_GHOST fixes
    # -----------------------------------------------------------------------
    print()
    print("--- Applying DEDUP_GHOST fixes ---")
    for e in classification["dedup_ghost"]:
        pid = e["prospect_id"]
        name = e["display_name"]
        school = e["school_canonical"]

        # Deactivate if currently active (idempotent guard in WHERE)
        if e["is_active"] == 1:
            cur.execute(
                """
                UPDATE prospects
                SET is_active = 0, updated_at = ?
                WHERE season_id = ? AND prospect_id = ? AND is_active = 1
                """,
                (_now_utc(), SEASON_ID, pid),
            )
            if cur.rowcount > 0:
                _audit(
                    cur,
                    season_id=SEASON_ID,
                    prospect_id=pid,
                    snapshot_id=None,
                    action="deactivate_prospect",
                    reason="dedup_or_ghost_school_canonical",
                )
                deactivations += 1
                print(f"  DEACTIVATED  pid={pid:>6}  {name}  school={school}")
            else:
                print(f"  SKIP (already inactive)  pid={pid:>6}  {name}")

        # Remove from all snapshots (idempotent — DELETE on missing row is safe)
        for snap_id, rank in e["snapshot_rows"]:
            cur.execute(
                """
                DELETE FROM prospect_board_snapshot_rows
                WHERE snapshot_id = ? AND prospect_id = ?
                """,
                (snap_id, pid),
            )
            if cur.rowcount > 0:
                _audit(
                    cur,
                    season_id=SEASON_ID,
                    prospect_id=pid,
                    snapshot_id=snap_id,
                    action="delete_snapshot_row",
                    reason="dedup_or_ghost_in_snapshot",
                )
                snap_deletes += 1
                print(
                    f"  DEL_SNAPSHOT  pid={pid:>6}  snap={snap_id}  "
                    f"rank={rank}  {name}"
                )

    # -----------------------------------------------------------------------
    # INACTIVE_SNAPSHOT fixes
    # -----------------------------------------------------------------------
    print()
    print("--- Applying INACTIVE_SNAPSHOT fixes ---")
    for e in classification["inactive_snapshot"]:
        pid = e["prospect_id"]
        name = e["display_name"]

        for snap_id, rank in e["snapshot_rows"]:
            cur.execute(
                """
                DELETE FROM prospect_board_snapshot_rows
                WHERE snapshot_id = ? AND prospect_id = ?
                """,
                (snap_id, pid),
            )
            if cur.rowcount > 0:
                _audit(
                    cur,
                    season_id=SEASON_ID,
                    prospect_id=pid,
                    snapshot_id=snap_id,
                    action="delete_snapshot_row",
                    reason="inactive_prospect_in_snapshot",
                )
                snap_deletes += 1
                print(
                    f"  DEL_SNAPSHOT  pid={pid:>6}  snap={snap_id}  "
                    f"rank={rank}  {name}"
                )

    # -----------------------------------------------------------------------
    # MULTI_ACTIVE — print only, no writes
    # -----------------------------------------------------------------------
    ma = classification["multi_active"]
    if ma:
        print()
        print(f"--- MULTI_ACTIVE: {len(ma)} clusters skipped (manual review required) ---")

    con.commit()
    con.close()

    print()
    print("=" * 70)
    print(f"  DONE — deactivations={deactivations}  snapshot_deletes={snap_deletes}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Apply prospect ghost fixes for DraftOS 2026. "
            "Requires ALLOW_WRITES=True AND --apply 1 for real writes."
        )
    )
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        default=0,
        help="0=dry run (default), 1=execute writes (requires ALLOW_WRITES=True).",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        raise SystemExit(1)

    apply_writes = args.apply == 1

    print(f"DraftOS Prospect Ghost Fixer — season_id={SEASON_ID} (2026)")
    print(f"DB   : {DB_PATH.resolve()}")
    print(f"Mode : {'WRITE' if apply_writes else 'DRY RUN'}")

    if apply_writes:
        print()
        print("!" * 70)
        print("  BACKUP REQUIRED before any writes. Run this command FIRST:")
        print()
        print(f"      {BACKUP_COMMAND}")
        print()
        if not ALLOW_WRITES:
            print(
                "  BLOCKED: ALLOW_WRITES is False.\n"
                "  Open this script and set ALLOW_WRITES = True, then re-run."
            )
            print("!" * 70)
            raise SystemExit(0)
        print("  ALLOW_WRITES=True detected — proceeding with writes.")
        print("!" * 70)

    classification = classify_all(DB_PATH)
    _print_plan(classification)

    if apply_writes and ALLOW_WRITES:
        _execute_fixes(classification, DB_PATH)
    elif apply_writes and not ALLOW_WRITES:
        # Already exited above, but belt-and-suspenders guard
        print("Writes blocked by ALLOW_WRITES=False.")
    else:
        print()
        print("Dry run complete. No changes made.")
        print(
            "To apply: set ALLOW_WRITES=True in script, run the backup command, "
            "then re-run with --apply 1."
        )


if __name__ == "__main__":
    main()
