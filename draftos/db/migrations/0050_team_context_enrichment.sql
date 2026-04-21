-- Migration 0050: team_draft_context enrichment columns
-- Additive only. No destructive changes. Season-scoped via team_draft_context.season_id.
--
-- Adds five columns used by build_team_context_2026.py to store:
--   secondary_needs_json         — ordered secondary positional needs (JSON array)
--   failure_mode_sensitivity_json — FM activation/suppression notes per scheme (JSON object)
--   source_provenance             — free-text source attribution for this team's context data
--   context_version               — version stamp for future refresh tracking
--   snapshot_date                 — ISO date when context data was last populated
--
-- NOTE: SQLite does not support "ALTER TABLE … ADD COLUMN IF NOT EXISTS".
-- The build_team_context_2026.py script guards against duplicate adds via PRAGMA table_info().
-- This file is the formal documentation artifact; the script is the enforcement layer.

ALTER TABLE team_draft_context ADD COLUMN secondary_needs_json          TEXT NOT NULL DEFAULT '[]';
ALTER TABLE team_draft_context ADD COLUMN failure_mode_sensitivity_json  TEXT NOT NULL DEFAULT '{}';
ALTER TABLE team_draft_context ADD COLUMN source_provenance              TEXT;
ALTER TABLE team_draft_context ADD COLUMN context_version               TEXT NOT NULL DEFAULT 'v1.0';
ALTER TABLE team_draft_context ADD COLUMN snapshot_date                 TEXT;

-- Verify
SELECT 'migration_0050_applied' AS status,
       (SELECT COUNT(*) FROM pragma_table_info('team_draft_context')
        WHERE name IN ('secondary_needs_json','failure_mode_sensitivity_json',
                       'source_provenance','context_version','snapshot_date')) AS new_cols_present;
