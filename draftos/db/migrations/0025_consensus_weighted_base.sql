-- Migration 0025: Add weighted_base_score column to prospect_consensus_rankings
-- Stores the quality-weighted base score for auditability alongside unweighted base.
ALTER TABLE prospect_consensus_rankings
  ADD COLUMN weighted_base_score REAL;
