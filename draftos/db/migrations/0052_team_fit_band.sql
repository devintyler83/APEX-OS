-- Migration 0052: add fit_band to v_team_prospect_fit_signal_2026
-- Additive representation layer only. No scoring changes. No table alterations.
--
-- SQLite views are immutable after creation. This migration drops and recreates
-- v_team_prospect_fit_signal_2026 to append a computed fit_band column.
-- All prior columns are preserved in identical order. fit_band is appended last.
--
-- fit_band thresholds (pure CASE on fit_score):
--   A : fit_score >= 80   — true target hits
--   B : fit_score >= 70   — solid, context-dependent
--   C : fit_score >= 60   — fallback options (floor of VIABLE tier)
--
-- The view remains pre-filtered to season_id=1, fit_tier IN ('IDEAL','STRONG','VIABLE').
-- No FRINGE or POOR rows are present, so fit_band is never NULL within the view.

DROP VIEW IF EXISTS v_team_prospect_fit_signal_2026;

CREATE VIEW v_team_prospect_fit_signal_2026 AS
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
    tdc.primary_defense_family,
    CASE
        WHEN tpf.fit_score >= 80 THEN 'A'
        WHEN tpf.fit_score >= 70 THEN 'B'
        ELSE                          'C'
    END                           AS fit_band
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
    'migration_0052_applied'                                       AS status,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'view' AND name = 'v_team_prospect_fit_signal_2026') AS view_present,
    (SELECT COUNT(*) FROM v_team_prospect_fit_signal_2026)             AS total_rows,
    (SELECT COUNT(*) FROM v_team_prospect_fit_signal_2026
     WHERE fit_band = 'A')                                             AS band_a,
    (SELECT COUNT(*) FROM v_team_prospect_fit_signal_2026
     WHERE fit_band = 'B')                                             AS band_b,
    (SELECT COUNT(*) FROM v_team_prospect_fit_signal_2026
     WHERE fit_band = 'C')                                             AS band_c,
    (SELECT COUNT(*) FROM v_team_prospect_fit_signal_2026
     WHERE fit_band IS NULL)                                           AS band_null;
