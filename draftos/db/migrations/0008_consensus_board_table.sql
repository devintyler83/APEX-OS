-- 0008_consensus_board_table.sql
-- Additive: stores consensus/aggregated rankings at the prospect level.

CREATE TABLE IF NOT EXISTS prospect_consensus_rankings (
  consensus_id INTEGER PRIMARY KEY,
  season_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,

  consensus_rank INTEGER NOT NULL,
  score REAL NOT NULL,                 -- 0-100

  sources_covered INTEGER NOT NULL,
  avg_rank REAL,
  median_rank REAL,
  min_rank INTEGER,
  max_rank INTEGER,

  explain_json TEXT,                   -- per-source ranks + summary
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  UNIQUE(season_id, prospect_id)
);

CREATE INDEX IF NOT EXISTS ix_consensus_season_rank
  ON prospect_consensus_rankings (season_id, consensus_rank);

CREATE INDEX IF NOT EXISTS ix_consensus_season_prospect
  ON prospect_consensus_rankings (season_id, prospect_id);
