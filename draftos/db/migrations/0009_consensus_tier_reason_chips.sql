-- 0009_consensus_tier_reason_chips.sql
-- Additive: enrich consensus rows with tier + reason chips for UI/model consumption.

ALTER TABLE prospect_consensus_rankings
ADD COLUMN tier TEXT;

ALTER TABLE prospect_consensus_rankings
ADD COLUMN reason_chips_json TEXT;