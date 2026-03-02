from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_apply_review_queue.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply resolved review-queue mappings into source_player_map.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--by", type=str, default="manual")
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    with connect() as conn:
        row = conn.execute("SELECT season_id FROM seasons WHERE draft_year=?;", (args.season,)).fetchone()
        if not row:
            raise SystemExit(f"FAIL: season not found: {args.season}")
        season_id = int(row["season_id"])

        rows = conn.execute(
            """
            SELECT source_player_id, resolved_prospect_id
            FROM source_player_review_queue
            WHERE season_id = ?
              AND status = 'resolved'
              AND resolved_prospect_id IS NOT NULL;
            """,
            (season_id,),
        ).fetchall()

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"RESOLVED_QUEUE_ROWS: {len(rows)}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    now = utc_now_iso()
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        n = 0
        for r in rows:
            spid = int(r["source_player_id"])
            pid = int(r["resolved_prospect_id"])

            conn.execute(
                """
                INSERT INTO source_player_map(
                  source_player_id, prospect_id, match_method, match_score, match_notes,
                  reviewed, reviewed_by, reviewed_at
                )
                VALUES (?, ?, 'manual_queue', 1.0, 'review_queue_resolved', 1, ?, ?)
                ON CONFLICT(source_player_id)
                DO NOTHING;
                """,
                (spid, pid, args.by, now),
            )
            n += 1

        conn.commit()

    print(f"OK: applied mappings inserted={n} (existing mappings are not overwritten).")


if __name__ == "__main__":
    main()