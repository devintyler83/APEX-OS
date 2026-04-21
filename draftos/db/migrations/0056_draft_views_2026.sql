-- Migration 0056: Draft Mode spec views — v_draft_remaining_2026 + v_draft_team_board_2026
-- Additive only. No destructive changes to existing tables or views.
-- Season-scoped to season_id=1 (2026 draft year) throughout.
--
-- Adds:
--   v_draft_remaining_2026       — canonical spec alias for v_draft_targets_remaining_2026
--   v_draft_team_board_2026      — per-team remaining board enriched with v_team_fit_context_2026
--
-- Dependency chain (must already exist):
--   v_draft_targets_remaining_2026  — Migration 0055
--   v_team_fit_context_2026         — Migration 0054
--
-- Consumer modules:
--   draftos/queries/draft_mode.py  — get_draft_remaining_board(), get_draft_team_board()
--   app/app.py                     — Team Companion tab → Top Fits expander

-- ──────────────────────────────────────────────────────────────────────────────
-- View: v_draft_remaining_2026
-- ──────────────────────────────────────────────────────────────────────────────
-- Canonical spec-named alias for v_draft_targets_remaining_2026.
-- Exposes all 28 columns from the approved remaining-board read path.
-- UI and query helpers may use either name; this view is the spec contract surface.

CREATE VIEW IF NOT EXISTS v_draft_remaining_2026 AS
SELECT
    prospect_id,
    team_id,
    season_id,
    fit_score,
    fit_tier,
    fit_band,
    deployment_fit,
    pick_fit,
    fm_risk_score,
    verdict,
    why_for,
    why_against,
    confidence,
    fit_explanation,
    capital_adjusted,
    failure_mode_primary,
    failure_mode_secondary,
    team_primary_needs,
    team_secondary_needs,
    coverage_bias,
    primary_defense_family,
    consensus_rank,
    apex_rank,
    divergence_delta,
    divergence_flag,
    divergence_magnitude,
    jfoster_con_rank,
    recon_bucket
FROM v_draft_targets_remaining_2026;

-- ──────────────────────────────────────────────────────────────────────────────
-- View: v_draft_team_board_2026
-- ──────────────────────────────────────────────────────────────────────────────
-- Per-team remaining board: v_draft_remaining_2026 enriched with team scheme/context
-- columns from v_team_fit_context_2026. Join key: (team_id, season_id).
--
-- The base prospect+fit columns come from v_draft_remaining_2026 (approved read path).
-- The enrichment columns (scheme_family, capital_profile, needs_json, etc.) come from
-- v_team_fit_context_2026, which is a team-level view (one row per team) — not prospect-level.
-- This means each prospect×team fit row gains the full team context for that team.
--
-- Callers filter by team_id to get the board for a specific team:
--   SELECT * FROM v_draft_team_board_2026 WHERE team_id = 'SF' ORDER BY fit_band, fit_score DESC
--
-- NOTE: v_team_fit_context_2026 has no prospect_id column. The join is team-level only.
--       coverage_bias from r (prospect fit row) is preserved as-is; team_coverage_bias
--       from v_team_fit_context_2026 is added as a distinct column for cross-reference.

CREATE VIEW IF NOT EXISTS v_draft_team_board_2026 AS
SELECT
    -- prospect + fit identity
    r.prospect_id,
    r.team_id,
    r.season_id,
    -- fit scoring
    r.fit_score,
    r.fit_tier,
    r.fit_band,
    r.deployment_fit,
    r.pick_fit,
    r.fm_risk_score,
    -- fit narrative
    r.verdict,
    r.why_for,
    r.why_against,
    r.confidence,
    r.fit_explanation,
    -- prospect capital/risk
    r.capital_adjusted,
    r.failure_mode_primary,
    r.failure_mode_secondary,
    -- team needs context (from signal view)
    r.team_primary_needs,
    r.team_secondary_needs,
    r.coverage_bias,
    r.primary_defense_family,
    -- divergence
    r.consensus_rank,
    r.apex_rank,
    r.divergence_delta,
    r.divergence_flag,
    r.divergence_magnitude,
    r.jfoster_con_rank,
    r.recon_bucket,
    -- team scheme context (from v_team_fit_context_2026)
    c.team_name,
    c.scheme_family,
    c.capital_profile,
    c.failure_mode_bias,
    c.coverage_bias      AS team_coverage_bias,
    c.development_timeline,
    c.risk_tolerance,
    c.needs_json,
    c.deployment_traits_json
FROM v_draft_remaining_2026 r
JOIN v_team_fit_context_2026 c
  ON  c.team_id   = r.team_id
  AND c.season_id = r.season_id
WHERE r.season_id = 1;

-- ──────────────────────────────────────────────────────────────────────────────
-- Verify
-- ──────────────────────────────────────────────────────────────────────────────

SELECT
    'migration_0056_applied'                                                AS status,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'view' AND name = 'v_draft_remaining_2026')              AS remaining_view_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'view' AND name = 'v_draft_team_board_2026')             AS team_board_view_present,
    (SELECT COUNT(*) FROM v_draft_remaining_2026  WHERE season_id = 1)     AS remaining_rows,
    (SELECT COUNT(*) FROM v_draft_team_board_2026 WHERE season_id = 1)     AS team_board_rows;
