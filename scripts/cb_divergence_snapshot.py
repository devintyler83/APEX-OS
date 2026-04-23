"""
cb_divergence_snapshot.py

Read-only diagnostic:
- List all active CB prospects with APEX vs consensus divergence.
- One row per prospect (best apex_composite where multiple archetype evals exist).
- Groups into APEX_HIGH / ALIGNED / APEX_LOW bands.
- CB is a premium position — divergence is actionable here.

No writes. Safe to run at any time.

Usage:
    python -m scripts.cb_divergence_snapshot [--season-id 1] [--min-sources 0]
"""

import argparse
import datetime
import pathlib
import sqlite3
from textwrap import dedent

from draftos.config import PATHS

LOG_DIR = pathlib.Path(__file__).resolve().parents[1] / "draftos" / "logs"

# Band thresholds (rank-relative, consistent with divergence engine)
HIGH_THRESHOLD  =  20   # consensus_rank - apex rank >= this → APEX_HIGH
LOW_THRESHOLD   = -20   # <= this → APEX_LOW


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(PATHS.db)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_cb_board(conn: sqlite3.Connection, season_id: int, min_sources: int) -> list:
    """
    Returns one row per active CB prospect using the highest apex_composite score.
    When a prospect has multiple archetype evaluations, the best-performing one is
    the model's primary assessment.
    Divergence comes from divergence_flags (latest div_id per prospect).
    """
    sql = dedent("""
        WITH best_apex AS (
            SELECT
                prospect_id,
                MAX(apex_composite) AS best_composite
            FROM apex_scores
            WHERE season_id = ?
              AND is_calibration_artifact = 0
            GROUP BY prospect_id
        ),
        primary_score AS (
            SELECT a.*
            FROM apex_scores a
            JOIN best_apex b
                ON a.prospect_id = b.prospect_id
               AND a.apex_composite = b.best_composite
               AND a.season_id = ?
               AND a.is_calibration_artifact = 0
        ),
        latest_div AS (
            SELECT *
            FROM divergence_flags
            WHERE season_id = ?
              AND div_id IN (
                  SELECT MAX(div_id)
                  FROM divergence_flags
                  WHERE season_id = ?
                  GROUP BY prospect_id
              )
        )
        SELECT
            p.prospect_id,
            p.display_name,
            p.school_canonical          AS school,
            a.matched_archetype         AS archetype,
            a.apex_composite            AS apex_score,
            a.apex_tier,
            a.eval_confidence,
            a.failure_mode_primary      AS fm_primary,
            a.failure_mode_secondary    AS fm_secondary,
            cr.consensus_rank,
            cr.sources_covered,
            df.divergence_flag,
            df.divergence_rank_delta,
            df.divergence_mag,
            df.apex_favors_text
        FROM prospects p
        JOIN primary_score a
            ON p.prospect_id = a.prospect_id
        LEFT JOIN prospect_consensus_rankings cr
            ON p.prospect_id = cr.prospect_id
           AND cr.season_id = ?
        LEFT JOIN latest_div df
            ON p.prospect_id = df.prospect_id
        WHERE p.is_active = 1
          AND p.position_group = 'CB'
          AND (? = 0 OR COALESCE(cr.sources_covered, 0) >= ?)
        ORDER BY
            COALESCE(df.divergence_rank_delta, 0) DESC,
            a.apex_composite DESC
    """)
    return list(conn.execute(sql, (
        season_id, season_id, season_id, season_id, season_id,
        min_sources, min_sources
    )))


def fetch_tags(conn: sqlite3.Connection, pids: list) -> dict:
    if not pids:
        return {}
    placeholders = ", ".join("?" * len(pids))
    sql = f"""
        SELECT pt.prospect_id, td.tag_name
        FROM prospect_tags pt
        JOIN tag_definitions td ON pt.tag_def_id = td.tag_def_id
        WHERE pt.prospect_id IN ({placeholders})
          AND pt.is_active = 1
        ORDER BY pt.prospect_id, td.display_order
    """
    rows = conn.execute(sql, pids).fetchall()
    result: dict = {}
    for row in rows:
        result.setdefault(row["prospect_id"], []).append(row["tag_name"])
    return result


def _band(delta) -> str:
    if delta is None:
        return "NO_CONSENSUS"
    if delta >= HIGH_THRESHOLD:
        return "APEX_HIGH"
    if delta <= LOW_THRESHOLD:
        return "APEX_LOW"
    return "ALIGNED"


def _fmt_delta(delta) -> str:
    if delta is None:
        return "  ?"
    return f"{delta:+4d}"


