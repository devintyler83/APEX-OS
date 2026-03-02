from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_snapshot_coverage.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def colnames(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()]


def pick_first(cols: set[str], *cands: str) -> Optional[str]:
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
        f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col} = ?;",
        (draft_year,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found for draft_year={draft_year}")
    return int(row["season_id"])


def resolve_model_id(conn, season_id: int, model_key_or_name: str) -> int:
    cols = set(colnames(conn, "models"))
    id_col = pick_first(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models missing id column. found={sorted(cols)}")

    if "season_id" in cols:
        key_col = pick_first(cols, "model_key", "model_name", "name")
        if not key_col:
            raise SystemExit(f"FAIL: models missing model key/name column. found={sorted(cols)}")
        row = conn.execute(
            f"""
            SELECT {id_col} AS model_id
            FROM models
            WHERE season_id = ? AND {key_col} = ?;
            """,
            (season_id, model_key_or_name),
        ).fetchone()
        if row:
            return int(row["model_id"])

        for alt in ("model_key", "model_name", "name"):
            if alt in cols and alt != key_col:
                row2 = conn.execute(
                    f"SELECT {id_col} AS model_id FROM models WHERE season_id = ? AND {alt} = ?;",
                    (season_id, model_key_or_name),
                ).fetchone()
                if row2:
                    return int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season_id={season_id} model='{model_key_or_name}'")

    name_col = pick_first(cols, "name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name column. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS model_id FROM models WHERE {name_col} = ?;",
        (model_key_or_name,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")
    return int(row["model_id"])


def get_latest_snapshot(conn, season_id: int, model_id: int) -> Tuple[int, str]:
    row = conn.execute(
        """
        SELECT id, snapshot_date_utc
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
        ORDER BY snapshot_date_utc DESC, id DESC
        LIMIT 1;
        """,
        (season_id, model_id),
    ).fetchone()
    if not row:
        raise SystemExit("FAIL: no snapshots found for this season/model")
    return int(row["id"]), str(row["snapshot_date_utc"])


def load_canonical_map(conn) -> Dict[int, int]:
    if not table_exists(conn, "source_canonical_map"):
        return {}
    rows = conn.execute("SELECT source_id, canonical_source_id FROM source_canonical_map;").fetchall()
    m: Dict[int, int] = {}
    for r in rows:
        m[int(r["source_id"])] = int(r["canonical_source_id"])
    return m


def canon_of(source_id: int, cmap: Dict[int, int]) -> int:
    return int(cmap.get(int(source_id), int(source_id)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute deterministic snapshot coverage_count by (snapshot_id, prospect_id).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--snapshot-id", type=int, default=None)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        required = [
            "prospect_board_snapshots",
            "prospect_board_snapshot_rows",
            "sources",
            "source_rankings",
            "source_player_map",
        ]
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        if not table_exists(conn, "prospect_board_snapshot_coverage"):
            raise SystemExit("FAIL: missing table prospect_board_snapshot_coverage (apply migration 0009 first)")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)
        else:
            row = conn.execute(
                """
                SELECT id, snapshot_date_utc
                FROM prospect_board_snapshots
                WHERE id = ? AND season_id = ? AND model_id = ?;
                """,
                (args.snapshot_id, season_id, model_id),
            ).fetchone()
            if not row:
                raise SystemExit("FAIL: snapshot_id not found for this season/model")
            snapshot_id, snapshot_date_utc = int(row["id"]), str(row["snapshot_date_utc"])

        cmap = load_canonical_map(conn)

        # Deterministically derive ranking_date_used per active source from source_rankings:
        # latest ranking_date (YYYY-MM-DD) on or before snapshot_date_utc.
        src_rows = conn.execute(
            """
            SELECT
              s.source_id,
              MAX(substr(sr.ranking_date, 1, 10)) AS ranking_date_used
            FROM sources s
            JOIN source_rankings sr
              ON sr.source_id = s.source_id
            WHERE s.is_active = 1
              AND sr.season_id = ?
              AND substr(sr.ranking_date, 1, 10) <= substr(?, 1, 10)
            GROUP BY s.source_id
            HAVING ranking_date_used IS NOT NULL
              AND length(trim(ranking_date_used)) >= 10
            ORDER BY s.source_id;
            """,
            (season_id, snapshot_date_utc),
        ).fetchall()

        if not src_rows:
            raise SystemExit("FAIL: no active sources with a ranking_date on/before snapshot_date_utc for this season")

        cov: Dict[int, set[int]] = {}

        for r in src_rows:
            sid = int(r["source_id"])
            rdu = str(r["ranking_date_used"])[:10]
            canon = canon_of(sid, cmap)

            rows = conn.execute(
                """
                SELECT spm.prospect_id
                FROM source_rankings sr
                JOIN source_player_map spm
                  ON spm.source_player_id = sr.source_player_id
                WHERE sr.source_id = ?
                  AND sr.season_id = ?
                  AND substr(sr.ranking_date, 1, 10) = substr(?, 1, 10);
                """,
                (sid, season_id, rdu),
            ).fetchall()

            for rr in rows:
                pid = int(rr["prospect_id"])
                cov.setdefault(pid, set()).add(canon)

        total = len(cov)
        cov_counts = [len(v) for v in cov.values()] if cov else []
        min_cov = min(cov_counts) if cov_counts else 0
        max_cov = max(cov_counts) if cov_counts else 0

        print(f"SNAPSHOT_ID: {snapshot_id}  SNAPSHOT_DATE_UTC: {snapshot_date_utc}")
        print(f"ACTIVE_SOURCES_WITH_DATES: {len(src_rows)}")
        print(f"CANONICAL_MAP: {'YES' if len(cmap) > 0 else 'NO'}")
        print(f"PROSPECTS_WITH_COVERAGE: {total}")
        print(f"COVERAGE_MIN_MAX: {min_cov}..{max_cov}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)
        else:
            row = conn.execute(
                "SELECT id, snapshot_date_utc FROM prospect_board_snapshots WHERE id = ? AND season_id = ? AND model_id = ?;",
                (args.snapshot_id, season_id, model_id),
            ).fetchone()
            if not row:
                raise SystemExit("FAIL: snapshot_id not found for this season/model")
            snapshot_id, snapshot_date_utc = int(row["id"]), str(row["snapshot_date_utc"])

        cmap = load_canonical_map(conn)

        src_rows = conn.execute(
            """
            SELECT
              s.source_id,
              MAX(substr(sr.ranking_date, 1, 10)) AS ranking_date_used
            FROM sources s
            JOIN source_rankings sr
              ON sr.source_id = s.source_id
            WHERE s.is_active = 1
              AND sr.season_id = ?
              AND substr(sr.ranking_date, 1, 10) <= substr(?, 1, 10)
            GROUP BY s.source_id
            HAVING ranking_date_used IS NOT NULL
              AND length(trim(ranking_date_used)) >= 10
            ORDER BY s.source_id;
            """,
            (season_id, snapshot_date_utc),
        ).fetchall()

        cov: Dict[int, set[int]] = {}
        for r in src_rows:
            sid = int(r["source_id"])
            rdu = str(r["ranking_date_used"])[:10]
            canon = canon_of(sid, cmap)

            rows = conn.execute(
                """
                SELECT spm.prospect_id
                FROM source_rankings sr
                JOIN source_player_map spm
                  ON spm.source_player_id = sr.source_player_id
                WHERE sr.source_id = ?
                  AND sr.season_id = ?
                  AND substr(sr.ranking_date, 1, 10) = substr(?, 1, 10);
                """,
                (sid, season_id, rdu),
            ).fetchall()

            for rr in rows:
                pid = int(rr["prospect_id"])
                cov.setdefault(pid, set()).add(canon)

        ts = utc_now_iso()

        n = 0
        conn.execute("BEGIN;")
        try:
            for pid, canon_set in cov.items():
                canon_list = sorted(int(x) for x in canon_set)
                conn.execute(
                    """
                    INSERT INTO prospect_board_snapshot_coverage(
                      snapshot_id, prospect_id, coverage_count, source_ids_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(snapshot_id, prospect_id) DO UPDATE SET
                      coverage_count = excluded.coverage_count,
                      source_ids_json = excluded.source_ids_json,
                      updated_at = excluded.updated_at;
                    """,
                    (
                        snapshot_id,
                        int(pid),
                        int(len(canon_list)),
                        json.dumps(canon_list, ensure_ascii=False),
                        ts,
                        ts,
                    ),
                )
                n += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    print(f"OK: snapshot coverage saved: snapshot_id={snapshot_id} rows={n}")


if __name__ == "__main__":
    main()