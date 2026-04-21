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
        "team_id":                row["team_id"],
        "team_name":              row["team_name"],
        "development_timeline":   row["development_timeline"],
        "risk_tolerance":         row["risk_tolerance"],
        "primary_offense_family": row["primary_offense_family"],
        "primary_defense_family": row["primary_defense_family"],
        "coverage_bias":          row["coverage_bias"],
        "man_rate_tolerance":     row["man_rate_tolerance"],
        "premium_needs":          _loads(row["premium_needs_json"], []),
        "depth_chart_pressure":   _loads(row["depth_chart_pressure_json"], {}),
        "draft_capital":          _loads(row["draft_capital_json"], {}),
        "notes":                  row["notes"],
    }


def get_player_team_fit_context(
    conn,
    prospect_id: int,
    season_id: int,
    model_version: str = "apex_v2.3",
) -> dict[str, Any] | None:
    """
    Return prospect context dict shaped for evaluate_team_fit().

    Fixed: uses correct apex_scores column names:
      failure_mode_primary   (was: failuremodeprimary)
      failure_mode_secondary (was: failuremodesecondary)
      capital_adjusted       (was: capitalrange — column does not exist)
    """
    row = conn.execute(
        """
        SELECT
            p.prospect_id,
            p.display_name,
            p.position_group,
            a.matched_archetype,
            a.failure_mode_primary,
            a.failure_mode_secondary,
            a.capital_adjusted,
            a.apex_tier,
            a.eval_confidence,
            d.divergence_rank_delta
        FROM prospects p
        JOIN apex_scores a
          ON a.prospect_id = p.prospect_id
         AND a.season_id   = p.season_id
        LEFT JOIN divergence_flags d
          ON d.prospect_id   = p.prospect_id
         AND d.season_id     = p.season_id
         AND d.model_version = a.model_version
        WHERE p.prospect_id = ?
          AND p.season_id   = ?
          AND p.is_active   = 1
          AND a.model_version = ?
          AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
        """,
        (prospect_id, season_id, model_version),
    ).fetchone()

    if not row:
        return None

    # Extract FM codes ("FM-4 Body Breakdown" → "FM-4")
    fms = [
        x.split()[0]
        for x in [row["failure_mode_primary"], row["failure_mode_secondary"]]
        if x
    ]

    return {
        "prospect_id":           row["prospect_id"],
        "display_name":          row["display_name"],
        "position_group":        row["position_group"],
        "matched_archetype":     row["matched_archetype"],
        "active_fm_codes":       fms,
        "capital_range":         row["capital_adjusted"],
        "apex_tier":             row["apex_tier"],
        "eval_confidence":       row["eval_confidence"],
        "divergence_rank_delta": row["divergence_rank_delta"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Signal view helpers — backed by v_team_prospect_fit_signal_2026 (Migration 0051)
# View is pre-filtered to season_id=1, fit_tier IN ('IDEAL','STRONG','VIABLE').
# ──────────────────────────────────────────────────────────────────────────────

# Tier quality order, highest to lowest, matching the view's allowed set.
_SIGNAL_TIER_ORDER: list[str] = ["IDEAL", "STRONG", "VIABLE"]


def _tiers_at_or_above(min_tier: str) -> list[str]:
    """
    Return all tier labels that are >= min_tier in the fit quality hierarchy.

    The signal view covers only IDEAL/STRONG/VIABLE.  Passing a tier outside
    that set raises ValueError so callers fail loudly rather than silently
    returning an empty result.

    Examples:
        _tiers_at_or_above("VIABLE") → ["IDEAL", "STRONG", "VIABLE"]
        _tiers_at_or_above("STRONG") → ["IDEAL", "STRONG"]
        _tiers_at_or_above("IDEAL")  → ["IDEAL"]
    """
    key = min_tier.upper()
    if key not in _SIGNAL_TIER_ORDER:
        raise ValueError(
            f"min_tier must be one of {_SIGNAL_TIER_ORDER}, got {min_tier!r}. "
            "The signal view does not include FRINGE or POOR rows."
        )
    cutoff = _SIGNAL_TIER_ORDER.index(key)
    return _SIGNAL_TIER_ORDER[: cutoff + 1]


def get_team_fit_signal_for_team(
    conn,
    team_id: str,
    min_tier: str = "VIABLE",
    season_id: int = 1,
) -> list[dict[str, Any]]:
    """
    Return all signal-tier prospect fits for a given team, ordered by fit_score DESC.

    Backed by v_team_prospect_fit_signal_2026 (Migration 0051).
    The view is pre-filtered to season_id=1 and fit_tier IN ('IDEAL','STRONG','VIABLE').

    Args:
        conn:      sqlite3 connection with row_factory = sqlite3.Row.
        team_id:   NFL team abbreviation (e.g. "KC", "PHI").
        min_tier:  Minimum fit quality to include. One of 'IDEAL', 'STRONG', 'VIABLE'.
                   Defaults to 'VIABLE' (returns all three signal tiers).
        season_id: Season scope. Defaults to 1 (2026 draft year). Must match the
                   view's baked-in season_id=1 filter or the result will be empty.

    Returns:
        List of dicts, each containing all view columns. Empty list if no matches.
    """
    tiers = _tiers_at_or_above(min_tier)
    placeholders = ",".join("?" * len(tiers))
    rows = conn.execute(
        f"""
        SELECT *
        FROM v_team_prospect_fit_signal_2026
        WHERE season_id = ?
          AND team_id   = ?
          AND fit_tier IN ({placeholders})
        ORDER BY fit_score DESC
        """,
        (season_id, team_id, *tiers),
    ).fetchall()
    return [dict(r) for r in rows]


def get_team_fit_signal_for_prospect(
    conn,
    prospect_id: int,
    min_tier: str = "VIABLE",
    season_id: int = 1,
) -> list[dict[str, Any]]:
    """
    Return all signal-tier team fits for a given prospect, ordered by fit_score DESC.

    Backed by v_team_prospect_fit_signal_2026 (Migration 0051).
    The view is pre-filtered to season_id=1 and fit_tier IN ('IDEAL','STRONG','VIABLE').

    Args:
        conn:        sqlite3 connection with row_factory = sqlite3.Row.
        prospect_id: Prospect primary key from the prospects table.
        min_tier:    Minimum fit quality to include. One of 'IDEAL', 'STRONG', 'VIABLE'.
                     Defaults to 'VIABLE' (returns all three signal tiers).
        season_id:   Season scope. Defaults to 1 (2026 draft year). Must match the
                     view's baked-in season_id=1 filter or the result will be empty.

    Returns:
        List of dicts, each containing all view columns. Empty list if no matches.
    """
    tiers = _tiers_at_or_above(min_tier)
    placeholders = ",".join("?" * len(tiers))
    rows = conn.execute(
        f"""
        SELECT *
        FROM v_team_prospect_fit_signal_2026
        WHERE season_id   = ?
          AND prospect_id = ?
          AND fit_tier IN ({placeholders})
        ORDER BY fit_score DESC
        """,
        (season_id, prospect_id, *tiers),
    ).fetchall()
    return [dict(r) for r in rows]
