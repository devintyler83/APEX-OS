# scripts/learn_school_aliases_from_mapped_2026.py
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set, List

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_learn_school_aliases.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone()
    return row is not None


def colnames(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()]


def pick_first(cols: Set[str], *cands: str) -> Optional[str]:
    for c in cands:
        if c in cols:
            return c
    return None


def resolve_season_id(conn, draft_year: int) -> int:
    cols = set(colnames(conn, "seasons"))
    id_col = pick_first(cols, "season_id", "id")
    year_col = pick_first(cols, "draft_year", "year")
    if not id_col or not year_col:
        raise SystemExit(f"FAIL: seasons missing expected cols. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col}=?;",
        (draft_year,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found for draft_year={draft_year}")
    return int(row["season_id"])


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Learn school_aliases from already-mapped source_players -> prospects, then backfill source_players.school_canonical."
    )
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        required = ("seasons", "school_aliases", "source_players", "source_player_map", "prospects")
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)

        # How many source_players still missing school_canonical?
        rows_needing_canon = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM source_players
            WHERE season_id=?
              AND (school_canonical IS NULL OR TRIM(school_canonical)='');
            """,
            (season_id,),
        ).fetchone()["n"]

        # PLAN: how many aliases could be learned (unique by normalized alias)
        plan_new_aliases = conn.execute(
            """
            WITH learned AS (
              SELECT
                LOWER(TRIM(sp.raw_school)) AS alias_norm,
                MIN(TRIM(sp.raw_school))   AS school_alias,
                MIN(p.school_canonical)    AS school_canonical
              FROM source_players sp
              JOIN source_player_map m ON m.source_player_id = sp.source_player_id
              JOIN prospects p ON p.prospect_id = m.prospect_id
              WHERE sp.season_id = ?
                AND sp.raw_school IS NOT NULL AND TRIM(sp.raw_school) <> ''
                AND p.school_canonical IS NOT NULL AND TRIM(p.school_canonical) <> ''
              GROUP BY LOWER(TRIM(sp.raw_school))
            ),
            existing AS (
              SELECT LOWER(TRIM(school_alias)) AS alias_norm
              FROM school_aliases
            )
            SELECT COUNT(*) AS n
            FROM learned l
            LEFT JOIN existing e ON e.alias_norm = l.alias_norm
            WHERE e.alias_norm IS NULL;
            """,
            (season_id,),
        ).fetchone()["n"]

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"PLAN_NEW_ALIASES: {int(plan_new_aliases)}")
        print(f"ROWS_NEEDING_SCHOOL_CANON_BACKFILL: {int(rows_needing_canon)}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)
        now = utc_now_iso()

        # 1) Insert aliases learned from mapped rows (case/whitespace-safe)
        #    This is the critical fix for the UNIQUE constraint failure.
        conn.execute(
            """
            INSERT INTO school_aliases(school_alias, school_canonical)
            SELECT
              x.school_alias,
              x.school_canonical
            FROM (
              SELECT
                LOWER(TRIM(sp.raw_school)) AS alias_norm,
                MIN(TRIM(sp.raw_school))   AS school_alias,
                MIN(p.school_canonical)    AS school_canonical
              FROM source_players sp
              JOIN source_player_map m ON m.source_player_id = sp.source_player_id
              JOIN prospects p ON p.prospect_id = m.prospect_id
              WHERE sp.season_id = ?
                AND sp.raw_school IS NOT NULL AND TRIM(sp.raw_school) <> ''
                AND p.school_canonical IS NOT NULL AND TRIM(p.school_canonical) <> ''
              GROUP BY LOWER(TRIM(sp.raw_school))
            ) x
            LEFT JOIN (
              SELECT LOWER(TRIM(school_alias)) AS alias_norm
              FROM school_aliases
            ) sa
              ON sa.alias_norm = x.alias_norm
            WHERE sa.alias_norm IS NULL;
            """,
            (season_id,),
        )
        aliases_inserted = conn.total_changes  # safe enough for logging

        # 2) Backfill source_players.school_canonical from school_aliases (only blanks)
        #    Join is done on LOWER(TRIM()) to match the learning normalization.
        conn.execute(
            """
            UPDATE source_players
            SET school_canonical = (
              SELECT sa.school_canonical
              FROM school_aliases sa
              WHERE LOWER(TRIM(sa.school_alias)) = LOWER(TRIM(source_players.raw_school))
              LIMIT 1
            )
            WHERE season_id = ?
              AND (school_canonical IS NULL OR TRIM(school_canonical)='')
              AND raw_school IS NOT NULL AND TRIM(raw_school) <> ''
              AND EXISTS (
                SELECT 1
                FROM school_aliases sa
                WHERE LOWER(TRIM(sa.school_alias)) = LOWER(TRIM(source_players.raw_school))
              );
            """,
            (season_id,),
        )
        canon_updates = conn.total_changes - aliases_inserted  # remaining changes from update

        # 3) Stamp updated_at if you have it (optional, schema-adaptive)
        sp_cols = set(colnames(conn, "source_players"))
        if "updated_at" in sp_cols:
            conn.execute(
                """
                UPDATE source_players
                SET updated_at = ?
                WHERE season_id = ?
                  AND updated_at IS NOT NULL;
                """,
                (now, season_id),
            )

        conn.commit()

    print(f"OK: learn_school_aliases applied aliases_inserted≈{aliases_inserted} school_canon_updates≈{canon_updates}")


if __name__ == "__main__":
    main()