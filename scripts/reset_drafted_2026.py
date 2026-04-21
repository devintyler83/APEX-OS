"""
scripts/reset_drafted_2026.py — Draft Mode pick rollback utility (2026)

Deletes rows from drafted_picks_2026 to support clean testing and draft-night
corrections. Three modes:

  --apply 0 (default): dry run — shows rows that would be deleted, no changes.
  --apply 1           : backs up DB, then deletes matching rows.

Scope filters (combinable):
  --team PHI          : delete only picks drafted by PHI
  --pick-number 7     : delete only the pick at position #7

If no filter is given, all rows for season_id=1 are targeted (full reset).
A full reset requires --apply 1; dry run still shows the count.

Usage:
    # Dry run — see what would be deleted
    python -m scripts.reset_drafted_2026

    # Full reset (all picks, apply)
    python -m scripts.reset_drafted_2026 --apply 1

    # Delete a specific pick number only
    python -m scripts.reset_drafted_2026 --pick-number 7 --apply 1

    # Delete all picks drafted by a specific team
    python -m scripts.reset_drafted_2026 --team PHI --apply 1

    # Both filters combined (AND logic)
    python -m scripts.reset_drafted_2026 --team PHI --pick-number 7 --apply 1
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.config import PATHS
from draftos.db.connect import connect


def _backup_db(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_reset_drafted.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete rows from drafted_picks_2026 (season_id=1)."
    )
    parser.add_argument("--team",        type=str, default=None,
                        help="Limit deletion to picks by this team (e.g. PHI).")
    parser.add_argument("--pick-number", type=int, default=None,
                        help="Limit deletion to this pick number only.")
    parser.add_argument("--apply",       type=int, choices=[0, 1], default=0,
                        help="0 = dry run (default), 1 = delete from DB.")
    args = parser.parse_args()

    season_id = 1

    # Build WHERE clause (all conditions qualified with dp. to avoid ambiguity in JOIN)
    conditions = ["dp.season_id = ?"]
    params: list = [season_id]

    if args.team:
        conditions.append("dp.drafting_team = ?")
        params.append(args.team.strip().upper())

    if args.pick_number is not None:
        conditions.append("dp.pick_number = ?")
        params.append(args.pick_number)

    where_clause = " AND ".join(conditions)
    # Unqualified WHERE for the DELETE (single-table, no ambiguity)
    delete_conditions = ["season_id = ?"]
    delete_params: list = [season_id]
    if args.team:
        delete_conditions.append("drafting_team = ?")
        delete_params.append(args.team.strip().upper())
    if args.pick_number is not None:
        delete_conditions.append("pick_number = ?")
        delete_params.append(args.pick_number)
    delete_where = " AND ".join(delete_conditions)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT dp.id, dp.pick_number, dp.round_number, dp.drafting_team,
                   dp.prospect_id, dp.drafted_at, dp.source, dp.note,
                   p.display_name, p.position_group
            FROM drafted_picks_2026 dp
            LEFT JOIN prospects p ON p.prospect_id = dp.prospect_id
            WHERE {where_clause}
            ORDER BY dp.pick_number
            """,
            params,
        ).fetchall()

    print("=" * 60)
    print("RESET DRAFTED — 2026 (season_id=1)")
    print("=" * 60)

    if not rows:
        print("No rows match the given filters. Nothing to delete.")
        return

    print(f"Rows targeted for deletion: {len(rows)}")
    print()
    for r in rows:
        name = r["display_name"] or f"pid={r['prospect_id']}"
        pos  = r["position_group"] or "?"
        rnd  = f" R{r['round_number']}" if r["round_number"] else ""
        note = f" | note: {r['note']}" if r["note"] else ""
        print(f"  Pick #{r['pick_number']:>3}{rnd} — {name} ({pos}) — {r['drafting_team']}"
              f" — {r['drafted_at']}{note}")
    print()

    if args.apply == 0:
        print("DRY RUN: no DB writes. Re-run with --apply 1 to delete.")
        return

    backup_path = _backup_db(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        result = conn.execute(
            f"DELETE FROM drafted_picks_2026 WHERE {delete_where}",
            delete_params,
        )
        conn.commit()

    print(f"OK: {result.rowcount} row(s) deleted from drafted_picks_2026.")


if __name__ == "__main__":
    main()
