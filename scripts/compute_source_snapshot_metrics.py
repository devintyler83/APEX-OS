# scripts/compute_source_snapshot_metrics.py
from __future__ import annotations

import argparse
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_source_snapshot_metrics.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def column_names(conn, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return [r["name"] for r in rows]


def pick_first_existing(cols: set[str], *cands: str) -> Optional[str]:
    for c in cands:
        if c in cols:
            return c
    return None


def resolve_season_id(conn, draft_year: int) -> int:
    if not table_exists(conn, "seasons"):
        raise SystemExit("FAIL: seasons table not found")

    cols = set(column_names(conn, "seasons"))
    id_col = pick_first_existing(cols, "season_id", "id")
    year_col = pick_first_existing(cols, "draft_year", "year")
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
    if not table_exists(conn, "models"):
        raise SystemExit("FAIL: models table not found")

    cols = set(column_names(conn, "models"))
    id_col = pick_first_existing(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models missing id column. found={sorted(cols)}")

    if "season_id" in cols:
        key_col = pick_first_existing(cols, "model_key", "model_name", "name")
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

    name_col = pick_first_existing(cols, "name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name column. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS model_id FROM models WHERE {name_col} = ?;",
        (model_key_or_name,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")
    return int(row["model_id"])


def get_current_snapshot(conn, season_id: int, model_id: int) -> Tuple[int, str]:
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


def parse_yyyy_mm_dd(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s2 = s.strip()
    if not s2:
        return None
    # Accept "YYYY-MM-DD" or longer strings, we only trust the date portion.
    d = s2[:10]
    try:
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def mean(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    return sum(xs) / float(len(xs))


def compute_metrics_for_source(
    conn,
    snapshot_id: int,
    season_id: int,
    model_id: int,
    snapshot_date_utc: str,
    source_id: int,
    total_board: int,
    stale_days: int,
    coverage_min: float,
    mad_noisy: float,
) -> Dict[str, Any]:
    # Choose ranking_date_used: MAX(ranking_date) <= snapshot_date_utc
    row = conn.execute(
        """
        SELECT MAX(ranking_date) AS ranking_date_used
        FROM source_rankings
        WHERE source_id = ? AND season_id = ?
          AND ranking_date IS NOT NULL
          AND substr(ranking_date, 1, 10) <= substr(?, 1, 10);
        """,
        (source_id, season_id, snapshot_date_utc),
    ).fetchone()

    ranking_date_used = row["ranking_date_used"] if row else None
    used_dt = parse_yyyy_mm_dd(ranking_date_used)
    snap_dt = parse_yyyy_mm_dd(snapshot_date_utc)

    if not ranking_date_used:
        return {
            "snapshot_id": snapshot_id,
            "season_id": season_id,
            "model_id": model_id,
            "source_id": source_id,
            "ranking_date_used": None,
            "players_ranked": 0,
            "coverage_pct": 0.0,
            "avg_rank_diff": None,
            "mad_rank_diff": None,
            "stale_flag": 1,
            "health_chip": "Stale",
        }

    # Pull mapped prospects and compare to snapshot ranks.
    rows = conn.execute(
        """
        SELECT
          spm.prospect_id,
          sr.overall_rank AS source_rank,
          srow.rank_overall AS board_rank
        FROM source_rankings sr
        JOIN source_player_map spm
          ON spm.source_player_id = sr.source_player_id
        JOIN prospect_board_snapshot_rows srow
          ON srow.snapshot_id = ? AND srow.prospect_id = spm.prospect_id
        WHERE sr.source_id = ?
          AND sr.season_id = ?
          AND substr(sr.ranking_date, 1, 10) = substr(?, 1, 10);
        """,
        (snapshot_id, source_id, season_id, ranking_date_used),
    ).fetchall()

    players_ranked = len({int(r["prospect_id"]) for r in rows})
    coverage_pct = float(players_ranked) / float(total_board) if total_board > 0 else 0.0

    diffs: List[float] = []
    abs_diffs: List[float] = []
    for r in rows:
        srank = r["source_rank"]
        brank = r["board_rank"]
        if srank is None or brank is None:
            continue
        d = float(srank) - float(brank)
        diffs.append(d)
        abs_diffs.append(abs(d))

    avg_rank_diff = mean(diffs)
    mad_rank_diff = mean(abs_diffs)

    # Stale flag
    stale_flag = 0
    if snap_dt and used_dt:
        age_days = int((snap_dt - used_dt).total_seconds() // 86400)
        if age_days > stale_days:
            stale_flag = 1
    else:
        stale_flag = 1

    # Health chip
    if stale_flag == 1:
        health_chip = "Stale"
    elif coverage_pct < coverage_min:
        health_chip = "Thin Coverage"
    elif mad_rank_diff is not None and mad_rank_diff >= mad_noisy:
        health_chip = "Noisy"
    else:
        health_chip = "Healthy"

    return {
        "snapshot_id": snapshot_id,
        "season_id": season_id,
        "model_id": model_id,
        "source_id": source_id,
        "ranking_date_used": str(ranking_date_used)[:10],
        "players_ranked": int(players_ranked),
        "coverage_pct": float(coverage_pct),
        "avg_rank_diff": avg_rank_diff,
        "mad_rank_diff": mad_rank_diff,
        "stale_flag": int(stale_flag),
        "health_chip": health_chip,
    }


def list_active_sources(conn) -> List[int]:
    if not table_exists(conn, "sources"):
        raise SystemExit("FAIL: sources table not found")
    cols = set(column_names(conn, "sources"))
    if "is_active" in cols:
        rows = conn.execute("SELECT source_id FROM sources WHERE is_active = 1 ORDER BY source_id;").fetchall()
    else:
        rows = conn.execute("SELECT source_id FROM sources ORDER BY source_id;").fetchall()
    return [int(r["source_id"]) for r in rows]


def upsert_rows(conn, computed_at: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0

    snapshot_id = int(rows[0]["snapshot_id"])

    # Idempotent: clear metrics for snapshot, then insert.
    conn.execute("DELETE FROM source_board_snapshot_metrics WHERE snapshot_id = ?;", (snapshot_id,))

    for r in rows:
        conn.execute(
            """
            INSERT INTO source_board_snapshot_metrics(
              snapshot_id, season_id, model_id, source_id,
              ranking_date_used, players_ranked, coverage_pct,
              avg_rank_diff, mad_rank_diff,
              stale_flag, health_chip,
              computed_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_id, source_id)
            DO UPDATE SET
              ranking_date_used = excluded.ranking_date_used,
              players_ranked = excluded.players_ranked,
              coverage_pct = excluded.coverage_pct,
              avg_rank_diff = excluded.avg_rank_diff,
              mad_rank_diff = excluded.mad_rank_diff,
              stale_flag = excluded.stale_flag,
              health_chip = excluded.health_chip,
              computed_at_utc = excluded.computed_at_utc;
            """,
            (
                r["snapshot_id"],
                r["season_id"],
                r["model_id"],
                r["source_id"],
                r["ranking_date_used"],
                r["players_ranked"],
                r["coverage_pct"],
                r["avg_rank_diff"],
                r["mad_rank_diff"],
                r["stale_flag"],
                r["health_chip"],
                computed_at,
            ),
        )

    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute per-source snapshot metrics (coverage + drift + staleness).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--snapshot-id", type=int, default=None, help="Optional explicit snapshot_id. Default: latest.")
    ap.add_argument("--stale-days", type=int, default=7)
    ap.add_argument("--coverage-min", type=float, default=0.50)
    ap.add_argument("--mad-noisy", type=float, default=50.0)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1], help="--apply 1 writes. --apply 0 dry run.")
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        if not table_exists(conn, "source_board_snapshot_metrics"):
            raise SystemExit("FAIL: source_board_snapshot_metrics table not found. Apply migration 0004 first.")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, snapshot_date_utc = get_current_snapshot(conn, season_id, model_id)
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

        total_board = conn.execute(
            "SELECT COUNT(*) AS n FROM prospect_board_snapshot_rows WHERE snapshot_id = ?;",
            (snapshot_id,),
        ).fetchone()["n"]

        source_ids = list_active_sources(conn)

        computed_at = utc_now_iso()
        metrics_rows: List[Dict[str, Any]] = []
        for sid in source_ids:
            metrics_rows.append(
                compute_metrics_for_source(
                    conn=conn,
                    snapshot_id=snapshot_id,
                    season_id=season_id,
                    model_id=model_id,
                    snapshot_date_utc=snapshot_date_utc,
                    source_id=sid,
                    total_board=int(total_board),
                    stale_days=int(args.stale_days),
                    coverage_min=float(args.coverage_min),
                    mad_noisy=float(args.mad_noisy),
                )
            )

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            print(
                f"PLAN: would compute source metrics snapshot_id={snapshot_id} date_utc={snapshot_date_utc} sources={len(metrics_rows)}"
            )
            stale = sum(1 for r in metrics_rows if int(r["stale_flag"]) == 1)
            thin = sum(1 for r in metrics_rows if r["health_chip"] == "Thin Coverage")
            noisy = sum(1 for r in metrics_rows if r["health_chip"] == "Noisy")
            healthy = sum(1 for r in metrics_rows if r["health_chip"] == "Healthy")
            print(f"PLAN: chips Healthy={healthy} Thin={thin} Noisy={noisy} Stale={stale}")
            ex = metrics_rows[0]
            print(
                "EXAMPLE:",
                f"source_id={ex['source_id']}",
                f"ranking_date_used={ex['ranking_date_used']}",
                f"coverage_pct={ex['coverage_pct']:.3f}",
                f"mad_rank_diff={ex['mad_rank_diff']}",
                f"chip={ex['health_chip']}",
            )
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, snapshot_date_utc = get_current_snapshot(conn, season_id, model_id)
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

        total_board = conn.execute(
            "SELECT COUNT(*) AS n FROM prospect_board_snapshot_rows WHERE snapshot_id = ?;",
            (snapshot_id,),
        ).fetchone()["n"]

        source_ids = list_active_sources(conn)

        computed_at = utc_now_iso()
        metrics_rows = []
        for sid in source_ids:
            metrics_rows.append(
                compute_metrics_for_source(
                    conn=conn,
                    snapshot_id=snapshot_id,
                    season_id=season_id,
                    model_id=model_id,
                    snapshot_date_utc=snapshot_date_utc,
                    source_id=sid,
                    total_board=int(total_board),
                    stale_days=int(args.stale_days),
                    coverage_min=float(args.coverage_min),
                    mad_noisy=float(args.mad_noisy),
                )
            )

        n = upsert_rows(conn, computed_at, metrics_rows)
        conn.commit()

    print(f"OK: source snapshot metrics saved: snapshot_id={snapshot_id} sources={n}")


if __name__ == "__main__":
    main()