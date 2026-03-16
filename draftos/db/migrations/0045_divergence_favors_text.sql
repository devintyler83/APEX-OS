-- Migration 0045: divergence_flags.apex_favors_text
-- Adds apex_favors_text TEXT column to divergence_flags.
-- apex_favors (INTEGER, 0/1/-1) is retained for backwards compat.
-- apex_favors_text carries a short human-readable phrase describing
-- what the APEX engine weights higher than the market:
--   APEX_HIGH  → archetype mechanism phrase  (e.g. "Elite Pass Rusher profile")
--   APEX_LOW   → failure mode risk phrase    (e.g. "FM-2 Conditional risk")
--   ALIGNED    → NULL
-- Populated by run_apex_scoring_2026.py --batch divergence at write time.
-- Additive only — no existing data modified.

ALTER TABLE divergence_flags ADD COLUMN apex_favors_text TEXT;
