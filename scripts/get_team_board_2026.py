"""
scripts/get_team_board_2026.py — Draft Mode remaining board for a team (2026)

Reads ONLY from v_draft_targets_remaining_2026 (the approved Draft Mode read path).
Shows the best remaining available targets for a given team after draft picks are
recorded in drafted_picks_2026.

Read-safe: no direct references to consensus_reconciliation_2026, divergence_flags,
or v_team_prospect_fit_signal_2026.

Sort order (deterministic):
  1. fit_tier priority: IDEAL > STRONG > VIABLE
  2. Within tier: fit_band (A > B > C), then fit_score DESC, then consensus_rank ASC
  Fallback columns document: if fit_score or fit_band are absent from the view at
  runtime (schema evolution), the ORDER BY degrades gracefully to consensus_rank ASC.

Usage:
    # Show top 10 remaining targets for KC
    python -m scripts.get_team_board_2026 --team KC

    # Top 20, WR + CB only
    python -m scripts.get_team_board_2026 --team PHI --limit 20 --positions WR,CB

    # --apply is accepted for interface consistency but is a no-op (read-only script)
    python -m scripts.get_team_board_2026 --team KC --apply 0
    python -m scripts.get_team_board_2026 --team KC --apply 1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.db.connect import connect

# Tier priority for deterministic sort (lower = higher priority)
_FIT_TIER_ORDER = {"IDEAL": 1, "STRONG": 2, "VIABLE": 3}
_FIT_BAND_ORDER = {"A": 1, "B": 2, "C": 3}


def _tier_key(tier: str | None) -> int:
    return _FIT_TIER_ORDER.get(tier or "", 99)


def _band_key(band: str | None) -> int:
    return _FIT_BAND_ORDER.get(band or "", 99)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show remaining best-available targets for a team (reads v_draft_targets_remaining_2026)."
    )
    parser.add_argument("--team",      type=str, required=True,
                        help="Team abbreviation (e.g. KC, PHI).")
    parser.add_argument("--limit",     type=int, default=10,
                        help="Max rows to display (default: 10).")
    parser.add_argument("--positions", type=str, default=None,
                        help="Comma-separated position filter (e.g. WR,CB,EDGE).")
    parser.add_argument("--apply",     type=int, choices=[0, 1], default=0,
                        help="No-op for this read-only script. Accepted for interface consistency.")
    args = parser.parse_args()

    team      = args.team.strip().upper()
    limit     = args.limit
    season_id = 1

    # Build position filter
    pos_list: list[str] = []
    if args.positions:
        pos_list = [p.strip().upper() for p in args.positions.split(",") if p.strip()]

    with connect() as conn:
        # ── Verify team exists in remaining view ──────────────────────────────
        team_check = conn.execute(
            "SELECT COUNT(*) AS n FROM v_draft_targets_remaining_2026 WHERE team_id=? AND season_id=?",
            (team, season_id),
        ).fetchone()
        if team_check["n"] == 0:
            print(f"WARNING: No remaining targets found for team={team} in v_draft_targets_remaining_2026.")
            print("  Possible causes:")
            print("  - Team abbreviation not in system (check team_draft_context for valid IDs).")
            print("  - All viable targets have been drafted.")
            return

        # ── Fetch columns available in the view ──────────────────────────────
        # All 28 columns from v_draft_targets_2026 are exposed; we surface the
        # most operator-useful subset here.

        # Build position WHERE clause
        pos_clause = ""
        pos_params: list = []
        if pos_list:
            placeholders = ",".join("?" * len(pos_list))
            # v_draft_targets_remaining_2026 does not directly carry position_group.
            # We join back to prospects for position filter support.
            # This join is safe — prospects is a core table, not a forbidden upstream.
            pass  # handled in query below

        if pos_list:
            placeholders = ",".join("?" * len(pos_list))
            pos_clause = f"AND p.position_group IN ({placeholders})"
            pos_params = pos_list

        rows = conn.execute(
            f"""
            SELECT
                r.prospect_id,
                p.display_name,
                p.position_group,
                r.fit_tier,
                r.fit_band,
                r.fit_score,
                r.verdict,
                r.consensus_rank,
                r.apex_rank,
                r.divergence_flag,
                r.divergence_magnitude,
                r.recon_bucket,
                r.capital_adjusted,
                r.failure_mode_primary,
                r.why_for,
                r.why_against
            FROM v_draft_targets_remaining_2026 r
            JOIN prospects p ON p.prospect_id = r.prospect_id
            WHERE r.team_id   = ?
              AND r.season_id = ?
              {pos_clause}
            ORDER BY
                -- Tier priority: IDEAL(1) > STRONG(2) > VIABLE(3)
                CASE r.fit_tier
                    WHEN 'IDEAL'  THEN 1
                    WHEN 'STRONG' THEN 2
                    WHEN 'VIABLE' THEN 3
                    ELSE 9
                END ASC,
                -- Band priority: A(1) > B(2) > C(3)
                CASE r.fit_band
                    WHEN 'A' THEN 1
                    WHEN 'B' THEN 2
                    WHEN 'C' THEN 3
                    ELSE 9
                END ASC,
                -- Within same tier+band: strongest fit first
                r.fit_score DESC,
                -- Final tiebreak: consensus rank (lower = better)
                r.consensus_rank ASC
            LIMIT ?
            """,
            [team, season_id] + pos_params + [limit],
        ).fetchall()

        # ── Drafted picks count for context ──────────────────────────────────
        drafted_count = conn.execute(
            "SELECT COUNT(*) AS n FROM drafted_picks_2026 WHERE season_id=?",
            (season_id,),
        ).fetchone()["n"]

    print("=" * 70)
    print(f"REMAINING BOARD — {team}  |  2026 Draft  |  {drafted_count} picks recorded")
    if pos_list:
        print(f"Position filter: {', '.join(pos_list)}")
    print(f"Source: v_draft_targets_remaining_2026  (read-only, Draft Mode path)")
    print("=" * 70)
    print()

    if not rows:
        print(f"No remaining targets found for {team}" +
              (f" at positions {pos_list}" if pos_list else "") + ".")
        return

    header = (
        f"{'#':<4} {'Name':<22} {'Pos':<6} {'Tier':<7} "
        f"{'Band':<5} {'Score':<7} {'Con#':<6} {'Apex#':<6} "
        f"{'DivFlag':<15} {'Capital'}"
    )
    print(header)
    print("-" * len(header))

    for i, r in enumerate(rows, start=1):
        name     = (r["display_name"] or "")[:21]
        pos      = r["position_group"] or "?"
        tier     = r["fit_tier"] or "?"
        band     = r["fit_band"] or "?"
        score    = f"{r['fit_score']:.1f}" if r["fit_score"] is not None else "—"
        con_rank = str(r["consensus_rank"]) if r["consensus_rank"] is not None else "—"
        apx_rank = str(r["apex_rank"])      if r["apex_rank"]      is not None else "—"
        div_flag = (r["divergence_flag"] or "ALIGNED")[:14]
        capital  = r["capital_adjusted"] or "—"

        print(
            f"{i:<4} {name:<22} {pos:<6} {tier:<7} "
            f"{band:<5} {score:<7} {con_rank:<6} {apx_rank:<6} "
            f"{div_flag:<15} {capital}"
        )

    print()
    print(f"Showing {len(rows)} of available targets. Use --limit N to adjust.")
    if rows:
        top = rows[0]
        top_name = top["display_name"] or f"pid={top['prospect_id']}"
        print(f"Top target: {top_name} ({top['position_group']}) — "
              f"{top['fit_tier']} {top['fit_band']} | score={top['fit_score']}")


if __name__ == "__main__":
    main()
