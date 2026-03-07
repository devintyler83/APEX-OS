-- Migration 0026: Add dispersion_cap_applied flag to prospect_board_snapshot_confidence
-- Tracks whether a prospect's confidence band was downgraded due to high rank dispersion.
ALTER TABLE prospect_board_snapshot_confidence
  ADD COLUMN dispersion_cap_applied INTEGER DEFAULT 0;
