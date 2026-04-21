"""
draftosqueriestargets.py

Read-only query helpers for v_draft_targets_2026 (Migration 0053).

The targets view is the unified signal layer combining:
  - v_team_prospect_fit_signal_2026  (fit tier/band, scheme context)
  - divergence_flags                 (APEX vs consensus divergence)
  - consensus_reconciliation_2026    (jFosterFilm recon, recon_bucket)

Season-scoped to season_id=1 (2026 draft year) — the view bakes this in.

Column reference
----------------
  fit_band          'A'(>=80) / 'B'(>=70) / 'C'(>=60)
  divergence_flag   APEX_HIGH / APEX_LOW / APEX_LOW_PVC_STRUCTURAL / ALIGNED
                    (legacy space-variants normalized in view)
  divergence_magnitude  MAJOR / MODERATE / MINOR
  divergence_delta  consensus_rank - apex_rank
                    positive = APEX bullish (same sign as divergence_flags.divergence_rank_delta)
  recon_bucket      HIGH / LOW / NONE / COVERAGE_GAP
                    HIGH = APEX bullish vs jFoster-blended market (|div|>=25, apex better)
                    LOW  = APEX bearish vs jFoster-blended market
                    NONE = covered by jFoster, small delta
                    COVERAGE_GAP = no jFoster CON rank for this prospect

recon_bucket semantics (from consensus_reconciliation_2026)
-----------------------------------------------------------
  HIGH          divergence_25 < -24 (apex_rank numerically lower = better rank than
                jFoster combined rank by >=25 positions). APEX is meaningfully bullish
                relative to the jFoster-blended market. Strong convergence signal.
  LOW           divergence_25 > 24 (APEX rates the prospect >=25 spots below jFoster).
                APEX is bearish relative to market. Monitor as potential FM-driven discount.
  NONE          jFoster coverage exists and |divergence_25| <= 24. APEX and jFoster agree
                within margin. Treat as aligned; no additional edge.
  COVERAGE_GAP  No jFoster CON rank exists for this prospect (has_jfoster_con=0).
                Cannot compute divergence_25; recon_bucket defaults to this sentinel.
                Does not mean APEX is wrong — only that external validation is absent.

Orphan divergence target definition
------------------------------------
A prospect is an "orphan" when:
  - divergence_flag = 'APEX_HIGH' (APEX rates meaningfully above consensus)
  - divergence_magnitude >= MAJOR (strongest signal tier)
  - The prospect has NO Band A or Band B fit at ANY of the 32 teams in v_draft_targets_2026
    (all fits are Band C or the prospect has no fit rows at all)

Orphans represent profiles where APEX believes the market undervalues the player, but no
team's scheme/needs align well enough to produce a STRONG or IDEAL fit score. These are
candidates for "value in wrong context" — track for trades or positional scheme changes.

consensus_reconciliation_2026 schema (9 columns, PK: prospect_id + season_id)
------------------------------------------------------------------------------
  prospect_id      INTEGER NOT NULL  — FK to prospects.prospect_id
  season_id        INTEGER NOT NULL  — default 1 (2026 draft year)
  has_jfoster_con  INTEGER NOT NULL  — 1 if jFoster CON rank exists, else 0
  jfoster_con_rank INTEGER           — jFoster blended consensus rank (NULL if no coverage)
  apex_rank        INTEGER NOT NULL  — derived from apex_composite DESC rank order
  consensus_rank   INTEGER NOT NULL  — from prospect_consensus_rankings.consensus_rank
  divergence_delta INTEGER NOT NULL  — consensus_rank - apex_rank (positive = APEX bullish)
  recon_bucket     TEXT    NOT NULL  — HIGH / LOW / NONE / COVERAGE_GAP
  notes            TEXT              — free-text provenance note

v_draft_targets_2026 column list (28 columns)
----------------------------------------------
  From team_prospect_fit (via signal view):
    prospect_id           INTEGER
    team_id               TEXT
    season_id             INTEGER
    fit_score             REAL
    fit_tier              TEXT        IDEAL / STRONG / VIABLE
    fit_band              TEXT        A / B / C  (computed CASE, not stored)
    deployment_fit        INTEGER
    pick_fit              INTEGER
    fm_risk_score         INTEGER
    verdict               TEXT
    why_for               TEXT        JSON array (stored as text)
    why_against           TEXT        JSON array (stored as text)
    confidence            REAL
    fit_explanation       TEXT
  From apex_scores (via signal view):
    capital_adjusted      TEXT
    failure_mode_primary  TEXT
    failure_mode_secondary TEXT
  From team_draft_context (via signal view):
    team_primary_needs    TEXT        JSON (premium_needs_json)
    team_secondary_needs  TEXT        JSON (secondary_needs_json)
    coverage_bias         TEXT
    primary_defense_family TEXT
  From prospect_consensus_rankings (via divergence_flags):
    consensus_rank        INT
  Derived / reconciled:
    apex_rank             INTEGER     COALESCE(recon.apex_rank, fallback from delta)
    divergence_delta      INTEGER     consensus_rank - apex_rank (positive = APEX bullish)
    divergence_flag       TEXT        normalized: APEX_HIGH / APEX_LOW / ALIGNED / etc.
    divergence_magnitude  TEXT        MAJOR / MODERATE / MINOR
    jfoster_con_rank      INTEGER     NULL if COVERAGE_GAP
    recon_bucket          TEXT        HIGH / LOW / NONE / COVERAGE_GAP (COALESCE from recon table)

Usage
-----
    import sqlite3
    from draftosqueriestargets import (
        get_connection,
        get_targets_for_team,
        get_targets_for_prospect,
        get_orphan_divergence_targets,
    )

    conn = get_connection("data/edge/draftos.sqlite")

    # Band A/B fits for KC where APEX is a major bull
    rows = get_targets_for_team(conn, "KC")

    # All team fits for a specific prospect
    rows = get_targets_for_prospect(conn, prospect_id=34)

    # Prospects APEX loves that no scheme wants
    rows = get_orphan_divergence_targets(conn)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ordered quality ladders (highest to lowest)
# ---------------------------------------------------------------------------

# fit_band: A=best, C=lowest. Comparison is lexicographic (A < B < C).
_BAND_ORDER: list[str] = ["A", "B", "C"]

# divergence_magnitude: MAJOR=strongest, MINOR=weakest.
_MAGNITUDE_ORDER: list[str] = ["MAJOR", "MODERATE", "MINOR"]


def _bands_at_or_above(min_band: str) -> list[str]:
    """
    Return all band labels that are >= min_band in quality.

    'A' is highest quality; 'C' is lowest.  'At or above' means at least
    as good — so min_band='B' returns ['A', 'B'].

    Raises ValueError if min_band is not in ('A', 'B', 'C').

    Examples:
        _bands_at_or_above('A') → ['A']
        _bands_at_or_above('B') → ['A', 'B']
        _bands_at_or_above('C') → ['A', 'B', 'C']
    """
    key = min_band.upper()
    if key not in _BAND_ORDER:
        raise ValueError(f"min_band must be one of {_BAND_ORDER}, got {min_band!r}")
    cutoff = _BAND_ORDER.index(key)
    return _BAND_ORDER[: cutoff + 1]


def _magnitudes_at_or_above(min_magnitude: str) -> list[str]:
    """
    Return all divergence magnitude labels that are >= min_magnitude in strength.

    'MAJOR' is the strongest signal; 'MINOR' is the weakest.

    Raises ValueError if min_magnitude is not in ('MAJOR', 'MODERATE', 'MINOR').

    Examples:
        _magnitudes_at_or_above('MAJOR')    → ['MAJOR']
        _magnitudes_at_or_above('MODERATE') → ['MAJOR', 'MODERATE']
        _magnitudes_at_or_above('MINOR')    → ['MAJOR', 'MODERATE', 'MINOR']
    """
    key = min_magnitude.upper()
    if key not in _MAGNITUDE_ORDER:
        raise ValueError(
            f"min_magnitude must be one of {_MAGNITUDE_ORDER}, got {min_magnitude!r}"
        )
    cutoff = _MAGNITUDE_ORDER.index(key)
    return _MAGNITUDE_ORDER[: cutoff + 1]


# ---------------------------------------------------------------------------
# Connection / row infrastructure
# ---------------------------------------------------------------------------

def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    """sqlite3 row_factory that returns rows as plain dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_connection(path: str | Path) -> sqlite3.Connection:
    """
    Open a read-only sqlite3 connection to the DraftOS DB with dict_factory applied.

    Args:
        path: Absolute or relative path to the SQLite database file.

    Returns:
        sqlite3.Connection with row_factory=dict_factory set.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = dict_factory
    return conn


def _select(
    conn: sqlite3.Connection,
    where_clause: str,
    params: tuple = (),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Internal helper: SELECT * FROM v_draft_targets_2026 WHERE <where_clause>
    ORDER BY apex_rank ASC [LIMIT <limit>].

    All public query helpers route through this function so the view name and
    default ordering are defined in exactly one place.

    Args:
        conn:         sqlite3 connection (row_factory must return dicts).
        where_clause: SQL fragment appended after WHERE (no leading WHERE keyword).
        params:       Positional parameters bound to the query.
        limit:        Optional row cap; omit for unlimited.

    Returns:
        List of row dicts. Empty list if no rows match.
    """
    sql = f"SELECT * FROM v_draft_targets_2026 WHERE {where_clause} ORDER BY apex_rank ASC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall()
    # Support both dict_factory connections and sqlite3.Row connections.
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_targets_for_team(
    conn,
    team_id: str,
    min_band: str = "B",
    min_divergence: str = "MAJOR",
    season_id: int = 1,
) -> list[dict[str, Any]]:
    """
    Return Band A/B fit prospects for a team where APEX is meaningfully above market.

    Filters applied:
      - fit_band <= min_band       ('A' only if min_band='A'; 'A'+'B' if min_band='B')
      - divergence_flag = 'APEX_HIGH'
      - divergence_magnitude IN (magnitudes >= min_divergence)

    Ordered by apex_rank ASC (highest-conviction APEX targets first).

    Args:
        conn:           sqlite3 connection with row_factory = sqlite3.Row.
        team_id:        NFL team abbreviation (e.g. "KC", "PHI").
        min_band:       Minimum fit quality band. One of 'A', 'B', 'C'.
                        Defaults to 'B' — returns Band A and Band B fits.
        min_divergence: Minimum divergence magnitude. One of 'MAJOR', 'MODERATE', 'MINOR'.
                        Defaults to 'MAJOR' — strongest divergence signals only.
        season_id:      Season scope. Defaults to 1 (2026). Must match view's baked-in filter.

    Returns:
        List of dicts (all view columns). Empty list if no qualifying rows.

    Example:
        rows = get_targets_for_team(conn, "KC")
        # KC: Band A/B prospects APEX rates MAJOR higher than consensus
    """
    bands      = _bands_at_or_above(min_band)
    magnitudes = _magnitudes_at_or_above(min_divergence)
    band_ph    = ",".join("?" * len(bands))
    mag_ph     = ",".join("?" * len(magnitudes))

    rows = conn.execute(
        f"""
        SELECT *
        FROM v_draft_targets_2026
        WHERE season_id          = ?
          AND team_id            = ?
          AND fit_band           IN ({band_ph})
          AND divergence_flag    = 'APEX_HIGH'
          AND divergence_magnitude IN ({mag_ph})
        ORDER BY apex_rank ASC
        """,
        (season_id, team_id, *bands, *magnitudes),
    ).fetchall()
    return [dict(r) for r in rows]


