-- Migration 0024: Add dispersion columns to prospect_consensus_rankings
-- Additive only. No existing columns modified.

ALTER TABLE prospect_consensus_rankings
  ADD COLUMN rank_std_dev REAL;

ALTER TABLE prospect_consensus_rankings
  ADD COLUMN dispersion_penalty REAL;
