# scripts/export_board_csv.py
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Optional, Tuple, List

from draftos.db.connect import connect


def table_cols(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def pick_col(cols: set[str], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return None


def get_ids(conn, season: int, model: str) -> Tuple[int, int]:
    # seasons: season_id or id; draft_year or year
    s_cols = table_cols(conn, "seasons")
    s_id = "season_id" if "season_id" in s_cols else "id"
    s_year = "draft_year" if "draft_year" in s_cols else "year"

    row = conn.execute(
        f"SELECT {s_id} AS season_id FROM seasons WHERE {s_year} = ?;",
        (season,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found: {season}")
    season_id = int(row["season_id"])

    m_cols = table_cols(conn, "models")
    m_id = "model_id" if "model_id" in m_cols else "id"

    # season-scoped models if season_id column exists
    if "season_id" in m_cols:
        key_col = pick_col(m_cols, ["model_key", "model_name", "name"])
        if not key_col:
            raise SystemExit("FAIL: models missing model key/name column")

        row = conn.execute(
            f"SELECT {m_id} AS model_id FROM models WHERE season_id = ? AND {key_col} = ?;",
            (season_id, model),
        ).fetchone()
        if row:
            return season_id, int(row["model_id"])

        # fallback try alternates
        for alt in ["model_key", "model_name", "name"]:
            if alt in m_cols:
                row2 = conn.execute(
                    f"SELECT {m_id} AS model_id FROM models WHERE season_id = ? AND {alt} = ?;",
                    (season_id, model),
                ).fetchone()
                if row2:
                    return season_id, int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season={season} model={model}")

    # fallback: non-season-scoped models
    name_col = "name" if "name" in m_cols else None
    if not name_col:
        raise SystemExit("FAIL: models table missing name")
    row = conn.execute(
        f"SELECT {m_id} AS model_id FROM models WHERE {name_col} = ?;",
        (model,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found: {model}")
    return season_id, int(row["model_id"])


def latest_snapshot_ids(conn, season_id: int, model_id: int) -> Tuple[int, Optional[int]]:
    cur = conn.execute(
        """
        SELECT id, snapshot_date_utc
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
        ORDER BY snapshot_date_utc DESC, id DESC
        LIMIT 1;
        """,
        (season_id, model_id),
    ).fetchone()
    if not cur:
        return -1, None

    prev = conn.execute(
        """
        SELECT id
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
          AND (snapshot_date_utc < ? OR (snapshot_date_utc = ? AND id < ?))
        ORDER BY snapshot_date_utc DESC, id DESC
        LIMIT 1;
        """,
        (season_id, model_id, cur["snapshot_date_utc"], cur["snapshot_date_utc"], cur["id"]),
    ).fetchone()

    return int(cur["id"]), (int(prev["id"]) if prev else None)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export board CSV with deltas + snapshot metrics + confidence.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--window", type=int, default=3)
    args = ap.parse_args()

    exports_dir = Path("exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    out_path = exports_dir / f"board_{args.season}_{args.model}.csv"

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id, model_id = get_ids(conn, args.season, args.model)
        cur_snap_id, prev_snap_id = latest_snapshot_ids(conn, season_id, model_id)
        if cur_snap_id == -1:
            raise SystemExit("FAIL: no snapshots found. Run snapshot_board first.")

        # Detect prospects name column (schema-adaptive)
        p_cols = table_cols(conn, "prospects")
        name_col = pick_col(p_cols, ["full_name", "display_name", "name"])
        if not name_col:
            raise SystemExit("FAIL: prospects missing name column (expected full_name/display_name/name)")

        # Detect snapshot metrics column names (schema-adaptive)
        sm_cols = table_cols(conn, "prospect_board_snapshot_metrics")

        momentum_rank_col = pick_col(sm_cols, ["momentum_rank", "momentum_rank_delta", "momentum_rank_change"])
        momentum_score_col = pick_col(sm_cols, ["momentum_score", "momentum_score_delta", "momentum_score_change"])

        vol_mad_col = pick_col(
            sm_cols,
            ["volatility_rank_mad", "volatility_mad", "volatility_mad_rank", "volatility_mad_diff"],
        )
        vol_std_col = pick_col(
            sm_cols,
            ["volatility_rank_std", "volatility_std", "volatility_std_rank", "volatility_std_diff"],
        )

        momentum_chip_col = pick_col(sm_cols, ["momentum_chip", "momentum_label"])
        volatility_chip_col = pick_col(sm_cols, ["volatility_chip", "volatility_label"])

        def sel(col: Optional[str], alias: str) -> str:
            return f"sm.{col} AS {alias}" if col else f"NULL AS {alias}"

        sm_select = ",\n              ".join(
            [
                sel(momentum_rank_col, "momentum_rank_window"),
                sel(momentum_score_col, "momentum_score_window"),
                sel(vol_mad_col, "volatility_rank_mad_window"),
                sel(vol_std_col, "volatility_rank_std_window"),
                sel(momentum_chip_col, "momentum_chip"),
                sel(volatility_chip_col, "volatility_chip"),
            ]
        )

        prev_id = prev_snap_id if prev_snap_id is not None else -1

        rows = conn.execute(
            f"""
            WITH cur AS (
              SELECT
                r.snapshot_id,
                r.prospect_id,
                r.rank_overall,
                r.score,
                r.tier,
                r.coverage_count
              FROM prospect_board_snapshot_rows r
              WHERE r.snapshot_id = ?
            ),
            prev AS (
              SELECT
                r.prospect_id,
                r.rank_overall AS prev_rank_overall,
                r.score AS prev_score,
                r.coverage_count AS prev_coverage_count
              FROM prospect_board_snapshot_rows r
              WHERE r.snapshot_id = ?
            )
            SELECT
              cur.prospect_id,
              p.{name_col} AS player_name,
              cur.rank_overall,
              cur.score,
              cur.tier,
              cur.coverage_count,

              CASE
                WHEN prev.prev_rank_overall IS NULL THEN ''
                ELSE CAST((prev.prev_rank_overall - cur.rank_overall) AS TEXT)
              END AS delta_rank,

              CASE
                WHEN prev.prev_score IS NULL THEN ''
                ELSE CAST((cur.score - prev.prev_score) AS TEXT)
              END AS delta_score,

              CASE
                WHEN prev.prev_coverage_count IS NULL OR cur.coverage_count IS NULL THEN ''
                ELSE CAST((cur.coverage_count - prev.prev_coverage_count) AS TEXT)
              END AS delta_coverage,

              {sm_select},

              cf.active_sources,
              cf.sources_present,
              cf.coverage_pct AS confidence_coverage_pct,
              cf.rank_std AS confidence_rank_std,
              cf.rank_mad AS confidence_rank_mad,
              cf.confidence_score,
              cf.confidence_band,
              cf.confidence_reasons_json
            FROM cur
            JOIN prospects p
              ON p.prospect_id = cur.prospect_id
            LEFT JOIN prev
              ON prev.prospect_id = cur.prospect_id
            LEFT JOIN prospect_board_snapshot_metrics sm
              ON sm.snapshot_id = cur.snapshot_id
             AND sm.prospect_id = cur.prospect_id
             AND sm.window_n = ?
            LEFT JOIN prospect_board_snapshot_confidence cf
              ON cf.snapshot_id = cur.snapshot_id
             AND cf.prospect_id = cur.prospect_id
            ORDER BY cur.rank_overall ASC;
            """,
            (cur_snap_id, prev_id, args.window),
        ).fetchall()

    header = [
        "prospect_id",
        "player_name",
        "rank_overall",
        "delta_rank",
        "score",
        "delta_score",
        "tier",
        "coverage_count",
        "delta_coverage",
        f"momentum_rank_{args.window}",
        f"momentum_score_{args.window}",
        f"volatility_rank_mad_{args.window}",
        f"volatility_rank_std_{args.window}",
        "momentum_chip",
        "volatility_chip",
        "confidence_score",
        "confidence_band",
        "confidence_reasons_json",
        "confidence_coverage_pct",
        "confidence_rank_std",
        "confidence_rank_mad",
        "confidence_sources_present",
        "confidence_active_sources",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            d = dict(r)
            out = {
                "prospect_id": d.get("prospect_id", ""),
                "player_name": d.get("player_name", ""),
                "rank_overall": d.get("rank_overall", ""),
                "delta_rank": d.get("delta_rank", ""),
                "score": d.get("score", ""),
                "delta_score": d.get("delta_score", ""),
                "tier": d.get("tier", ""),
                "coverage_count": d.get("coverage_count", ""),
                "delta_coverage": d.get("delta_coverage", ""),
                f"momentum_rank_{args.window}": d.get("momentum_rank_window", ""),
                f"momentum_score_{args.window}": d.get("momentum_score_window", ""),
                f"volatility_rank_mad_{args.window}": d.get("volatility_rank_mad_window", ""),
                f"volatility_rank_std_{args.window}": d.get("volatility_rank_std_window", ""),
                "momentum_chip": d.get("momentum_chip", ""),
                "volatility_chip": d.get("volatility_chip", ""),
                "confidence_score": d.get("confidence_score", ""),
                "confidence_band": d.get("confidence_band", ""),
                "confidence_reasons_json": d.get("confidence_reasons_json", ""),
                "confidence_coverage_pct": d.get("confidence_coverage_pct", ""),
                "confidence_rank_std": d.get("confidence_rank_std", ""),
                "confidence_rank_mad": d.get("confidence_rank_mad", ""),
                "confidence_sources_present": d.get("sources_present", ""),
                "confidence_active_sources": d.get("active_sources", ""),
            }
            w.writerow(out)

    print(f"OK: exported: {out_path}")
    print(f"OK: deltas: current_snapshot_id={cur_snap_id} previous_snapshot_id={prev_snap_id}")


if __name__ == "__main__":
    main()