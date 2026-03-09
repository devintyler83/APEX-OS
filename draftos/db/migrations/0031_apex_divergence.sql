-- ============================================================
-- DraftOS Migration 002 — APEX + Divergence Layer
-- File: C:\DraftOS\draftos\db\migrations\002_apex_divergence.sql
-- Apply via: python migrate.py
-- Additive only — does not touch existing tables
-- ============================================================

PRAGMA foreign_keys = ON;

-- ── CONSENSUS RANKINGS ──────────────────────────────────────
-- Computed from source_rankings across all active sources
CREATE TABLE IF NOT EXISTS consensus_rankings (
  consensus_id      INTEGER PRIMARY KEY,
  prospect_id       INTEGER NOT NULL,
  season_id         INTEGER NOT NULL DEFAULT 1,
  computed_at       TEXT NOT NULL DEFAULT (datetime('now')),
  -- Coverage
  source_count      INTEGER NOT NULL DEFAULT 0,
  coverage_pct      REAL NOT NULL DEFAULT 0.0,
  -- Overall rank outputs
  avg_ovr_rank      REAL,
  median_ovr_rank   REAL,
  min_ovr_rank      INTEGER,
  max_ovr_rank      INTEGER,
  rank_std_dev      REAL,
  -- Position rank outputs
  avg_pos_rank      REAL,
  median_pos_rank   REAL,
  -- Round projection (derived: rank 1-32 = R1, 33-64 = R2, etc.)
  median_draft_round REAL,
  consensus_tier    TEXT,  -- 'R1 Early','R1 Mid','R1 Late','Day 2','Day 3','UDFA'
  UNIQUE(prospect_id, season_id),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ── APEX SCORES ─────────────────────────────────────────────
-- One row per prospect per model version
-- model_version is the FK anchor (stored as string for readability)
CREATE TABLE IF NOT EXISTS apex_scores (
  apex_id            INTEGER PRIMARY KEY,
  prospect_id        INTEGER NOT NULL,
  season_id          INTEGER NOT NULL DEFAULT 1,
  model_version      TEXT NOT NULL DEFAULT 'apex_v2.2',
  scored_at          TEXT NOT NULL DEFAULT (datetime('now')),
  -- Trait vectors (1-10 input scores, post-PAA adjustments applied)
  v_processing       REAL,
  v_athleticism      REAL,
  v_scheme_vers      REAL,
  v_comp_tough       REAL,
  v_character        REAL,
  v_dev_traj         REAL,
  v_production       REAL,
  v_injury           REAL,
  -- Character sub-components
  c1_public_record   REAL,
  c2_motivation      REAL,
  c3_psych_profile   REAL,
  -- APEX engine outputs
  matched_archetype  TEXT,   -- e.g. 'ILB-1_GreenDot'
  archetype_gap      REAL,   -- pts between rank-1 and rank-2 archetype score
  gap_label          TEXT,   -- CLEAN / SOLID / TWEENER / COMPRESSION / NO_FIT
  raw_score          REAL,   -- pre-PVC composite
  pvc                REAL,   -- positional value coefficient applied
  apex_composite     REAL,   -- final APEX Score (raw × PVC)
  apex_tier          TEXT,   -- ELITE / APEX / SOLID / DEVELOPMENTAL / ARCHETYPE MISS
  apex_pos_rank      INTEGER, -- rank within position group on this board
  -- Capital
  capital_base       TEXT,   -- 'R1 Picks 11-32'
  capital_adjusted   TEXT,   -- after Schwesinger / Smith / Tweener modifiers
  eval_confidence    TEXT,   -- Tier A / B / C
  -- Tags (comma-separated for simplicity; queryable via LIKE)
  tags               TEXT,   -- 'CRUSH,Walk-On Flag,Smith Rule,Two-Way Premium'
  -- Override fields
  override_arch      TEXT,   -- analyst-specified archetype override
  override_delta     REAL,   -- score delta applied
  override_rationale TEXT,   -- mandatory one-sentence explanation
  -- Boolean flags
  schwesinger_full   INTEGER NOT NULL DEFAULT 0,
  schwesinger_half   INTEGER NOT NULL DEFAULT 0,
  smith_rule         INTEGER NOT NULL DEFAULT 0,
  -- Extended scores (populated when available)
  ras_score          REAL,
  ath_score          REAL,
  size_score         REAL,
  speed_score        REAL,
  acc_score          REAL,
  agi_score          REAL,
  iq_score           REAL,
  composite_score    REAL,
  gem_score          REAL,
  nextgen_grade      REAL,
  -- Analyst notes
  strengths          TEXT,
  red_flags          TEXT,
  UNIQUE(prospect_id, season_id, model_version),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ── DIVERGENCE FLAGS ────────────────────────────────────────
-- The featured output: where APEX disagrees with consensus
CREATE TABLE IF NOT EXISTS divergence_flags (
  div_id             INTEGER PRIMARY KEY,
  prospect_id        INTEGER NOT NULL,
  season_id          INTEGER NOT NULL DEFAULT 1,
  computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
  model_version      TEXT NOT NULL DEFAULT 'apex_v2.2',
  -- Scores at time of computation
  apex_composite     REAL NOT NULL,
  apex_tier          TEXT NOT NULL,
  apex_capital       TEXT,
  consensus_ovr_rank REAL,           -- median_ovr_rank from consensus_rankings
  consensus_tier     TEXT,
  consensus_round    REAL,           -- median_draft_round
  -- Divergence metrics
  divergence_score   REAL,           -- apex_composite - consensus_implied_score
  rounds_diff        REAL,           -- apex round projection minus consensus round
  divergence_flag    TEXT NOT NULL,  -- 'APEX HIGH' / 'APEX LOW' / 'ALIGNED'
  divergence_mag     TEXT,           -- 'MAJOR' / 'MODERATE' / 'MINOR'
  apex_favors        INTEGER,        -- +1 APEX higher, -1 APEX lower, 0 aligned
  UNIQUE(prospect_id, season_id, model_version),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ── OVERRIDE LOG ────────────────────────────────────────────
-- Full audit trail, every override recorded
CREATE TABLE IF NOT EXISTS override_log (
  log_id          INTEGER PRIMARY KEY,
  prospect_id     INTEGER NOT NULL,
  season_id       INTEGER NOT NULL DEFAULT 1,
  model_version   TEXT NOT NULL DEFAULT 'apex_v2.2',
  override_type   TEXT NOT NULL,  -- 'ARCH' / 'SCORE' / 'CAPITAL'
  field_changed   TEXT NOT NULL,
  old_value       TEXT,
  new_value       TEXT,
  magnitude       REAL,           -- numeric delta for SCORE overrides
  rationale       TEXT NOT NULL,  -- mandatory
  applied_at      TEXT NOT NULL DEFAULT (datetime('now')),
  applied_by      TEXT NOT NULL DEFAULT 'analyst',
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ── BOARD SNAPSHOTS ─────────────────────────────────────────
-- Immutable frozen board states (Pre-Combine, Post-Combine, Pre-Draft, Post-Draft)
CREATE TABLE IF NOT EXISTS board_snapshots (
  snapshot_id       INTEGER PRIMARY KEY,
  season_id         INTEGER NOT NULL DEFAULT 1,
  snapshot_date     TEXT NOT NULL,
  snapshot_label    TEXT NOT NULL,  -- 'Pre-Draft', 'Post-Draft', etc.
  prospect_id       INTEGER NOT NULL,
  apex_composite    REAL,
  apex_tier         TEXT,
  apex_capital      TEXT,
  consensus_rank    REAL,
  consensus_tier    TEXT,
  divergence_score  REAL,
  divergence_flag   TEXT,
  tags              TEXT,
  -- Post-draft audit fields (populated after draft day)
  actual_pick       INTEGER,
  actual_round      INTEGER,
  actual_team       TEXT,
  UNIQUE(snapshot_date, prospect_id),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ── VIEWS ───────────────────────────────────────────────────

-- Full board: every prospect with consensus + APEX + divergence in one row
CREATE VIEW IF NOT EXISTS v_board AS
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
LEFT JOIN apex_scores     a ON a.prospect_id = p.prospect_id AND a.model_version = 'apex_v2.2'
LEFT JOIN consensus_rankings c ON c.prospect_id = p.prospect_id
LEFT JOIN divergence_flags   d ON d.prospect_id = p.prospect_id AND d.model_version = 'apex_v2.2'
WHERE p.season_id = 1
ORDER BY a.apex_composite DESC NULLS LAST;

-- Divergence board: only where APEX and consensus disagree, sorted by magnitude
CREATE VIEW IF NOT EXISTS v_divergence_board AS
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
JOIN apex_scores        a ON a.prospect_id = p.prospect_id AND a.model_version = 'apex_v2.2'
JOIN consensus_rankings c ON c.prospect_id = p.prospect_id
JOIN divergence_flags   d ON d.prospect_id = p.prospect_id AND d.model_version = 'apex_v2.2'
WHERE d.divergence_flag != 'ALIGNED'
  AND p.season_id = 1
ORDER BY ABS(d.divergence_score) DESC;

-- Position board: filterable by pos, ordered by APEX pos rank
CREATE VIEW IF NOT EXISTS v_position_board AS
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
JOIN apex_scores        a ON a.prospect_id = p.prospect_id AND a.model_version = 'apex_v2.2'
JOIN consensus_rankings c ON c.prospect_id = p.prospect_id
LEFT JOIN divergence_flags d ON d.prospect_id = p.prospect_id AND d.model_version = 'apex_v2.2'
WHERE p.season_id = 1
ORDER BY p.position_group, a.apex_pos_rank NULLS LAST;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_apex_prospect     ON apex_scores(prospect_id, model_version);
CREATE INDEX IF NOT EXISTS idx_consensus_prospect ON consensus_rankings(prospect_id);
CREATE INDEX IF NOT EXISTS idx_divergence_prospect ON divergence_flags(prospect_id, model_version);
CREATE INDEX IF NOT EXISTS idx_snapshots_date     ON board_snapshots(snapshot_date, prospect_id);
CREATE INDEX IF NOT EXISTS idx_override_prospect  ON override_log(prospect_id);