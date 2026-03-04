# scripts/export_movers_csv.py
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Optional, Set


from draftos.db.connect import connect


def _to_int(v: str) -> int:
    v = (v or "").strip()
    if v == "":
        return 0
    try:
        return int(float(v))
    except Exception:
        return 0


def _to_float(v: str) -> float:
    v = (v or "").strip()
    if v == "":
        return 0.0
    try:
        return float(v)
    except Exception:
        return 0.0


def load_board(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"FAIL: board export not found: {path}")
    # board exporter writes utf-8 without BOM; tolerate either
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})
    print(f"OK: exported: {path}")


def table_cols(conn, table: str) -> Set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def pick_col(cols: Set[str], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return None


def load_prospect_names(prospect_ids: List[int]) -> Dict[int, str]:
    """
    Read-only enrichment: map prospect_id -> full_name (or best available)
    This is EXPORTS-layer safe and guarantees names even if upstream CSV is missing them.
    """
    if not prospect_ids:
        return {}

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        p_cols = table_cols(conn, "prospects")
        name_col = pick_col(p_cols, ["full_name", "display_name", "name"])
        if not name_col:
            return {}

        placeholders = ",".join(["?"] * len(prospect_ids))
        rows = conn.execute(
            f"SELECT prospect_id, {name_col} AS full_name FROM prospects WHERE prospect_id IN ({placeholders});",
            tuple(prospect_ids),
        ).fetchall()

        out: Dict[int, str] = {}
        for r in rows:
            out[int(r["prospect_id"])] = (r["full_name"] or "").strip()
        return out


def _nonzero_int_field(r: Dict[str, str], key: str) -> bool:
    return _to_int(r.get(key, "")) != 0


def _nonzero_float_field(r: Dict[str, str], key: str) -> bool:
    return abs(_to_float(r.get(key, ""))) > 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Export movers/volatility CSVs from board export.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    exports_dir = Path("exports")
    board_path = exports_dir / f"board_{args.season}_{args.model}.csv"
    rows = load_board(board_path)

    # Ensure season/model present and normalize IDs
    prospect_ids: List[int] = []
    for r in rows:
        r["season"] = str(args.season)
        r["model"] = str(args.model)

        pid = _to_int(r.get("prospect_id", ""))
        if pid > 0:
            prospect_ids.append(pid)

    # Read-only fallback name enrichment (only if needed)
    name_map = load_prospect_names(sorted(set(prospect_ids)))

    for r in rows:
        pn = (r.get("player_name") or "").strip()
        if pn == "":
            pid = _to_int(r.get("prospect_id", ""))
            r["player_name"] = name_map.get(pid, "")

    # Common export header (keeps existing columns, adds confidence fields already present on board)
    header_common = [
        "season",
        "model",
        "prospect_id",
        "player_name",
        "rank_overall",
        "score",
        "tier",
        "coverage_count",
        "delta_rank",
        "delta_score",
        "delta_coverage",
        f"momentum_rank_{args.window}",
        f"momentum_score_{args.window}",
        f"volatility_rank_mad_{args.window}",
        f"volatility_rank_std_{args.window}",
        "momentum_chip",
        "volatility_chip",
        "confidence_score",
        "confidence_band",
        "confidence_coverage_pct",
        "confidence_rank_std",
        "confidence_rank_mad",
        "confidence_sources_present",
        "confidence_active_sources",
    ]

    # -----------------------------
    # 1) Daily movers (delta_rank)
    # -----------------------------
    daily_pool = [r for r in rows if _nonzero_int_field(r, "delta_rank")]

    risers_daily = sorted(
        daily_pool,
        key=lambda r: (_to_int(r.get("delta_rank", "")), -_to_int(r.get("rank_overall", "0"))),
        reverse=True,
    )
    fallers_daily = sorted(
        daily_pool,
        key=lambda r: (_to_int(r.get("delta_rank", "")), _to_int(r.get("rank_overall", "0"))),
    )

    movers_daily = risers_daily[: args.top] + fallers_daily[: args.top]
    out_daily = exports_dir / f"movers_daily_{args.season}_{args.model}.csv"
    write_csv(out_daily, header_common, movers_daily)

    # -----------------------------------------
    # 2) Window movers (momentum_rank_{window})
    # -----------------------------------------
    mom_col = f"momentum_rank_{args.window}"
    win_pool = [r for r in rows if _nonzero_int_field(r, mom_col)]

    risers_win = sorted(
        win_pool,
        key=lambda r: (_to_int(r.get(mom_col, "")), -_to_int(r.get("rank_overall", "0"))),
        reverse=True,
    )
    fallers_win = sorted(
        win_pool,
        key=lambda r: (_to_int(r.get(mom_col, "")), _to_int(r.get("rank_overall", "0"))),
    )

    movers_win = risers_win[: args.top] + fallers_win[: args.top]
    out_win = exports_dir / f"movers_window{args.window}_{args.season}_{args.model}.csv"
    write_csv(out_win, header_common, movers_win)

    # -----------------------------
    # 3) Volatility (rank MAD)
    # -----------------------------
    vol_col = f"volatility_rank_mad_{args.window}"
    vol_pool = [r for r in rows if _to_float(r.get(vol_col, "")) > 0.0]

    vol_rows = sorted(
        vol_pool,
        key=lambda r: (_to_float(r.get(vol_col, "")), -_to_int(r.get("rank_overall", "0"))),
        reverse=True,
    )
    out_vol = exports_dir / f"volatility_window{args.window}_{args.season}_{args.model}.csv"
    write_csv(out_vol, header_common, vol_rows[: (args.top * 2)])

    # --------------------------------
    # 4) NEW: Score movers (delta_score)
    # --------------------------------
    score_pool = [r for r in rows if _nonzero_float_field(r, "delta_score")]

    risers_score = sorted(
        score_pool,
        key=lambda r: (_to_float(r.get("delta_score", "")), -_to_int(r.get("rank_overall", "0"))),
        reverse=True,
    )
    fallers_score = sorted(
        score_pool,
        key=lambda r: (_to_float(r.get("delta_score", "")), _to_int(r.get("rank_overall", "0"))),
    )

    movers_score = risers_score[: args.top] + fallers_score[: args.top]
    out_score = exports_dir / f"movers_score_daily_{args.season}_{args.model}.csv"
    write_csv(out_score, header_common, movers_score)

    # --------------------------------------
    # 5) NEW: Coverage movers (delta_coverage)
    # --------------------------------------
    cov_pool = [r for r in rows if _nonzero_int_field(r, "delta_coverage")]

    risers_cov = sorted(
        cov_pool,
        key=lambda r: (_to_int(r.get("delta_coverage", "")), -_to_int(r.get("rank_overall", "0"))),
        reverse=True,
    )
    fallers_cov = sorted(
        cov_pool,
        key=lambda r: (_to_int(r.get("delta_coverage", "")), _to_int(r.get("rank_overall", "0"))),
    )

    movers_cov = risers_cov[: args.top] + fallers_cov[: args.top]
    out_cov = exports_dir / f"movers_coverage_daily_{args.season}_{args.model}.csv"
    write_csv(out_cov, header_common, movers_cov)


if __name__ == "__main__":
    main()