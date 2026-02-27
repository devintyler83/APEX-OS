from __future__ import annotations

# --- sys.path bootstrap so "python scripts\..." always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # C:\DraftOS
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


TS_RE = re.compile(r"_staged_(\d{8})T\d{6}Z\.csv$", re.IGNORECASE)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def open_csv_with_fallbacks(path: Path):
    encodings = ["utf-8-sig", "utf-16", "cp1252", "latin-1"]
    last_err = None
    for enc in encodings:
        try:
            f = path.open("r", encoding=enc, newline="")
            f.read(4096)
            f.seek(0)
            return f, enc
        except UnicodeDecodeError as e:
            last_err = e
        except Exception as e:
            last_err = e
    raise SystemExit(f"FAIL: cannot decode {path.name}. Last error: {last_err}")


def sources_has_col(conn, col: str) -> bool:
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(sources);").fetchall()]
    return col in cols


def get_season_id(conn, draft_year: int) -> int:
    row = conn.execute("SELECT season_id FROM seasons WHERE draft_year = ?", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season {draft_year} not found. Run migrations/seeds first.")
    return int(row["season_id"])


def upsert_source(conn, source_name: str, *, source_type: str = "ranking") -> int:
    row = conn.execute("SELECT source_id FROM sources WHERE source_name = ?", (source_name,)).fetchone()
    if row:
        return int(row["source_id"])

    # Handle schema with/without is_active + superseded_by_source_id (migrations add these)
    has_is_active = sources_has_col(conn, "is_active")
    has_sup = sources_has_col(conn, "superseded_by_source_id")
    has_url = sources_has_col(conn, "url")
    has_notes = sources_has_col(conn, "notes")
    has_type = sources_has_col(conn, "source_type")

    cols = ["source_name"]
    vals = [source_name]
    if has_type:
        cols.append("source_type")
        vals.append(source_type)
    if has_url:
        cols.append("url")
        vals.append(None)
    if has_notes:
        cols.append("notes")
        vals.append(None)
    if has_is_active:
        cols.append("is_active")
        vals.append(1)
    if has_sup:
        cols.append("superseded_by_source_id")
        vals.append(None)

    qcols = ", ".join(cols)
    qmarks = ", ".join(["?"] * len(cols))
    conn.execute(f"INSERT INTO sources ({qcols}) VALUES ({qmarks})", tuple(vals))

    row2 = conn.execute("SELECT source_id FROM sources WHERE source_name = ?", (source_name,)).fetchone()
    return int(row2["source_id"])


def stable_source_player_key(player_name: str, school: str, position: str) -> str:
    """
    Stable within a source+season: depends on identity-ish fields, NOT rank.
    """
    def k(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    base = f"{k(player_name)}|{k(school)}|{k(position)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def upsert_source_player(
    conn,
    *,
    source_id: int,
    season_id: int,
    player_key: str,
    raw_full_name: str,
    raw_school: str,
    raw_position: str,
    raw_json: Dict,
    ingested_at: str,
) -> int:
    row = conn.execute(
        """
        SELECT source_player_id
        FROM source_players
        WHERE source_id = ? AND season_id = ? AND source_player_key = ?
        """,
        (source_id, season_id, player_key),
    ).fetchone()
    if row:
        return int(row["source_player_id"])

    conn.execute(
        """
        INSERT INTO source_players(
          source_id, season_id, source_player_key,
          raw_full_name, raw_school, raw_position,
          raw_class_year, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            season_id,
            player_key,
            raw_full_name,
            raw_school,
            raw_position,
            None,
            json.dumps(raw_json, ensure_ascii=False),
            ingested_at,
        ),
    )
    row2 = conn.execute(
        """
        SELECT source_player_id
        FROM source_players
        WHERE source_id = ? AND season_id = ? AND source_player_key = ?
        """,
        (source_id, season_id, player_key),
    ).fetchone()
    return int(row2["source_player_id"])


def parse_int(val) -> Optional[int]:
    s = str(val or "").strip()
    if not s:
        return None
    s2 = re.sub(r"[^\d]", "", s)
    return int(s2) if s2.isdigit() else None


def parse_float(val) -> Optional[float]:
    s = str(val or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def infer_ranking_date_from_filename(path: Path) -> str:
    """
    From: source_2026_staged_YYYYMMDDTHHMMSSZ.csv -> YYYY-MM-DD
    Else: today UTC.
    """
    m = TS_RE.search(path.name)
    if not m:
        return today_utc_date()
    ymd = m.group(1)
    return f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"


def ingest_staged_file(conn, *, source_name: str, season_id: int, path: Path, ranking_date: Optional[str]) -> Tuple[int, int]:
    """
    Returns (players_upserted_count, rankings_inserted_count) for this file.
    """
    source_id = upsert_source(conn, source_name, source_type="ranking")
    ingested_at = utcnow_iso()
    rdate = ranking_date or infer_ranking_date_from_filename(path)

    f, enc = open_csv_with_fallbacks(path)
    players_new = 0
    rankings_new = 0

    try:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return (0, 0)

        required = {"rank", "player_name", "school", "position"}
        missing = [c for c in required if c not in set(reader.fieldnames)]
        if missing:
            raise SystemExit(f"FAIL: staged file missing columns {missing}: {path}")

        for row in reader:
            overall_rank = parse_int(row.get("rank"))
            player_name = (row.get("player_name") or "").strip()
            school = (row.get("school") or "").strip()
            position = (row.get("position") or "").strip()

            if overall_rank is None or not player_name:
                continue

            player_key = stable_source_player_key(player_name, school, position)

            # Upsert source_player
            before = conn.execute(
                "SELECT 1 FROM source_players WHERE source_id=? AND season_id=? AND source_player_key=?",
                (source_id, season_id, player_key),
            ).fetchone()

            spid = upsert_source_player(
                conn,
                source_id=source_id,
                season_id=season_id,
                player_key=player_key,
                raw_full_name=player_name,
                raw_school=school,
                raw_position=position,
                raw_json=row,
                ingested_at=ingested_at,
            )

            if before is None:
                players_new += 1

            # Insert ranking row if not exists for this date
            exists = conn.execute(
                """
                SELECT 1 FROM source_rankings
                WHERE source_id=? AND season_id=? AND source_player_id=? AND ranking_date=?
                """,
                (source_id, season_id, spid, rdate),
            ).fetchone()
            if exists:
                continue

            conn.execute(
                """
                INSERT INTO source_rankings(
                  source_id, season_id, source_player_id,
                  overall_rank, position_rank, position_raw,
                  grade, tier, ranking_date, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    season_id,
                    spid,
                    overall_rank,
                    parse_int(row.get("position_rank")),
                    (row.get("raw_position") or row.get("position") or "").strip(),
                    parse_float(row.get("grade")),
                    None,
                    rdate,
                    ingested_at,
                ),
            )
            rankings_new += 1

    finally:
        f.close()

    return (players_new, rankings_new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--ranking-date", type=str, default="", help="Override ranking_date YYYY-MM-DD for ALL files. Default: infer from filename.")
    ap.add_argument("--apply", type=int, default=0, help="0 dry run, 1 apply writes (backs up DB)")
    args = ap.parse_args()

    imports_root = ROOT / "data" / "imports" / "rankings"
    staged_files = sorted(imports_root.glob("*/*/staged/*.csv"))
    if not staged_files:
        staged_files = sorted(imports_root.glob("*/staged/*.csv"))  # tolerate missing nesting

    if not staged_files:
        raise SystemExit(f"FAIL: no staged files found under {imports_root}")

    ranking_date = args.ranking_date.strip() or None

    if args.apply == 1:
        b = backup_db(f"ingest_staged_{args.season}")
        print(f"DB BACKUP: {b}")
    else:
        print("DRY RUN: no DB writes, no backup")

    total_players_new = 0
    total_rankings_new = 0

    with connect() as conn:
        season_id = get_season_id(conn, args.season)

        for p in staged_files:
            # expected: ...\rankings\<source>\staged\<file>
            source_name = p.parent.parent.name.lower() if p.parent.name == "staged" else p.parent.name.lower()

            if args.apply != 1:
                # dry run counts without writing
                print(f"PLAN: would ingest {source_name} <- {p.name} (ranking_date={ranking_date or infer_ranking_date_from_filename(p)})")
                continue

            pn, rn = ingest_staged_file(conn, source_name=source_name, season_id=season_id, path=p, ranking_date=ranking_date)
            conn.commit()

            total_players_new += pn
            total_rankings_new += rn
            print(f"OK: ingested {source_name:<14} file={p.name:<40} players_new={pn:<4} rankings_new={rn:<4}")

    if args.apply == 1:
        print(f"OK: totals players_new={total_players_new} rankings_new={total_rankings_new}")


if __name__ == "__main__":
    main()