-- Migration 0028: Staging table for RAS ingest
-- Holds all rows including unmatched; idempotent upsert on (name_key, season_id)
CREATE TABLE IF NOT EXISTS ras_staging (
  ras_staging_id      INTEGER PRIMARY KEY,
  season_id           INTEGER NOT NULL,
  name_raw            TEXT NOT NULL,
  name_key            TEXT NOT NULL,
  pos_raw             TEXT,
  pos_normalized      TEXT,
  college_raw         TEXT,
  college_canonical   TEXT,
  ras_score           REAL,
  ras_score_raw       TEXT,
  matched_prospect_id INTEGER,
  match_method        TEXT,
  ingested_at         TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE(name_key, season_id)
);
