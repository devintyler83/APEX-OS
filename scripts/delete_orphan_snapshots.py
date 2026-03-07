"""
delete_orphan_snapshots.py

Deletes legacy orphan snapshots 1 and 2 from all snapshot tables.

Snapshots 1 and 2 are pre-pipeline artifacts: they have snapshot_rows but no
coverage or confidence data, and predate the clean pipeline. They are not valid
historical data and are safe to remove.

Snapshots 3+ are clean pipeline snapshots and must NOT be touched.

Dry run (default):
    python scripts/delete_orphan_snapshots.py --apply 0

Apply:
    python scripts/delete_orphan_snapshots.py --apply 1

Idempotent: safe to re-run. If rows are already gone, reports zero deletions.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect


ORPHAN_SNAPSHOT_IDS = (1, 2)

# Child tables first, then parent — FK order matters even with FK off
DELETION_ORDER = [
    ("prospect_board_snapshot_confidence", "snapshot_id"),
    ("prospect_board_snapshot_coverage",   "snapshot_id"),
    ("prospect_board_snapshot_rows",       "snapshot_id"),
    ("prospect_board_snapshots",           "id"),
]

# These snapshots must never be touched
PROTECTED_SNAPSHOT_IDS = (3, 4, 5, 6)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_delete_orphan_snapshots.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def count_rows(conn: sqlite3.Connection, table: str, col: str, ids: tuple) -> int:
    placeholders = ",".join("?" * len(ids))
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({placeholders});",
        ids,
    ).fetchone()
    return int(row[0])


def get_protected_counts(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    """Return row counts for each protected snapshot across all tables."""
    result: dict[int, dict[str, int]] = {}
    for snap_id in PROTECTED_SNAPSHOT_IDS:
        result[snap_id] = {}
        for table, col in DELETION_ORDER:
            if not table_exists(conn, table):
                result[snap_id][table] = -1
                continue
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ?;",
                (snap_id,),
            ).fetchone()
            result[snap_id][table] = int(row[0])
    return result


def print_plan(conn: sqlite3.Connection) -> None:
    print()
    print(f"=== ORPHAN SNAPSHOTS TO DELETE: ids={list(ORPHAN_SNAPSHOT_IDS)} ===")
    total_to_delete = 0
    for table, col in DELETION_ORDER:
        if not table_exists(conn, table):
            print(f"  {table:<45}  TABLE NOT FOUND (skip)")
            continue
        n = count_rows(conn, table, col, ORPHAN_SNAPSHOT_IDS)
        total_to_delete += n
        print(f"  {table:<45}  rows to delete: {n}")

    print()
    print(f"=== PROTECTED SNAPSHOTS (must be unchanged): ids={list(PROTECTED_SNAPSHOT_IDS)} ===")
    protected = get_protected_counts(conn)
    header = f"  {'snapshot_id':>11}  " + "  ".join(f"{t[0][:12]:<12}" for t in DELETION_ORDER)
    print(header)
    for snap_id in PROTECTED_SNAPSHOT_IDS:
        counts = protected[snap_id]
        row_str = "  ".join(f"{counts.get(t, -1):>12}" for t, _ in DELETION_ORDER)
        print(f"  {snap_id:>11}  {row_str}")

    print()
    print(f"TOTAL rows to delete: {total_to_delete}")


def verify_protected_unchanged(
    conn: sqlite3.Connection,
    before: dict[int, dict[str, int]],
) -> None:
    after = get_protected_counts(conn)
    for snap_id in PROTECTED_SNAPSHOT_IDS:
        for table, _ in DELETION_ORDER:
            b = before[snap_id].get(table, 0)
            a = after[snap_id].get(table, 0)
            if b != a:
                raise SystemExit(
                    f"FAIL: protected snapshot_id={snap_id} table={table} "
                    f"changed from {b} to {a} rows. Aborting."
                )
    print("OK: all protected snapshots (3, 4, 5, 6) verified unchanged.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Delete orphan snapshots 1 and 2 from all snapshot tables."
    )
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        for table, _ in DELETION_ORDER:
            if not table_exists(conn, table):
                raise SystemExit(f"FAIL: required table not found: {table}")

        # Safety check: confirm no orphan snapshot IDs overlap with protected IDs
        overlap = set(ORPHAN_SNAPSHOT_IDS) & set(PROTECTED_SNAPSHOT_IDS)
        if overlap:
            raise SystemExit(f"FAIL: orphan/protected ID overlap detected: {overlap}")

        print_plan(conn)
        protected_before = get_protected_counts(conn)

    if args.apply != 1:
        print()
        print("DRY_RUN: no changes applied. Pass --apply 1 to execute.")
        return

    # ------------------------------------------------------------------
    # APPLY
    # ------------------------------------------------------------------
    backup_path = ensure_backup(PATHS.db)
    print()
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        placeholders = ",".join("?" * len(ORPHAN_SNAPSHOT_IDS))

        conn.execute("BEGIN;")
        try:
            deleted: dict[str, int] = {}
            for table, col in DELETION_ORDER:
                conn.execute(
                    f"DELETE FROM {table} WHERE {col} IN ({placeholders});",
                    ORPHAN_SNAPSHOT_IDS,
                )
                deleted[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({placeholders});",
                    ORPHAN_SNAPSHOT_IDS,
                ).fetchone()[0]

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # Post-deletion verification
    print()
    print("=== POST-DELETION COUNTS (expect all zeros for orphan IDs) ===")
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        all_zero = True
        for table, col in DELETION_ORDER:
            n = count_rows(conn, table, col, ORPHAN_SNAPSHOT_IDS)
            status = "OK" if n == 0 else "FAIL"
            if n != 0:
                all_zero = False
            print(f"  {status}  {table:<45}  remaining rows for ids={list(ORPHAN_SNAPSHOT_IDS)}: {n}")

        print()
        print("=== PROTECTED SNAPSHOT ROW COUNTS (must match pre-deletion) ===")
        verify_protected_unchanged(conn, protected_before)

        print()
        print("=== REMAINING SNAPSHOTS IN prospect_board_snapshots ===")
        rows = conn.execute(
            "SELECT id, snapshot_date_utc, season_id, model_id FROM prospect_board_snapshots ORDER BY id"
        ).fetchall()
        for r in rows:
            print(f"  id={r['id']}  date={r['snapshot_date_utc']}  season_id={r['season_id']}  model_id={r['model_id']}")

    if not all_zero:
        raise SystemExit("FAIL: not all orphan rows were deleted. Investigate.")

    print()
    print("OK: orphan snapshots 1 and 2 deleted successfully.")


if __name__ == "__main__":
    main()
