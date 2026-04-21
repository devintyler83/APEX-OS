"""
draftos/queries/draft_mode.py — Draft Mode query and write layer (2026)

Read path: v_draft_targets_remaining_2026 ONLY for target-selection reads.
           prospects table for display enrichment (core table, not forbidden).
           drafted_picks_2026 for pick history.
           team_draft_context + team_needs_2026 for team context display.

Forbidden upstream tables (NEVER reference directly here):
  - consensus_reconciliation_2026
  - divergence_flags
  - v_team_prospect_fit_signal_2026

Write path: drafted_picks_2026 only. One row per pick. Backup before write.

Season scope: season_id=1 (2026) baked into all queries.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect

_SEASON_ID = 1


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _backup_db_once_today() -> None:
    """Back up DB at most once per calendar day before any Draft Mode write."""
    if not PATHS.db.exists():
        return
    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if list(backup_dir.glob(f"draftos.sqlite.backup.{today}*")):
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATHS.db, backup_dir / f"draftos.sqlite.backup.{ts}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_round(pick_number: int) -> int:
    """Derive round number from pick number using standard 32-pick-per-round sizing."""
    if pick_number <= 32:
        return 1
    elif pick_number <= 64:
        return 2
    elif pick_number <= 96:
        return 3
    elif pick_number <= 128:
        return 4
    elif pick_number <= 160:
        return 5
    elif pick_number <= 192:
        return 6
    else:
        return 7


# ─────────────────────────────────────────────────────────────
# Team context reads (team_draft_context + team_needs_2026)
# ─────────────────────────────────────────────────────────────

def get_all_teams() -> list[str]:
    """All 32 team IDs from team_draft_context, alphabetically."""
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT team_id FROM team_draft_context WHERE is_active=1 ORDER BY team_id"
            ).fetchall()
            return [r["team_id"] for r in rows]
    except Exception:
        return []


def get_team_context(team_id: str) -> dict | None:
    """
    Team context for Draft Mode display: needs, picks, scheme.
    Reads from team_draft_context + team_needs_2026 + drafted_picks_2026.
    Returns None if team not found.
    """
    try:
        with connect() as conn:
            tdc = conn.execute(
                """
                SELECT team_id, team_name, scheme_family, offense_style, defense_structure,
                       coverage_bias, draft_capital_json, primary_offense_family,
                       primary_defense_family
                FROM team_draft_context
                WHERE team_id = ? AND is_active = 1
                """,
                (team_id,),
            ).fetchone()
            if tdc is None:
                return None

            needs = conn.execute(
                """
                SELECT need_tier, position_code, need_rank
                FROM team_needs_2026
                WHERE team_id = ? AND season_id = ?
                ORDER BY
                    CASE need_tier WHEN 'PREMIUM' THEN 1 WHEN 'SECONDARY' THEN 2 ELSE 3 END,
                    need_rank
                """,
                (team_id, _SEASON_ID),
            ).fetchall()

            # Picks this team has already recorded in Draft Mode
            recorded = conn.execute(
                """
                SELECT pick_number
                FROM drafted_picks_2026
                WHERE season_id = ? AND drafting_team = ?
                ORDER BY pick_number
                """,
                (_SEASON_ID, team_id),
            ).fetchall()

        capital_raw = tdc["draft_capital_json"] or "{}"
        try:
            capital = json.loads(capital_raw)
        except (json.JSONDecodeError, TypeError):
            capital = {}

        recorded_picks = {r["pick_number"] for r in recorded}
        remaining_picks = {k: v for k, v in capital.items() if v not in recorded_picks}

        return {
            "team_id":          team_id,
            "team_name":        tdc["team_name"] or team_id,
            "scheme_family":    tdc["scheme_family"] or tdc["primary_offense_family"] or "—",
            "defense_structure":tdc["defense_structure"] or tdc["primary_defense_family"] or "—",
            "coverage_bias":    tdc["coverage_bias"] or "—",
            "draft_capital":    capital,          # full original dict
            "remaining_picks":  remaining_picks,  # picks not yet marked as used
            "recorded_picks":   sorted(recorded_picks),
            "needs": [
                {"tier": r["need_tier"], "position": r["position_code"], "rank": r["need_rank"]}
                for r in needs
            ],
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Pick history reads (drafted_picks_2026)
# ─────────────────────────────────────────────────────────────

def get_drafted_count(season_id: int = _SEASON_ID) -> int:
    try:
        with connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM drafted_picks_2026 WHERE season_id=?",
                (season_id,),
            ).fetchone()["n"]
    except Exception:
        return 0


def get_next_pick_suggestion(season_id: int = _SEASON_ID) -> int:
    """Return max(pick_number) + 1 from drafted_picks_2026, or 1 if empty."""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT MAX(pick_number) AS mx FROM drafted_picks_2026 WHERE season_id=?",
                (season_id,),
            ).fetchone()
            mx = row["mx"]
            return (mx + 1) if mx is not None else 1
    except Exception:
        return 1


def get_drafted_picks(season_id: int = _SEASON_ID, limit: int = 10) -> list[dict]:
    """
    Recent drafted picks with prospect display info.
    Source: drafted_picks_2026 + prospects join.
    """
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT dp.pick_number, dp.round_number, dp.drafting_team,
                       dp.prospect_id, dp.drafted_at, dp.note,
                       p.display_name, p.position_group
                FROM drafted_picks_2026 dp
                LEFT JOIN prospects p ON p.prospect_id = dp.prospect_id
                WHERE dp.season_id = ?
                ORDER BY dp.pick_number DESC
                LIMIT ?
                """,
                (season_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_drafted_picks_since(since_pick_number: int,
                             season_id: int = _SEASON_ID) -> list[dict]:
    """
    All picks recorded after since_pick_number. Used for 'recently off board' display.
    """
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT dp.pick_number, dp.round_number, dp.drafting_team,
                       dp.prospect_id, dp.drafted_at,
                       p.display_name, p.position_group
                FROM drafted_picks_2026 dp
                LEFT JOIN prospects p ON p.prospect_id = dp.prospect_id
                WHERE dp.season_id = ?
                  AND dp.pick_number > ?
                ORDER BY dp.pick_number ASC
                """,
                (season_id, since_pick_number),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_team_last_pick(team_id: str, season_id: int = _SEASON_ID) -> int:
    """Return the highest pick_number recorded for a team, or 0 if none."""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT MAX(pick_number) AS mx FROM drafted_picks_2026 WHERE season_id=? AND drafting_team=?",
                (season_id, team_id),
            ).fetchone()
            mx = row["mx"]
            return mx if mx is not None else 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────
# Remaining board reads (v_draft_targets_remaining_2026 ONLY)
# ─────────────────────────────────────────────────────────────

def search_available_prospects(name_search: str = "",
                                season_id: int = _SEASON_ID,
                                limit: int = 100) -> list[dict]:
    """
    Return DISTINCT available prospects matching name_search.
    Source: v_draft_targets_remaining_2026 + prospects.
    Ordered by consensus_rank ASC.
    """
    try:
        with connect() as conn:
            if name_search.strip():
                pattern = f"%{name_search.strip()}%"
                rows = conn.execute(
                    """
                    SELECT DISTINCT r.prospect_id, p.display_name, p.position_group,
                           r.consensus_rank
                    FROM v_draft_targets_remaining_2026 r
                    JOIN prospects p ON p.prospect_id = r.prospect_id
                    WHERE r.season_id = ?
                      AND p.display_name LIKE ? COLLATE NOCASE
                    ORDER BY r.consensus_rank ASC
                    LIMIT ?
                    """,
                    (season_id, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DISTINCT r.prospect_id, p.display_name, p.position_group,
                           r.consensus_rank
                    FROM v_draft_targets_remaining_2026 r
                    JOIN prospects p ON p.prospect_id = r.prospect_id
                    WHERE r.season_id = ?
                    ORDER BY r.consensus_rank ASC
                    LIMIT ?
                    """,
                    (season_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_remaining_board(
    position_filter: list[str] | None = None,
    tier_filter: str | None = None,       # 'IDEAL', 'STRONG', 'VIABLE', or None = all
    div_filter: str | None = None,        # 'APEX_HIGH', 'APEX_LOW', 'ALIGNED', or None = all
    sort_by: str = "consensus",           # 'consensus' | 'apex' | 'fit'
    limit: int = 100,
    season_id: int = _SEASON_ID,
) -> list[dict]:
    """
    DISTINCT available prospects from v_draft_targets_remaining_2026.
    Best fit tier = best (lowest) fit_tier across all team rows for this prospect.
    Best fit score = max fit_score across all teams.
    team_fit_count = number of teams with a fit row for this prospect.

    Source: v_draft_targets_remaining_2026 ONLY (+ prospects for display_name/position_group).
    """
    conditions = ["r.season_id = ?"]
    params: list = [season_id]

    if position_filter:
        placeholders = ",".join("?" * len(position_filter))
        conditions.append(f"p.position_group IN ({placeholders})")
        params.extend(position_filter)

    if div_filter:
        conditions.append("r.divergence_flag = ?")
        params.append(div_filter)

    where_clause = " AND ".join(conditions)

    # Tier filter maps to a HAVING condition on best_tier_num
    tier_num_map = {"IDEAL": 1, "STRONG": 2, "VIABLE": 3}
    having_clause = ""
    if tier_filter and tier_filter in tier_num_map:
        having_clause = f"HAVING MIN(CASE r.fit_tier WHEN 'IDEAL' THEN 1 WHEN 'STRONG' THEN 2 WHEN 'VIABLE' THEN 3 ELSE 9 END) <= {tier_num_map[tier_filter]}"

    order_map = {
        "consensus": "r.consensus_rank ASC",
        "apex":      "r.apex_rank ASC NULLS LAST",
        "fit":       "best_fit_score DESC, r.consensus_rank ASC",
    }
    order_clause = order_map.get(sort_by, "r.consensus_rank ASC")

    params.append(limit)

    try:
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    r.prospect_id,
                    p.display_name,
                    p.position_group,
                    r.consensus_rank,
                    r.apex_rank,
                    r.divergence_flag,
                    r.divergence_magnitude,
                    r.capital_adjusted,
                    r.failure_mode_primary,
                    r.recon_bucket,
                    CASE MIN(CASE r.fit_tier
                        WHEN 'IDEAL'  THEN 1
                        WHEN 'STRONG' THEN 2
                        WHEN 'VIABLE' THEN 3
                        ELSE 9
                    END)
                        WHEN 1 THEN 'IDEAL'
                        WHEN 2 THEN 'STRONG'
                        WHEN 3 THEN 'VIABLE'
                        ELSE '—'
                    END AS best_fit_tier,
                    MAX(r.fit_score)           AS best_fit_score,
                    COUNT(DISTINCT r.team_id)  AS team_fit_count
                FROM v_draft_targets_remaining_2026 r
                JOIN prospects p ON p.prospect_id = r.prospect_id
                WHERE {where_clause}
                GROUP BY r.prospect_id
                {having_clause}
                ORDER BY {order_clause}
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_team_fits(
    team_id: str,
    position_filter: list[str] | None = None,
    tier_filter: str | None = None,   # 'STRONG', 'IDEAL' — filter to this tier or better
    limit: int = 25,
    season_id: int = _SEASON_ID,
) -> list[dict]:
    """
    Best remaining fits for a specific team.
    Source: v_draft_targets_remaining_2026 WHERE team_id = ?
    """
    conditions = ["r.team_id = ?", "r.season_id = ?"]
    params: list = [team_id, season_id]

    if position_filter:
        placeholders = ",".join("?" * len(position_filter))
        conditions.append(f"p.position_group IN ({placeholders})")
        params.extend(position_filter)

    if tier_filter:
        conditions.append("r.fit_tier = ?")
        params.append(tier_filter)

    where_clause = " AND ".join(conditions)
    params.append(limit)

    try:
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    r.prospect_id,
                    p.display_name,
                    p.position_group,
                    r.fit_tier,
                    r.fit_band,
                    r.fit_score,
                    r.consensus_rank,
                    r.apex_rank,
                    r.divergence_flag,
                    r.capital_adjusted,
                    r.failure_mode_primary,
                    r.verdict,
                    r.why_for,
                    r.why_against,
                    r.deployment_fit,
                    r.pick_fit
                FROM v_draft_targets_remaining_2026 r
                JOIN prospects p ON p.prospect_id = r.prospect_id
                WHERE {where_clause}
                ORDER BY
                    CASE r.fit_tier WHEN 'IDEAL' THEN 1 WHEN 'STRONG' THEN 2 WHEN 'VIABLE' THEN 3 ELSE 9 END ASC,
                    CASE r.fit_band WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 9 END ASC,
                    r.fit_score DESC,
                    r.consensus_rank ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_value_plays(
    team_id: str | None = None,
    limit: int = 15,
    season_id: int = _SEASON_ID,
) -> list[dict]:
    """
    APEX_HIGH prospects still available — best value plays.
    If team_id is provided: filter to rows where that team has a fit.
    Otherwise: DISTINCT prospects with APEX_HIGH flag.
    Ordered by apex_rank ASC (model-bullish = lower apex rank vs consensus).
    """
    try:
        with connect() as conn:
            if team_id:
                rows = conn.execute(
                    """
                    SELECT
                        r.prospect_id,
                        p.display_name,
                        p.position_group,
                        r.fit_tier,
                        r.fit_band,
                        r.fit_score,
                        r.consensus_rank,
                        r.apex_rank,
                        r.divergence_flag,
                        r.divergence_magnitude,
                        r.capital_adjusted,
                        r.failure_mode_primary,
                        r.recon_bucket
                    FROM v_draft_targets_remaining_2026 r
                    JOIN prospects p ON p.prospect_id = r.prospect_id
                    WHERE r.season_id      = ?
                      AND r.team_id        = ?
                      AND r.divergence_flag = 'APEX_HIGH'
                    ORDER BY r.apex_rank ASC, r.fit_score DESC
                    LIMIT ?
                    """,
                    (season_id, team_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DISTINCT
                        r.prospect_id,
                        p.display_name,
                        p.position_group,
                        r.consensus_rank,
                        r.apex_rank,
                        r.divergence_magnitude,
                        r.capital_adjusted,
                        r.failure_mode_primary,
                        r.recon_bucket,
                        NULL AS fit_tier,
                        NULL AS fit_score
                    FROM v_draft_targets_remaining_2026 r
                    JOIN prospects p ON p.prospect_id = r.prospect_id
                    WHERE r.season_id       = ?
                      AND r.divergence_flag  = 'APEX_HIGH'
                    ORDER BY r.apex_rank ASC
                    LIMIT ?
                    """,
                    (season_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_pick_window_targets(
    team_id: str,
    pick_numbers: list[int],
    limit: int = 20,
    season_id: int = _SEASON_ID,
) -> list[dict]:
    """
    Prospects available at the team's upcoming pick positions.
    Maps pick_number to capital round, then filters remaining board
    to prospects with matching capital_adjusted tier.

    Source: v_draft_targets_remaining_2026.
    Capital_adjusted is a free-text field (e.g. 'R2 Mid', 'R1 Picks 1-10').
    We filter by round prefix match: pick 1-32 → capital LIKE 'R1%', etc.
    """
    if not pick_numbers:
        return []

    round_prefixes = set()
    for pick in pick_numbers:
        rnd = derive_round(pick)
        round_prefixes.add(f"R{rnd}")

    # Build OR conditions for capital_adjusted LIKE 'R?%'
    capital_conditions = " OR ".join(
        "r.capital_adjusted LIKE ?" for _ in round_prefixes
    )
    capital_params = [f"{prefix}%" for prefix in sorted(round_prefixes)]

    try:
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    r.prospect_id,
                    p.display_name,
                    p.position_group,
                    r.fit_tier,
                    r.fit_band,
                    r.fit_score,
                    r.consensus_rank,
                    r.apex_rank,
                    r.divergence_flag,
                    r.capital_adjusted,
                    r.failure_mode_primary,
                    r.why_for
                FROM v_draft_targets_remaining_2026 r
                JOIN prospects p ON p.prospect_id = r.prospect_id
                WHERE r.team_id  = ?
                  AND r.season_id = ?
                  AND ({capital_conditions})
                ORDER BY
                    CASE r.fit_tier WHEN 'IDEAL' THEN 1 WHEN 'STRONG' THEN 2 WHEN 'VIABLE' THEN 3 ELSE 9 END ASC,
                    r.fit_score DESC,
                    r.consensus_rank ASC
                LIMIT ?
                """,
                [team_id, season_id] + capital_params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# Write path — drafted_picks_2026 only
# ─────────────────────────────────────────────────────────────

def mark_prospect_drafted(
    prospect_id: int,
    pick_number: int,
    round_number: int | None,
    team: str,
    note: str | None,
    source: str = "ui",
    season_id: int = _SEASON_ID,
) -> str:
    """
    Record a drafted pick in drafted_picks_2026.

    Validation before any write:
      1. Prospect exists in v_draft_targets_2026 (legitimate target)
      2. Prospect not already in drafted_picks_2026 for this season
      3. Pick number not already used for this season

    Backs up DB before write (at most once per calendar day).

    Returns:
      "OK: pick #N recorded."  on success
      "REJECT: ..."            on validation failure
      "ERROR: ..."             on unexpected DB error
    """
    team_upper = team.strip().upper()
    try:
        with connect() as conn:
            # Validate: prospect is a legitimate 2026 target
            target = conn.execute(
                "SELECT prospect_id FROM v_draft_targets_2026 WHERE prospect_id=? AND season_id=? LIMIT 1",
                (prospect_id, season_id),
            ).fetchone()
            if target is None:
                return (
                    f"REJECT: prospect_id={prospect_id} not found in v_draft_targets_2026. "
                    f"Prospect must have an active consensus and divergence row."
                )

            # Validate: prospect not already drafted
            dup_pid = conn.execute(
                "SELECT pick_number FROM drafted_picks_2026 WHERE season_id=? AND prospect_id=?",
                (season_id, prospect_id),
            ).fetchone()
            if dup_pid:
                return f"REJECT: prospect_id={prospect_id} already drafted at pick #{dup_pid['pick_number']}."

            # Validate: pick number not already used
            dup_pick = conn.execute(
                "SELECT prospect_id FROM drafted_picks_2026 WHERE season_id=? AND pick_number=?",
                (season_id, pick_number),
            ).fetchone()
            if dup_pick:
                return (
                    f"REJECT: pick #{pick_number} already used "
                    f"(prospect_id={dup_pick['prospect_id']})."
                )

            drafted_at = _utc_now_iso()
            _backup_db_once_today()

            conn.execute(
                """
                INSERT INTO drafted_picks_2026
                    (season_id, pick_number, round_number, drafting_team,
                     prospect_id, drafted_at, source, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season_id,
                    pick_number,
                    round_number,
                    team_upper,
                    prospect_id,
                    drafted_at,
                    source,
                    note or None,
                ),
            )
            conn.commit()
        return f"OK: pick #{pick_number} recorded."

    except Exception as exc:
        return f"ERROR: {exc}"


# ─────────────────────────────────────────────────────────────
# Phase 2 spec helpers (Migration 0056 views)
#
# These four functions match the Phase 2 API spec exactly.
# They read from v_draft_remaining_2026 and v_draft_team_board_2026
# (added in migration 0056) and write to drafted_picks_2026.
#
# `conn` is optional in all signatures: pass an open connection for
# transaction control, or omit to have the function create one internally.
# The `team_code` argument maps to the `team_id` column in the DB.
# ─────────────────────────────────────────────────────────────

def get_draft_remaining_board(
    conn=None,
    seasonid: int = _SEASON_ID,
    limit: int = 300,
) -> list[dict]:
    """
    All remaining (not-yet-drafted) prospects as a flat list ordered for the
    main board: APEX rank → consensus rank.

    Source: v_draft_remaining_2026 (spec-named alias for v_draft_targets_remaining_2026).
    Returns DISTINCT prospect rows (one row per prospect, not one per team).

    `conn` is accepted for API compatibility but managed internally — pass None
    (the default) or omit it; the function opens and closes its own connection.

    Deterministic sort:
      1. APEX rank ASC (lower = model-higher-ranked)
      2. Consensus rank ASC
      3. prospect_id ASC (tiebreak)
    """
    try:
        with connect() as _conn:
            rows = _conn.execute(
                """
                SELECT DISTINCT
                    r.prospect_id,
                    p.display_name,
                    p.position_group,
                    r.consensus_rank,
                    r.apex_rank,
                    r.capital_adjusted,
                    r.failure_mode_primary,
                    r.divergence_flag,
                    r.divergence_magnitude,
                    r.recon_bucket
                FROM v_draft_remaining_2026 r
                JOIN prospects p ON p.prospect_id = r.prospect_id
                WHERE r.season_id = ?
                ORDER BY
                    r.apex_rank ASC NULLS LAST,
                    r.consensus_rank ASC NULLS LAST,
                    r.prospect_id ASC
                LIMIT ?
                """,
                (seasonid, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_draft_team_board(
    conn=None,
    team_code: str = "",
    seasonid: int = _SEASON_ID,
    limit: int = 50,
) -> list[dict]:
    """
    Per-team remaining best-available board ordered for team-specific decision making.

    Source: v_draft_team_board_2026 (Migration 0056).
    Includes scheme context columns (scheme_family, capital_profile, etc.) from
    v_team_fit_context_2026 alongside each prospect×team fit row.

    `team_code` maps to the `team_id` column in the DB.
    `conn` is accepted for API compatibility but managed internally.

    Sort order (spec-aligned):
      1. fit_band ASC (A before B before C)
      2. fit_tier ASC (IDEAL before STRONG before VIABLE)
      3. fit_score DESC
      4. consensus_rank ASC
    """
    team_key = team_code.strip().upper() if team_code else ""
    try:
        with connect() as _conn:
            rows = _conn.execute(
                """
                SELECT
                    b.prospect_id,
                    b.team_id,
                    b.season_id,
                    p.display_name,
                    p.position_group,
                    b.fit_tier,
                    b.fit_band,
                    b.fit_score,
                    b.consensus_rank,
                    b.apex_rank,
                    b.divergence_flag,
                    b.capital_adjusted,
                    b.failure_mode_primary,
                    b.verdict,
                    b.why_for,
                    b.why_against,
                    b.deployment_fit,
                    b.pick_fit,
                    b.team_name,
                    b.scheme_family,
                    b.capital_profile,
                    b.failure_mode_bias,
                    b.development_timeline,
                    b.risk_tolerance,
                    b.needs_json
                FROM v_draft_team_board_2026 b
                JOIN prospects p ON p.prospect_id = b.prospect_id
                WHERE b.season_id = ?
                  AND b.team_id   = ?
                ORDER BY
                    CASE b.fit_band WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 9 END ASC,
                    CASE b.fit_tier WHEN 'IDEAL' THEN 1 WHEN 'STRONG' THEN 2 WHEN 'VIABLE' THEN 3 ELSE 9 END ASC,
                    b.fit_score   DESC,
                    b.consensus_rank ASC NULLS LAST
                LIMIT ?
                """,
                (seasonid, team_key, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_next_pick(
    conn=None,
    seasonid: int = _SEASON_ID,
) -> dict:
    """
    Compute the next pick position for the ongoing draft session.

    Returns a dict:
      {
        "overall_pick":  <int>,  # next pick number (max existing + 1, or 1 if none)
        "round_number":  <int>,  # (overall_pick - 1) // 32 + 1
        "pick_in_round": <int>,  # (overall_pick - 1) % 32 + 1
      }

    Uses a 32-team-per-round convention matching the NFL draft structure.
    `conn` is accepted for API compatibility but managed internally.
    """
    next_overall = 1
    try:
        with connect() as _conn:
            row = _conn.execute(
                "SELECT COALESCE(MAX(pick_number), 0) AS mx FROM drafted_picks_2026 WHERE season_id = ?",
                (seasonid,),
            ).fetchone()
            if row and row["mx"] is not None:
                next_overall = row["mx"] + 1
    except Exception:
        pass

    round_number  = (next_overall - 1) // 32 + 1
    pick_in_round = (next_overall - 1) % 32 + 1
    return {
        "overall_pick":  next_overall,
        "round_number":  round_number,
        "pick_in_round": pick_in_round,
    }


def insert_draft_pick(
    conn=None,
    *,
    seasonid: int,
    overall_pick: int,
    round_number: int,
    pick_in_round: int,
    drafting_team: str,
    prospectid: int,
) -> None:
    """
    Insert a single pick into drafted_picks_2026.

    Keyword-only after `conn` to prevent positional-arg mistakes on draft night.
    `pick_in_round` is stored in the `note` field as metadata (the table stores
    pick_number = overall_pick and round_number directly).
    `conn` is accepted for API compatibility but managed internally.

    Raises ValueError with a clear message on:
      - Duplicate (seasonid, overall_pick) — pick number already used
      - Duplicate (seasonid, prospectid)   — prospect already drafted

    Does NOT silently overwrite. Backs up the DB before any write (at most once
    per calendar day, shared with mark_prospect_drafted()).
    """
    team_upper = drafting_team.strip().upper()
    note_meta  = f"pick_in_round={pick_in_round}"

    with connect() as _conn:
        # Guard: pick number not already used
        dup_pick = _conn.execute(
            "SELECT prospect_id FROM drafted_picks_2026 WHERE season_id=? AND pick_number=?",
            (seasonid, overall_pick),
        ).fetchone()
        if dup_pick:
            raise ValueError(
                f"insert_draft_pick: pick #{overall_pick} already recorded "
                f"(prospect_id={dup_pick['prospect_id']}) for season_id={seasonid}. "
                f"No INSERT performed."
            )

        # Guard: prospect not already drafted
        dup_pid = _conn.execute(
            "SELECT pick_number FROM drafted_picks_2026 WHERE season_id=? AND prospect_id=?",
            (seasonid, prospectid),
        ).fetchone()
        if dup_pid:
            raise ValueError(
                f"insert_draft_pick: prospect_id={prospectid} already drafted "
                f"at pick #{dup_pid['pick_number']} for season_id={seasonid}. "
                f"No INSERT performed."
            )

        _backup_db_once_today()

        _conn.execute(
            """
            INSERT INTO drafted_picks_2026
                (season_id, pick_number, round_number, drafting_team,
                 prospect_id, drafted_at, source, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seasonid,
                overall_pick,
                round_number,
                team_upper,
                prospectid,
                _utc_now_iso(),
                "ui",
                note_meta,
            ),
        )
        _conn.commit()
