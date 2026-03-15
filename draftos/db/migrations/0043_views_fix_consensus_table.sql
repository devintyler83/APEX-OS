-- Migration 0043: Fix board views — consensus table and column name alignment
--
-- Migration 0042 bumped model_version v2.2→v2.3 but the views still JOIN
-- against `consensus_rankings` (empty stub table, 0 rows).
-- Live consensus data is in `prospect_consensus_rankings`.
--
-- Column mapping:
--   old consensus_rankings.median_ovr_rank  → pcr.median_rank     AS median_ovr_rank
--   old consensus_rankings.avg_ovr_rank     → pcr.avg_rank        AS avg_ovr_rank
--   old consensus_rankings.consensus_tier   → pcr.tier            AS consensus_tier
--   old consensus_rankings.source_count     → pcr.sources_covered AS source_count
--   old consensus_rankings.rank_std_dev     → pcr.rank_std_dev
--   old consensus_rankings.median_pos_rank  → NULL (no per-position rank in pcr)
--   old consensus_rankings.avg_pos_rank     → NULL
--   old consensus_rankings.median_draft_round → NULL
--   old consensus_rankings.coverage_pct    → NULL
--
-- Also adds season_id filter on the consensus join.

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
  -- Consensus (mapped from prospect_consensus_rankings)
  c.median_rank      AS median_ovr_rank,
  c.avg_rank         AS avg_ovr_rank,
  NULL               AS median_pos_rank,
  NULL               AS avg_pos_rank,
  NULL               AS median_draft_round,
  c.tier             AS consensus_tier,
  c.sources_covered  AS source_count,
  NULL               AS coverage_pct,
  c.rank_std_dev,
  c.consensus_rank,
  c.score            AS consensus_score,
  -- Divergence
  d.divergence_score,
  d.divergence_flag,
  d.divergence_mag,
  d.rounds_diff,
  d.apex_favors
FROM prospects p
LEFT JOIN apex_scores              a ON a.prospect_id = p.prospect_id
                                     AND a.model_version = 'apex_v2.3'
LEFT JOIN prospect_consensus_rankings c ON c.prospect_id = p.prospect_id
                                        AND c.season_id = 1
LEFT JOIN divergence_flags         d ON d.prospect_id = p.prospect_id
                                     AND d.model_version = 'apex_v2.3'
WHERE p.season_id = 1
ORDER BY a.apex_composite DESC NULLS LAST;

-- -----------------------------------------------------------------------
-- v_divergence_board
-- -----------------------------------------------------------------------
DROP VIEW IF EXISTS v_divergence_board;
CREATE VIEW v_divergence_board AS
SELECT
  p.full_name,
  p.position_group   AS pos,
  p.school_canonical AS school,
  a.apex_composite,
  a.apex_tier,
  a.capital_adjusted,
  c.median_rank      AS median_ovr_rank,
  c.tier             AS consensus_tier,
  c.consensus_rank,
  d.divergence_score,
  d.divergence_flag,
  d.divergence_mag,
  d.rounds_diff,
  a.tags
FROM prospects p
JOIN apex_scores                   a ON a.prospect_id = p.prospect_id
                                     AND a.model_version = 'apex_v2.3'
JOIN prospect_consensus_rankings   c ON c.prospect_id = p.prospect_id
                                     AND c.season_id = 1
JOIN divergence_flags              d ON d.prospect_id = p.prospect_id
                                     AND d.model_version = 'apex_v2.3'
WHERE d.divergence_flag != 'ALIGNED'
  AND p.season_id = 1
ORDER BY ABS(d.divergence_score) DESC;

-- -----------------------------------------------------------------------
-- v_position_board
-- -----------------------------------------------------------------------
DROP VIEW IF EXISTS v_position_board;
CREATE VIEW v_position_board AS
SELECT
  p.position_group   AS pos,
  a.apex_pos_rank,
  p.full_name,
  p.school_canonical AS school,
  a.apex_composite,
  a.apex_tier,
  a.matched_archetype,
  a.capital_adjusted,
  c.median_rank      AS median_ovr_rank,
  c.consensus_rank,
  c.tier             AS consensus_tier,
  d.divergence_flag,
  d.divergence_score
FROM prospects p
JOIN apex_scores                   a ON a.prospect_id = p.prospect_id
                                     AND a.model_version = 'apex_v2.3'
JOIN prospect_consensus_rankings   c ON c.prospect_id = p.prospect_id
                                     AND c.season_id = 1
LEFT JOIN divergence_flags         d ON d.prospect_id = p.prospect_id
                                     AND d.model_version = 'apex_v2.3'
WHERE p.season_id = 1
ORDER BY p.position_group, a.apex_pos_rank NULLS LAST;