def get_targets_for_prospect(
    conn,
    prospect_id: int,
    season_id: int = 1,
) -> list[dict[str, Any]]:
    """
    Return all team fits for a given prospect, ordered by fit quality.

    Returns every row from v_draft_targets_2026 for this prospect, regardless
    of divergence flag, sorted by fit_band ASC then fit_score DESC so the
    best-scheme fits appear first.

    Args:
        conn:        sqlite3 connection with row_factory = sqlite3.Row.
        prospect_id: Prospect primary key from the prospects table.
        season_id:   Season scope. Defaults to 1 (2026).

    Returns:
        List of dicts (all view columns). Empty list if prospect has no signal-tier fits.

    Example:
        rows = get_targets_for_prospect(conn, prospect_id=34)
        # All IDEAL/STRONG/VIABLE team slots for prospect 34, best-fit first.
    """
    rows = conn.execute(
        """
        SELECT *
        FROM v_draft_targets_2026
        WHERE season_id   = ?
          AND prospect_id = ?
        ORDER BY fit_band ASC, fit_score DESC
        """,
        (season_id, prospect_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_orphan_divergence_targets(
    conn,
    min_divergence: str = "MAJOR",
    season_id: int = 1,
) -> list[dict[str, Any]]:
    """
    Return prospects APEX is bullish on that have no Band A or B fit at any team.

    These are "scheme orphan" profiles: APEX rates them meaningfully above market
    consensus, but no team's scheme/needs produce a STRONG+ fit (all fits in the
    view are Band C or absent entirely).

    A prospect is orphaned when:
      - divergence_flag = 'APEX_HIGH'
      - divergence_magnitude >= min_divergence
      - NOT IN (SELECT prospect_id FROM v_draft_targets_2026 WHERE fit_band IN ('A','B'))

    Returns one row per prospect (not per team). Fields included: prospect_id,
    consensus_rank, apex_rank, divergence_flag, divergence_magnitude, divergence_delta,
    capital_adjusted, failure_mode_primary, failure_mode_secondary, recon_bucket.

    Ordered by apex_rank ASC (highest-conviction orphans first).

    Args:
        conn:           sqlite3 connection with row_factory = sqlite3.Row.
        min_divergence: Minimum divergence magnitude. Defaults to 'MAJOR'.
        season_id:      Season scope. Defaults to 1 (2026).

    Returns:
        List of dicts. Empty list if all APEX_HIGH prospects have at least one B-band fit.

    Example:
        orphans = get_orphan_divergence_targets(conn)
        # Prospects APEX loves but no NFL scheme accommodates at STRONG or better
    """
    magnitudes = _magnitudes_at_or_above(min_divergence)
    mag_ph     = ",".join("?" * len(magnitudes))

    rows = conn.execute(
        f"""
        SELECT DISTINCT
            prospect_id,
            consensus_rank,
            apex_rank,
            divergence_flag,
            divergence_magnitude,
            divergence_delta,
            capital_adjusted,
            failure_mode_primary,
            failure_mode_secondary,
            recon_bucket
        FROM v_draft_targets_2026
        WHERE season_id            = ?
          AND divergence_flag      = 'APEX_HIGH'
          AND divergence_magnitude IN ({mag_ph})
          AND prospect_id NOT IN (
              SELECT prospect_id
              FROM   v_draft_targets_2026
              WHERE  season_id = ?
                AND  fit_band IN ('A', 'B')
          )
        ORDER BY apex_rank ASC
        """,
        (season_id, *magnitudes, season_id),
    ).fetchall()
    return [dict(r) for r in rows]
