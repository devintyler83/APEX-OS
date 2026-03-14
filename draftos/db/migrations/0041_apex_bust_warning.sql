-- ============================================================
-- DraftOS Migration 0041 — APEX bust_warning text field
-- File: draftos/db/migrations/0041_apex_bust_warning.sql
-- Apply via: python -m draftos.db.migrate
-- Additive only — does not touch existing data
-- ============================================================

PRAGMA foreign_keys = ON;

-- Short mechanism sentence summarising why this prospect busts.
-- Populated on re-score; UI falls back to FM_DESCRIPTIONS until then.
ALTER TABLE apex_scores ADD COLUMN bust_warning TEXT;
