from __future__ import annotations

# --- sys.path bootstrap so "python -m scripts.ingest_jfosterfilm_measurables_2026" always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
import html
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.names import name_norm_and_key
from draftos.normalize.positions import normalize_position

# ── Constants ──────────────────────────────────────────────────────────────────
SEASON_ID = 1
DRAFT_YEAR = 2026

CSV_PATH = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "jfosterfilm_2026.csv"

# Null sentinels in the jfosterfilm CSV
_NULL_SENTINELS = {"?", "--", "-", ""}


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
    Maps lower(name_alias) → name_canonical.
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
      - Prefers prospects with consensus coverage, then lowest prospect_id.

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


def parse_float(val: str) -> Optional[float]:
    """Return float or None for blank/sentinel values."""
    v = (val or "").strip()
    if v in _NULL_SENTINELS:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_int(val: str) -> Optional[int]:
    """Return int or None for blank/sentinel values."""
    v = (val or "").strip()
    if v in _NULL_SENTINELS:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def parse_height(val: str) -> Optional[int]:
    """
    Convert jfosterfilm 4-digit NFL height notation to raw inches.
    Format: XYZW where X=feet, YZ=inches, W=eighth-inches.
    Example: 6050 → 6*12 + 05 = 77 inches
             5115 → 5*12 + 11 = 71 inches
    Returns None for blank/sentinel or malformed values.
    """
    v = (val or "").strip()
    if v in _NULL_SENTINELS:
        return None
    v_clean = v.replace("-", "").replace("'", "").replace('"', "").strip()
    if len(v_clean) != 4:
        return None
    try:
        feet = int(v_clean[0])
        inches = int(v_clean[1:3])
        return feet * 12 + inches
    except (ValueError, IndexError):
        return None


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read the jfosterfilm CSV (latin-1 encoded)."""
    with open(path, encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def match_prospect(
    name_raw: str,
    school_raw: str,
    school_alias_map: Dict[str, str],
    name_alias_token_map: Dict[str, str],
    by_name_school: Dict[Tuple[str, str], int],
    by_name: Dict[str, List[int]],
) -> Tuple[Optional[int], str]:
    """
    Attempt to match a player to a prospect_id.
    Returns (prospect_id, match_method).
    """
    _, name_key = name_norm_and_key(name_raw, alias_token_map=name_alias_token_map)

    school_decoded = html.unescape(school_raw) if school_raw else ""
    school_canonical: Optional[str] = None
    if school_decoded:
        school_canonical = school_alias_map.get(school_decoded.lower())

    # 1. EXACT: name_key + school_canonical
    if name_key and school_canonical:
        pid = by_name_school.get((name_key, school_canonical))
        if pid is not None:
            return pid, "exact_name_school"

    # 1b. EXACT RAW: name_key + school_raw as-is
    if name_key and school_raw:
        pid = by_name_school.get((name_key, school_raw.strip()))
        if pid is not None:
            return pid, "exact_name_school_raw"

    # 2. ALIAS: name_alias token map → re-match with school
    if name_alias_token_map and name_key:
        canonical_name = name_alias_token_map.get(name_key)
        if canonical_name:
            _, alias_name_key = name_norm_and_key(canonical_name)
            if alias_name_key and school_canonical:
                pid = by_name_school.get((alias_name_key, school_canonical))
                if pid is not None:
                    return pid, "alias_name_school"

    # 3. NAME_ONLY: exactly 1 prospect with this name_key
    if name_key:
        name_matches = by_name.get(name_key, [])
        if len(name_matches) == 1:
            return name_matches[0], "name_only"

    return None, "unmatched"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest jfosterfilm 2026 expanded measurables into prospect_measurables."
    )
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not CSV_PATH.exists():
        raise SystemExit(f"FAIL: CSV not found: {CSV_PATH}")
    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    raw_rows = read_csv(CSV_PATH)
    total_rows = len(raw_rows)

    with connect() as conn:
        school_alias_map = load_school_alias_map(conn)
        name_alias_token_map = load_name_alias_map(conn)
        by_name_school, by_name = build_prospect_lookup(conn)

    # ── Process all rows ────────────────────────────────────────────────────────
    matched_rows: List[Dict] = []
    unmatched_rows: List[Dict] = []
    method_counts: Dict[str, int] = {}

    for raw in raw_rows:
        name_raw = (raw.get("Player") or "").strip()
        school_raw = (raw.get("School") or "").strip()
        pos_raw = (raw.get("Pos") or "").strip()

        pid, method = match_prospect(
            name_raw, school_raw,
            school_alias_map, name_alias_token_map,
            by_name_school, by_name,
        )
        method_counts[method] = method_counts.get(method, 0) + 1

        row_data = {
            "name_raw": name_raw,
            "school_raw": school_raw,
            "pos_raw": pos_raw,
            "prospect_id": pid,
            "match_method": method,
            # Rankings
            "jff_ovr_rank":    parse_int(raw.get("OVR", "")),
            "jff_pos_rank":    parse_int(raw.get("POS", "")),
            "consensus_rank":  parse_int(raw.get("CON", "")),
            # Bio
            "age":             parse_float(raw.get("AGE", "")),
            "height_in":       parse_height(raw.get("HEIGHT", "")),
            "weight_lbs":      parse_int(raw.get("WEIGHT", "")),
            # Arm/wing/hand
            "arm_length":      parse_float(raw.get("ARM", "")),
            "wingspan":        parse_float(raw.get("WING", "")),
            "hand_size":       parse_float(raw.get("HAND", "")),
            # Drills
            "ten_yard_split":  parse_float(raw.get("10Y", "")),
            "forty_yard_dash": parse_float(raw.get("40Y", "")),
            "shuttle":         parse_float(raw.get("SHUTTLE", "")),
            "three_cone":      parse_float(raw.get("3Cone", "")),
            # Explosiveness
            "vertical_jump":   parse_float(raw.get("VRT", "")),
            "broad_jump":      parse_int(raw.get("BRD", "")),
            # Composite scores
            "prod_score":      parse_float(raw.get("PROD", "")),
            "ath_score":       parse_float(raw.get("ATH", "")),
            "size_score":      parse_float(raw.get("SIZE", "")),
            "speed_score":     parse_float(raw.get("SPEED", "")),
            "acc_score":       parse_float(raw.get("ACC", "")),
            "agi_score":       parse_float(raw.get("AGI", "")),
        }

        if pid is not None:
            matched_rows.append(row_data)
        else:
            unmatched_rows.append(row_data)

    # ── Output ──────────────────────────────────────────────────────────────────
    mode_label = "DRY RUN" if args.apply == 0 else "APPLY"
    print(f"{mode_label}: jfosterfilm measurables ingest for season {DRAFT_YEAR}")
    print(f"SOURCE: {CSV_PATH}")
    print()
    print(f"CSV SUMMARY:")
    print(f"  Total rows:   {total_rows}")
    print(f"  Matched:      {len(matched_rows)}")
    print(f"  Unmatched:    {len(unmatched_rows)}")
    print()
    print("MATCH BREAKDOWN:")
    for method in ["exact_name_school", "exact_name_school_raw", "alias_name_school", "name_only", "unmatched"]:
        print(f"  {method:<28}: {method_counts.get(method, 0)}")
    print()

    print("EXAMPLE MATCHED rows (up to 10):")
    print(f"  {'Name':<28} {'School':<22} {'CON':>4} {'OVR':>4} {'40Y':>5} Method")
    print(f"  {'-'*28} {'-'*22} {'-'*4} {'-'*4} {'-'*5} ------")
    for r in matched_rows[:10]:
        con = str(r["consensus_rank"]) if r["consensus_rank"] is not None else "--"
        ovr = str(r["jff_ovr_rank"]) if r["jff_ovr_rank"] is not None else "--"
        yd40 = f"{r['forty_yard_dash']:.2f}" if r["forty_yard_dash"] is not None else "  --"
        print(f"  {r['name_raw']:<28} {r['school_raw']:<22} {con:>4} {ovr:>4} {yd40:>5} {r['match_method']}")

    print()
    print("EXAMPLE UNMATCHED rows (up to 10):")
    print(f"  {'Name':<28} {'School':<22} Pos")
    print(f"  {'-'*28} {'-'*22} ---")
    for r in unmatched_rows[:10]:
        print(f"  {r['name_raw']:<28} {r['school_raw']:<22} {r['pos_raw']}")

    if args.apply == 0:
        print()
        print("DRY RUN complete. Rerun with --apply 1 to write.")
        return

    # ── APPLY ───────────────────────────────────────────────────────────────────
    backup = backup_db("ingest_jff_measurables_2026")
    print(f"\nDB BACKUP: {backup}")

    now = utcnow_iso()
    n_written = 0

    with connect() as conn:
        for row in matched_rows:
            conn.execute(
                """
                INSERT INTO prospect_measurables (
                    prospect_id, season_id,
                    jff_ovr_rank, jff_pos_rank, consensus_rank,
                    age, height_in, weight_lbs,
                    arm_length, wingspan, hand_size,
                    ten_yard_split, forty_yard_dash, shuttle, three_cone,
                    vertical_jump, broad_jump,
                    prod_score, ath_score, size_score,
                    speed_score, acc_score, agi_score,
                    source, created_at, updated_at
                ) VALUES (
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    'jfosterfilm_2026', ?, ?
                )
                ON CONFLICT(prospect_id, season_id) DO UPDATE SET
                    jff_ovr_rank    = excluded.jff_ovr_rank,
                    jff_pos_rank    = excluded.jff_pos_rank,
                    consensus_rank  = excluded.consensus_rank,
                    age             = excluded.age,
                    height_in       = excluded.height_in,
                    weight_lbs      = excluded.weight_lbs,
                    arm_length      = excluded.arm_length,
                    wingspan        = excluded.wingspan,
                    hand_size       = excluded.hand_size,
                    ten_yard_split  = excluded.ten_yard_split,
                    forty_yard_dash = excluded.forty_yard_dash,
                    shuttle         = excluded.shuttle,
                    three_cone      = excluded.three_cone,
                    vertical_jump   = excluded.vertical_jump,
                    broad_jump      = excluded.broad_jump,
                    prod_score      = excluded.prod_score,
                    ath_score       = excluded.ath_score,
                    size_score      = excluded.size_score,
                    speed_score     = excluded.speed_score,
                    acc_score       = excluded.acc_score,
                    agi_score       = excluded.agi_score,
                    source          = excluded.source,
                    updated_at      = excluded.updated_at;
                """,
                (
                    row["prospect_id"], SEASON_ID,
                    row["jff_ovr_rank"], row["jff_pos_rank"], row["consensus_rank"],
                    row["age"], row["height_in"], row["weight_lbs"],
                    row["arm_length"], row["wingspan"], row["hand_size"],
                    row["ten_yard_split"], row["forty_yard_dash"],
                    row["shuttle"], row["three_cone"],
                    row["vertical_jump"], row["broad_jump"],
                    row["prod_score"], row["ath_score"], row["size_score"],
                    row["speed_score"], row["acc_score"], row["agi_score"],
                    now, now,
                ),
            )
            n_written += 1
        conn.commit()

    print(f"\nOK: rows written to prospect_measurables: {n_written}")
    print(f"OK: unmatched (not written): {len(unmatched_rows)}")


if __name__ == "__main__":
    main()
