-- Migration 0055: Draft Mode event layer — drafted_picks_2026 + v_draft_targets_remaining_2026
-- Additive only. No destructive changes to existing tables or views.
-- Season-scoped to season_id=1 (2026 draft year) throughout.
--
-- Adds:
--   drafted_picks_2026              — one row per (season_id, pick_number); records each drafted player
--   idx_drafted_picks_season_pick   — covering index for season+pick queries
--   idx_drafted_picks_season_pid    — covering index for season+prospect lookup
--   idx_drafted_picks_team          — index for per-team pick queries
--   v_draft_targets_remaining_2026  — derived view: v_draft_targets_2026 minus drafted prospects
--
-- Purpose:
--   drafted_picks_2026 is a write-append event log for draft night. Each pick is a single
--   row. The UNIQUE constraints on (season_id, pick_number) and (season_id, prospect_id)
--   enforce draft-night invariants at the DB level:
--     - no pick number can be used twice in a season
--     - no prospect can be drafted twice in a season
--
--   v_draft_targets_remaining_2026 is the approved Draft Mode remaining-board read path.
--   It reads only from v_draft_targets_2026 and drafted_picks_2026. No direct joins to
--   forbidden upstream source tables (consensus_reconciliation_2026, divergence_flags,
--   v_team_prospect_fit_signal_2026). Those are accessed only through the approved view chain.
--
-- Consumer scripts:
--   scripts/mark_drafted_2026.py    — writes to drafted_picks_2026 (--apply 0/1)
--   scripts/reset_drafted_2026.py   — deletes from drafted_picks_2026 (--apply 0/1)
--   scripts/get_team_board_2026.py  — reads from v_draft_targets_remaining_2026
--
-- Dependency chain:
--   v_draft_targets_2026  — Migration 0053 (must exist)

-- ──────────────────────────────────────────────────────────
-- Table: drafted_picks_2026
-- ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS drafted_picks_2026 (
    id                  INTEGER PRIMARY KEY,
    season_id           INTEGER NOT NULL,
    pick_number         INTEGER NOT NULL,
    round_number        INTEGER,
    drafting_team       TEXT    NOT NULL,
    prospect_id         INTEGER NOT NULL,
    drafted_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    draft_session_label TEXT,
    source              TEXT    NOT NULL DEFAULT 'manual',
    note                TEXT,
    UNIQUE (season_id, pick_number),
    UNIQUE (season_id, prospect_id)
);

-- Covering index: pick-order queries within a season
CREATE INDEX IF NOT EXISTS idx_drafted_picks_season_pick
    ON drafted_picks_2026 (season_id, pick_number);

-- Covering index: prospect-existence checks within a season
CREATE INDEX IF NOT EXISTS idx_drafted_picks_season_pid
    ON drafted_picks_2026 (season_id, prospect_id);

-- Per-team pick history
CREATE INDEX IF NOT EXISTS idx_drafted_picks_team
    ON drafted_picks_2026 (drafting_team);

-- ──────────────────────────────────────────────────────────
-- View: v_draft_targets_remaining_2026
-- ──────────────────────────────────────────────────────────
-- Approved Draft Mode remaining-board read path.
-- Base source: v_draft_targets_2026 ONLY.
-- Excludes any prospect_id that appears in drafted_picks_2026 for season_id=1.
-- All 28 columns from v_draft_targets_2026 are preserved unchanged.
--
-- Callers must never bypass this view to query upstream tables directly.

CREATE VIEW IF NOT EXISTS v_draft_targets_remaining_2026 AS
SELECT
    t.prospect_id,
    t.team_id,
    t.season_id,
    t.fit_score,
    t.fit_tier,
    t.fit_band,
    t.deployment_fit,
    t.pick_fit,
    t.fm_risk_score,
    t.verdict,
    t.why_for,
    t.why_against,
    t.confidence,
    t.fit_explanation,
    t.capital_adjusted,
    t.failure_mode_primary,
    t.failure_mode_secondary,
    t.team_primary_needs,
    t.team_secondary_needs,
    t.coverage_bias,
    t.primary_defense_family,
    t.consensus_rank,
    t.apex_rank,
    t.divergence_delta,
    t.divergence_flag,
    t.divergence_magnitude,
    t.jfoster_con_rank,
    t.recon_bucket
FROM v_draft_targets_2026 t
WHERE NOT EXISTS (
    SELECT 1
    FROM drafted_picks_2026 dp
    WHERE dp.prospect_id = t.prospect_id
      AND dp.season_id   = 1
);

-- ──────────────────────────────────────────────────────────
-- Verify
-- ──────────────────────────────────────────────────────────

SELECT
    'migration_0055_applied'                                                    AS status,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'table' AND name = 'drafted_picks_2026')                     AS event_table_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_drafted_picks_season_pick')          AS idx_pick_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_drafted_picks_season_pid')           AS idx_pid_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_drafted_picks_team')                 AS idx_team_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'view'  AND name = 'v_draft_targets_remaining_2026')         AS remaining_view_present,
    (SELECT COUNT(*) FROM drafted_picks_2026)                                   AS drafted_picks_rows,
    (SELECT COUNT(*) FROM v_draft_targets_remaining_2026)                       AS remaining_view_rows;
