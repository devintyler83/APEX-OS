"""
cb4_tweener_audit.py

Read-only diagnostic: surfaces all CB-4 Slot Specialist prospects, their APEX scores,
divergence signals, tags, and override history. Flags candidates where the CB-4
archetype assignment may warrant re-review against CB library criteria.

No writes. No --apply flag. Safe to run at any time.

Usage:
    python -m scripts.cb4_tweener_audit [--season-id 1]
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


def fetch_cb4_prospects(conn: sqlite3.Connection, season_id: int) -> list:
    sql = dedent("""
        SELECT
            p.prospect_id,
            p.display_name,
            p.school_canonical          AS school,
            p.position_group,
            a.matched_archetype         AS archetype,
            a.apex_composite            AS apex_score,
            a.apex_tier,
            a.apex_pos_rank,
            a.eval_confidence,
            a.failure_mode_primary,
            a.failure_mode_secondary,
            a.override_arch,
            a.override_rationale,
            cr.consensus_rank,
            cr.sources_covered,
            df.divergence_flag,
            df.divergence_rank_delta,
            df.divergence_mag,
            df.apex_favors_text,
            df.apex_composite           AS df_apex_composite
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
          AND a.matched_archetype LIKE 'CB-4%'
        ORDER BY a.apex_composite DESC
    """)
    return list(conn.execute(sql, (season_id, season_id, season_id, season_id)))


def fetch_tags(conn: sqlite3.Connection, pids: list, season_id: int) -> dict:
    if not pids:
        return {}
    placeholders = ", ".join("?" * len(pids))
    sql = f"""
        SELECT pt.prospect_id, td.tag_name, td.tag_category
        FROM prospect_tags pt
        JOIN tag_definitions td ON pt.tag_def_id = td.tag_def_id
        WHERE pt.prospect_id IN ({placeholders})
          AND pt.is_active = 1
        ORDER BY pt.prospect_id, td.display_order
    """
    rows = conn.execute(sql, pids).fetchall()
    tags: dict = {}
    for row in rows:
        tags.setdefault(row["prospect_id"], []).append(row["tag_name"])
    return tags


def fetch_overrides(conn: sqlite3.Connection, pids: list) -> dict:
    if not pids:
        return {}
    placeholders = ", ".join("?" * len(pids))
    sql = f"""
        SELECT
            prospect_id,
            override_type,
            field_changed,
            old_value,
            new_value,
            rationale,
            applied_at,
            applied_by
        FROM override_log
        WHERE prospect_id IN ({placeholders})
        ORDER BY prospect_id, applied_at DESC
    """
    rows = conn.execute(sql, pids).fetchall()
    overrides: dict = {}
    for row in rows:
        overrides.setdefault(row["prospect_id"], []).append(dict(row))
    return overrides


# CB-4 review flags: conditions that suggest potential archetype mis-assignment
def _review_flags(row, tags: list) -> list:
    flags = []
    div = row["divergence_flag"] or ""
    if div == "APEX_HIGH" and (row["divergence_rank_delta"] or 0) >= 20:
        flags.append(f"LARGE APEX_HIGH +{row['divergence_rank_delta']} ranks — verify slot deployment gate")
    if "Divergence Alert" in tags and "Scheme Dependent" in tags:
        flags.append("Divergence Alert + Scheme Dependent co-present — re-check CB-4 vs CB-3 assignment")
    if row["apex_tier"] == "ELITE":
        flags.append("ELITE tier at CB-4 — confirm era premium and confirmed-slot-deployment gate are met")
    if "Development Bet" in tags:
        flags.append("Development Bet tag — CB-4 capital eligibility requires confirmed slot deployment, not projection")
    fm = (row["failure_mode_primary"] or "") + " " + (row["failure_mode_secondary"] or "")
    if "FM-1" in fm:
        flags.append("FM-1 present — more consistent with CB-3 freak profile than CB-4 slot specialist")
    return flags


def _fmt_nullable(val, default="—") -> str:
    return str(val) if val is not None else default


def format_report(prospects: list, tags: dict, overrides: dict) -> str:
    lines = [
        "=" * 64,
        "CB-4 SLOT SPECIALIST AUDIT REPORT",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Divergence edge = consensus_rank - apex_pos_rank (positive = APEX above market).",
        "Review flags are heuristics — verify each candidate against the CB library.",
        "=" * 64,
        "",
    ]

    if not prospects:
        lines.append("No active CB-4 Slot Specialist prospects found for this season.")
        return "\n".join(lines)

    lines.append(f"Total CB-4 candidates: {len(prospects)}")
    lines.append("")

    for row in prospects:
        pid = row["prospect_id"]
        prospect_tags = tags.get(pid, [])
        prospect_overrides = overrides.get(pid, [])
        review_flags = _review_flags(row, prospect_tags)

        consensus_rank = _fmt_nullable(row["consensus_rank"])
        apex_pos_rank = _fmt_nullable(row["apex_pos_rank"])
        rank_delta = _fmt_nullable(row["divergence_rank_delta"])
        if row["divergence_rank_delta"] is not None and row["divergence_rank_delta"] > 0:
            rank_delta = f"+{row['divergence_rank_delta']}"

        lines += [
            "-" * 64,
            f"PID:            {pid}",
            f"Name:           {row['display_name']} ({row['school']})",
            f"Archetype:      {row['archetype']}",
            f"APEX:           {row['apex_score']:.1f}  {row['apex_tier']}",
            f"Consensus Rank: {consensus_rank}  (sources: {_fmt_nullable(row['sources_covered'])})",
            f"APEX Pos Rank:  {apex_pos_rank}",
            f"Rank Delta:     {rank_delta}  ({_fmt_nullable(row['divergence_flag'])}  {_fmt_nullable(row['divergence_mag'])})",
            f"Eval Conf:      {_fmt_nullable(row['eval_confidence'])}",
            f"FM Primary:     {_fmt_nullable(row['failure_mode_primary'])}",
            f"FM Secondary:   {_fmt_nullable(row['failure_mode_secondary'])}",
            f"Tags:           {' | '.join(prospect_tags) if prospect_tags else '—'}",
        ]

        if row["override_arch"]:
            lines.append(f"Inline Override:{row['override_arch']}  — {_fmt_nullable(row['override_rationale'])}")
        else:
            lines.append("Inline Override:—")

        if prospect_overrides:
            lines.append("Override Log:")
            for ov in prospect_overrides:
                lines.append(
                    f"  [{ov['applied_at'][:10]}] {ov['override_type']} | "
                    f"{ov['field_changed']}: {ov['old_value']} → {ov['new_value']} | "
                    f"{ov['rationale']} ({ov['applied_by']})"
                )
        else:
            lines.append("Override Log:   —")

        if review_flags:
            lines.append("REVIEW FLAGS:")
            for flag in review_flags:
                lines.append(f"  !! {flag}")
        else:
            lines.append("Review Flags:   none")

        lines.append("")

    lines += [
        "=" * 64,
        "CB-4 ARCHETYPE DEFINITION CHECKLIST (from CB library)",
        "",
        "  CONFIRM before accepting assignment:",
        "  1. Confirmed slot deployment (not projected) — capital gate",
        "  2. Elite processing / anticipation in condensed space",
        "  3. Era premium applied (slot scarcity in modern NFL)",
        "  4. FM-6 Role Mismatch is primary bust mode, not FM-1",
        "  5. CB-3 athletic-freak profile NOT the win mechanism",
        "",
        "  For each candidate with REVIEW FLAGS above:",
        "    A. Open DraftOS_Position_CB.docx, CB-4 section",
        "    B. Watch 5-6 film reps — slot alignment + route recognition",
        "    C. Override via ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py",
        "       + re-score: python -m scripts.run_apex_scoring_2026 --batch top50 --force --apply 1",
        "=" * 64,
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Read-only audit of CB-4 Slot Specialist archetype assignments."
    )
    parser.add_argument("--season-id", type=int, default=1,
                        help="Season ID to audit (default: 1 for 2026).")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        prospects = fetch_cb4_prospects(conn, args.season_id)
        pids = [r["prospect_id"] for r in prospects]
        tags = fetch_tags(conn, pids, args.season_id)
        overrides = fetch_overrides(conn, pids)
    finally:
        conn.close()

    report = format_report(prospects, tags, overrides)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"cb4_tweener_audit_{stamp}.txt"
    log_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport written to {log_path}")


if __name__ == "__main__":
    main()
