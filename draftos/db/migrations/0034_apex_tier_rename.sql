-- Migration 0034: Rename APEX tier vocabulary to draft-capital naming
-- APEX -> DAY1, SOLID -> DAY2, DEVELOPMENTAL -> DAY3, ELITE stays ELITE
-- UDFA-P and UDFA are new tiers added via engine threshold changes (no existing rows).
-- Idempotent: rows already renamed to DAY1/DAY2/DAY3 are unaffected.

UPDATE apex_scores SET apex_tier = 'DAY1' WHERE apex_tier = 'APEX';
UPDATE apex_scores SET apex_tier = 'DAY2' WHERE apex_tier = 'SOLID';
UPDATE apex_scores SET apex_tier = 'DAY3' WHERE apex_tier = 'DEVELOPMENTAL';

-- divergence_flags.gap_label uses 'APEX HIGH'/'APEX LOW'/'ALIGNED' (divergence labels,
-- not tier names) -- leave untouched.

-- ELITE stays as ELITE. No change needed.
