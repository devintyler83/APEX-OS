-- 0010_model_outputs_table.sql
-- Additive: stores model outputs at the prospect level (v1_default etc).
-- Engine-only. Auditable. UI reads this later.

CREATE TABLE IF NOT EXISTS prospect_model_outputs (
  output_id INTEGER PRIMARY KEY,
  season_id INTEGER NOT NULL,
  model_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,

  score REAL NOT NULL,                 -- 0-100
  tier TEXT,                           -- Elite/Strong/Playable/Watch
  reason_chips_json TEXT,              -- JSON list[str]
  explain_json TEXT,                   -- JSON object (full explainability payload)

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  UNIQUE(season_id, model_id, prospect_id)
);

CREATE INDEX IF NOT EXISTS ix_model_outputs_season_model_score
  ON prospect_model_outputs (season_id, model_id, score DESC);

CREATE INDEX IF NOT EXISTS ix_model_outputs_season_model_prospect
  ON prospect_model_outputs (season_id, model_id, prospect_id);