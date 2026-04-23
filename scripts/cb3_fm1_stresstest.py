"""
cb3_fm1_stresstest.py

Read-only diagnostic:
- Identify CB-3 prospects with FM-1 (Athleticism Mirage) as primary or secondary failure mode.
- Surface divergence vs consensus and dev-trajectory / eval-confidence context.
- Flags: over-penalizing (large APEX_LOW + FM-1 secondary only) vs confirmed mirage
  (FM-1 primary, low v_athleticism, weak processing).

No writes. Safe to run at any time.

Usage:
    python -m scripts.cb3_fm1_stresstest [--season-id 1]
"""

import argparse
import datetime
import pathlib
import sqlite3
from textwrap import dedent

from draftos.config import PATHS

LOG_DIR = pathlib.Path(__file__).resolve().parents[1] / "draftos" / "logs"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(PATHS.db)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_cb3_candidates(conn: sqlite3.Connection, season_id: int) -> list:
    """
    Returns one row per (prospect, apex_scores) combination where:
      - position_group = CB, is_active = 1
      - matched_archetype starts with CB-3
      - FM-1 present in primary OR secondary failure mode
    Also pulls deep-APEX_LOW CB-3s even without FM-1 (potential over-penalization
    via a different mechanism that may still need PAA Q3/Q4 re-check).
    Multiple archetype rows per prospect are intentional — surfaces the full
    scoring picture when the model evaluated more than one CB-3 sub-archetype.
    """
    sql = dedent("""
        SELECT
            p.prospect_id,
            p.display_name,
            p.school_canonical          AS school,
            a.apex_id,
            a.matched_archetype         AS archetype,
            a.apex_composite            AS apex_score,
            a.apex_tier,
            a.eval_confidence,
            a.failure_mode_primary      AS fm_primary,
            a.failure_mode_secondary    AS fm_secondary,
            a.v_athleticism,
            a.v_processing,
            a.v_dev_traj,
            a.v_production,
            a.v_scheme_vers,
            a.v_comp_tough,
            cr.consensus_rank,
            cr.sources_covered,
            df.divergence_flag,
            df.divergence_rank_delta,
            df.divergence_mag,
            df.apex_favors_text
        FROM prospects p
        JOIN apex_scores a
            ON p.prospect_id = a.prospect_id
           AND a.season_id = ?
           AND a.is_calibration_artifact = 0
        LEFT JOIN prospect_consensus_rankings cr
            ON p.prospect_id = cr.prospect_id
           AND cr.season_id = ?
        LEFT JOIN (
            SELECT *
            FROM divergence_flags
            WHERE season_id = ?
              AND div_id IN (
                  SELECT MAX(div_id)
                  FROM divergence_flags
                  WHERE season_id = ?
                  GROUP BY prospect_id
              )
        ) df ON p.prospect_id = df.prospect_id
        WHERE p.is_active = 1
          AND p.position_group = 'CB'
          AND a.matched_archetype LIKE 'CB-3%'
          AND (
              a.failure_mode_primary   LIKE '%FM-1%'
           OR a.failure_mode_secondary LIKE '%FM-1%'
           OR (df.divergence_rank_delta IS NOT NULL AND df.divergence_rank_delta <= -50)
          )
        ORDER BY p.prospect_id, a.apex_composite DESC
    """)
    return list(conn.execute(sql, (season_id, season_id, season_id, season_id)))


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


def _fm1_stress_flags(row) -> list:
    """Heuristics for separating confirmed mirage from potential over-penalty."""
    flags = []
    fm1_primary   = (row["fm_primary"]   or "").startswith("FM-1")
    fm1_secondary = (row["fm_secondary"] or "").startswith("FM-1")
    div_delta     = row["divergence_rank_delta"] or 0
    v_ath         = row["v_athleticism"]
    v_proc        = row["v_processing"]

    if fm1_primary and (v_ath is None or v_ath >= 7.0):
        flags.append("FM-1 PRIMARY but v_athleticism high — re-check if mirage or genuine freak")
    if fm1_primary and v_proc is not None and v_proc >= 7.5:
        flags.append("FM-1 PRIMARY but v_processing high — may be CB-3 Athletic Freak mis-labelled Press Man")
    if fm1_secondary and div_delta <= -75:
        flags.append(f"FM-1 SECONDARY + APEX_LOW {div_delta} — check if PAA Q3/Q4 is the actual driver, not FM-1")
    if fm1_primary and div_delta >= 20:
        flags.append(f"FM-1 PRIMARY + APEX_HIGH +{div_delta} — unusual; verify archetype assignment before trusting edge")
    if not fm1_primary and not fm1_secondary and div_delta <= -50:
        flags.append(f"No FM-1 but APEX_LOW {div_delta} — large gap driven by different mechanism; note for PAA review")
    return flags


