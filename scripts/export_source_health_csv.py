from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_date_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?;",
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

    name_col = pick_first(cols, "name", "model_key", "model_name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name/key column. found={sorted(cols)}")

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


def select_expr(cols: set[str], preferred: List[str], alias: str) -> str:
    c = pick_first(cols, *preferred)
    if c:
        return f"m.{c} AS {alias}"
    return f"NULL AS {alias}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Export source health diagnostics for the latest snapshot.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    out_dir = PATHS.root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_date_yyyymmdd()
    out_path = Path(args.out) if args.out else out_dir / f"source_health_{stamp}_{args.season}_{args.model}.csv"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        required = ["prospect_board_snapshots", "source_board_snapshot_metrics", "sources", "seasons", "models"]
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)
        snapshot_id, snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)

        metric_cols = set(colnames(conn, "source_board_snapshot_metrics"))

        coverage_expr = select_expr(
            metric_cols,
            ["coverage_pct", "coverage_percent", "coverage_ratio", "coverage"],
            "coverage_pct",
        )
        mad_expr = select_expr(
            metric_cols,
            ["mad_diff", "mad_rank_diff", "mad_overall_diff", "mad_delta", "mad"],
            "mad_diff",
        )
        stale_expr = select_expr(
            metric_cols,
            ["is_stale", "stale_flag", "stale"],
            "is_stale",
        )
        rdu_expr = select_expr(
            metric_cols,
            ["ranking_date_used", "ranking_date", "ranking_date_utc"],
            "ranking_date_used",
        )
        chip_expr = select_expr(
            metric_cols,
            ["health_chip", "chip", "health_label"],
            "health_chip",
        )

        q = f"""
            SELECT
              s.source_id,
              s.source_name,
              s.source_type,
              s.url,
              s.is_active,
              {rdu_expr},
              {coverage_expr},
              {mad_expr},
              {stale_expr},
              {chip_expr}
            FROM source_board_snapshot_metrics m
            JOIN sources s
              ON s.source_id = m.source_id
            WHERE m.snapshot_id = ?
            ORDER BY s.is_active DESC, health_chip, s.source_id;
        """

        rows = conn.execute(q, (snapshot_id,)).fetchall()

    fieldnames = [
        "snapshot_id",
        "snapshot_date_utc",
        "season",
        "model",
        "source_id",
        "source_name",
        "source_type",
        "url",
        "is_active",
        "ranking_date_used",
        "coverage_pct",
        "mad_diff",
        "is_stale",
        "health_chip",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "snapshot_id": snapshot_id,
                    "snapshot_date_utc": snapshot_date_utc,
                    "season": args.season,
                    "model": args.model,
                    "source_id": int(r["source_id"]),
                    "source_name": r["source_name"],
                    "source_type": r["source_type"],
                    "url": r["url"],
                    "is_active": int(r["is_active"]) if r["is_active"] is not None else None,
                    "ranking_date_used": r["ranking_date_used"],
                    "coverage_pct": r["coverage_pct"],
                    "mad_diff": r["mad_diff"],
                    "is_stale": r["is_stale"],
                    "health_chip": r["health_chip"],
                }
            )

    print(f"OK: exported source health: {out_path}")


if __name__ == "__main__":
    main()