def _short_tags(tag_list: list) -> str:
    if not tag_list:
        return ""
    return " | ".join(tag_list)[:60]


def format_report(rows: list, tags: dict, min_sources: int) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = [
        "=" * 80,
        "CB DIVERGENCE SNAPSHOT",
        f"Generated: {now}",
        f"Min sources filter: {min_sources}  (0 = show all)",
        "",
        "EDGE = consensus_rank - apex_rank  (+pos = APEX above market, -neg = APEX below).",
        f"Bands: APEX_HIGH >= +{HIGH_THRESHOLD} | ALIGNED | APEX_LOW <= {LOW_THRESHOLD}",
        "One row per prospect; best apex_composite used when multiple evals exist.",
        "=" * 80,
        "",
    ]

    if not rows:
        return "\n".join(header + ["No active CB prospects found."])

    # Separate bands
    high  = [r for r in rows if _band(r["divergence_rank_delta"]) == "APEX_HIGH"]
    aln   = [r for r in rows if _band(r["divergence_rank_delta"]) == "ALIGNED"]
    low   = [r for r in rows if _band(r["divergence_rank_delta"]) == "APEX_LOW"]
    nocon = [r for r in rows if _band(r["divergence_rank_delta"]) == "NO_CONSENSUS"]

    col_hdr = (
        f"{'BAND':<14} {'PID':>4}  {'APEX':>5}  {'CONS':>4}  {'EDGE':>5}  "
        f"{'TIER':<6}  {'ARCHETYPE':<26}  {'NAME (SCHOOL)'}"
    )

    def fmt_row(row) -> list:
        band  = _band(row["divergence_rank_delta"])
        delta = _fmt_delta(row["divergence_rank_delta"])
        apex  = f"{row['apex_score']:5.1f}" if row["apex_score"] else "  —  "
        cons  = f"{row['consensus_rank']:4d}" if row["consensus_rank"] else "  ?"
        arch  = (row["archetype"] or "—")[:26]
        tier  = (row["apex_tier"] or "—")[:6]
        pid   = row["prospect_id"]
        name  = f"{row['display_name']} ({row['school']})"
        tag_str = _short_tags(tags.get(pid, []))
        fm_str = ""
        if row["fm_primary"]:
            fm_str = f"  [{row['fm_primary']}"
            if row["fm_secondary"]:
                fm_str += f" / {row['fm_secondary']}"
            fm_str += "]"

        line1 = (
            f"{band:<14} {pid:>4}  {apex}  {cons}  {delta}  "
            f"{tier:<6}  {arch:<26}  {name}"
        )
        extras = []
        if fm_str:
            extras.append(f"{'':>14}       FM: {fm_str.strip()}")
        if tag_str:
            extras.append(f"{'':>14}       Tags: {tag_str}")
        return [line1] + extras

    lines = header[:]

    for band_label, band_rows, note in [
        ("APEX_HIGH", high, f"APEX above market (+{HIGH_THRESHOLD}+ ranks) — monitor for mis-priced signal"),
        ("ALIGNED",   aln,  "Within ±20 ranks of consensus"),
        ("APEX_LOW",  low,  f"APEX below market (>{abs(LOW_THRESHOLD)} ranks) — check FM-1/PAA gate correctness"),
        ("NO_CONSENSUS", nocon, "No consensus row (coverage gap — divergence not actionable)"),
    ]:
        if not band_rows:
            continue
        lines += [
            f"-- {band_label} ({len(band_rows)})  {note}",
            col_hdr,
            "-" * 80,
        ]
        for row in band_rows:
            lines.extend(fmt_row(row))
        lines.append("")

    lines += [
        "=" * 80,
        f"TOTAL: {len(rows)} CBs  |  HIGH={len(high)}  ALIGNED={len(aln)}  "
        f"LOW={len(low)}  NO_CONSENSUS={len(nocon)}",
        "=" * 80,
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Snapshot of all CB divergence (APEX vs consensus) with archetype and tags."
    )
    parser.add_argument("--season-id", type=int, default=1,
                        help="Season ID (default: 1 for 2026).")
    parser.add_argument("--min-sources", type=int, default=0,
                        help="Filter to prospects with >= N sources covered (default: 0 = all).")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        rows = fetch_cb_board(conn, args.season_id, args.min_sources)
        pids = [r["prospect_id"] for r in rows]
        tags = fetch_tags(conn, pids)
    finally:
        conn.close()

    report = format_report(rows, tags, args.min_sources)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"cb_divergence_snapshot_{stamp}.txt"
    log_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport written to {log_path}")


if __name__ == "__main__":
    main()
