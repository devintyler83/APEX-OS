-- ============================================================
-- DraftOS Migration — APEX v2.3 Mechanism-Grade Fields
-- File: draftos/db/migrations/XXXX_apex_v23_mechanism_fields.sql
-- Apply via: python migrate.py
-- Additive only — does not touch existing data
-- ============================================================

PRAGMA foreign_keys = ON;

-- New analytical fields for mechanism-grade evaluations (APEX v2.3)
-- These store the structured output from Section E of the upgraded prompt.

ALTER TABLE apex_scores ADD COLUMN failure_mode_primary TEXT;
-- FM-1 through FM-6 code + name, e.g. "FM-4 Body Breakdown"
-- REQUIRED on all scored prospects.

ALTER TABLE apex_scores ADD COLUMN failure_mode_secondary TEXT;
-- FM code + name, or "NONE"
-- Optional: only when a second failure mode has >20% probability.

ALTER TABLE apex_scores ADD COLUMN signature_play TEXT;
-- One sentence: the single play/pattern that captures the prospect's winning mechanism.

ALTER TABLE apex_scores ADD COLUMN translation_risk TEXT;
-- One sentence: the specific NFL scenario most likely to cause underperformance.

-- NOTE: strengths and red_flags columns already exist in apex_scores.
-- The v2.3 prompt upgrade changes the CONTENT QUALITY of these fields
-- (mechanism-specific vs. generic), not the schema.
-- A --force re-score will overwrite existing vague text with mechanism-grade text.
