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


def main() -> None:
    ap = argparse.ArgumentParser(description="Export confidence summary for the latest snapshot.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--elite-top", type=int, default=100, help="Consider top N board ranks as elite set.")
    ap.add_argument("--elite-show", type=int, default=25, help="Show worst confidence among elite set.")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    out_dir = PATHS.root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_date_yyyymmdd()
    out_path = Path(args.out) if args.out else out_dir / f"confidence_summary_{stamp}_{args.season}_{args.model}.csv"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        required = [
            "prospect_board_snapshots",
            "prospect_board_snapshot_rows",
            "prospect_board_snapshot_confidence",
            "prospects",
            "seasons",
            "models",
        ]
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)
        snapshot_id, snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)

        band_counts = conn.execute(
            """
            SELECT confidence_band, COUNT(*) AS n
            FROM prospect_board_snapshot_confidence
            WHERE snapshot_id = ?
            GROUP BY confidence_band
            ORDER BY confidence_band;
            """,
            (snapshot_id,),
        ).fetchall()
        band_map = {str(r["confidence_band"]): int(r["n"]) for r in band_counts}
        high_n = band_map.get("High", 0)
        med_n = band_map.get("Medium", 0)
        low_n = band_map.get("Low", 0)

        prospect_cols = set(colnames(conn, "prospects"))
        pos_col = pick_first(prospect_cols, "position_group", "position", "pos", "position_code")
        school_col = pick_first(prospect_cols, "school_canonical", "school", "college", "school_name")
        name_col = pick_first(prospect_cols, "full_name", "display_name")

        if not name_col:
            raise SystemExit(f"FAIL: prospects missing name column. found={sorted(prospect_cols)}")

        pos_expr = f"p.{pos_col} AS position" if pos_col else "NULL AS position"
        school_expr = f"p.{school_col} AS school" if school_col else "NULL AS school"

        elite_rows = conn.execute(
            f"""
            SELECT
              r.rank_overall,
              p.prospect_id,
              p.{name_col} AS full_name,
              {pos_expr},
              {school_expr},
              c.confidence_score,
              c.confidence_band,
              c.sources_present,
              c.active_sources,
              c.coverage_pct
            FROM prospect_board_snapshot_rows r
            JOIN prospects p
              ON p.prospect_id = r.prospect_id
            JOIN prospect_board_snapshot_confidence c
              ON c.snapshot_id = r.snapshot_id AND c.prospect_id = r.prospect_id
            WHERE r.snapshot_id = ?
              AND r.rank_overall IS NOT NULL
              AND r.rank_overall <= ?
            ORDER BY c.confidence_score ASC, r.rank_overall ASC
            LIMIT ?;
            """,
            (snapshot_id, args.elite_top, args.elite_show),
        ).fetchall()

    fieldnames = [
        "snapshot_id",
        "snapshot_date_utc",
        "season",
        "model",
        "band_high_n",
        "band_medium_n",
        "band_low_n",
        "elite_top_n",
        "elite_show_n",
        "elite_rank_overall",
        "elite_prospect_id",
        "elite_full_name",
        "elite_position",
        "elite_school",
        "elite_confidence_score",
        "elite_confidence_band",
        "elite_sources_present",
        "elite_active_sources",
        "elite_coverage_pct",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        if not elite_rows:
            w.writerow(
                {
                    "snapshot_id": snapshot_id,
                    "snapshot_date_utc": snapshot_date_utc,
                    "season": args.season,
                    "model": args.model,
                    "band_high_n": high_n,
                    "band_medium_n": med_n,
                    "band_low_n": low_n,
                    "elite_top_n": args.elite_top,
                    "elite_show_n": args.elite_show,
                }
            )
        else:
            for er in elite_rows:
                w.writerow(
                    {
                        "snapshot_id": snapshot_id,
                        "snapshot_date_utc": snapshot_date_utc,
                        "season": args.season,
                        "model": args.model,
                        "band_high_n": high_n,
                        "band_medium_n": med_n,
                        "band_low_n": low_n,
                        "elite_top_n": args.elite_top,
                        "elite_show_n": args.elite_show,
                        "elite_rank_overall": int(er["rank_overall"]),
                        "elite_prospect_id": int(er["prospect_id"]),
                        "elite_full_name": er["full_name"],
                        "elite_position": er["position"],
                        "elite_school": er["school"],
                        "elite_confidence_score": er["confidence_score"],
                        "elite_confidence_band": er["confidence_band"],
                        "elite_sources_present": int(er["sources_present"]),
                        "elite_active_sources": int(er["active_sources"]),
                        "elite_coverage_pct": er["coverage_pct"],
                    }
                )

    print(f"OK: exported confidence summary: {out_path}")


if __name__ == "__main__":
    main()