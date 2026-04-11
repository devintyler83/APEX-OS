from __future__ import annotations

# --- sys.path bootstrap so "python -m scripts.ingest_perplexity_agg_2026" always works ---
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
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from draftos.config import PATHS
from draftos.db.connect import connect

# ── Constants ──────────────────────────────────────────────────────────────────
SEASON_ID = 1
SOURCE_NAME = "perplexity_agg_2026"
SOURCE_NOTES = (
    "Perplexity Research aggregation board for 2026 prospects. "
    "Structured external scout aggregation track. "
    "Treat as T3 experimental scout source pending formal weighting decision. "
    "Seeded Session 79."
)
CSV_PATH = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "perplexityagg2026.csv"

# Position normalization for common aliases that may appear in research exports
_POS_NORM: Dict[str, str] = {
    "OC": "C",
    "IOL": "OG",
    "G": "OG",
    "OTT": "OT",
    "FS": "S",
    "SS": "S",
    "SAF": "S",
    "DB": "CB",
    "NICKEL": "CB",
    "NB": "CB",
    "DL": "DT",
    "IDL": "DT",
    "NT": "DT",
    "3T": "DT",
    "1T": "DT",
    "EDGE": "EDGE",
    "ED": "EDGE",
    "ER": "EDGE",
    "OLB": "LB",
    "ILB": "LB",
    "LB": "LB",
    "HB": "RB",
    "FB": "RB",
    "XWR": "WR",
    "ZWR": "WR",
    "SLOT": "WR",
    "WR/CB": "WR",
    "ATH": "ATH",
}

# ── Utilities ──────────────────────────────────────────────────────────────────

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_csv(path: Path) -> List[Dict[str, str]]:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc, newline="", errors="replace") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"FAIL: cannot decode {path}")


