-- Seed initial model definition for 2026 (additive, idempotent)
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
  '{"version":"v1","notes":"placeholder weights; replace via additive migration later","weights":{}}',
  datetime('now'),
  datetime('now')
FROM seasons s
WHERE s.draft_year = 2026;