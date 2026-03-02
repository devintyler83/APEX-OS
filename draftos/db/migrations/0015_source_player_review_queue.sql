-- 0015_source_player_review_queue.sql
-- Additive manual review queue for unresolved source_player mapping.
-- Does not change historical data.

CREATE TABLE IF NOT EXISTS source_player_review_queue (
  queue_id INTEGER PRIMARY KEY,
  season_id INTEGER NOT NULL,
  source_player_id INTEGER NOT NULL,
  name_key TEXT,
  pos_hint TEXT,
  reason TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',           -- open|resolved|ignored
  resolved_prospect_id INTEGER,
  resolved_by TEXT,
  resolved_at_utc TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL,
  UNIQUE(season_id, source_player_id)
);

CREATE INDEX IF NOT EXISTS idx_sprq_season_status
  ON source_player_review_queue(season_id, status);

CREATE INDEX IF NOT EXISTS idx_sprq_season_name_key
  ON source_player_review_queue(season_id, name_key);