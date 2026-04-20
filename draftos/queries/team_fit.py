"""
Team Fit query stubs.

No team tables exist in the DB yet — these return safe empty values so all
app-layer guards (``if not team_options: return None``) short-circuit cleanly.
Implement once team_fit tables are migrated in.
"""
from __future__ import annotations
from typing import Any


def get_team_fit_pilot_teams() -> list[dict[str, str]]:
    """Return list of pilot team dicts: [{'team_code': str, 'team_name': str}, ...]."""
    return []


def get_team_fit_context(
    conn: Any,
    team_code: str,
    season_id: int = 1,
) -> dict[str, Any] | None:
    """Return team context dict for evaluate_team_fit, or None if not available."""
    return None


def resolve_team_fit_pick(
    team_context: dict[str, Any],
    pick_override: int = 0,
) -> int | None:
    """Resolve effective pick number from team context + optional override."""
    if pick_override and pick_override > 0:
        return pick_override
    return team_context.get("projected_pick") if team_context else None