def stable_source_player_key(name: str, school: str, position: str) -> str:
    def k(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s
    base = f"{k(name)}|{k(school)}|{k(position)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def parse_int(val) -> Optional[int]:
    s = str(val or "").strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def parse_float(val) -> Optional[float]:
    s = str(val or "").strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def clean_str(val) -> str:
    return str(val or "").strip()


def normalize_pos(raw: str) -> str:
    s = clean_str(raw).upper()
    if not s:
        return ""
    return _POS_NORM.get(s, s)


def first_present(row: Dict[str, str], *keys: str) -> str:
    for k in keys:
        if k in row and clean_str(row.get(k)):
            return clean_str(row.get(k))
    return ""


def extract_row_fields(row: Dict[str, str]) -> Dict[str, Optional[str]]:
    overall_rank = parse_int(first_present(row, "rank", "Rank", "overall_rank", "overall", "Overall", "OVR"))
    player_name = first_present(row, "player_name", "name", "Name", "player", "Player")
    school = first_present(row, "school", "School", "college", "College")
    position_raw = first_present(row, "position", "Position", "pos", "Pos")
    position = normalize_pos(position_raw)

    position_rank = parse_int(first_present(row, "position_rank", "pos_rank", "PosRank", "positionrank"))
    grade = parse_float(first_present(row, "grade", "Grade", "score", "Score"))
    tier = first_present(row, "tier", "Tier")

    return {
        "overall_rank": overall_rank,
        "player_name": player_name,
        "school": school,
        "position_raw": position,
        "position_original": position_raw,
        "position_rank": position_rank,
        "grade": grade,
        "tier": tier or None,
    }


# ── Source record ──────────────────────────────────────────────────────────────

def ensure_source(conn) -> int:
    conn.execute(
        """
        INSERT OR IGNORE INTO sources (source_name, source_type, notes, is_active)
        VALUES (?, ?, ?, ?)
        """,
        (SOURCE_NAME, "ranking", SOURCE_NOTES, 1),
    )
    row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name = ?",
        (SOURCE_NAME,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"FAIL: source row missing after ensure_source for {SOURCE_NAME}")
    return int(row["source_id"])


# ── Rankings ingest ────────────────────────────────────────────────────────────

def run_ingest(
    conn,
    rows: List[Dict[str, str]],
    source_id: int,
    apply: bool,
    ingested_at: str,
    ranking_date: str,
) -> Dict:
    players_new = 0
    players_exist = 0
    rankings_new = 0
    rankings_exist = 0
    skipped = 0
    pos_normalized: Dict[str, int] = {}
    sample_rows: List[str] = []

    for row in rows:
        parsed = extract_row_fields(row)

        overall_rank = parsed["overall_rank"]
        name_raw = str(parsed["player_name"] or "").strip()
        school_raw = str(parsed["school"] or "").strip()
        position_raw = str(parsed["position_raw"] or "").strip()
        position_original = str(parsed["position_original"] or "").strip()
        position_rank = parsed["position_rank"]
        grade = parsed["grade"]
        tier = parsed["tier"]

        if overall_rank is None or not name_raw:
            skipped += 1
            continue

        if position_original and position_raw and position_original.upper() != position_raw.upper():
            pos_normalized[position_original] = pos_normalized.get(position_original, 0) + 1

        player_key = stable_source_player_key(name_raw, school_raw, position_raw)

        existing_sp = conn.execute(
            """
            SELECT source_player_id
            FROM source_players
            WHERE source_id = ? AND season_id = ? AND source_player_key = ?
            """,
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
                        source_id,
                        season_id,
                        source_player_key,
                        raw_full_name,
                        raw_school,
                        raw_position,
                        raw_class_year,
                        raw_json,
                        ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        SEASON_ID,
                        player_key,
                        name_raw,
                        school_raw,
                        position_raw,
                        None,
                        json.dumps(
                            {
                                "rank": overall_rank,
                                "name": name_raw,
                                "school": school_raw,
                                "pos": position_raw,
                                "pos_raw_original": position_original,
                                "position_rank": position_rank,
                                "grade": grade,
                                "tier": tier,
                                "source": SOURCE_NAME,
                            },
                            ensure_ascii=False,
                        ),
                        ingested_at,
                    ),
                )
                sp_row = conn.execute(
                    """
                    SELECT source_player_id
                    FROM source_players
                    WHERE source_id = ? AND season_id = ? AND source_player_key = ?
                    """,
                    (source_id, SEASON_ID, player_key),
                ).fetchone()
                if sp_row is None:
                    raise SystemExit(f"FAIL: source_player missing after insert for {name_raw}")
                spid = int(sp_row["source_player_id"])
            else:
                spid = -1

        if apply and spid > 0:
            existing_rank = conn.execute(
                """
                SELECT 1
                FROM source_rankings
                WHERE source_id = ? AND season_id = ? AND source_player_id = ? AND ranking_date = ?
                """,
                (source_id, SEASON_ID, spid, ranking_date),
            ).fetchone()

            if existing_rank:
                rankings_exist += 1
            else:
                rankings_new += 1
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_rankings(
                        source_id,
                        season_id,
                        source_player_id,
                        overall_rank,
                        position_rank,
                        position_raw,
                        grade,
                        tier,
                        ranking_date,
                        ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        SEASON_ID,
                        spid,
                        overall_rank,
                        position_rank,
                        position_raw,
                        grade,
                        tier,
                        ranking_date,
                        ingested_at,
                    ),
                )
        elif not apply:
            if existing_sp:
                sp_check = conn.execute(
                    """
                    SELECT source_player_id
                    FROM source_players
                    WHERE source_id = ? AND season_id = ? AND source_player_key = ?
                    """,
                    (source_id, SEASON_ID, player_key),
                ).fetchone()
                if sp_check:
                    rank_check = conn.execute(
                        """
                        SELECT 1
                        FROM source_rankings
                        WHERE source_id = ? AND season_id = ? AND source_player_id = ? AND ranking_date = ?
                        """,
                        (source_id, SEASON_ID, int(sp_check["source_player_id"]), ranking_date),
                    ).fetchone()
                    if rank_check:
                        rankings_exist += 1
                    else:
                        rankings_new += 1
                else:
                    rankings_new += 1
            else:
                rankings_new += 1

        if len(sample_rows) < 5:
            sample_rows.append(
                f" {name_raw:<28} {position_raw:<6} {school_raw:<20} rank={overall_rank}"
            )

    return {
        "players_new": players_new,
        "players_exist": players_exist,
        "rankings_new": rankings_new,
        "rankings_exist": rankings_exist,
        "skipped": skipped,
        "pos_normalized": pos_normalized,
        "sample_rows": sample_rows,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest Perplexity aggregated 2026 big board CSV."
    )
    ap.add_argument(
        "--apply",
        type=int,
        default=0,
        choices=[0, 1],
        help="0=dry run (default), 1=write to DB",
    )
    args = ap.parse_args()
    apply = bool(args.apply)

    if not CSV_PATH.exists():
        raise SystemExit(f"FAIL: CSV not found: {CSV_PATH}")
    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    rows = read_csv(CSV_PATH)
    print(
        f"{'APPLY' if apply else 'DRY RUN'}: Perplexity aggregation ingest — "
        f"{len(rows)} rows from {CSV_PATH.name}"
    )

    ingested_at = utcnow_iso()
    ranking_date = today_utc_date()

    with connect() as conn:
        source_id = ensure_source(conn)

        result = run_ingest(
            conn=conn,
            rows=rows,
            source_id=source_id,
            apply=apply,
            ingested_at=ingested_at,
            ranking_date=ranking_date,
        )

        if apply:
            conn.commit()

    print()
    print("=== PERPLEXITY AGG 2026 INGEST" + (" — DRY RUN ===" if not apply else " — APPLIED ==="))
    print()
    print(f" Source: {SOURCE_NAME} (source_id={source_id}) experimental T3")
    if not apply:
        print(f" source_players: {result['players_new']} would insert, {result['players_exist']} already exist")
        print(f" source_rankings: {result['rankings_new']} would insert, {result['rankings_exist']} already exist")
    else:
        print(f" source_players: {result['players_new']} inserted, {result['players_exist']} already existed")
        print(f" source_rankings: {result['rankings_new']} inserted, {result['rankings_exist']} already existed")

    if result["skipped"]:
        print(f" {result['skipped']} rows skipped (missing rank or player name)")
    if result["pos_normalized"]:
        print(f" Positions normalized at ingest: {result['pos_normalized']}")

    if result["sample_rows"]:
        print()
        print(" Sample:")
        for s in result["sample_rows"]:
            print(s)

    print()
    if not apply:
        print("DRY RUN complete. Rerun with --apply 1 to write.")
    else:
        print("APPLY complete.")


if __name__ == "__main__":
    main()