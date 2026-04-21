-- Migration 0054: Normalized team context schema + v_team_fit_context_2026 view
-- Additive only. No destructive changes.  All tables keyed by (team_id, season_id).
--
-- NOTE: The design spec referenced this as "0049_team_context_2026" but migration 0049
-- (team_draft_context) is already applied.  This is the correct sequence number.
--
-- team_id type is TEXT (not INTEGER) — DraftOS uses abbreviations ("KC", "PHI").
--
-- Table inventory:
--   team_context_snapshots      — one row per team/season; replaces ad-hoc JSON blobs
--   team_needs_2026             — normalized needs, one row per (team, season, tier, rank)
--   team_depth_pressure_2026    — one row per (team, season, position_group)
--   team_deployment_traits_2026 — controlled-vocab trait rows per position_group
--   team_context_sources_2026   — raw source log for deterministic re-derivation
--
-- View:
--   v_team_fit_context_2026     — evaluator-ready context assembled from all five tables
--                                 plus a LEFT JOIN to team_draft_context for fields
--                                 not yet migrated to the normalized schema
--                                 (primary_defense_family, coverage_bias,
--                                  man_rate_tolerance, draft_capital_json).
--
-- Seeder: scripts/seed_team_context_normalized_2026.py (idempotent, --apply 0/1)
-- Consumer: rebuild_team_fit_2026.py _load_teams() reads v_team_fit_context_2026.

-- ──────────────────────────────────────────────────────────────────────────────
-- 1. team_context_snapshots
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS team_context_snapshots (
    team_id            TEXT    NOT NULL,
    season_id          INTEGER NOT NULL,
    snapshot_version   TEXT    NOT NULL,          -- e.g. '2026.v1'
    scheme_family      TEXT,                      -- e.g. '4-3_Tampa2_zone'
    offensive_coord    TEXT,
    defensive_coord    TEXT,
    base_personnel     TEXT,                      -- e.g. '11', '12', '21'
    play_style_notes   TEXT,                      -- short free text
    capital_profile    TEXT,                      -- summary of picks / aggressiveness
    failure_mode_bias  TEXT,                      -- e.g. 'FM-3 sensitive; FM-4 tolerant'
    provenance_note    TEXT,                      -- human-readable source attribution
    last_updated_utc   TEXT    NOT NULL,
    PRIMARY KEY (team_id, season_id)
);

CREATE INDEX IF NOT EXISTS idx_tcs_season
    ON team_context_snapshots (season_id);

-- ──────────────────────────────────────────────────────────────────────────────
-- 2. team_needs_2026
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS team_needs_2026 (
    team_id        TEXT    NOT NULL,
    season_id      INTEGER NOT NULL,
    need_rank      INTEGER NOT NULL,    -- 1, 2, 3 … within the tier
    position_code  TEXT    NOT NULL,   -- 'QB','CB','EDGE','OT','WR','IDL', etc.
    need_tier      TEXT    NOT NULL,   -- 'PREMIUM' or 'SECONDARY'
    confidence     TEXT,               -- 'A','B','C' — default 'B'
    rationale      TEXT,               -- one-line why
    source_url     TEXT,
    source_date    TEXT,
    PRIMARY KEY (team_id, season_id, need_tier, need_rank)
);

CREATE INDEX IF NOT EXISTS idx_tn26_season_team
    ON team_needs_2026 (season_id, team_id);

CREATE INDEX IF NOT EXISTS idx_tn26_season_position
    ON team_needs_2026 (season_id, position_code);

-- ──────────────────────────────────────────────────────────────────────────────
-- 3. team_depth_pressure_2026
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS team_depth_pressure_2026 (
    team_id             TEXT    NOT NULL,
    season_id           INTEGER NOT NULL,
    position_group      TEXT    NOT NULL,   -- normalized APEX groups: 'QB','CB','EDGE'…
    pressure_score      INTEGER NOT NULL,   -- 0–100
    starter_quality     TEXT,               -- 'BLUE','SOLID','REPLACEABLE','UNKNOWN'
    snaps_blocker_flag  INTEGER NOT NULL DEFAULT 0,  -- 1 = clear starter blocks early pick
    rationale           TEXT,
    source_url          TEXT,
    source_date         TEXT,
    PRIMARY KEY (team_id, season_id, position_group)
);

CREATE INDEX IF NOT EXISTS idx_tdp26_season_team
    ON team_depth_pressure_2026 (season_id, team_id);

-- ──────────────────────────────────────────────────────────────────────────────
-- 4. team_deployment_traits_2026
-- ──────────────────────────────────────────────────────────────────────────────
-- Controlled trait_code vocabulary (Claude may extend, but the spine is fixed):
--   EDGE_HAS_WIDE9_ROLE    YES / NO
--   EDGE_BASE_FRONT        ODD / EVEN / MULTIPLE
--   CB_PRIMARY_COVERAGE    MAN / ZONE / MIXED
--   S_SPLIT_FIELD_USAGE    TWO_HIGH_HEAVY / ROTATION_HEAVY
--   RB_RUN_SCHEME          WIDE_ZONE / GAP / MIXED
--   WR_PRIMARY_USAGE       X_ISOLATION / MOTION_SLOT_HEAVY / VERTICAL_OUTSIDE
--   OT_PROTECTION_STYLE    PLAY_ACTION_HEAVY / PURE_DROPBACK_HEAVY

