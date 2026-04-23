-- Migration 0059: historical_comps v2 — additive column expansion
-- Adds: season_id, nfl_team, draft_year, outcome, primary_fm, secondary_fm,
--       era_flag, pvc_eligible, position_note, notes
-- Backfills: outcome=translation_outcome, primary_fm=fm_code for existing rows
-- Backfills: pvc_eligible=1 for known modern-era CB-1 records
-- Updates: unique index to (player_name, archetype_code, season_id)
-- Applied via: scripts/seed_cb1_comps_s108_batch2.py

ALTER TABLE historical_comps ADD COLUMN season_id    INTEGER NOT NULL DEFAULT 1;
ALTER TABLE historical_comps ADD COLUMN nfl_team     TEXT;
ALTER TABLE historical_comps ADD COLUMN draft_year   INTEGER;
ALTER TABLE historical_comps ADD COLUMN outcome      TEXT;
ALTER TABLE historical_comps ADD COLUMN primary_fm   TEXT;
ALTER TABLE historical_comps ADD COLUMN secondary_fm TEXT;
ALTER TABLE historical_comps ADD COLUMN era_flag     TEXT;
ALTER TABLE historical_comps ADD COLUMN pvc_eligible INTEGER NOT NULL DEFAULT 0;
ALTER TABLE historical_comps ADD COLUMN position_note TEXT;
ALTER TABLE historical_comps ADD COLUMN notes        TEXT;

-- Backfill new alias columns from legacy columns
UPDATE historical_comps SET outcome    = translation_outcome;
UPDATE historical_comps SET primary_fm = fm_code;

-- Mark known modern-era CB-1 records as pvc_eligible
-- Champ Bailey (1999 draft) excluded — pre-2004 cap era
UPDATE historical_comps
SET    pvc_eligible = 1
WHERE  archetype_code = 'CB-1'
AND    player_name IN ('Darrelle Revis', 'Stephon Gilmore', 'Jalen Ramsey', 'Patrick Peterson');

-- Update unique index to include season_id (enables future cross-season records)
DROP INDEX IF EXISTS idx_comps_unique;
CREATE UNIQUE INDEX idx_comps_unique ON historical_comps(player_name, archetype_code, season_id);
