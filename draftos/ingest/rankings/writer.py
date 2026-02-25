from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.ingest.rankings.loader import load_rankings_csv


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backup_db(reason: str) -> Path:
    """
    Backup DB before bulk ingest. Stored under data/exports/backups.
    """
    if not PATHS.db.exists():
        raise RuntimeError("DB does not exist. Run migrations first.")

    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.{ts}.{reason}"
    shutil.copy2(PATHS.db, backup_path)
    return backup_path


def _get_season_id(conn, draft_year: int) -> int:
    row = conn.execute("SELECT season_id FROM seasons WHERE draft_year = ?", (draft_year,)).fetchone()
    if not row:
        raise RuntimeError(f"season {draft_year} not found. Run migrations/seed first.")
    return int(row["season_id"])


def _ensure_source(conn, source_name: str, source_type: str = "ranking", url: str | None = None) -> int:
    conn.execute(
        """
        INSERT OR IGNORE INTO sources (source_name, source_type, url, notes)
        VALUES (?, ?, ?, ?)
        """,
        (source_name, source_type, url, None),
    )
    row = conn.execute("SELECT source_id FROM sources WHERE source_name = ?", (source_name,)).fetchone()
    return int(row["source_id"])


def _stable_source_player_key(raw_full_name: str, raw_school: str | None, raw_position: str | None, raw_json: str) -> str:
    """
    Deterministic key per source row.
    We avoid using rank because ranks change; identity should be stable across refreshes.
    """
    base = "|".join(
        [
            (raw_full_name or "").strip().lower(),
            (raw_school or "").strip().lower(),
            (raw_position or "").strip().lower(),
            (raw_json or "").strip(),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def write_rankings_csv(
    csv_path: Path,
    *,
    draft_year: int,
    source_name: str,
    source_url: str | None = None,
    dry_run: bool = True,
    col_name: str | None = None,
    col_school: str | None = None,
    col_position: str | None = None,
    col_class_year: str | None = None,
    col_overall_rank: str | None = None,
    col_position_rank: str | None = None,
    col_grade: str | None = None,
    col_tier: str | None = None,
    col_ranking_date: str | None = None,
) -> None:
    rows = load_rankings_csv(
        csv_path,
        col_name=col_name,
        col_school=col_school,
        col_position=col_position,
        col_class_year=col_class_year,
        col_overall_rank=col_overall_rank,
        col_position_rank=col_position_rank,
        col_grade=col_grade,
        col_tier=col_tier,
        col_ranking_date=col_ranking_date,
    )

    if not rows:
        print("No rows to ingest.")
        return

    # Backup before any DB mutation (even if dry-run is off)
    if not dry_run:
        bp = _backup_db("rankings_ingest")
        print(f"DB BACKUP: {bp}")

    ingested_at = _now_iso()

    with connect() as conn:
        season_id = _get_season_id(conn, draft_year)
        source_id = _ensure_source(conn, source_name, "ranking", source_url)

        # Handle within-file hash collisions deterministically
        key_counts: dict[str, int] = {}

        inserted_players = 0
        inserted_rankings = 0

        for r in rows:
            base_key = _stable_source_player_key(r.raw_full_name, r.raw_school, r.raw_position, r.raw_json)
            n = key_counts.get(base_key, 0)
            key_counts[base_key] = n + 1
            source_player_key = base_key if n == 0 else f"{base_key}:{n}"

            if dry_run:
                continue

            # Insert source_player (idempotent)
            conn.execute(
                """
                INSERT OR IGNORE INTO source_players (
                  source_id, season_id, source_player_key,
                  raw_full_name, raw_school, raw_position, raw_class_year,
                  raw_json, ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    season_id,
                    source_player_key,
                    r.raw_full_name,
                    r.raw_school,
                    r.raw_position,
                    r.raw_class_year,
                    r.raw_json,
                    ingested_at,
                ),
            )

            # Fetch source_player_id
            sp = conn.execute(
                """
                SELECT source_player_id
                FROM source_players
                WHERE source_id = ? AND season_id = ? AND source_player_key = ?
                """,
                (source_id, season_id, source_player_key),
            ).fetchone()
            source_player_id = int(sp["source_player_id"])

            # Insert ranking (idempotent)
            ranking_date = r.ranking_date or ingested_at[:10]
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO source_rankings (
                  source_id, season_id, source_player_id,
                  overall_rank, position_rank, position_raw,
                  grade, tier, ranking_date, ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    season_id,
                    source_player_id,
                    r.overall_rank,
                    r.position_rank,
                    r.raw_position,
                    r.grade,
                    r.tier,
                    ranking_date,
                    ingested_at,
                ),
            )

        if dry_run:
            print(f"DRY RUN: parsed {len(rows)} rows. No DB writes performed.")
            return

        conn.commit()

    print(f"OK: ingested {len(rows)} rows into source_players/source_rankings for {draft_year} - {source_name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="DraftOS: write rankings CSV into source_* tables (no prospect mapping)")
    ap.add_argument("--csv", required=True, help="Path to rankings CSV")
    ap.add_argument("--season", type=int, required=True, help="Draft year, e.g. 2026")
    ap.add_argument("--source", required=True, help="Source name, e.g. PFF, Dane Brugler, Consensus")
    ap.add_argument("--url", default=None, help="Optional source URL")
    ap.add_argument("--dry-run", type=int, default=1, help="1 = no writes, 0 = write")
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

    write_rankings_csv(
        Path(args.csv),
        draft_year=args.season,
        source_name=args.source,
        source_url=args.url,
        dry_run=bool(args.dry_run),
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


if __name__ == "__main__":
    main()