CREATE TABLE IF NOT EXISTS team_deployment_traits_2026 (
    team_id        TEXT    NOT NULL,
    season_id      INTEGER NOT NULL,
    position_group TEXT    NOT NULL,   -- 'EDGE','CB','S','RB','WR','OT'
    trait_code     TEXT    NOT NULL,   -- controlled vocab above
    trait_value    TEXT    NOT NULL,   -- 'YES'/'NO' or small enum
    rationale      TEXT,
    source_url     TEXT,
    source_date    TEXT,
    PRIMARY KEY (team_id, season_id, position_group, trait_code)
);

CREATE INDEX IF NOT EXISTS idx_tdt26_season_team
    ON team_deployment_traits_2026 (season_id, team_id);

-- ──────────────────────────────────────────────────────────────────────────────
-- 5. team_context_sources_2026
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS team_context_sources_2026 (
    team_id        TEXT    NOT NULL,
    season_id      INTEGER NOT NULL,
    source_name    TEXT    NOT NULL,   -- 'NFL.com','ESPN','Ourlads','Manual', etc.
    source_type    TEXT    NOT NULL,   -- 'NEEDS_ARTICLE','DEPTH_CHART','SCHEME_NOTE'
    url            TEXT    NOT NULL,
    fetched_at_utc TEXT    NOT NULL,
    notes          TEXT,
    PRIMARY KEY (team_id, season_id, source_name, source_type)
);

-- ──────────────────────────────────────────────────────────────────────────────
-- 6. v_team_fit_context_2026
-- ──────────────────────────────────────────────────────────────────────────────
-- Assembles the evaluator-ready team context from the five normalized tables.
-- Also LEFT JOINs team_draft_context for evaluator-critical fields not yet
-- migrated to the normalized schema:
--   primary_defense_family, coverage_bias, man_rate_tolerance, draft_capital_json,
--   team_name, development_timeline, risk_tolerance.
--
-- Python consumers: parse needs_json to get premium_needs list; parse
-- depth_pressure_json to get pressure dict; parse deployment_traits_json
-- for archetype-level deployment deltas.
--
-- Caller must have run seed_team_context_normalized_2026.py --apply 1 AND
-- build_team_context_2026.py --apply 1 for all columns to be non-null.

CREATE VIEW IF NOT EXISTS v_team_fit_context_2026 AS
SELECT
    snap.team_id,
    snap.season_id,
    snap.snapshot_version,
    snap.scheme_family,
    snap.capital_profile,
    snap.failure_mode_bias,
    snap.offensive_coord,
    snap.defensive_coord,
    snap.base_personnel,
    snap.play_style_notes,
    snap.provenance_note,
    -- evaluator fields from team_draft_context (not yet in normalized tables)
    tdc.team_name,
    tdc.primary_defense_family,
    tdc.coverage_bias,
    tdc.man_rate_tolerance,
    tdc.draft_capital_json,
    tdc.development_timeline,
    tdc.risk_tolerance,
    -- normalized needs (PREMIUM first, then SECONDARY, ordered by rank)
    (
        SELECT json_group_array(
            json_object(
                'rank',       need_rank,
                'position',   position_code,
                'tier',       need_tier,
                'confidence', COALESCE(confidence, 'B')
            )
        )
        FROM (
            SELECT * FROM team_needs_2026
            WHERE team_id  = snap.team_id
              AND season_id = snap.season_id
            ORDER BY need_tier ASC, need_rank ASC
        )
    ) AS needs_json,
    -- normalized depth pressure (highest pressure first)
    (
        SELECT json_group_array(
            json_object(
                'position_group',  position_group,
                'pressure',        pressure_score,
                'starter_quality', starter_quality,
                'snaps_blocker',   snaps_blocker_flag
            )
        )
        FROM (
            SELECT * FROM team_depth_pressure_2026
            WHERE team_id  = snap.team_id
              AND season_id = snap.season_id
            ORDER BY pressure_score DESC
        )
    ) AS depth_pressure_json,
    -- deployment traits (alphabetical by position_group + trait_code)
    (
        SELECT json_group_array(
            json_object(
                'position_group', position_group,
                'trait_code',     trait_code,
                'trait_value',    trait_value
            )
        )
        FROM (
            SELECT * FROM team_deployment_traits_2026
            WHERE team_id  = snap.team_id
              AND season_id = snap.season_id
            ORDER BY position_group ASC, trait_code ASC
        )
    ) AS deployment_traits_json
FROM team_context_snapshots snap
LEFT JOIN team_draft_context tdc
  ON  tdc.team_id  = snap.team_id
  AND tdc.season_id = snap.season_id
  AND tdc.is_active = 1;

-- ──────────────────────────────────────────────────────────────────────────────
-- Verify
-- ──────────────────────────────────────────────────────────────────────────────

SELECT
    'migration_0054_applied'                                                   AS status,
    (SELECT COUNT(*) FROM sqlite_master WHERE type='table'
     AND name='team_context_snapshots')                                        AS snapshots_table,
    (SELECT COUNT(*) FROM sqlite_master WHERE type='table'
     AND name='team_needs_2026')                                               AS needs_table,
    (SELECT COUNT(*) FROM sqlite_master WHERE type='table'
     AND name='team_depth_pressure_2026')                                      AS depth_table,
    (SELECT COUNT(*) FROM sqlite_master WHERE type='table'
     AND name='team_deployment_traits_2026')                                   AS traits_table,
    (SELECT COUNT(*) FROM sqlite_master WHERE type='table'
     AND name='team_context_sources_2026')                                     AS sources_table,
    (SELECT COUNT(*) FROM sqlite_master WHERE type='view'
     AND name='v_team_fit_context_2026')                                       AS view_present;
