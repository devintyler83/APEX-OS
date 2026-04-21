-- Migration 0051: team_prospect_fit signal view + covering indexes
-- Additive only. No destructive changes. No schema alterations.
-- Season-scoped to season_id=1 (2026 draft year) in the view definition.
--
-- Adds:
--   idx_tpf_season_team_tier_score     — covering index for per-team signal queries
--   idx_tpf_season_prospect_tier_score — covering index for per-prospect signal queries
--   v_team_prospect_fit_signal_2026    — read-only view over IDEAL/STRONG/VIABLE rows
--
-- The view joins team_prospect_fit → apex_scores → team_draft_context to surface
-- prospect FM data and team scheme context alongside the precomputed fit fields.
-- Callers must not apply additional season_id filters — season=1 is baked in.

-- ──────────────────────────────────────────────────────────
-- Covering indexes
-- ──────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_tpf_season_team_tier_score
    ON team_prospect_fit (season_id, team_id, fit_tier, fit_score DESC);

CREATE INDEX IF NOT EXISTS idx_tpf_season_prospect_tier_score
    ON team_prospect_fit (season_id, prospect_id, fit_tier, fit_score DESC);

-- ──────────────────────────────────────────────────────────
-- Signal view
-- ──────────────────────────────────────────────────────────

CREATE VIEW IF NOT EXISTS v_team_prospect_fit_signal_2026 AS
SELECT
    tpf.prospect_id,
    tpf.team_id,
    tpf.season_id,
    tpf.fit_score,
    tpf.fit_tier,
    tpf.deployment_fit,
    tpf.pick_fit,
    tpf.fm_risk_score,
    tpf.verdict,
    tpf.why_for,
    tpf.why_against,
    tpf.confidence,
    tpf.fit_explanation,
    a.capital_adjusted,
    a.failure_mode_primary,
    a.failure_mode_secondary,
    tdc.premium_needs_json        AS team_primary_needs,
    tdc.secondary_needs_json      AS team_secondary_needs,
    tdc.coverage_bias,
    tdc.primary_defense_family
FROM team_prospect_fit tpf
JOIN apex_scores a
  ON  a.prospect_id          = tpf.prospect_id
  AND a.season_id            = tpf.season_id
  AND a.model_version        = 'apex_v2.3'
  AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
JOIN team_draft_context tdc
  ON  tdc.team_id   = tpf.team_id
  AND tdc.season_id = tpf.season_id
  AND tdc.is_active = 1
WHERE tpf.season_id = 1
  AND tpf.fit_tier IN ('IDEAL', 'STRONG', 'VIABLE');

-- ──────────────────────────────────────────────────────────
-- Verify
-- ──────────────────────────────────────────────────────────

SELECT
    'migration_0051_applied'                                          AS status,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_tpf_season_team_tier_score')    AS idx_team_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_tpf_season_prospect_tier_score') AS idx_prospect_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'view'  AND name = 'v_team_prospect_fit_signal_2026')   AS view_present;
