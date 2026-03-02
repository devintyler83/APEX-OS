from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_prospect_canonicalization.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def resolve_season_id(conn, draft_year: int) -> int:
    row = conn.execute("SELECT season_id FROM seasons WHERE draft_year = ?;", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found: {draft_year}")
    return int(row["season_id"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill strict duplicate prospect canonicalization for a season.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)

        # Find strict duplicates
        dups = conn.execute(
            """
            SELECT
              name_key,
              position_group,
              school_canonical,
              COUNT(*) AS n
            FROM prospects
            WHERE season_id = ?
              AND name_key IS NOT NULL AND name_key <> ''
              AND position_group IS NOT NULL AND position_group <> ''
              AND school_canonical IS NOT NULL AND school_canonical <> ''
            GROUP BY name_key, position_group, school_canonical
            HAVING COUNT(*) > 1
            ORDER BY n DESC, name_key ASC;
            """,
            (season_id,),
        ).fetchall()

        mappings: List[Tuple[int, int, str]] = []  # (alias_pid, canon_pid, reason)

        for d in dups:
            key = d["name_key"]
            pg = d["position_group"]
            sc = d["school_canonical"]

            ids = conn.execute(
                """
                SELECT prospect_id
                FROM prospects
                WHERE season_id = ?
                  AND name_key = ?
                  AND position_group = ?
                  AND school_canonical = ?
                ORDER BY prospect_id ASC;
                """,
                (season_id, key, pg, sc),
            ).fetchall()

            pids = [int(r["prospect_id"]) for r in ids]
            if len(pids) < 2:
                continue

            canon = min(pids)
            for pid in pids:
                if pid == canon:
                    continue
                reason = f"strict_duplicate name_key={key} pos={pg} school={sc}"
                mappings.append((pid, canon, reason))

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"STRICT_DUP_ALIAS_ROWS: {len(mappings)}")
        if mappings:
            print("EXAMPLE:", json.dumps({"alias": mappings[0][0], "canonical": mappings[0][1], "reason": mappings[0][2]}, indent=2))

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)
        now = utc_now_iso()

        n = 0
        for alias_pid, canon_pid, reason in mappings:
            conn.execute(
                """
                INSERT INTO prospect_canonical_map(season_id, prospect_id, canonical_prospect_id, reason, created_at_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(season_id, prospect_id)
                DO UPDATE SET
                  canonical_prospect_id = excluded.canonical_prospect_id,
                  reason = excluded.reason,
                  created_at_utc = excluded.created_at_utc;
                """,
                (season_id, alias_pid, canon_pid, reason, now),
            )
            n += 1

        conn.commit()

    print(f"OK: prospect canonicalization applied: rows={n}")


if __name__ == "__main__":
    main()