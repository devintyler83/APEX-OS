from __future__ import annotations

# --- sys.path bootstrap so "python -m scripts.ingest_combine_2026" always works ---
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
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.names import name_norm_and_key

# ── Constants ──────────────────────────────────────────────────────────────────
SEASON_ID = 1
SOURCE_KEY = "nflcom_2026"
SOURCE_NOTES = (
    "NFL.com combine big board. Overall rank 1-735. "
    "Also provides combine measurables: hand_size, arm_length, wingspan. "
    "T2 weight (1.0). Added Session 23."
)
CSV_PATH = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "combine_2026.csv"


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
    """Read CSV with UTF-8 fallback to latin-1."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
                return rows
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"FAIL: cannot decode {path}")


def stable_source_player_key(name: str, school: str, position: str) -> str:
    def k(s: str) -> str:
        import re
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
    """INSERT OR IGNORE the nflcom_2026 source. Return source_id."""
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


# ── Prospect lookup (for Phase B matching) ─────────────────────────────────────

def build_prospect_lookup(
    conn,
) -> Tuple[Dict[Tuple[str, str], int], Dict[Tuple[str, str], int], Dict[str, List[int]]]:
    """
    Build name-based lookup tables from active 2026 prospects.
    Returns:
      by_name_school       : (name_key, school_canonical) → prospect_id  [exact canonical]
      by_name_school_lower : (name_key, school_lower)     → prospect_id  [case-insensitive school]
      by_name              : name_key → [prospect_ids]    [name-only, only used when exactly 1]
    Ordered by sources_covered DESC so highest-coverage row wins on duplicates.
    """
    rows = conn.execute(
        """
        SELECT
            p.prospect_id,
            p.name_key,
            p.school_canonical,
            COALESCE(pcr.sources_covered, 0) AS sources_covered
        FROM prospects p
        LEFT JOIN prospect_consensus_rankings pcr
            ON pcr.prospect_id = p.prospect_id AND pcr.season_id = ?
        WHERE p.season_id = ?
          AND p.is_active = 1
          AND p.name_key IS NOT NULL
          AND p.name_key != ''
        ORDER BY sources_covered DESC, p.prospect_id ASC;
        """,
        (SEASON_ID, SEASON_ID),
    ).fetchall()

    by_name_school: Dict[Tuple[str, str], int] = {}
    by_name_school_lower: Dict[Tuple[str, str], int] = {}
    by_name: Dict[str, List[int]] = {}

    for r in rows:
        nk = r["name_key"]
        sc = (r["school_canonical"] or "").strip()
        sc_lower = sc.lower()
        pid = int(r["prospect_id"])

        key = (nk, sc)
        if key not in by_name_school:
            by_name_school[key] = pid

        key_lower = (nk, sc_lower)
        if key_lower not in by_name_school_lower:
            by_name_school_lower[key_lower] = pid

        if nk not in by_name:
            by_name[nk] = []
        if pid not in by_name[nk]:
            by_name[nk].append(pid)

    return by_name_school, by_name_school_lower, by_name


def load_school_alias_map(conn) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT school_alias, school_canonical FROM school_aliases;"
    ).fetchall()
    return {r["school_alias"].lower(): r["school_canonical"] for r in rows}


def resolve_prospect(
    name_raw: str,
    school_raw: str,
    school_alias_map: Dict[str, str],
    by_name_school: Dict[Tuple[str, str], int],
    by_name_school_lower: Dict[Tuple[str, str], int],
    by_name: Dict[str, List[int]],
) -> Optional[int]:
    """
    Match a CSV row to an active prospect_id. Returns None on no match.
    Strategy (in order):
      1. name_key + school_alias_map lookup (for non-standard school names)
      2. name_key + school_raw (case-insensitive, against school_canonical.lower())
      3. name_only (only when exactly 1 active prospect has this name_key)
    """
    _, name_key = name_norm_and_key(name_raw)
    if not name_key:
        return None

    # 1. Alias-resolved school
    if school_raw:
        school_canonical = school_alias_map.get(school_raw.lower())
        if school_canonical:
            pid = by_name_school.get((name_key, school_canonical))
            if pid is not None:
                return pid

    # 2. Direct case-insensitive school match (CSV school → school_canonical.lower())
    if school_raw:
        pid = by_name_school_lower.get((name_key, school_raw.lower()))
        if pid is not None:
            return pid

    # 3. Name-only: exactly 1 active prospect with this name_key
    name_matches = by_name.get(name_key, [])
    if len(name_matches) == 1:
        return name_matches[0]

    return None


# ── Phase A: Rankings ingest ───────────────────────────────────────────────────

def run_phase_a(
    conn,
    rows: List[Dict[str, str]],
    source_id: int,
    apply: bool,
    ingested_at: str,
    ranking_date: str,
) -> Dict:
    """Ingest source_players + source_rankings for nflcom_2026."""
    players_new = 0
    players_exist = 0
    rankings_new = 0
    rankings_exist = 0

    for row in rows:
        overall_rank = parse_int(row.get("rank"))
        name_raw = (row.get("name") or "").strip()
        school_raw = (row.get("school") or "").strip()
        position_raw = (row.get("position") or "").strip()

        if overall_rank is None or not name_raw:
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
                        json.dumps({"rank": overall_rank, "name": name_raw,
                                   "school": school_raw, "position": position_raw},
                                  ensure_ascii=False),
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
            # In dry run, count as new if we would have inserted the player
            if existing_sp:
                # Player exists — check if ranking exists
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

    return {
        "players_new": players_new,
        "players_exist": players_exist,
        "rankings_new": rankings_new,
        "rankings_exist": rankings_exist,
    }


# ── Phase B: Measurables ingest ───────────────────────────────────────────────

def run_phase_b(
    conn,
    rows: List[Dict[str, str]],
    school_alias_map: Dict[str, str],
    by_name_school: Dict[Tuple[str, str], int],
    by_name_school_lower: Dict[Tuple[str, str], int],
    by_name: Dict[str, List[int]],
    apply: bool,
) -> Dict:
    """Write hand_size, arm_length, wingspan to ras table."""
    matched_update = 0   # prospect matched, ras row exists → UPDATE
    matched_insert = 0   # prospect matched, no ras row → INSERT
    unmatched = 0
    skipped_no_data = 0
    zero_suspect = 0
    sample_rows = []
    unmatched_names = []
    now = utcnow_iso()

    for row in rows:
        name_raw = (row.get("name") or "").strip()
        school_raw = (row.get("school") or "").strip()

        hand_raw = (row.get("hand_size") or "").strip()
        arm_raw = (row.get("arm_length") or "").strip()
        wing_raw = (row.get("wingspan") or "").strip()

        hand = parse_float(hand_raw)
        arm = parse_float(arm_raw)
        wing = parse_float(wing_raw)

        # Skip rows with no measurable data at all
        if hand is None and arm is None and wing is None:
            skipped_no_data += 1
            continue

        # Warn and skip 0.0 values (no player has 0-inch measurements)
        flagged = False
        if hand == 0.0:
            print(f"  WARN: hand_size=0.0 for {name_raw} — skipping hand_size")
            hand = None
            zero_suspect += 1
            flagged = True
        if arm == 0.0:
            print(f"  WARN: arm_length=0.0 for {name_raw} — skipping arm_length")
            arm = None
            zero_suspect += 1
            flagged = True
        if wing == 0.0:
            print(f"  WARN: wingspan=0.0 for {name_raw} — skipping wingspan")
            wing = None
            zero_suspect += 1
            flagged = True

        # After zeroing out suspects, skip if no data remains
        if hand is None and arm is None and wing is None:
            skipped_no_data += 1
            continue

        # Resolve prospect
        pid = resolve_prospect(name_raw, school_raw, school_alias_map, by_name_school, by_name_school_lower, by_name)
        if pid is None:
            unmatched += 1
            unmatched_names.append(f"{name_raw} ({school_raw})")
            continue

        # Check for existing ras row
        ras_row = conn.execute(
            "SELECT ras_id FROM ras WHERE prospect_id = ? AND season_id = ?",
            (pid, SEASON_ID),
        ).fetchone()

        # Collect sample (first 5 matched)
        if len(sample_rows) < 5:
            pos_raw = (row.get("position") or "").strip()
            sample_rows.append(
                f"  {name_raw} ({pos_raw})"
                f"  hand={hand}  arm={arm}  wing={wing}"
            )

        if apply:
            if ras_row:
                matched_update += 1
                # Build SET clause — only update non-null values
                set_parts = []
                vals = []
                if hand is not None:
                    set_parts.append("hand_size = ?")
                    vals.append(hand)
                if arm is not None:
                    set_parts.append("arm_length = ?")
                    vals.append(arm)
                if wing is not None:
                    set_parts.append("wingspan = ?")
                    vals.append(wing)
                set_parts.append("updated_at = ?")
                vals.append(now)
                vals.extend([pid, SEASON_ID])
                conn.execute(
                    f"UPDATE ras SET {', '.join(set_parts)} "
                    f"WHERE prospect_id = ? AND season_id = ?",
                    tuple(vals),
                )
            else:
                matched_insert += 1
                conn.execute(
                    """
                    INSERT INTO ras (
                        prospect_id, season_id,
                        hand_size, arm_length, wingspan,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (pid, SEASON_ID, hand, arm, wing, now),
                )
        else:
            if ras_row:
                matched_update += 1
            else:
                matched_insert += 1

    return {
        "matched_update": matched_update,
        "matched_insert": matched_insert,
        "unmatched": unmatched,
        "skipped_no_data": skipped_no_data,
        "zero_suspect": zero_suspect,
        "sample_rows": sample_rows,
        "unmatched_names": unmatched_names,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest NFL.com combine rankings + measurables for 2026."
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
    print(f"{'APPLY' if apply else 'DRY RUN'}: combine ingest — {len(rows)} rows from {CSV_PATH.name}")

    ingested_at = utcnow_iso()
    ranking_date = today_utc_date()

    with connect() as conn:
        source_id = ensure_source(conn)
        school_alias_map = load_school_alias_map(conn)
        by_name_school, by_name_school_lower, by_name = build_prospect_lookup(conn)

        # ── Phase A: Rankings ──────────────────────────────────────────────────
        phase_a = run_phase_a(
            conn, rows, source_id, apply, ingested_at, ranking_date
        )

        # ── Phase B: Measurables ───────────────────────────────────────────────
        phase_b = run_phase_b(
            conn, rows, school_alias_map, by_name_school, by_name_school_lower, by_name, apply
        )

        if apply:
            conn.commit()

    # ── Output ─────────────────────────────────────────────────────────────────
    print()
    print("=== COMBINE INGEST" + (" — DRY RUN ===" if not apply else " — APPLIED ==="))
    print()
    print("Phase A (Rankings):")
    print(f"  Source: {SOURCE_KEY} (source_id={source_id})")
    print(f"  source_players: {phase_a['players_new']} would insert, {phase_a['players_exist']} already exist" if not apply else
          f"  source_players: {phase_a['players_new']} inserted, {phase_a['players_exist']} already existed")
    print(f"  source_rankings: {phase_a['rankings_new']} would insert, {phase_a['rankings_exist']} already exist" if not apply else
          f"  source_rankings: {phase_a['rankings_new']} inserted, {phase_a['rankings_exist']} already existed")
    print()
    print("Phase B (Measurables):")
    print(f"  {phase_b['matched_update']} prospects matched to existing ras rows ({'would update' if not apply else 'updated'})")
    print(f"  {phase_b['matched_insert']} prospects matched — no ras row ({'would insert' if not apply else 'inserted'})")
    print(f"  {phase_b['unmatched']} prospects unmatched — skipped")
    if phase_b["skipped_no_data"]:
        print(f"  {phase_b['skipped_no_data']} rows skipped — no measurable data")
    if phase_b["zero_suspect"] > 0:
        print(f"  {phase_b['zero_suspect']} zero-value fields skipped (suspect — see WARN above)")

    if phase_b["sample_rows"]:
        print()
        print("  Sample matched rows:")
        for s in phase_b["sample_rows"]:
            print(s)

    if phase_b["unmatched_names"]:
        print()
        n_show = min(20, len(phase_b["unmatched_names"]))
        print(f"  Unmatched names (first {n_show} of {len(phase_b['unmatched_names'])}):")
        for name in phase_b["unmatched_names"][:n_show]:
            print(f"    [unmatched] {name}")

    print()
    if not apply:
        print("DRY RUN complete. Rerun with --apply 1 to write.")
    else:
        print("APPLY complete.")


if __name__ == "__main__":
    main()
