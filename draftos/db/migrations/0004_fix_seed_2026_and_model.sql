-- Ensure 2026 season exists (idempotent)
INSERT OR IGNORE INTO seasons (draft_year, created_at)
VALUES (2026, datetime('now'));

-- Ensure v1_default exists for 2026 (idempotent)
INSERT OR IGNORE INTO models (
  season_id,
  model_key,
  model_name,
  model_json,
  created_at,
  updated_at
)
SELECT
  s.season_id,
  'v1_default',
  'DraftOS v1 Default',
  '{"version":"v1","notes":"phase1 bootstrap","weights":{}}',
  datetime('now'),
  datetime('now')
FROM seasons s
WHERE s.draft_year = 2026;