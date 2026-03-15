-- Migration 0042: Bump view model_version filter from apex_v2.2 → apex_v2.3
--
-- All three board views (v_board, v_divergence_board, v_position_board) were
-- created in migration 0031 with hardcoded model_version = 'apex_v2.2'.
-- The scoring engine writes apex_v2.3 rows since Session 28. The stale filter
-- makes 149 current rows invisible to every view query.
--
-- Fix: DROP and recreate all three views with apex_v2.3.
-- The apex_scores and divergence_flags column DEFAULTs also say apex_v2.2
-- but SQLite does not support ALTER COLUMN — the DEFAULT is cosmetic since
-- all write paths set model_version explicitly.
--
-- Idempotent: DROP IF EXISTS before CREATE.

-- -----------------------------------------------------------------------
-- v_board
-- -----------------------------------------------------------------------
DROP VIEW IF EXISTS v_board;
CREATE VIEW v_board AS
SELECT
  p.prospect_id,
  p.full_name,
  p.display_name,
  p.position_group   AS pos,
  p.school_canonical AS school,
  -- APEX
  a.apex_composite,
  a.apex_tier,
  a.capital_adjusted,
  a.matched_archetype,
  a.gap_label,
  a.eval_confidence,
  a.tags,
  -- Consensus
  c.median_ovr_rank,
  c.avg_ovr_rank,
  c.median_pos_rank,
  c.avg_pos_rank,
  c.median_draft_round,
  c.consensus_tier,
  c.source_count,
  c.coverage_pct,
  c.rank_std_dev,
  -- Divergence
  d.divergence_score,
  d.divergence_flag,
  d.divergence_mag,
  d.rounds_diff,
  d.apex_favors
FROM prospects p
LEFT JOIN apex_scores        a ON a.prospect_id = p.prospect_id AND a.model_version = 'apex_v2.3'
LEFT JOIN consensus_rankings c ON c.prospect_id = p.prospect_id
LEFT JOIN divergence_flags   d ON d.prospect_id = p.prospect_id AND d.model_version = 'apex_v2.3'
WHERE p.season_id = 1
ORDER BY a.apex_composite DESC NULLS LAST;

-- -----------------------------------------------------------------------
-- v_divergence_board
-- -----------------------------------------------------------------------
DROP VIEW IF EXISTS v_divergence_board;
CREATE VIEW v_divergence_board AS
SELECT
  p.full_name,
  p.position_group  AS pos,
  p.school_canonical AS school,
  a.apex_composite,
  a.apex_tier,
  a.capital_adjusted,
  c.median_ovr_rank,
  c.consensus_tier,
  d.divergence_score,
  d.divergence_flag,
  d.divergence_mag,
  d.rounds_diff,
  a.tags
FROM prospects p
JOIN apex_scores        a ON a.prospect_id = p.prospect_id AND a.model_version = 'apex_v2.3'
JOIN consensus_rankings c ON c.prospect_id = p.prospect_id
JOIN divergence_flags   d ON d.prospect_id = p.prospect_id AND d.model_version = 'apex_v2.3'
WHERE d.divergence_flag != 'ALIGNED'
  AND p.season_id = 1
ORDER BY ABS(d.divergence_score) DESC;

-- -----------------------------------------------------------------------
-- v_position_board
-- -----------------------------------------------------------------------
DROP VIEW IF EXISTS v_position_board;
CREATE VIEW v_position_board AS
SELECT
  p.position_group  AS pos,
  a.apex_pos_rank,
  p.full_name,
  p.school_canonical AS school,
  a.apex_composite,
  a.apex_tier,
  a.matched_archetype,
  a.capital_adjusted,
  c.median_ovr_rank,
  c.consensus_tier,
  d.divergence_flag,
  d.divergence_score
FROM prospects p
JOIN apex_scores        a ON a.prospect_id = p.prospect_id AND a.model_version = 'apex_v2.3'
JOIN consensus_rankings c ON c.prospect_id = p.prospect_id
LEFT JOIN divergence_flags d ON d.prospect_id = p.prospect_id AND d.model_version = 'apex_v2.3'
WHERE p.season_id = 1
ORDER BY p.position_group, a.apex_pos_rank NULLS LAST;
