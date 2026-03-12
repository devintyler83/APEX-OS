from __future__ import annotations

# --- sys.path bootstrap so "python -m scripts.ingest_ngs_2026" always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from draftos.config import PATHS
from draftos.db.connect import connect

# ── Constants ──────────────────────────────────────────────────────────────────
SEASON_ID = 1
SOURCE_KEY = "ngs_2026"
SOURCE_NOTES = (
    "NFL Next Gen Stats 2026 draft class scores. "
    "ngs_score (50-99 composite) stored in grade column. "
    "ngs_position_rank stored in position_rank. "
    "overall_rank derived from ngs_score DESC order. "
    "T2 weight (1.0). Added Session 23."
)
CSV_PATH = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "ngs_2026.csv"


# ── Utilities ──────────────────────────────────────────────────────────────────

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def backup_db(reason: str) -> Path:
    src = PATHS.db
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"draftos_{ts}_{reason}.sqlite"
    dst.write_bytes(Path(src).read_bytes())
    return dst


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read CSV as UTF-8 (NGS encoding confirmed)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def stable_source_player_key(name: str, school: str, position: str) -> str:
    import re
    def k(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s
    base = f"{k(name)}|{k(school)}|{k(position)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def parse_float(val) -> Optional[float]:
    s = str(val or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_int(val) -> Optional[int]:
    s = str(val or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


# ── Source record ──────────────────────────────────────────────────────────────

def ensure_source(conn) -> int:
    """INSERT OR IGNORE the ngs_2026 source. Return source_id."""
    conn.execute(
        """
        INSERT OR IGNORE INTO sources (source_name, source_type, notes, is_active)
        VALUES (?, ?, ?, ?)
        """,
        (SOURCE_KEY, "ranking", SOURCE_NOTES, 1),
    )
    row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name = ?", (SOURCE_KEY,)
    ).fetchone()
    return int(row["source_id"])


# ── Derived overall_rank from ngs_score ───────────────────────────────────────

def derive_overall_ranks(rows: List[Dict[str, str]]) -> Dict[int, int]:
    """
    Sort all rows by ngs_score DESC and assign overall_rank 1, 2, 3...
    Returns {row_index → overall_rank}.
    Rows with no ngs_score are excluded from ranking.
    Ties in ngs_score maintain stable order (original CSV order).
    """
    scored = []
    for i, row in enumerate(rows):
        score = parse_float(row.get("ngs_score"))
        if score is not None:
            scored.append((i, score))

    # Sort by score descending, stable (preserves original order for ties)
    scored.sort(key=lambda x: x[1], reverse=True)

    return {idx: rank for rank, (idx, _) in enumerate(scored, start=1)}


# ── Rankings ingest ───────────────────────────────────────────────────────────

def run_ingest(
    conn,
    rows: List[Dict[str, str]],
    source_id: int,
    apply: bool,
    ingested_at: str,
    ranking_date: str,
) -> Dict:
    """Write source_players + source_rankings for ngs_2026."""
    overall_rank_map = derive_overall_ranks(rows)

    players_new = 0
    players_exist = 0
    rankings_new = 0
    rankings_exist = 0
    skipped_no_score = 0
    sample_rows = []

    for i, row in enumerate(rows):
        name_raw = (row.get("name") or "").strip()
        school_raw = (row.get("school") or "").strip()
        position_raw = (row.get("position") or "").strip()
        ngs_score = parse_float(row.get("ngs_score"))
        ngs_pos_rank = parse_int(row.get("ngs_position_rank"))

        if not name_raw or ngs_score is None:
            skipped_no_score += 1
            continue

        overall_rank = overall_rank_map.get(i)
        player_key = stable_source_player_key(name_raw, school_raw, position_raw)

        # Check source_player existence
        existing_sp = conn.execute(
            "SELECT source_player_id FROM source_players "
            "WHERE source_id=? AND season_id=? AND source_player_key=?",
            (source_id, SEASON_ID, player_key),
        ).fetchone()

        if existing_sp:
            spid = int(existing_sp["source_player_id"])
            players_exist += 1
        else:
            players_new += 1
            if apply:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_players(
                      source_id, season_id, source_player_key,
                      raw_full_name, raw_school, raw_position,
                      raw_class_year, raw_json, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id, SEASON_ID, player_key,
                        name_raw, school_raw, position_raw,
                        None,
                        json.dumps({
                            "name": name_raw, "school": school_raw,
                            "position": position_raw, "ngs_score": ngs_score,
                            "ngs_position_rank": ngs_pos_rank,
                        }, ensure_ascii=False),
                        ingested_at,
                    ),
                )
                sp_row = conn.execute(
                    "SELECT source_player_id FROM source_players "
                    "WHERE source_id=? AND season_id=? AND source_player_key=?",
                    (source_id, SEASON_ID, player_key),
                ).fetchone()
                spid = int(sp_row["source_player_id"])
            else:
                spid = -1  # placeholder in dry run

        # source_rankings
        if apply and spid > 0:
            existing_rank = conn.execute(
                "SELECT 1 FROM source_rankings "
                "WHERE source_id=? AND season_id=? AND source_player_id=? AND ranking_date=?",
                (source_id, SEASON_ID, spid, ranking_date),
            ).fetchone()
            if existing_rank:
                rankings_exist += 1
            else:
                rankings_new += 1
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_rankings(
                      source_id, season_id, source_player_id,
                      overall_rank, position_rank, position_raw,
                      grade, tier, ranking_date, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id, SEASON_ID, spid,
                        overall_rank, ngs_pos_rank, position_raw,
                        ngs_score, None, ranking_date, ingested_at,
                    ),
                )
        elif not apply:
            if existing_sp:
                sp_check = conn.execute(
                    "SELECT source_player_id FROM source_players "
                    "WHERE source_id=? AND season_id=? AND source_player_key=?",
                    (source_id, SEASON_ID, player_key),
                ).fetchone()
                if sp_check:
                    rank_check = conn.execute(
                        "SELECT 1 FROM source_rankings "
                        "WHERE source_id=? AND season_id=? AND source_player_id=? AND ranking_date=?",
                        (source_id, SEASON_ID, int(sp_check["source_player_id"]), ranking_date),
                    ).fetchone()
                    if rank_check:
                        rankings_exist += 1
                    else:
                        rankings_new += 1
            else:
                rankings_new += 1

        # Collect sample rows (first 5 with high ngs_score)
        if len(sample_rows) < 5 and ngs_score is not None and overall_rank is not None and overall_rank <= 10:
            sample_rows.append(
                f"  {name_raw} ({position_raw})  ngs_score={ngs_score}"
                f"  pos_rank={ngs_pos_rank}  overall_rank={overall_rank}"
            )

    return {
        "players_new": players_new,
        "players_exist": players_exist,
        "rankings_new": rankings_new,
        "rankings_exist": rankings_exist,
        "skipped_no_score": skipped_no_score,
        "sample_rows": sample_rows,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest NFL Next Gen Stats 2026 draft class rankings."
    )
    ap.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="0=dry run (default), 1=write to DB"
    )
    args = ap.parse_args()
    apply = bool(args.apply)

    if not CSV_PATH.exists():
        raise SystemExit(f"FAIL: CSV not found: {CSV_PATH}")
    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    rows = read_csv(CSV_PATH)
    print(f"{'APPLY' if apply else 'DRY RUN'}: NGS ingest — {len(rows)} rows from {CSV_PATH.name}")

    ingested_at = utcnow_iso()
    ranking_date = today_utc_date()

    with connect() as conn:
        source_id = ensure_source(conn)

        result = run_ingest(
            conn, rows, source_id, apply, ingested_at, ranking_date
        )

        if apply:
            conn.commit()

    # ── Output ─────────────────────────────────────────────────────────────────
    print()
    print("=== NGS INGEST" + (" — DRY RUN ===" if not apply else " — APPLIED ==="))
    print()
    print(f"  Source: {SOURCE_KEY} (source_id={source_id})")
    print(f"  source_players: {result['players_new']} would insert, {result['players_exist']} already exist" if not apply else
          f"  source_players: {result['players_new']} inserted, {result['players_exist']} already existed")
    print(f"  source_rankings: {result['rankings_new']} would insert, {result['rankings_exist']} already exist" if not apply else
          f"  source_rankings: {result['rankings_new']} inserted, {result['rankings_exist']} already existed")
    if result["skipped_no_score"]:
        print(f"  {result['skipped_no_score']} rows skipped — no ngs_score")
    print()
    print("  Ranking note: overall_rank derived from ngs_score DESC order.")
    print("                ngs_score stored in source_rankings.grade column.")
    print("                ngs_position_rank stored in position_rank column.")

    if result["sample_rows"]:
        print()
        print("  Sample top-ranked rows:")
        for s in result["sample_rows"]:
            print(s)

    print()
    if not apply:
        print("DRY RUN complete. Rerun with --apply 1 to write.")
    else:
        print("APPLY complete.")


if __name__ == "__main__":
    main()
