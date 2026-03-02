-- 0012_source_players_pos_hint.sql
-- Add a deterministic position hint extracted from raw_full_name prefixes (e.g., "S Caleb Downs").
-- Additive only.

ALTER TABLE source_players ADD COLUMN pos_hint TEXT;