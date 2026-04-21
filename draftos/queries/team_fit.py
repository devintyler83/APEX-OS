"""
draftos/queries/team_fit.py

Team Fit query layer. Fetches team context from team_draft_context table.
DB access only — no scoring logic. Pure evaluator lives in draftos/team_fitevaluator.py.

Tables required: team_draft_context (migration 0049)
"""
from __future__ import annotations

import json
from typing import Any


# Canonical 32-team registry — always shown in dropdown regardless of DB seed state.
# team_id must match the team_id used in team_draft_context rows.
_NFL_32_TEAMS: list[dict[str, str]] = [
    # AFC East
    {"team_id": "BUF", "team_name": "Buffalo Bills",           "short_label": "Bills",     "conference": "AFC", "division": "AFC East"},
    {"team_id": "MIA", "team_name": "Miami Dolphins",          "short_label": "Dolphins",  "conference": "AFC", "division": "AFC East"},
    {"team_id": "NE",  "team_name": "New England Patriots",    "short_label": "Patriots",  "conference": "AFC", "division": "AFC East"},
    {"team_id": "NYJ", "team_name": "New York Jets",           "short_label": "Jets",      "conference": "AFC", "division": "AFC East"},
    # AFC North
    {"team_id": "BAL", "team_name": "Baltimore Ravens",        "short_label": "Ravens",    "conference": "AFC", "division": "AFC North"},
    {"team_id": "CIN", "team_name": "Cincinnati Bengals",      "short_label": "Bengals",   "conference": "AFC", "division": "AFC North"},
    {"team_id": "CLE", "team_name": "Cleveland Browns",        "short_label": "Browns",    "conference": "AFC", "division": "AFC North"},
    {"team_id": "PIT", "team_name": "Pittsburgh Steelers",     "short_label": "Steelers",  "conference": "AFC", "division": "AFC North"},
    # AFC South
    {"team_id": "HOU", "team_name": "Houston Texans",          "short_label": "Texans",    "conference": "AFC", "division": "AFC South"},
    {"team_id": "IND", "team_name": "Indianapolis Colts",      "short_label": "Colts",     "conference": "AFC", "division": "AFC South"},
    {"team_id": "JAX", "team_name": "Jacksonville Jaguars",    "short_label": "Jaguars",   "conference": "AFC", "division": "AFC South"},
    {"team_id": "TEN", "team_name": "Tennessee Titans",        "short_label": "Titans",    "conference": "AFC", "division": "AFC South"},
    # AFC West
    {"team_id": "DEN", "team_name": "Denver Broncos",          "short_label": "Broncos",   "conference": "AFC", "division": "AFC West"},
    {"team_id": "KC",  "team_name": "Kansas City Chiefs",      "short_label": "Chiefs",    "conference": "AFC", "division": "AFC West"},
    {"team_id": "LAC", "team_name": "Los Angeles Chargers",    "short_label": "Chargers",  "conference": "AFC", "division": "AFC West"},
    {"team_id": "LV",  "team_name": "Las Vegas Raiders",       "short_label": "Raiders",   "conference": "AFC", "division": "AFC West"},
    # NFC East
    {"team_id": "DAL", "team_name": "Dallas Cowboys",          "short_label": "Cowboys",   "conference": "NFC", "division": "NFC East"},
    {"team_id": "NYG", "team_name": "New York Giants",         "short_label": "Giants",    "conference": "NFC", "division": "NFC East"},
    {"team_id": "PHI", "team_name": "Philadelphia Eagles",     "short_label": "Eagles",    "conference": "NFC", "division": "NFC East"},
    {"team_id": "WAS", "team_name": "Washington Commanders",   "short_label": "Commanders","conference": "NFC", "division": "NFC East"},
    # NFC North
    {"team_id": "CHI", "team_name": "Chicago Bears",           "short_label": "Bears",     "conference": "NFC", "division": "NFC North"},
    {"team_id": "DET", "team_name": "Detroit Lions",           "short_label": "Lions",     "conference": "NFC", "division": "NFC North"},
    {"team_id": "GB",  "team_name": "Green Bay Packers",       "short_label": "Packers",   "conference": "NFC", "division": "NFC North"},
    {"team_id": "MIN", "team_name": "Minnesota Vikings",       "short_label": "Vikings",   "conference": "NFC", "division": "NFC North"},
    # NFC South
    {"team_id": "ATL", "team_name": "Atlanta Falcons",         "short_label": "Falcons",   "conference": "NFC", "division": "NFC South"},
    {"team_id": "CAR", "team_name": "Carolina Panthers",       "short_label": "Panthers",  "conference": "NFC", "division": "NFC South"},
    {"team_id": "NO",  "team_name": "New Orleans Saints",      "short_label": "Saints",    "conference": "NFC", "division": "NFC South"},
    {"team_id": "TB",  "team_name": "Tampa Bay Buccaneers",    "short_label": "Buccaneers","conference": "NFC", "division": "NFC South"},
    # NFC West
    {"team_id": "ARI", "team_name": "Arizona Cardinals",       "short_label": "Cardinals", "conference": "NFC", "division": "NFC West"},
    {"team_id": "LAR", "team_name": "Los Angeles Rams",        "short_label": "Rams",      "conference": "NFC", "division": "NFC West"},
    {"team_id": "SEA", "team_name": "Seattle Seahawks",        "short_label": "Seahawks",  "conference": "NFC", "division": "NFC West"},
    {"team_id": "SF",  "team_name": "San Francisco 49ers",     "short_label": "49ers",     "conference": "NFC", "division": "NFC West"},
]


def get_all_32_teams(conn: Any | None = None, season_id: int = 1) -> list[dict[str, str]]:
    """
    Return all 32 NFL teams from the canonical registry.
    Each entry includes has_context=True if the team has a seeded row in team_draft_context.
    conn and season_id are accepted for signature consistency but conn may be None.
    """
    seeded: set[str] = set()
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT team_id FROM team_draft_context WHERE season_id = ? AND is_active = 1",
                (season_id,),
            ).fetchall()
            seeded = {r["team_id"] for r in rows}
        except Exception:
            pass
    return [
        {**t, "has_context": t["team_id"] in seeded}
        for t in _NFL_32_TEAMS
    ]


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
