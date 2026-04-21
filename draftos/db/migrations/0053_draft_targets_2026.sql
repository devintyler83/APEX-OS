-- Migration 0053: consensus_reconciliation_2026 table + v_draft_targets_2026 view
-- Additive only. No destructive changes to existing tables or views.
-- Season-scoped to season_id=1 (2026 draft year) throughout.
--
-- Adds:
--   consensus_reconciliation_2026      — season-scoped recon store (INSERT OR REPLACE target)
--   idx_recon_season_bucket            — filter index for recon_bucket queries
--   v_draft_targets_2026               — unified targets view (fit × divergence × reconciliation)
--
-- Dependency chain (all must exist before view creation):
--   v_team_prospect_fit_signal_2026    — Migration 0051/0052
--   divergence_flags                   — core schema
--   consensus_reconciliation_2026      — created in this migration

-- ──────────────────────────────────────────────────────────
-- Table: consensus_reconciliation_2026
-- ──────────────────────────────────────────────────────────
-- Populated by reconcile_consensus_vs_jfosterfilm_2026.py --apply 1.
-- One row per prospect per season. INSERT OR REPLACE — idempotent.
--
-- recon_bucket values:
--   HIGH         : |divergence| >= 25 AND APEX ranks prospect HIGHER (lower rank number)
--                  i.e. divergence_25 (apex_ovr_rank - combined) < -24
--   LOW          : |divergence| >= 25 AND APEX ranks prospect LOWER
--                  i.e. divergence_25 > 24
--   NONE         : |divergence| < 25 AND has jFoster CON coverage (small signal)
--   COVERAGE_GAP : no jFoster CON rank available for this prospect
--
-- divergence_delta sign convention matches divergence_flags.divergence_rank_delta:
--   positive = APEX bullish (APEX assigns a better rank than engine consensus)
--   divergence_delta = consensus_rank - apex_rank

CREATE TABLE IF NOT EXISTS consensus_reconciliation_2026 (
    prospect_id      INTEGER NOT NULL,
    season_id        INTEGER NOT NULL DEFAULT 1,
    has_jfoster_con  INTEGER NOT NULL DEFAULT 0 CHECK (has_jfoster_con IN (0, 1)),
    jfoster_con_rank INTEGER,
    apex_rank        INTEGER NOT NULL,
    consensus_rank   INTEGER NOT NULL,
    divergence_delta INTEGER NOT NULL,
    recon_bucket     TEXT    NOT NULL
                     CHECK (recon_bucket IN ('HIGH', 'LOW', 'NONE', 'COVERAGE_GAP')),
    notes            TEXT,
    PRIMARY KEY (prospect_id, season_id)
);

CREATE INDEX IF NOT EXISTS idx_recon_season_bucket
    ON consensus_reconciliation_2026 (season_id, recon_bucket);

-- ──────────────────────────────────────────────────────────
-- View: v_draft_targets_2026
-- ──────────────────────────────────────────────────────────
-- One row per (prospect_id, team_id) where:
--   season_id = 1 (baked in from signal view)
--   fit_tier IN ('IDEAL','STRONG','VIABLE')
--
-- Column notes:
--   divergence_flag     : legacy 'APEX LOW'/'APEX HIGH' (with spaces) normalized to
--                         underscore form so callers can use a single string literal.
--   divergence_magnitude: sourced from divergence_flags.divergence_mag (MAJOR/MODERATE/MINOR).
--   apex_rank           : from consensus_reconciliation_2026 when populated; falls back
--                         to (consensus_ovr_rank - divergence_rank_delta) for the 11
--                         legacy NULL-delta rows.
--   recon_bucket        : COALESCE to 'COVERAGE_GAP' when no recon row exists (pre-seed).
--
-- Run reconcile_consensus_vs_jfosterfilm_2026.py --apply 1 to populate recon table.

CREATE VIEW IF NOT EXISTS v_draft_targets_2026 AS
SELECT
    -- identity
    sig.prospect_id,
    sig.team_id,
    sig.season_id,
    -- fit fields
    sig.fit_score,
    sig.fit_tier,
    sig.fit_band,
    sig.deployment_fit,
    sig.pick_fit,
    sig.fm_risk_score,
    sig.verdict,
    sig.why_for,
    sig.why_against,
    sig.confidence,
    sig.fit_explanation,
    -- prospect attributes (surfaced from signal view)
    sig.capital_adjusted,
    sig.failure_mode_primary,
    sig.failure_mode_secondary,
    -- team context (surfaced from signal view)
    sig.team_primary_needs,
    sig.team_secondary_needs,
    sig.coverage_bias,
    sig.primary_defense_family,
    -- divergence fields (normalized)
    CAST(df.consensus_ovr_rank AS INTEGER)              AS consensus_rank,
    COALESCE(
        recon.apex_rank,
        CASE WHEN df.divergence_rank_delta IS NOT NULL
             THEN CAST(df.consensus_ovr_rank - df.divergence_rank_delta AS INTEGER)
             ELSE NULL
        END
    )                                                   AS apex_rank,
    df.divergence_rank_delta                            AS divergence_delta,
    CASE df.divergence_flag
        WHEN 'APEX HIGH' THEN 'APEX_HIGH'
        WHEN 'APEX LOW'  THEN 'APEX_LOW'
        ELSE                  df.divergence_flag
    END                                                 AS divergence_flag,
    df.divergence_mag                                   AS divergence_magnitude,
    -- reconciliation fields
    recon.jfoster_con_rank,
    COALESCE(recon.recon_bucket, 'COVERAGE_GAP')        AS recon_bucket
FROM v_team_prospect_fit_signal_2026 sig
JOIN divergence_flags df
  ON  df.prospect_id   = sig.prospect_id
  AND df.season_id     = sig.season_id
  AND df.model_version = 'apex_v2.3'
LEFT JOIN consensus_reconciliation_2026 recon
  ON  recon.prospect_id = sig.prospect_id
  AND recon.season_id   = sig.season_id;

-- ──────────────────────────────────────────────────────────
-- Verify
-- ──────────────────────────────────────────────────────────

SELECT
    'migration_0053_applied'                                              AS status,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'table' AND name = 'consensus_reconciliation_2026')    AS recon_table_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'index' AND name = 'idx_recon_season_bucket')          AS recon_idx_present,
    (SELECT COUNT(*) FROM sqlite_master
     WHERE type = 'view'  AND name = 'v_draft_targets_2026')             AS view_present,
    (SELECT COUNT(*) FROM v_draft_targets_2026)                          AS view_rows_pre_seed,
    (SELECT COUNT(DISTINCT divergence_flag) FROM v_draft_targets_2026)   AS distinct_div_flags;
