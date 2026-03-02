-- 0011_name_normalization.sql
PRAGMA foreign_keys = OFF;

-- Prospects
ALTER TABLE prospects ADD COLUMN name_norm TEXT;
ALTER TABLE prospects ADD COLUMN name_key TEXT;

-- Source players
ALTER TABLE source_players ADD COLUMN name_norm TEXT;
ALTER TABLE source_players ADD COLUMN name_key TEXT;
ALTER TABLE source_players ADD COLUMN school_canonical TEXT;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prospects_season_name_key
  ON prospects(season_id, name_key);

CREATE INDEX IF NOT EXISTS idx_source_players_season_name_key
  ON source_players(season_id, name_key);

CREATE INDEX IF NOT EXISTS idx_source_players_season_school_name_key
  ON source_players(season_id, school_canonical, name_key);

PRAGMA foreign_keys = ON;