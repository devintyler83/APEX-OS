from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from draftos.normalize.names import normalize_whitespace
from draftos.normalize.positions import normalize_position_raw
from draftos.normalize.schools import normalize_school_raw


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon_col(s: str) -> str:
    return (
        s.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace(".", "")
    )


def _pick_col(cols: list[str], preferred: list[str]) -> str | None:
    cset = {_canon_col(c): c for c in cols}
    for p in preferred:
        if p in cset:
            return cset[p]
    return None


@dataclass(frozen=True)
class LoadedRow:
    raw_full_name: str
    raw_school: str | None
    raw_position: str | None
    raw_class_year: int | None
    overall_rank: int | None
    position_rank: int | None
    grade: float | None
    tier: str | None
    ranking_date: str | None
    raw_json: str
    ingested_at: str


def load_rankings_csv(
    csv_path: Path,
    *,
    col_name: str | None = None,
    col_school: str | None = None,
    col_position: str | None = None,
    col_class_year: str | None = None,
    col_overall_rank: str | None = None,
    col_position_rank: str | None = None,
    col_grade: str | None = None,
    col_tier: str | None = None,
    col_ranking_date: str | None = None,
) -> list[LoadedRow]:
    df = pl.read_csv(csv_path, ignore_errors=True)

    cols = df.columns

    # Heuristic column inference (override with CLI flags if needed)
    name_col = col_name or _pick_col(cols, ["player", "name", "full_name", "player_name"])
    school_col = col_school or _pick_col(cols, ["school", "college", "team"])
    pos_col = col_position or _pick_col(cols, ["pos", "position"])
    class_col = col_class_year or _pick_col(cols, ["class_year", "year", "draft_year", "class"])
    ovr_col = col_overall_rank or _pick_col(cols, ["overall_rank", "rank", "ovr_rank", "overall"])
    posr_col = col_position_rank or _pick_col(cols, ["position_rank", "pos_rank", "rank_pos"])
    grade_col = col_grade or _pick_col(cols, ["grade", "score"])
    tier_col = col_tier or _pick_col(cols, ["tier"])
    date_col = col_ranking_date or _pick_col(cols, ["ranking_date", "date", "as_of"])

    if not name_col:
        raise ValueError(
            f"Could not infer name column from: {cols}. "
            f"Provide --col-name explicitly."
        )

    ingested_at = _now_iso()

    rows: list[LoadedRow] = []
    for rec in df.to_dicts():
        raw_full_name = normalize_whitespace(str(rec.get(name_col, "") or "")).strip()
        if not raw_full_name:
            continue

        raw_school = normalize_school_raw(rec.get(school_col) if school_col else None)
        raw_position = normalize_position_raw(rec.get(pos_col) if pos_col else None)

        raw_class_year: int | None = None
        if class_col and rec.get(class_col) not in (None, ""):
            try:
                raw_class_year = int(rec.get(class_col))
            except Exception:
                raw_class_year = None

        def _to_int(x: Any) -> int | None:
            if x in (None, ""):
                return None
            try:
                return int(float(x))
            except Exception:
                return None

        def _to_float(x: Any) -> float | None:
            if x in (None, ""):
                return None
            try:
                return float(x)
            except Exception:
                return None

        overall_rank = _to_int(rec.get(ovr_col)) if ovr_col else None
        position_rank = _to_int(rec.get(posr_col)) if posr_col else None
        grade = _to_float(rec.get(grade_col)) if grade_col else None

        tier = None
        if tier_col and rec.get(tier_col) not in (None, ""):
            tier = normalize_whitespace(str(rec.get(tier_col)))

        ranking_date = None
        if date_col and rec.get(date_col) not in (None, ""):
            ranking_date = normalize_whitespace(str(rec.get(date_col)))

        # Store extra columns as JSON (exclude the mapped fields)
        used = {name_col, school_col, pos_col, class_col, ovr_col, posr_col, grade_col, tier_col, date_col}
        extra = {k: v for k, v in rec.items() if k not in used and v not in (None, "")}
        raw_json = json.dumps(extra, ensure_ascii=False)

        rows.append(
            LoadedRow(
                raw_full_name=raw_full_name,
                raw_school=raw_school,
                raw_position=raw_position,
                raw_class_year=raw_class_year,
                overall_rank=overall_rank,
                position_rank=position_rank,
                grade=grade,
                tier=tier,
                ranking_date=ranking_date,
                raw_json=raw_json,
                ingested_at=ingested_at,
            )
        )

    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="DraftOS: load rankings CSV (parse/normalize only, no DB writes)")
    ap.add_argument("--csv", required=True, help="Path to rankings CSV")
    ap.add_argument("--print-sample", type=int, default=10, help="Print first N parsed rows")

    # Optional explicit mappings
    ap.add_argument("--col-name", default=None)
    ap.add_argument("--col-school", default=None)
    ap.add_argument("--col-position", default=None)
    ap.add_argument("--col-class-year", default=None)
    ap.add_argument("--col-overall-rank", default=None)
    ap.add_argument("--col-position-rank", default=None)
    ap.add_argument("--col-grade", default=None)
    ap.add_argument("--col-tier", default=None)
    ap.add_argument("--col-ranking-date", default=None)

    args = ap.parse_args()
    rows = load_rankings_csv(
        Path(args.csv),
        col_name=args.col_name,
        col_school=args.col_school,
        col_position=args.col_position,
        col_class_year=args.col_class_year,
        col_overall_rank=args.col_overall_rank,
        col_position_rank=args.col_position_rank,
        col_grade=args.col_grade,
        col_tier=args.col_tier,
        col_ranking_date=args.col_ranking_date,
    )

    print(f"OK: loaded {len(rows)} rows from {args.csv}")
    for r in rows[: args.print_sample]:
        print(
            {
                "raw_full_name": r.raw_full_name,
                "raw_school": r.raw_school,
                "raw_position": r.raw_position,
                "overall_rank": r.overall_rank,
                "position_rank": r.position_rank,
                "grade": r.grade,
                "tier": r.tier,
                "ranking_date": r.ranking_date,
            }
        )


if __name__ == "__main__":
    main()