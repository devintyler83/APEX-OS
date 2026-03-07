from __future__ import annotations

# --- sys.path bootstrap so "python -m scripts.ingest_ras_2026" always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
import html
import json
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.names import name_norm_and_key
from draftos.normalize.positions import normalize_position

# ── Constants ──────────────────────────────────────────────────────────────────
SEASON_ID = 1
DRAFT_YEAR = 2026

# Source file — located in rankings raw directory (not a dedicated ras/ subdirectory)
RAS_CSV = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "ras_2026.csv"

# Position pre-overrides for values the existing normalize module can't handle correctly.
# OC (offset center) → C canonical; all others handled by normalize_position().
_RAS_POS_OVERRIDES: Dict[str, str] = {
    "OC": "C",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup_db(reason: str) -> Path:
    src = PATHS.db
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"draftos_{ts}_{reason}.sqlite"
    dst.write_bytes(Path(src).read_bytes())
    return dst


def normalize_pos_ras(raw: str) -> Optional[str]:
    """
    Normalize a RAS file position string to canonical form.
    Applies _RAS_POS_OVERRIDES first, then falls through to normalize_position().
    Returns None if raw is blank.
    """
    r = (raw or "").strip().upper()
    if not r:
        return None
    override = _RAS_POS_OVERRIDES.get(r)
    if override:
        return override
    result = normalize_position(r)
    return result.canonical


def load_school_alias_map(conn) -> Dict[str, str]:
    """
    Build case-insensitive lookup: lower(school_alias) → school_canonical.
    """
    rows = conn.execute(
        "SELECT school_alias, school_canonical FROM school_aliases;"
    ).fetchall()
    return {r["school_alias"].lower(): r["school_canonical"] for r in rows}


def load_name_alias_map(conn) -> Dict[str, str]:
    """
    Build name alias token map from name_aliases table.
    Maps lower(name_alias) → name_canonical for use in name_norm_and_key().
    Currently empty (0 rows) but implemented for future population.
    """
    rows = conn.execute(
        "SELECT name_alias, name_canonical FROM name_aliases;"
    ).fetchall()
    return {r["name_alias"].lower(): r["name_canonical"] for r in rows}


def build_prospect_lookup(
    conn,
) -> Tuple[Dict[Tuple[str, str], int], Dict[str, List[int]]]:
    """
    Build two lookups for matching:

    by_name_school: (name_key, school_canonical) → prospect_id
      - Among duplicates, prefers prospects with consensus coverage (sources_covered > 0),
        then lowest prospect_id. This ensures we link to the "real" draft prospect.

    by_name: name_key → [prospect_ids]
      - For name_only matching. Only used when exactly 1 entry exists.
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
            ON pcr.prospect_id = p.prospect_id
            AND pcr.season_id = ?
        WHERE p.season_id = ?
          AND p.name_key IS NOT NULL
          AND p.name_key != ''
        ORDER BY sources_covered DESC, p.prospect_id ASC;
        """,
        (SEASON_ID, SEASON_ID),
    ).fetchall()

    by_name_school: Dict[Tuple[str, str], int] = {}
    by_name: Dict[str, List[int]] = {}

    for r in rows:
        nk = r["name_key"]
        sc = (r["school_canonical"] or "").strip()
        pid = int(r["prospect_id"])

        key = (nk, sc)
        if key not in by_name_school:
            by_name_school[key] = pid

        if nk not in by_name:
            by_name[nk] = []
        if pid not in by_name[nk]:
            by_name[nk].append(pid)

    return by_name_school, by_name


