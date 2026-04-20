"""
draftos/queries/team_fit.py

Team Fit query layer. Fetches team context from team_draft_context table.
DB access only — no scoring logic. Pure evaluator lives in draftos/team_fitevaluator.py.

Tables required: team_draft_context (migration 0049)
"""
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


def get_team_fit_pilot_teams(conn: Any | None = None, season_id: int = 1) -> list[dict[str, str]]:
    """
    Return list of active pilot team dicts: [{'team_id': str, 'team_name': str}, ...].
    Accepts optional conn for consistency with other query functions.
    Falls back to empty list if table doesn't exist yet.
    """
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT team_id, team_name
            FROM team_draft_context
            WHERE season_id = ? AND is_active = 1
            ORDER BY team_name
            """,
            (season_id,),
        ).fetchall()
        return [{"team_id": r["team_id"], "team_name": r["team_name"]} for r in rows]
    except Exception:
        return []


def get_team_fit_context(
    conn: Any,
    team_code: str,
    season_id: int = 1,
) -> dict[str, Any] | None:
    """
    Return full team context dict for evaluate_team_fit, or None if not available.
    Keys mirror what draftosqueriesteamfit.py (get_team_draft_context) returns
    so the evaluator receives a consistent shape from either query path.
    """
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT
                team_id, team_name,
                development_timeline, risk_tolerance,
                primary_offense_family, primary_defense_family,
                coverage_bias, man_rate_tolerance,
                premium_needs_json, depth_chart_pressure_json,
                draft_capital_json, notes
            FROM team_draft_context
            WHERE season_id = ? AND team_id = ? AND is_active = 1
            """,
            (season_id, team_code),
        ).fetchone()
        if not row:
            return None
        return {
            "team_id":               row["team_id"],
            "team_name":             row["team_name"],
            "development_timeline":  row["development_timeline"],
            "risk_tolerance":        row["risk_tolerance"],
            "primary_offense_family": row["primary_offense_family"],
            "primary_defense_family": row["primary_defense_family"],
            "coverage_bias":         row["coverage_bias"],
            "man_rate_tolerance":    row["man_rate_tolerance"],
            "premium_needs":         _loads(row["premium_needs_json"], []),
            "depth_chart_pressure":  _loads(row["depth_chart_pressure_json"], {}),
            "draft_capital":         _loads(row["draft_capital_json"], {}),
            "notes":                 row["notes"],
        }
    except Exception:
        return None


def resolve_team_fit_pick(
    team_context: dict[str, Any] | None,
    pick_override: int = 0,
) -> int | None:
    """
    Resolve effective pick number.
    Priority: explicit pick_override > team's pick_1 from draft_capital.
    Returns None when both are unavailable.
    """
    if pick_override and pick_override > 0:
        return int(pick_override)
    if team_context:
        capital = team_context.get("draft_capital") or {}
        p = capital.get("pick_1")
        if p is not None:
            try:
                return int(p)
            except (TypeError, ValueError):
                pass
    return None
