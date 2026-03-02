-- 0014_prospect_canonical_map.sql
-- Additive prospect canonicalization. Does not delete or modify historical rows.
-- Canonical is the "winner" prospect_id. Aliases map to canonical.

CREATE TABLE IF NOT EXISTS prospect_canonical_map (
  season_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,              -- alias (or canonical itself if you want identity rows later)
  canonical_prospect_id INTEGER NOT NULL,    -- winner
  reason TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  PRIMARY KEY (season_id, prospect_id)
);

CREATE INDEX IF NOT EXISTS idx_pcm_season_canon
  ON prospect_canonical_map(season_id, canonical_prospect_id);