def read_ras_csv(path: Path) -> List[Dict[str, str]]:
    """Read the RAS CSV, handling utf-8-sig (BOM)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def process_rows(
    raw_rows: List[Dict[str, str]],
    school_alias_map: Dict[str, str],
    name_alias_token_map: Dict[str, str],
    by_name_school: Dict[Tuple[str, str], int],
    by_name: Dict[str, List[int]],
) -> List[Dict]:
    """
    Process all RAS CSV rows into staging dicts.
    Applies name normalization, position normalization, school normalization,
    and prospect matching (exact → alias → name_only → unmatched).
    """
    now = utcnow_iso()
    results = []

    pos_recognized = 0
    pos_unrecognized = 0

    for raw in raw_rows:
        name_raw = (raw.get("Name") or "").strip()
        pos_raw = (raw.get("Pos") or "").strip()
        college_raw = (raw.get("College") or "").strip()
        ras_raw = (raw.get("RAS") or "").strip()

        # Name normalization
        _, name_key = name_norm_and_key(name_raw, alias_token_map=name_alias_token_map)

        # Position normalization
        pos_normalized = normalize_pos_ras(pos_raw)
        if pos_raw and pos_normalized:
            pos_recognized += 1
        elif pos_raw and not pos_normalized:
            pos_unrecognized += 1

        # RAS score
        ras_score: Optional[float] = None
        if ras_raw:
            try:
                ras_score = float(ras_raw)
            except ValueError:
                pass

        # School normalization via school_aliases
        # html.unescape handles encoded values in the CSV (e.g. "Texas A&amp;M" → "Texas A&M")
        college_canonical: Optional[str] = None
        if college_raw:
            college_decoded = html.unescape(college_raw)
            college_canonical = school_alias_map.get(college_decoded.lower())

        # Matching logic
        matched_prospect_id: Optional[int] = None
        match_method = "unmatched"

        # 1. EXACT: name_key + college_canonical
        if name_key and college_canonical:
            pid = by_name_school.get((name_key, college_canonical))
            if pid is not None:
                matched_prospect_id = pid
                match_method = "exact_name_college"

        # 2. ALIAS: look up via name_aliases → new name_key → match with college
        if matched_prospect_id is None and name_alias_token_map and name_key:
            canonical_name = name_alias_token_map.get(name_key)
            if canonical_name:
                _, alias_name_key = name_norm_and_key(canonical_name)
                if alias_name_key and college_canonical:
                    pid = by_name_school.get((alias_name_key, college_canonical))
                    if pid is not None:
                        matched_prospect_id = pid
                        match_method = "alias_name_college"

        # 3. NAME_ONLY: exactly 1 prospect with this name_key
        if matched_prospect_id is None and name_key:
            name_matches = by_name.get(name_key, [])
            if len(name_matches) == 1:
                matched_prospect_id = name_matches[0]
                match_method = "name_only"

        results.append(
            {
                "season_id": SEASON_ID,
                "name_raw": name_raw,
                "name_key": name_key,
                "pos_raw": pos_raw or None,
                "pos_normalized": pos_normalized,
                "college_raw": college_raw or None,
                "college_canonical": college_canonical,
                "ras_score": ras_score,
                "ras_score_raw": ras_raw or None,
                "matched_prospect_id": matched_prospect_id,
                "match_method": match_method,
                "ingested_at": now,
                "updated_at": now,
                "_pos_raw": pos_raw,
                "_recognized": bool(pos_raw and pos_normalized),
            }
        )

    return results


def upsert_staging(conn, rows: List[Dict]) -> int:
    n = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO ras_staging (
                season_id, name_raw, name_key,
                pos_raw, pos_normalized,
                college_raw, college_canonical,
                ras_score, ras_score_raw,
                matched_prospect_id, match_method,
                ingested_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name_key, season_id) DO UPDATE SET
                ras_score            = excluded.ras_score,
                ras_score_raw        = excluded.ras_score_raw,
                matched_prospect_id  = excluded.matched_prospect_id,
                match_method         = excluded.match_method,
                updated_at           = excluded.updated_at;
            """,
            (
                row["season_id"],
                row["name_raw"],
                row["name_key"],
                row["pos_raw"],
                row["pos_normalized"],
                row["college_raw"],
                row["college_canonical"],
                row["ras_score"],
                row["ras_score_raw"],
                row["matched_prospect_id"],
                row["match_method"],
                row["ingested_at"],
                row["updated_at"],
            ),
        )
        n += 1
    return n


