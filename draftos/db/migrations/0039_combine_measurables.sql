-- ============================================================
-- DraftOS Migration 0039 — Combine Measurables Columns
-- File: draftos/db/migrations/0039_combine_measurables.sql
-- Apply via: python -m draftos.db.migrate
-- Additive only — no drops, no modifications to existing columns
-- ============================================================
--
-- Adds three nullable REAL columns to the ras table:
--   hand_size  — hand circumference in decimal inches (e.g. 9.88)
--   arm_length — arm length in decimal inches (e.g. 34.38)
--   wingspan   — wingspan in decimal inches (e.g. 82.25)
--
-- NULL = player did not measure; 0.0 is invalid for these fields.
-- Idempotency: runner skips via meta_migrations table check.
--   _apply_sql_file_tolerant() also silently skips duplicate-column
--   errors on ALTER TABLE — safe to re-run if migration was partially
--   applied.
-- ============================================================

PRAGMA foreign_keys = ON;

ALTER TABLE ras ADD COLUMN hand_size  REAL;
ALTER TABLE ras ADD COLUMN arm_length REAL;
ALTER TABLE ras ADD COLUMN wingspan   REAL;
