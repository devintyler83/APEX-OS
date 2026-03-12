from __future__ import annotations

# --- sys.path bootstrap so "python -m scripts.ingest_nflcom_2026" always works ---
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
from draftos.normalize.names import name_norm_and_key

# ── Constants ──────────────────────────────────────────────────────────────────
SEASON_ID = 1
SOURCE_NAME = "nflcom_2026"
SOURCE_NOTES = (
    "NFL.com Rankings 2026. 303 ranked prospects. "
    "T2 weight (1.0). Separate from combine_ranks_2026 "
    "(combine_2026.csv measurables + 735-player ranking). "
    "This is the NFL.com editorial big board ranking. "
    "Added Session 23b."
)
CSV_PATH = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "nflcom_2026.csv"


# ── Utilities ──────────────────────────────────────────────────────────────────

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read CSV with UTF-8 fallback to latin-1."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"FAIL: cannot decode {path}")


def stable_source_player_key(name: str, school: str, position: str) -> str:
    import re
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
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


# ── Source record ──────────────────────────────────────────────────────────────

def ensure_source(conn) -> int:
    """INSERT OR IGNORE the nflcom_2026 source. Return source_id."""
    conn.execute(
        """
        INSERT OR IGNORE INTO sources (source_name, source_type, notes, is_active)
        VALUES (?, ?, ?, ?)
        """,
        (SOURCE_NAME, "ranking", SOURCE_NOTES, 1),
    )
    row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name = ?", (SOURCE_NAME,)
    ).fetchone()
    return int(row["source_id"])


# ── Rankings ingest ───────────────────────────────────────────────────────────

def run_ingest(
    conn,
    rows: List[Dict[str, str]],
    source_id: int,
    apply: bool,
    ingested_at: str,
    ranking_date: str,
) -> Dict:
    """Write source_players + source_rankings for nflcom_2026."""
    players_new = 0
    players_exist = 0
    rankings_new = 0
    rankings_exist = 0
    skipped = 0
    sample_rows = []

    for row in rows:
        # CSV columns: rank, name, school, pos
        overall_rank = parse_int(row.get("rank"))
        name_raw = (row.get("name") or "").strip()
        school_raw = (row.get("school") or "").strip()
        position_raw = (row.get("pos") or "").strip()

        if overall_rank is None or not name_raw:
            skipped += 1
            continue

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
                            "rank": overall_rank, "name": name_raw,
                            "school": school_raw, "pos": position_raw,
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
                spid = -1

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
                        overall_rank, None, position_raw,
                        None, None, ranking_date, ingested_at,
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

        # Collect sample (first 5 rows)
        if len(sample_rows) < 5:
            sample_rows.append(
                f"  {name_raw:<28} {position_raw:<6} rank={overall_rank}"
            )

    return {
        "players_new": players_new,
        "players_exist": players_exist,
        "rankings_new": rankings_new,
        "rankings_exist": rankings_exist,
        "skipped": skipped,
        "sample_rows": sample_rows,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest NFL.com 2026 rankings (303-player big board)."
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
    print(f"{'APPLY' if apply else 'DRY RUN'}: NFL.com rankings ingest — {len(rows)} rows from {CSV_PATH.name}")

    ingested_at = utcnow_iso()
    ranking_date = today_utc_date()

    with connect() as conn:
        source_id = ensure_source(conn)

        result = run_ingest(
            conn, rows, source_id, apply, ingested_at, ranking_date
        )

        if apply:
            conn.commit()

    print()
    print("=== NFLCOM 2026 RANKS INGEST" + (" — DRY RUN ===" if not apply else " — APPLIED ==="))
    print()
    print(f"  Source: {SOURCE_NAME} (source_id={source_id}) T2 1.0")
    if not apply:
        print(f"  source_players: {result['players_new']} would insert, {result['players_exist']} already exist")
        print(f"  source_rankings: {result['rankings_new']} would insert, {result['rankings_exist']} already exist")
    else:
        print(f"  source_players: {result['players_new']} inserted, {result['players_exist']} already existed")
        print(f"  source_rankings: {result['rankings_new']} inserted, {result['rankings_exist']} already existed")
    if result["skipped"]:
        print(f"  {result['skipped']} rows skipped (no rank or name)")

    if result["sample_rows"]:
        print()
        print("  Sample:")
        for s in result["sample_rows"]:
            print(s)

    print()
    if not apply:
        print("DRY RUN complete. Rerun with --apply 1 to write.")
    else:
        print("APPLY complete.")


if __name__ == "__main__":
    main()
