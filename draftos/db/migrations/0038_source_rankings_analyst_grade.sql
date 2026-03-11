-- ============================================================
-- DraftOS Migration 0038 — Add analyst_grade to source_rankings
-- File: draftos/db/migrations/0038_source_rankings_analyst_grade.sql
-- Apply via: python -m draftos.db.migrate
-- Additive only — nullable REAL column, no existing rows modified
-- ============================================================

PRAGMA foreign_keys = ON;

-- Nullable analyst grade (0-10 float scale) from source analyst.
-- Initially populated only for bleacherreport_2026 (Sobleski grades).
-- NULL for all other sources — never backfill, never default to 0.
-- Future sources with analyst grades use the same column.
ALTER TABLE source_rankings ADD COLUMN analyst_grade REAL;
