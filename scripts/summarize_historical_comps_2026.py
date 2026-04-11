"""
Read-only summary report for the historical_comps table.

Outputs three structured tables:
  1. Position Summary    -- coverage and hit rate per position group
  2. Archetype Detail    -- per-archetype HIT/PARTIAL/MISS, confidence distribution, FM exposure
  3. FM Code Usage       -- FM codes tagged on position comps, normalised from compound strings
  4. FM Reference Library -- is_fm_reference=1 rows by FM code
  5. Gap Report          -- archetypes below minimum comp threshold

Zero DB writes. Safe to run at any time.

Usage:
    python -m scripts.summarize_historical_comps_2026           # same as --apply 0
    python -m scripts.summarize_historical_comps_2026 --apply 0

Notes:
  - historical_comps stores interior DL as IDL-*.
    apex_scores.matched_archetype stores them as DT-* (APEX engine convention).
    get_historical_comps() normalises DT-* -> IDL-* at query time.
  - Some comps carry compound FM codes (e.g. 'FM-3, FM-4'). The FM summary
    splits and counts each code independently.
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime, timezone

from draftos.config import PATHS
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Canonical archetype counts per position  (CLAUDE.md + observed WR-6 reality)
# ---------------------------------------------------------------------------

CANONICAL_ARCHETYPE_COUNTS: dict[str, int] = {
    "QB":   6,
    "CB":   5,
    "EDGE": 5,
    "IDL":  5,
    "ILB":  5,
    "OLB":  5,
    "OT":   5,
    "OG":   5,
    "C":    6,
    "TE":   5,
    "RB":   5,
    "S":    5,
    "WR":   6,
}

CANONICAL_POSITIONS: list[str] = list(CANONICAL_ARCHETYPE_COUNTS.keys())

# Minimum comp count per archetype before it's flagged as a gap
GAP_THRESHOLD = 2

CANONICAL_FM_CODES = ["FM-1", "FM-2", "FM-3", "FM-4", "FM-5", "FM-6"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sep(width: int = 64, char: str = "-") -> str:
    return char * width


def _header(title: str, width: int = 64) -> str:
    return f"\n{_sep(width)}\n{title}\n{_sep(width)}"


def _parse_fm_codes(fm_str: str | None) -> list[str]:
    """
    Extract all FM codes from a possibly compound string.
    'FM-3, FM-4' -> ['FM-3', 'FM-4']
    'FM-1'       -> ['FM-1']
    None / ''    -> []
    """
    if not fm_str:
        return []
    return re.findall(r"FM-\d+", fm_str)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_position_comps(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT player_name, position, archetype_code,
               translation_outcome, comp_confidence, fm_code
        FROM   historical_comps
        WHERE  is_fm_reference = 0
        ORDER  BY position, archetype_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _load_fm_reference_rows(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT player_name, position, archetype_code,
               translation_outcome, comp_confidence, fm_code
        FROM   historical_comps
        WHERE  is_fm_reference = 1
        ORDER  BY fm_code, position
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _outcome_counts(rows: list[dict]) -> dict[str, int]:
    c = {"HIT": 0, "PARTIAL": 0, "MISS": 0}
    for r in rows:
        c[r["translation_outcome"]] = c.get(r["translation_outcome"], 0) + 1
    return c


def _hit_rate(counts: dict[str, int]) -> int:
    total = sum(counts.values())
    return round(counts.get("HIT", 0) / total * 100) if total > 0 else 0


def _conf_counts(rows: list[dict]) -> dict[str, int]:
    c = {"A": 0, "B": 0, "C": 0}
    for r in rows:
        c[r["comp_confidence"]] = c.get(r["comp_confidence"], 0) + 1
    return c


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _section_db_totals(pos_rows: list[dict], fm_rows: list[dict]) -> str:
    total     = len(pos_rows) + len(fm_rows)
    n_arch    = len({r["archetype_code"] for r in pos_rows})
    n_pos     = len({r["position"] for r in pos_rows})
    lines = [
        "",
        "DATABASE TOTALS",
        f"  Position comps     : {len(pos_rows):>4}",
        f"  FM reference rows  : {len(fm_rows):>4}",
        f"  Total rows         : {total:>4}",
        f"  Archetype codes    : {n_arch:>4}",
        f"  Positions covered  : {n_pos:>4}",
    ]
    return "\n".join(lines)


def _section_position_summary(pos_rows: list[dict]) -> str:
    # Group by position
    by_pos: dict[str, list[dict]] = defaultdict(list)
    for r in pos_rows:
        by_pos[r["position"]].append(r)

    hdr = (
        f"\n  {'Position':<8}  {'Comps':>5}  {'HIT':>4}  {'PARTIAL':>7}  {'MISS':>4}  "
        f"{'Hit%':>5}  {'Archetypes':>10}  {'Coverage'}"
    )
    lines = [_header("POSITION SUMMARY"), hdr, f"  {'-'*8}  {'-'*5}  {'-'*4}  {'-'*7}  {'-'*4}  {'-'*5}  {'-'*10}  {'-'*10}"]

    for pos in sorted(CANONICAL_POSITIONS):
        rows  = by_pos.get(pos, [])
        total = len(rows)
        oc    = _outcome_counts(rows)
        hr    = _hit_rate(oc)
        n_arch_actual   = len({r["archetype_code"] for r in rows})
        n_arch_expected = CANONICAL_ARCHETYPE_COUNTS.get(pos, "?")
        coverage = (
            "FULL" if n_arch_actual >= n_arch_expected
            else f"{n_arch_actual}/{n_arch_expected}"
        )
        lines.append(
            f"  {pos:<8}  {total:>5}  {oc['HIT']:>4}  {oc['PARTIAL']:>7}  {oc['MISS']:>4}  "
            f"{hr:>4}%  {n_arch_actual:>3}/{n_arch_expected:<6}  {coverage}"
        )

    # Positions in DB but not in canonical list (unexpected)
    extra = sorted({r["position"] for r in pos_rows} - set(CANONICAL_POSITIONS))
    if extra:
        lines.append(f"\n  NOTE  Non-canonical positions in DB: {', '.join(extra)}")

    return "\n".join(lines)


def _section_archetype_detail(pos_rows: list[dict]) -> str:
    # Group by archetype_code
    by_arch: dict[str, list[dict]] = defaultdict(list)
    for r in pos_rows:
        by_arch[r["archetype_code"]].append(r)

    hdr = (
        f"\n  {'Archetype':<10}  {'Comps':>5}  {'HIT':>4}  {'PAR':>3}  {'MSS':>3}  "
        f"{'Hit%':>5}  {'A':>2}  {'B':>2}  {'C':>2}  {'FM-tagged':>9}"
    )
    lines = [
        _header("ARCHETYPE DETAIL"),
        hdr,
        f"  {'-'*10}  {'-'*5}  {'-'*4}  {'-'*3}  {'-'*3}  {'-'*5}  {'-'*2}  {'-'*2}  {'-'*2}  {'-'*9}",
    ]

    # Sort: by position order then archetype number
    pos_order = {p: i for i, p in enumerate(CANONICAL_POSITIONS)}

    def _sort_key(code: str) -> tuple:
        if "-" not in code:
            return (99, 99, code)
        prefix, num = code.split("-", 1)
        try:
            n = int(num)
        except ValueError:
            n = 99
        return (pos_order.get(prefix, 98), n, code)

    prev_pos = None
    for arch in sorted(by_arch.keys(), key=_sort_key):
        rows   = by_arch[arch]
        pos    = rows[0]["position"] if rows else ""
        if pos != prev_pos:
            if prev_pos is not None:
                lines.append("")
            prev_pos = pos
        total  = len(rows)
        oc     = _outcome_counts(rows)
        hr     = _hit_rate(oc)
        cc     = _conf_counts(rows)
        fm_cnt = sum(1 for r in rows if r.get("fm_code"))
        lines.append(
            f"  {arch:<10}  {total:>5}  {oc['HIT']:>4}  {oc['PARTIAL']:>3}  {oc['MISS']:>3}  "
            f"{hr:>4}%  {cc['A']:>2}  {cc['B']:>2}  {cc['C']:>2}  {fm_cnt:>9}"
        )

    return "\n".join(lines)


def _section_fm_usage(pos_rows: list[dict]) -> str:
    """
    Tally canonical FM code usage across position comps.
    Compound fm_code strings (e.g. 'FM-3, FM-4') are split and each counted separately.
    """
    # fm_code -> { outcome -> count, positions: set }
    fm_data: dict[str, dict] = {
        code: {"HIT": 0, "PARTIAL": 0, "MISS": 0, "positions": set()}
        for code in CANONICAL_FM_CODES
    }
    unrecognised: dict[str, int] = defaultdict(int)

    for r in pos_rows:
        codes = _parse_fm_codes(r.get("fm_code") or "")
        for code in codes:
            if code in fm_data:
                fm_data[code][r["translation_outcome"]] += 1
                fm_data[code]["positions"].add(r["position"])
            else:
                unrecognised[code] += 1

    hdr = (
        f"\n  {'FM Code':<8}  {'Total':>5}  {'HIT':>4}  {'PAR':>3}  {'MSS':>3}  "
        f"{'Positions tagged'}"
    )
    lines = [
        _header("FM CODE USAGE  (position comps -- compound codes split)"),
        hdr,
        f"  {'-'*8}  {'-'*5}  {'-'*4}  {'-'*3}  {'-'*3}  {'-'*40}",
    ]

    for code in CANONICAL_FM_CODES:
        d     = fm_data[code]
        total = d["HIT"] + d["PARTIAL"] + d["MISS"]
        pos_s = ", ".join(sorted(d["positions"])) if d["positions"] else "--"
        lines.append(
            f"  {code:<8}  {total:>5}  {d['HIT']:>4}  {d['PARTIAL']:>3}  {d['MISS']:>3}  {pos_s}"
        )

    if unrecognised:
        lines.append(f"\n  Unrecognised FM codes: {dict(unrecognised)}")

    # Summary: comps with at least one FM tag
    tagged = sum(1 for r in pos_rows if _parse_fm_codes(r.get("fm_code") or ""))
    untagged = len(pos_rows) - tagged
    lines.append(f"\n  Comps with FM tag : {tagged}")
    lines.append(f"  Comps without FM  : {untagged}")

    return "\n".join(lines)


def _section_fm_reference(fm_rows: list[dict]) -> str:
    """
    Summarise FM reference rows (is_fm_reference=1) grouped by canonical FM code.
    """
    fm_data: dict[str, dict] = {
        code: {"HIT": 0, "PARTIAL": 0, "MISS": 0, "positions": set()}
        for code in CANONICAL_FM_CODES
    }
    uncovered: dict[str, int] = defaultdict(int)

    for r in fm_rows:
        codes = _parse_fm_codes(r.get("fm_code") or "")
        for code in codes:
            if code in fm_data:
                fm_data[code][r["translation_outcome"]] += 1
                fm_data[code]["positions"].add(r["position"])
            else:
                uncovered[code] += 1

    hdr = (
        f"\n  {'FM Code':<8}  {'Refs':>5}  {'MSS':>3}  {'PAR':>3}  {'HIT':>3}  "
        f"{'Positions covered'}"
    )
    lines = [
        _header("FM REFERENCE LIBRARY  (is_fm_reference=1)"),
        hdr,
        f"  {'-'*8}  {'-'*5}  {'-'*3}  {'-'*3}  {'-'*3}  {'-'*40}",
    ]

    for code in CANONICAL_FM_CODES:
        d     = fm_data[code]
        total = d["HIT"] + d["PARTIAL"] + d["MISS"]
        pos_s = ", ".join(sorted(d["positions"])) if d["positions"] else "--"
        lines.append(
            f"  {code:<8}  {total:>5}  {d['MISS']:>3}  {d['PARTIAL']:>3}  {d['HIT']:>3}  {pos_s}"
        )

    if uncovered:
        lines.append(f"\n  Rows with unrecognised FM codes: {dict(uncovered)}")

    return "\n".join(lines)


def _section_gap_report(pos_rows: list[dict]) -> str:
    """
    Flag canonical archetypes with fewer than GAP_THRESHOLD comps and
    canonical archetypes that have zero comps.
    """
    by_arch: dict[str, int] = defaultdict(int)
    for r in pos_rows:
        by_arch[r["archetype_code"]] += 1

    zero_coverage: list[str] = []
    thin_coverage: list[tuple[str, int]] = []

    for pos in CANONICAL_POSITIONS:
        n_arch = CANONICAL_ARCHETYPE_COUNTS[pos]
        for i in range(1, n_arch + 1):
            arch = f"{pos}-{i}"
            count = by_arch.get(arch, 0)
            if count == 0:
                zero_coverage.append(arch)
            elif count < GAP_THRESHOLD:
                thin_coverage.append((arch, count))

    lines = [_header("GAP REPORT")]
    lines.append(f"  Threshold: < {GAP_THRESHOLD} comps per archetype flagged as thin coverage.")
    lines.append("")

    if zero_coverage:
        lines.append(f"  ZERO COVERAGE ({len(zero_coverage)} archetypes -- not in historical_comps):")
        for arch in zero_coverage:
            lines.append(f"    {arch}")
    else:
        lines.append("  ZERO COVERAGE: none -- all canonical archetypes have at least one comp.")

    lines.append("")

    if thin_coverage:
        lines.append(f"  THIN COVERAGE ({len(thin_coverage)} archetypes -- below threshold {GAP_THRESHOLD}):")
        for arch, n in sorted(thin_coverage):
            lines.append(f"    {arch:<10}  {n} comp{'s' if n != 1 else ''}")
    else:
        lines.append(f"  THIN COVERAGE: none -- all canonical archetypes meet the {GAP_THRESHOLD}-comp threshold.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Read-only summary report for historical_comps table."
    )
    ap.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="Always 0 (read-only). Accepted for CLI convention consistency.",
    )
    args = ap.parse_args()

    if args.apply == 1:
        print("NOTE  --apply 1 has no effect. This script is read-only.")

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL  DB not found: {PATHS.db}")

    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db  = str(PATHS.db).replace("\\", "/")

    # Load data
    with connect() as conn:
        pos_rows = _load_position_comps(conn)
        fm_rows  = _load_fm_reference_rows(conn)

    # Render
    print("=" * 64)
    print(" APEX OS -- Historical Comps Summary")
    print(f" Generated : {ts}")
    print(f" DB        : {db}")
    print("=" * 64)

    print(_section_db_totals(pos_rows, fm_rows))
    print(_section_position_summary(pos_rows))
    print(_section_archetype_detail(pos_rows))
    print(_section_fm_usage(pos_rows))
    print(_section_fm_reference(fm_rows))
    print(_section_gap_report(pos_rows))

    print(f"\n{_sep()}")
    print(" END OF REPORT")
    print(_sep())
    print()


if __name__ == "__main__":
    main()
