-- Migration 0057: Draft sandbox picks — isolated per-session draft simulation
-- Additive only. No destructive changes to existing tables or views.
--
-- Adds:
--   draft_sandbox_picks              — sandbox drafted marks keyed by (sandbox_id, season_id, prospect_id)
--   idx_sandbox_picks_sandbox_season — covering index for per-sandbox-session queries
--   idx_sandbox_picks_season_pid     — covering index for canonical-overlap checks
--
-- Purpose:
--   draft_sandbox_picks stores "drafted" marks for isolated testing/scenario sessions.
--   It is completely separate from drafted_picks_2026 (no FK, no shared UNIQUE constraints).
--   A bug in sandbox logic cannot touch canonical draft data.
--
--   sandbox_id is a free-form string: typically a UUID assigned per Streamlit browser session,
--   or a named scenario label (e.g. "room_alpha"). The caller is responsible for generating
--   and persisting the sandbox_id within a session.
--
--   Sandbox marks are purely additive: they mark additional prospects as "drafted" for
--   display purposes inside one session. They do not assign pick numbers or team ownership.
--   Canonical drafted_picks_2026 rows always take precedence over sandbox marks.
--
-- Consumer:
--   draftos/queries/draft_mode.py — sandbox helpers (mark_prospect_sandboxed,
--   get_sandbox_picks, delete_sandbox_pick, reset_sandbox, get_remaining_board_sandbox,
--   get_draft_remaining_board_sandbox)
--
-- Relationship to canonical draft:
--   drafted_picks_2026 is canonical truth. draft_sandbox_picks is ephemeral overlay.
--   Any prospect that appears in drafted_picks_2026 for season_id=1 is drafted globally.
--   Any prospect that ONLY appears in draft_sandbox_picks is drafted for that sandbox only.

CREATE TABLE IF NOT EXISTS draft_sandbox_picks (
    sandbox_id    TEXT    NOT NULL,
    season_id     INTEGER NOT NULL,
    prospect_id   INTEGER NOT NULL,
    sandboxed_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    note          TEXT,
    PRIMARY KEY (sandbox_id, season_id, prospect_id)
);

-- Per-sandbox-session query index
CREATE INDEX IF NOT EXISTS idx_sandbox_picks_sandbox_season
    ON draft_sandbox_picks (sandbox_id, season_id);

-- Canonical-overlap check: quickly find if a prospect is sandboxed in any session
CREATE INDEX IF NOT EXISTS idx_sandbox_picks_season_pid
    ON draft_sandbox_picks (season_id, prospect_id);

-- ──────────────────────────────────────────────────────────
-- Verify
-- ──────────────────────────────────────────────────────────

SELECT
    'migration_0057_applied'                                                         AS status,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'table' AND name = 'draft_sandbox_picks')                          AS sandbox_table_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_sandbox_picks_sandbox_season')             AS idx_sandbox_season_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_sandbox_picks_season_pid')                 AS idx_season_pid_present;
