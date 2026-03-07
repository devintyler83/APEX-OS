-- Migration 0027: Add season scoping and raw score column to existing ras table
ALTER TABLE ras ADD COLUMN season_id INTEGER;
ALTER TABLE ras ADD COLUMN ras_score_raw TEXT;
