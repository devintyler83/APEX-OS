-- ============================================================
-- DraftOS Migration 0032 — apex_scores calibration artifact flag
-- File: draftos/db/migrations/0032_apex_calibration_artifact.sql
-- Apply via: python -m draftos.db.migrate
-- Additive only — adds one column to apex_scores
-- ============================================================

ALTER TABLE apex_scores ADD COLUMN is_calibration_artifact INTEGER NOT NULL DEFAULT 0;
