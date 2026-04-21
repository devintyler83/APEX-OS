"""
draftosqueries.team_fit

Team-fit query helpers for APEX OS 2026.

This module is a thin read-only layer over:

    - v_team_fit_context_2026   (team-side context, 32 rows)
    - v_draft_targets_2026      (team × prospect targets, 2,201 rows)

Design rules:
- No new business logic is introduced here.
- All scoring, divergence, and reconciliation logic lives in the
  underlying views and tables.
- All queries are season-scoped via the views (season_id = 1 baked in).
- recon_bucket semantics come exclusively from consensus_reconciliation_2026
  via v_draft_targets_2026.

Key domain definitions (from existing system):

- recon_bucket (consensus_reconciliation_2026):
    HIGH         APEX bullish >= 25 vs jFoster-blended market
    LOW          APEX bearish >= 25
    NONE         Covered by jFoster, small delta
    COVERAGE_GAP No jFoster CON rank

- Fit bands (v_draft_targets_2026):
    Band A   fit_score >= 80
    Band B   fit_score >= 70
    Band C   fit_score >= 60

- Fit tiers (v_team_prospect_fit_signal_2026 / evaluator):
    IDEAL, STRONG, VIABLE, FRINGE, POOR
    (v_draft_targets_2026 inherits signal-view filter: IDEAL/STRONG/VIABLE only)

All helpers below are read-only and deterministic. They are intended for
use by the Streamlit app, reports, and diagnostics.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

import draftosqueriestargets as _targets


Row = Dict[str, Any]


# ---------------------------------------------------------------------------
# Existing infrastructure (preserved from original module)
# ---------------------------------------------------------------------------

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
# Signal view helpers — backed by v_team_prospect_fit_signal_2026
#   Migration 0051: view created, covering indexes added.
#   Migration 0052: fit_band column added (CASE on fit_score, never NULL).
#
# View is pre-filtered to season_id=1, fit_tier IN ('IDEAL','STRONG','VIABLE').
# Every row carries a fit_band computed from fit_score:
#   'A' fit_score >= 80   true target hits
#   'B' fit_score >= 70   solid, context-dependent
#   'C' fit_score >= 60   fallback options
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

    Backed by v_team_prospect_fit_signal_2026 (Migrations 0051–0052).
    The view is pre-filtered to season_id=1 and fit_tier IN ('IDEAL','STRONG','VIABLE').
    Each returned dict includes fit_band ('A'/'B'/'C') derived from fit_score.

    Args:
        conn:      sqlite3 connection with row_factory = sqlite3.Row.
        team_id:   NFL team abbreviation (e.g. "KC", "PHI").
        min_tier:  Minimum fit quality to include. One of 'IDEAL', 'STRONG', 'VIABLE'.
                   Defaults to 'VIABLE' (returns all three signal tiers).
        season_id: Season scope. Defaults to 1 (2026 draft year). Must match the
                   view's baked-in season_id=1 filter or the result will be empty.

    Returns:
        List of dicts ordered by fit_score DESC, each containing all 21 view columns
        including fit_band. Empty list if no matches.
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

    Backed by v_team_prospect_fit_signal_2026 (Migrations 0051–0052).
    The view is pre-filtered to season_id=1 and fit_tier IN ('IDEAL','STRONG','VIABLE').
    Each returned dict includes fit_band ('A'/'B'/'C') derived from fit_score.

    Args:
        conn:        sqlite3 connection with row_factory = sqlite3.Row.
        prospect_id: Prospect primary key from the prospects table.
        min_tier:    Minimum fit quality to include. One of 'IDEAL', 'STRONG', 'VIABLE'.
                     Defaults to 'VIABLE' (returns all three signal tiers).
        season_id:   Season scope. Defaults to 1 (2026 draft year). Must match the
                     view's baked-in season_id=1 filter or the result will be empty.

    Returns:
        List of dicts ordered by fit_score DESC, each containing all 21 view columns
        including fit_band. Empty list if no matches.
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


# ---------------------------------------------------------------------------
# Connection infrastructure
# ---------------------------------------------------------------------------

def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> Row:
    """Return rows as dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_connection(path: str) -> sqlite3.Connection:
    """
    Open a SQLite connection with row_factory set to dicts.

    This mirrors draftosqueriestargets.get_connection and is provided
    for convenience when running standalone diagnostics or scripts that
    focus on team-fit surfaces.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = dict_factory
    return conn


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _select_team_ctx(
    conn: sqlite3.Connection,
    where_clause: str,
    params: Iterable[Any] = (),
) -> List[Row]:
    """
    Internal helper: SELECT * FROM v_team_fit_context_2026 WHERE <where_clause>
    ORDER BY team_id ASC.

    Single point where the team-context view name is referenced so that
    renaming the view only requires one change.
    """
    sql = (
        f"SELECT * FROM v_team_fit_context_2026 WHERE {where_clause} ORDER BY team_id ASC"
    )
    cur = conn.execute(sql, tuple(params))
    rows = cur.fetchall()
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_team_fit_summary(
    conn: sqlite3.Connection,
    team_id: str,
) -> Optional[Row]:
    """
    Return a one-row summary of team context for the given team.

    Reads v_team_fit_context_2026 (season_id=1 baked into the view).
    Returns the full row including scheme_family, capital_profile,
    failure_mode_bias, provenance_note, needs_json, depth_pressure_json,
    and deployment_traits_json.

    This is a pure context read: no prospect-level data.

    Returns None if the team_id is not found.
    """
    rows = _select_team_ctx(conn, "team_id = ?", [team_id])
    if not rows:
        return None
    return rows[0]


def get_team_fit_tier_counts(
    conn: sqlite3.Connection,
    team_id: str,
) -> List[Row]:
    """
    Return counts of prospects per fit_tier for a given team.

    Aggregates v_draft_targets_2026 for the specified team.
    Groups by fit_tier (IDEAL, STRONG, VIABLE only — the view excludes FRINGE/POOR).
    Returns rows: {fit_tier, cnt}, ordered from best to worst.

    This is a cheap way to see whether a team has a healthy spread of
    fit tiers or is concentrated at the lower end.
    """
    sql = """
        SELECT
            fit_tier,
            COUNT(*) AS cnt
        FROM v_draft_targets_2026
        WHERE team_id = ?
        GROUP BY fit_tier
        ORDER BY
            CASE fit_tier
                WHEN 'IDEAL'  THEN 1
                WHEN 'STRONG' THEN 2
                WHEN 'VIABLE' THEN 3
                ELSE 4
            END
    """
    cur = conn.execute(sql, (team_id,))
    rows = cur.fetchall()
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def get_best_fits_for_team(
    conn: sqlite3.Connection,
    team_id: str,
    min_band: str = "B",
    max_results: Optional[int] = None,
) -> List[Row]:
    """
    Return the best prospect fits for a given team.

    Reads from v_draft_targets_2026 only. Filters by team_id and fit_band,
    then delegates ordering to targets._select (apex_rank ASC).

    Parameters:
        team_id:     NFL team abbreviation (e.g. 'KC', 'PHI').
        min_band:    'A' → only Band A fits. 'B' → Band A and B fits.
                     Any other value is treated as 'B' for safety.
        max_results: Optional hard cap on returned rows.

    This is the "who are our best draft fits?" endpoint, independent of
    divergence or recon_bucket filtering.
    """
    bands: Tuple[str, ...] = ("A",) if min_band == "A" else ("A", "B")
    placeholders = ", ".join("?" for _ in bands)
    where = f"team_id = ? AND fit_band IN ({placeholders})"
    params: List[Any] = [team_id, *bands]
    return _targets._select(conn, where, params, limit=max_results)


def get_reconciled_targets_for_team(
    conn: sqlite3.Connection,
    team_id: str,
    recon_bucket: str = "HIGH",
    min_band: str = "B",
    max_results: Optional[int] = None,
) -> List[Row]:
    """
    Return reconciled draft targets for a given team, filtered by
    recon_bucket and fit band.

    Reads from v_draft_targets_2026. Filters by team_id, recon_bucket
    (COALESCE'd in the view from consensus_reconciliation_2026, defaulting
    to 'COVERAGE_GAP'), and fit_band. Ordered by apex_rank ASC via
    targets._select.

    Parameters:
        team_id:      NFL team abbreviation.
        recon_bucket: One of 'HIGH', 'LOW', 'NONE', 'COVERAGE_GAP'.
                      Defaults to 'HIGH' (APEX bullish vs jFoster market).
        min_band:     'A' or 'B' (inclusive). Defaults to 'B'.
        max_results:  Optional row cap.

    Typical usage:
        recon_bucket='HIGH', min_band='B'
        → places where APEX is bullish AND the team has a real A/B fit.
    """
    bands: Tuple[str, ...] = ("A",) if min_band == "A" else ("A", "B")
    placeholders = ", ".join("?" for _ in bands)
    where = f"team_id = ? AND recon_bucket = ? AND fit_band IN ({placeholders})"
    params: List[Any] = [team_id, recon_bucket, *bands]
    return _targets._select(conn, where, params, limit=max_results)


def get_scheme_sensitive_targets(
    conn: sqlite3.Connection,
    team_id: str,
    trait_filters: Optional[Dict[str, str]] = None,
    min_band: str = "B",
    max_results: Optional[int] = None,
) -> List[Row]:
    """
    Return draft targets for a team filtered by deployment trait requirements.

    Reads from v_draft_targets_2026 for prospect-side data. For each entry
    in trait_filters, an EXISTS subquery checks team_deployment_traits_2026
    (trait_code + trait_value match). This approach is necessary because
    deployment traits are stored as rows in team_deployment_traits_2026,
    not as individual columns in v_team_fit_context_2026 (which exposes them
    only via deployment_traits_json).

    Parameters:
        team_id:       NFL team abbreviation (e.g. 'KC').
        trait_filters: Dict mapping trait_code to required trait_value. Example:
                           {'CB_PRIMARY_COVERAGE': 'ZONE',
                            'EDGE_BASE_FRONT':     'ODD'}
                       Valid trait_codes (controlled vocab):
                           CB_PRIMARY_COVERAGE    MAN / ZONE / MIXED
                           EDGE_BASE_FRONT        ODD / EVEN / MULTIPLE
                           EDGE_HAS_WIDE9_ROLE    YES / NO
                           S_SPLIT_FIELD_USAGE    TWO_HIGH_HEAVY / ROTATION_HEAVY
                           RB_RUN_SCHEME          WIDE_ZONE / GAP / MIXED
                           WR_PRIMARY_USAGE       X_ISOLATION / MOTION_SLOT_HEAVY / VERTICAL_OUTSIDE
                           OT_PROTECTION_STYLE    PLAY_ACTION_HEAVY / PURE_DROPBACK_HEAVY
        min_band:      'A' or 'B'. Defaults to 'B'.
        max_results:   Optional row cap.

    Returns:
        List of v_draft_targets_2026 rows (all 28 columns) ordered by apex_rank ASC.
        Empty list if no targets match all supplied trait constraints.
    """
    bands: Tuple[str, ...] = ("A",) if min_band == "A" else ("A", "B")
    band_ph = ", ".join("?" for _ in bands)

    where_parts = [f"team_id = ?", f"fit_band IN ({band_ph})"]
    params: List[Any] = [team_id, *bands]

    for trait_code, trait_value in (trait_filters or {}).items():
        where_parts.append(
            "EXISTS ("
            "SELECT 1 FROM team_deployment_traits_2026 td "
            "WHERE td.team_id = v_draft_targets_2026.team_id "
            "AND td.season_id = 1 "
            "AND td.trait_code = ? AND td.trait_value = ?"
            ")"
        )
        params += [trait_code, trait_value]

    where = " AND ".join(where_parts)
    return _targets._select(conn, where, params, limit=max_results)