def promote_to_ras(conn, matched_rows: List[Dict]) -> int:
    """
    Promote matched staging rows to the ras table.
    Upserts on prospect_id (UNIQUE constraint on ras).
    """
    n = 0
    now = utcnow_iso()
    for row in matched_rows:
        pid = row["matched_prospect_id"]
        if pid is None:
            continue
        conn.execute(
            """
            INSERT INTO ras (
                prospect_id, season_id, ras_total, ras_score_raw, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(prospect_id) DO UPDATE SET
                season_id     = excluded.season_id,
                ras_total     = excluded.ras_total,
                ras_score_raw = excluded.ras_score_raw,
                updated_at    = excluded.updated_at;
            """,
            (pid, row["season_id"], row["ras_score"], row["ras_score_raw"], now),
        )
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest RAS data for 2026 draft class.")
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not RAS_CSV.exists():
        raise SystemExit(f"FAIL: RAS source file not found: {RAS_CSV}")

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    # Read CSV
    raw_rows = read_ras_csv(RAS_CSV)
    total_rows = len(raw_rows)
    scored_rows = [r for r in raw_rows if (r.get("RAS") or "").strip()]
    empty_rows = [r for r in raw_rows if not (r.get("RAS") or "").strip()]

    with connect() as conn:
        school_alias_map = load_school_alias_map(conn)
        name_alias_token_map = load_name_alias_map(conn)
        by_name_school, by_name = build_prospect_lookup(conn)

    processed = process_rows(
        raw_rows, school_alias_map, name_alias_token_map, by_name_school, by_name
    )

    # Tally
    method_counts: Dict[str, int] = {}
    for r in processed:
        m = r["match_method"]
        method_counts[m] = method_counts.get(m, 0) + 1

    pos_recognized = sum(1 for r in processed if r["_recognized"])
    pos_unrecognized = sum(1 for r in processed if r["_pos_raw"] and not r["_recognized"])

    matched = [r for r in processed if r["matched_prospect_id"] is not None]
    unmatched = [r for r in processed if r["matched_prospect_id"] is None]

    # ── DRY RUN OUTPUT ─────────────────────────────────────────────────────────
    print(f"{'DRY RUN' if args.apply == 0 else 'APPLY'}: RAS ingest for season {DRAFT_YEAR}")
    print(f"SOURCE: {RAS_CSV}")
    print()
    print(f"CSV SUMMARY:")
    print(f"  Total rows:        {total_rows}")
    print(f"  Rows with RAS score: {len(scored_rows)}")
    print(f"  Rows without score:  {len(empty_rows)}")
    print()
    print(f"POSITION NORMALIZATION:")
    print(f"  Recognized:   {pos_recognized}")
    print(f"  Unrecognized: {pos_unrecognized}")
    if pos_unrecognized:
        unrec = [r["_pos_raw"] for r in processed if r["_pos_raw"] and not r["_recognized"]]
        print(f"  Unrecognized values: {sorted(set(unrec))}")
    print()
    print(f"MATCH BREAKDOWN:")
    for method in ["exact_name_college", "alias_name_college", "name_only", "unmatched"]:
        print(f"  {method:<25}: {method_counts.get(method, 0)}")
    print(f"  {'TOTAL MATCHED':<25}: {len(matched)}")
    print()

    print(f"EXAMPLE MATCHED rows (up to 10):")
    print(f"  {'Name':<28} {'College':<20} {'RAS':>5} {'Method':<22} PID")
    print(f"  {'-'*28} {'-'*20} {'-'*5} {'-'*22} ---")
    for r in matched[:10]:
        ras_disp = f"{r['ras_score']:.2f}" if r["ras_score"] is not None else "  --"
        print(
            f"  {r['name_raw']:<28} {(r['college_raw'] or ''):<20} {ras_disp:>5}"
            f" {r['match_method']:<22} {r['matched_prospect_id']}"
        )

    print()
    print(f"EXAMPLE UNMATCHED rows (up to 10):")
    print(f"  {'Name':<28} {'College':<20} Pos")
    print(f"  {'-'*28} {'-'*20} ---")
    for r in unmatched[:10]:
        print(f"  {r['name_raw']:<28} {(r['college_raw'] or ''):<20} {r['pos_raw'] or ''}")

    if args.apply == 0:
        print()
        print("DRY RUN complete. Rerun with --apply 1 to write.")
        return

    # ── APPLY ──────────────────────────────────────────────────────────────────
    backup = backup_db("ingest_ras_2026")
    print(f"\nDB BACKUP: {backup}")

    with connect() as conn:
        n_staging = upsert_staging(conn, processed)
        n_promoted = promote_to_ras(conn, matched)
        conn.commit()

    print(f"\nOK: wrote ras_staging rows: {n_staging}")
    print(f"OK: promoted to ras table:   {n_promoted}")
    print(f"OK: unmatched held in staging: {len(unmatched)}")


if __name__ == "__main__":
    main()