def _v(val, precision: int = 1) -> str:
    if val is None:
        return "—"
    return f"{val:.{precision}f}"


def _fmt_delta(delta) -> str:
    if delta is None:
        return "—"
    return f"+{delta}" if delta > 0 else str(delta)


def format_report(rows: list, tags: dict) -> str:
    lines = [
        "=" * 68,
        "CB-3 FM-1 ATHLETICISM MIRAGE STRESS TEST",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Negative rank delta = APEX below market (model penalizing).",
        "Positive rank delta = APEX above market (model discounting FM-1 concern).",
        "",
        "Candidates: CB-3 rows with FM-1 primary/secondary, OR APEX_LOW >= -50 ranks.",
        "Multiple rows per prospect = multiple archetype evaluations (intentional).",
        "=" * 68,
        "",
    ]

    if not rows:
        lines.append("No CB-3 FM-1 / deep APEX_LOW candidates found.")
        return "\n".join(lines)

    lines.append(f"Total CB-3 FM-1 rows: {len(rows)}")
    lines.append(f"Unique prospects:     {len({r['prospect_id'] for r in rows})}")
    lines.append("")

    seen_pid = None
    for row in rows:
        pid = row["prospect_id"]
        if pid != seen_pid:
            seen_pid = pid
            prospect_tags = tags.get(pid, [])
            lines += [
                "-" * 68,
                f"PID:          {pid}",
                f"Name:         {row['display_name']} ({row['school']})",
                f"Consensus:    {_v(row['consensus_rank'], 0)}  (sources: {_v(row['sources_covered'], 0)})",
                f"Divergence:   {_fmt_delta(row['divergence_rank_delta'])}  "
                f"{row['divergence_flag'] or '—'}  {row['divergence_mag'] or ''}",
                f"Tags:         {' | '.join(prospect_tags) if prospect_tags else '—'}",
                "",
                "  Archetype evaluations:",
            ]

        fm_marker = ""
        if (row["fm_primary"] or "").startswith("FM-1"):
            fm_marker = "  << FM-1 PRIMARY"
        elif (row["fm_secondary"] or "").startswith("FM-1"):
            fm_marker = "  << FM-1 secondary"

        lines += [
            f"    Archetype:  {row['archetype']}",
            f"    APEX:       {row['apex_score']:.1f}  {row['apex_tier']}  "
            f"(conf: {row['eval_confidence'] or '—'})",
            f"    FM Primary: {row['fm_primary'] or '—'}{fm_marker}",
            f"    FM Second:  {row['fm_secondary'] or '—'}",
            f"    Vectors:    ATH={_v(row['v_athleticism'])}  "
            f"PROC={_v(row['v_processing'])}  "
            f"DEV={_v(row['v_dev_traj'])}  "
            f"PROD={_v(row['v_production'])}  "
            f"SCH={_v(row['v_scheme_vers'])}  "
            f"COMP={_v(row['v_comp_tough'])}",
        ]

        stress_flags = _fm1_stress_flags(row)
        if stress_flags:
            lines.append("    STRESS FLAGS:")
            for flag in stress_flags:
                lines.append(f"      !! {flag}")
        else:
            lines.append("    Stress Flags: none")
        lines.append("")

    lines += [
        "=" * 68,
        "PAA Q3/Q4 RE-CHECK PROTOCOL (CB library, CB-3 section)",
        "",
        "  Q3: Does athleticism translate to contested coverage wins?",
        "      (Not just measurables — FILM evidence of winning contested reps.)",
        "  Q4: Is the burst/twitch replicable vs NFL route trees, or scheme-assisted?",
        "",
        "  FM-1 CONFIRMED (keep penalty):  Q3=No, Q4=No, v_athleticism shows in",
        "      measurables but not in contested coverage outcomes.",
        "  FM-1 OVER-PENALTY (reduce/reclassify):  Q3=Yes on tape, v_processing>=7,",
        "      APEX_LOW driven by PAA gates not by athleticism ceiling.",
        "",
        "  If reclassifying: update ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py",
        "  and re-score: python -m scripts.run_apex_scoring_2026 --batch top50 --force --apply 1",
        "=" * 68,
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Stress-test CB-3 FM-1 Athleticism Mirage assignments vs divergence."
    )
    parser.add_argument("--season-id", type=int, default=1,
                        help="Season ID to audit (default: 1 for 2026).")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        rows = fetch_cb3_candidates(conn, args.season_id)
        pids = list({r["prospect_id"] for r in rows})
        tags = fetch_tags(conn, pids)
    finally:
        conn.close()

    report = format_report(rows, tags)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"cb3_fm1_stresstest_{stamp}.txt"
    log_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport written to {log_path}")


if __name__ == "__main__":
    main()
