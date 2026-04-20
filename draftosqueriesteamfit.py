from __future__ import annotations

import json
from typing import Any


def _loads(v: str | None, fallback):
    if not v:
        return fallback
    try:
        return json.loads(v)
    except Exception:
        return fallback


def get_team_draft_context(conn, season_id: int, team_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            team_id,
            team_name,
            development_timeline,
            risk_tolerance,
            primary_offense_family,
            primary_defense_family,
            coverage_bias,
            man_rate_tolerance,
            premium_needs_json,
            depth_chart_pressure_json,
            draft_capital_json,
            notes
        FROM team_draft_context
        WHERE season_id = ?
          AND team_id = ?
          AND is_active = 1
        """,
        (season_id, team_id),
    ).fetchone()

    if not row:
        return None

    return {
        "team_id": row["team_id"],
        "team_name": row["team_name"],
        "development_timeline": row["development_timeline"],
        "risk_tolerance": row["risk_tolerance"],
        "primary_offense_family": row["primary_offense_family"],
        "primary_defense_family": row["primary_defense_family"],
        "coverage_bias": row["coverage_bias"],
        "man_rate_tolerance": row["man_rate_tolerance"],
        "premium_needs": _loads(row["premium_needs_json"], []),
        "depth_chart_pressure": _loads(row["depth_chart_pressure_json"], {}),
        "draft_capital": _loads(row["draft_capital_json"], {}),
        "notes": row["notes"],
    }


def get_player_team_fit_context(conn, prospect_id: int, season_id: int, model_version: str = "apex_v2.3") -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            p.prospect_id,
            p.display_name,
            p.position_group,
            a.matched_archetype,
            a.failuremodeprimary,
            a.failuremodesecondary,
            a.capitalrange,
            a.apex_tier,
            a.eval_confidence,
            d.divergence_rank_delta
        FROM prospects p
        JOIN apex_scores a
          ON a.prospect_id = p.prospect_id
         AND a.season_id = p.season_id
        LEFT JOIN divergence_flags d
          ON d.prospect_id = p.prospect_id
         AND d.season_id = p.season_id
         AND d.model_version = a.model_version
        WHERE p.prospect_id = ?
          AND p.season_id = ?
          AND p.is_active = 1
          AND a.model_version = ?
          AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
        """,
        (prospect_id, season_id, model_version),
    ).fetchone()

    if not row:
        return None

    fms = [x for x in [row["failuremodeprimary"], row["failuremodesecondary"]] if x]
    fms = [x.split()[0] for x in fms]

    return {
        "prospect_id": row["prospect_id"],
        "display_name": row["display_name"],
        "position_group": row["position_group"],
        "matched_archetype": row["matched_archetype"],
        "active_fm_codes": fms,
        "capital_range": row["capitalrange"],
        "apex_tier": row["apex_tier"],
        "eval_confidence": row["eval_confidence"],
        "divergence_rank_delta": row["divergence_rank_delta"],
    }