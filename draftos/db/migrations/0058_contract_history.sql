-- Migration 0058: contract_history table
-- Additive only. Stores OTC position contract history for archetype PVC validation.
-- Dollar/percentage columns stored as REAL (parsed at ingest time).
-- archetype_code/confidence/classification_source seeded NULL — populated in separate pass.

CREATE TABLE IF NOT EXISTS contract_history (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  player                  TEXT NOT NULL,
  team                    TEXT,
  year_signed             INTEGER NOT NULL,
  contract_years          INTEGER,
  value_dollars           REAL,
  apy_dollars             REAL,
  guaranteed_dollars      REAL,
  cap_pct                 REAL,
  inflated_value          REAL,
  inflated_apy            REAL,
  inflated_guaranteed     REAL,
  position_group          TEXT NOT NULL,
  archetype_code          TEXT,
  archetype_confidence    TEXT,
  classification_source   TEXT,
  season_id               INTEGER NOT NULL DEFAULT 1,
  created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ch_position  ON contract_history(position_group);
CREATE INDEX IF NOT EXISTS idx_ch_year      ON contract_history(year_signed);
CREATE INDEX IF NOT EXISTS idx_ch_archetype ON contract_history(archetype_code);
CREATE INDEX IF NOT EXISTS idx_ch_season    ON contract_history(season_id);
