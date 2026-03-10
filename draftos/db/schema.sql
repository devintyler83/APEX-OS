PRAGMA foreign_keys = ON;

-- =============================================================================
-- DraftOS DATABASE SCHEMA — UNIFIED
-- =============================================================================
-- 11-layer architecture for the 2026 NFL Draft evaluation system.
--
-- Layer 1:  Meta & Infrastructure (migrations, sources, seasons)
-- Layer 2:  Canonical Prospects (+ board_status for draft night tracking)
-- Layer 3:  Aliasing & Normalization Dictionaries
-- Layer 4:  Raw Source Ingestion (staging)
-- Layer 5:  Source-to-Prospect Mapping
-- Layer 6:  Rankings from Sources
-- Layer 7:  Measurables, Testing, Production, RAS
-- Layer 8:  Notes (scout, medical, character, scheme)
-- Layer 9:  Models & Model Outputs (APEX, consensus, future models)
-- Layer 10: Tagging System (system + analyst tags, recommendations, audit)
-- Layer 11: Draft Results & Board State (draft night + post-draft audit)
-- =============================================================================


-- =============================================================================
-- LAYER 1: META & INFRASTRUCTURE
-- =============================================================================

CREATE TABLE IF NOT EXISTS meta_migrations (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  source_id INTEGER PRIMARY KEY,
  source_name TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL,          -- ranking, stats, combine, notes
  url TEXT,
  notes TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  superseded_by_source_id INTEGER
);

CREATE TABLE IF NOT EXISTS seasons (
  season_id INTEGER PRIMARY KEY,
  draft_year INTEGER NOT NULL UNIQUE, -- 2026
  created_at TEXT NOT NULL
);


-- =============================================================================
-- LAYER 2: CANONICAL PROSPECTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS prospects (
  prospect_id INTEGER PRIMARY KEY,
  season_id INTEGER NOT NULL,
  prospect_key TEXT NOT NULL UNIQUE,  -- stable deterministic key
  first_name TEXT,
  last_name TEXT,
  full_name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  suffix TEXT,                        -- Jr, III, etc
  position_group TEXT NOT NULL,       -- QB, RB, WR, TE, OL, DL, EDGE, LB, CB, S, ST
  position_raw TEXT,                  -- optional canonical raw
  school_canonical TEXT NOT NULL,
  height_in INTEGER,                  -- inches
  weight_lb INTEGER,
  hand_in REAL,
  arm_in REAL,
  wing_in REAL,
  birthdate TEXT,
  class_year INTEGER,                 -- if known (draft class)
  experience TEXT,                    -- FR/SO/JR/SR/RS etc
  board_status TEXT NOT NULL DEFAULT 'available',  -- available | drafted | traded | withdrawn
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(season_id, full_name, school_canonical, position_group)
);


-- =============================================================================
-- LAYER 3: ALIASING & NORMALIZATION DICTIONARIES
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_aliases (
  alias_id INTEGER PRIMARY KEY,
  school_alias TEXT NOT NULL UNIQUE,
  school_canonical TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS name_aliases (
  alias_id INTEGER PRIMARY KEY,
  name_alias TEXT NOT NULL UNIQUE,    -- e.g. "DJ" -> "DeeJay" (optional)
  name_canonical TEXT NOT NULL
);


-- =============================================================================
-- LAYER 4: RAW SOURCE INGESTION (staging-like but persisted)
-- =============================================================================

CREATE TABLE IF NOT EXISTS source_players (
  source_player_id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL,
  season_id INTEGER NOT NULL,
  source_player_key TEXT NOT NULL,    -- stable key inside that source file (or hash of row)
  raw_full_name TEXT NOT NULL,
  raw_school TEXT,
  raw_position TEXT,
  raw_class_year INTEGER,
  raw_json TEXT,                      -- store extra columns as json string
  ingested_at TEXT NOT NULL,
  UNIQUE(source_id, season_id, source_player_key)
);


-- =============================================================================
-- LAYER 5: SOURCE-TO-PROSPECT MAPPING
-- =============================================================================

CREATE TABLE IF NOT EXISTS source_player_map (
  map_id INTEGER PRIMARY KEY,
  source_player_id INTEGER NOT NULL UNIQUE,
  prospect_id INTEGER NOT NULL,
  match_method TEXT NOT NULL,         -- exact, fuzzy, manual, rule
  match_score REAL NOT NULL,          -- 0.00 - 1.00
  match_notes TEXT,
  reviewed INTEGER NOT NULL DEFAULT 0,
  reviewed_by TEXT,
  reviewed_at TEXT,
  FOREIGN KEY(source_player_id) REFERENCES source_players(source_player_id),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);


-- =============================================================================
-- LAYER 6: RANKINGS FROM SOURCES
-- =============================================================================

CREATE TABLE IF NOT EXISTS source_rankings (
  ranking_id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL,
  season_id INTEGER NOT NULL,
  source_player_id INTEGER NOT NULL,
  overall_rank INTEGER,
  position_rank INTEGER,
  position_raw TEXT,
  grade REAL,
  tier TEXT,
  ranking_date TEXT,                  -- as provided, else ingested date
  ingested_at TEXT NOT NULL,
  UNIQUE(source_id, season_id, source_player_id, ranking_date),
  FOREIGN KEY(source_player_id) REFERENCES source_players(source_player_id)
);


-- =============================================================================
-- LAYER 7: MEASURABLES, TESTING, PRODUCTION, RAS
-- =============================================================================

CREATE TABLE IF NOT EXISTS measurables (
  meas_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL UNIQUE,
  height_in INTEGER,
  weight_lb INTEGER,
  hand_in REAL,
  arm_in REAL,
  wing_in REAL,
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

CREATE TABLE IF NOT EXISTS testing (
  test_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,           -- combine, proday
  forty REAL,
  split10 REAL,
  shuttle REAL,
  cone3 REAL,
  vert REAL,
  broad REAL,
  bench INTEGER,
  event_date TEXT,
  source_id INTEGER,
  notes TEXT,
  UNIQUE(prospect_id, event_type, event_date),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

CREATE TABLE IF NOT EXISTS production (
  prod_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL,
  season INTEGER NOT NULL,            -- college season year
  games INTEGER,
  snaps INTEGER,
  raw_json TEXT,
  UNIQUE(prospect_id, season),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

CREATE TABLE IF NOT EXISTS ras (
  ras_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL UNIQUE,
  ras_total REAL,
  ras_json TEXT,
  source_id INTEGER,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);


-- =============================================================================
-- LAYER 8: NOTES
-- =============================================================================

CREATE TABLE IF NOT EXISTS notes (
  note_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL,
  note_type TEXT NOT NULL,            -- scout, medical, character, scheme
  note TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);


-- =============================================================================
-- LAYER 9: MODELS & MODEL OUTPUTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS models (
  model_id INTEGER PRIMARY KEY,
  season_id INTEGER NOT NULL,
  model_key TEXT NOT NULL,            -- "apex_v2", "consensus_v1"
  model_name TEXT NOT NULL,
  model_json TEXT NOT NULL,           -- weights, caps, toggles
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(season_id, model_key)
);

CREATE TABLE IF NOT EXISTS model_outputs (
  out_id INTEGER PRIMARY KEY,
  model_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,
  score REAL NOT NULL,                -- 0-100
  position_score REAL,
  tier TEXT,                          -- Elite/Apex/Solid/Developmental/Archetype Miss
  reasons_json TEXT,                  -- compact reason codes
  explain_json TEXT,                  -- feature contributions
  created_at TEXT NOT NULL,
  UNIQUE(model_id, prospect_id),
  FOREIGN KEY(model_id) REFERENCES models(model_id),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);


-- =============================================================================
-- LAYER 10: TAGGING SYSTEM
-- =============================================================================
-- Parallel signal layer: editorial intelligence alongside algorithmic scores.
--
-- Two tiers:
--   System tags  — auto-recommended based on trigger rules, user accepts/dismisses
--   Analyst tags — manual, conviction-driven, freeform
--
-- Multi-user ready: every tag attachment is per-user.
-- Full audit trail: soft deletes, history log, mandatory notes on high-stakes tags.
-- =============================================================================

-- ── 10a: Users ──────────────────────────────────────────────────────────────
-- Required for per-user tag ownership and multi-user boards.
-- For single-user mode, a default row (Devin) is seeded at init.

CREATE TABLE IF NOT EXISTS users (
  user_id       INTEGER PRIMARY KEY,
  username      TEXT    NOT NULL UNIQUE,
  display_name  TEXT    NOT NULL,
  role          TEXT    NOT NULL DEFAULT 'analyst',  -- admin | analyst | viewer
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO users (user_id, username, display_name, role)
VALUES (1, 'devin', 'Devin', 'admin');

-- ── 10b: Tag Definitions ────────────────────────────────────────────────────
-- Master catalog of all available tags. Defines meaning, color, category,
-- and whether the system can auto-recommend.
--
-- note_required = 1 forces rationale on attachment (enforced at app layer).

CREATE TABLE IF NOT EXISTS tag_definitions (
  tag_def_id        INTEGER PRIMARY KEY,
  tag_name          TEXT    NOT NULL UNIQUE,
  tag_category      TEXT    NOT NULL,  -- conviction | risk | informational | editorial
  tag_color         TEXT    NOT NULL,  -- green | red | blue | gold
  tag_source_type   TEXT    NOT NULL,  -- system | analyst | both
  description       TEXT    NOT NULL,  -- one-line explanation
  note_required     INTEGER NOT NULL DEFAULT 0,
  is_active         INTEGER NOT NULL DEFAULT 1,
  display_order     INTEGER NOT NULL DEFAULT 100,
  created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── 10c: Tag Trigger Rules ──────────────────────────────────────────────────
-- Automated logic for system-recommended tags. Each rule maps a tag to a
-- JSON-structured condition the engine evaluates after APEX runs or data updates.

CREATE TABLE IF NOT EXISTS tag_trigger_rules (
  rule_id           INTEGER PRIMARY KEY,
  tag_def_id        INTEGER NOT NULL,
  rule_name         TEXT    NOT NULL,
  rule_expression   TEXT    NOT NULL,  -- JSON: structured condition object
  rule_description  TEXT    NOT NULL,  -- human-readable explanation
  priority          INTEGER NOT NULL DEFAULT 1,
  is_active         INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (tag_def_id) REFERENCES tag_definitions(tag_def_id)
);

-- ── 10d: Prospect Tag Recommendations ───────────────────────────────────────
-- System-generated recommendations awaiting user action.
-- Accept → moves to prospect_tags with source = 'system'.
-- Dismiss → status updated, never deleted. Dismissed recs that were correct
-- are your most valuable post-draft learning signal.

CREATE TABLE IF NOT EXISTS prospect_tag_recommendations (
  rec_id            INTEGER PRIMARY KEY,
  prospect_id       INTEGER NOT NULL,
  tag_def_id        INTEGER NOT NULL,
  rule_id           INTEGER NOT NULL,
  status            TEXT    NOT NULL DEFAULT 'pending',  -- pending | accepted | dismissed
  triggered_value   TEXT,              -- actual value that fired the rule (e.g., "RAS: 9.4")
  actioned_by       INTEGER,
  actioned_at       TEXT,
  created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(prospect_id, tag_def_id, rule_id),
  FOREIGN KEY (prospect_id)  REFERENCES prospects(prospect_id),
  FOREIGN KEY (tag_def_id)   REFERENCES tag_definitions(tag_def_id),
  FOREIGN KEY (rule_id)      REFERENCES tag_trigger_rules(rule_id),
  FOREIGN KEY (actioned_by)  REFERENCES users(user_id)
);

-- ── 10e: Prospect Tags (authoritative attachment table) ─────────────────────
-- Every tag on every prospect for every user. Per-user ownership.
-- Soft delete only — tag removal history is a first-class audit artifact.

CREATE TABLE IF NOT EXISTS prospect_tags (
  ptag_id           INTEGER PRIMARY KEY,
  prospect_id       INTEGER NOT NULL,
  tag_def_id        INTEGER NOT NULL,
  user_id           INTEGER NOT NULL,
  source            TEXT    NOT NULL,  -- system | analyst
  note              TEXT,              -- rationale (mandatory for some tags, enforced at app layer)
  rec_id            INTEGER,           -- links to recommendation if system-sourced
  is_active         INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  deactivated_at    TEXT,
  UNIQUE(prospect_id, tag_def_id, user_id),
  FOREIGN KEY (prospect_id) REFERENCES prospects(prospect_id),
  FOREIGN KEY (tag_def_id)  REFERENCES tag_definitions(tag_def_id),
  FOREIGN KEY (user_id)     REFERENCES users(user_id),
  FOREIGN KEY (rec_id)      REFERENCES prospect_tag_recommendations(rec_id)
);

-- ── 10f: Prospect Tag History ───────────────────────────────────────────────
-- Full audit trail. Every tag state change is logged.

CREATE TABLE IF NOT EXISTS prospect_tag_history (
  history_id        INTEGER PRIMARY KEY,
  ptag_id           INTEGER NOT NULL,
  prospect_id       INTEGER NOT NULL,
  tag_def_id        INTEGER NOT NULL,
  user_id           INTEGER NOT NULL,
  action            TEXT    NOT NULL,  -- attached | deactivated | reactivated | note_edited
  old_note          TEXT,
  new_note          TEXT,
  timestamp         TEXT    NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (ptag_id)     REFERENCES prospect_tags(ptag_id),
  FOREIGN KEY (prospect_id) REFERENCES prospects(prospect_id),
  FOREIGN KEY (tag_def_id)  REFERENCES tag_definitions(tag_def_id),
  FOREIGN KEY (user_id)     REFERENCES users(user_id)
);


-- =============================================================================
-- LAYER 11: DRAFT RESULTS & BOARD STATE
-- =============================================================================
-- Two purposes:
--   1. Source of truth for actual draft outcomes — who went where, when.
--   2. Drives the board_status field on prospects (available → drafted).
--
-- On draft night: logging a draft_result row flips the prospect's
-- board_status to 'drafted'. The board UI greys out / moves the prospect
-- to the "off the board" section instantly.
--
-- Post-draft: this table is the foundation for the APEX audit loop —
-- comparing APEX tier predictions against actual pick positions and
-- eventual NFL career arcs (multi-year tracking).
-- =============================================================================

CREATE TABLE IF NOT EXISTS draft_results (
  result_id         INTEGER PRIMARY KEY,
  prospect_id       INTEGER NOT NULL,
  season_id         INTEGER NOT NULL,
  pick_overall      INTEGER NOT NULL,         -- overall pick number (1-262)
  pick_round        INTEGER NOT NULL,         -- round (1-7)
  pick_in_round     INTEGER NOT NULL,         -- pick within round
  team_name         TEXT    NOT NULL,         -- drafting team
  team_abbrev       TEXT,                     -- e.g. "KC", "NYG"
  was_trade_up      INTEGER NOT NULL DEFAULT 0,  -- 1 if team traded up for this pick
  trade_details     TEXT,                     -- JSON: assets exchanged if trade-up
  apex_score_at_draft   REAL,                 -- snapshot of APEX score at draft time
  apex_tier_at_draft    TEXT,                 -- snapshot of APEX tier at draft time
  consensus_rank_at_draft INTEGER,            -- snapshot of consensus rank at draft time
  divergence_at_draft   REAL,                 -- APEX - consensus delta, frozen at draft
  notes             TEXT,                     -- draft night observations
  career_outcome    TEXT,                     -- populated in multi-year audit: hit | starter | role_player | underperformed | bust
  career_outcome_updated_at TEXT,             -- when career_outcome was last assessed
  created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(prospect_id, season_id),
  UNIQUE(season_id, pick_overall),
  FOREIGN KEY (prospect_id) REFERENCES prospects(prospect_id),
  FOREIGN KEY (season_id)   REFERENCES seasons(season_id)
);


-- =============================================================================
-- INDEXES
-- =============================================================================

-- Layer 2: Prospects
CREATE INDEX IF NOT EXISTS idx_prospects_season_pos
  ON prospects(season_id, position_group);
CREATE INDEX IF NOT EXISTS idx_prospects_board_status
  ON prospects(season_id, board_status);

-- Layer 5: Source mapping
CREATE INDEX IF NOT EXISTS idx_map_prospect
  ON source_player_map(prospect_id);

-- Layer 6: Rankings
CREATE INDEX IF NOT EXISTS idx_rankings_source_date
  ON source_rankings(source_id, ranking_date);

-- Layer 10: Tags
CREATE INDEX IF NOT EXISTS idx_ptags_prospect_active
  ON prospect_tags(prospect_id, is_active);
CREATE INDEX IF NOT EXISTS idx_ptags_tag_active
  ON prospect_tags(tag_def_id, is_active);
CREATE INDEX IF NOT EXISTS idx_ptags_user_active
  ON prospect_tags(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_recs_prospect_status
  ON prospect_tag_recommendations(prospect_id, status);
CREATE INDEX IF NOT EXISTS idx_recs_status
  ON prospect_tag_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_tag_history_prospect
  ON prospect_tag_history(prospect_id);
CREATE INDEX IF NOT EXISTS idx_tag_history_ptag
  ON prospect_tag_history(ptag_id);

-- Layer 11: Draft Results
CREATE INDEX IF NOT EXISTS idx_draft_results_season
  ON draft_results(season_id, pick_overall);
CREATE INDEX IF NOT EXISTS idx_draft_results_team
  ON draft_results(team_abbrev, season_id);


-- =============================================================================
-- SEED DATA: TAG DEFINITIONS
-- =============================================================================
-- Tier 1 (System): Auto-recommended based on trigger rules.
-- Tier 2 (Analyst): Manual attachment, personal conviction.
-- Users can create additional custom tags at any time via INSERT.
-- =============================================================================

-- ── TIER 1: SYSTEM TAGS ─────────────────────────────────────────────────────

INSERT OR IGNORE INTO tag_definitions
  (tag_def_id, tag_name, tag_category, tag_color, tag_source_type, description, note_required, display_order)
VALUES
  -- Green: Positive system signals
  (1,  'Elite RAS',        'informational', 'green', 'system',
   'RAS score >= 9.0. Top-tier athletic testing profile relative to positional norms.', 0, 10),
  (2,  'Great RAS',        'informational', 'green', 'system',
   'RAS score 7.0-8.99. Above-average athletic testing profile.', 0, 11),

  -- Red: Risk system signals
  (3,  'Poor RAS',         'risk',          'red',   'system',
   'RAS score below 4.0. Athleticism floor gate at risk for most archetypes.', 0, 20),
  (4,  'Injury Flag',      'risk',          'red',   'system',
   'Injury & Durability trait vector <= 4/10. Elevated FM-4 Body Breakdown risk.', 0, 21),
  (5,  'Character Watch',  'risk',          'red',   'system',
   'Character composite < 5/10 or Smith Rule active. Elevated FM-5 risk.', 0, 22),

  -- Blue: Informational system signals
  (6,  'Compression Flag', 'informational', 'blue',  'system',
   'APEX gap between top two archetype matches < 5 pts. Tweener profile — no clean archetype fit.', 0, 30),
  (7,  'Divergence Alert', 'informational', 'blue',  'system',
   'APEX vs. consensus gap exceeds 15 pts in either direction. Highest-interest signal in the system.', 0, 31),
  (8,  'Scheme Dependent', 'informational', 'blue',  'system',
   'Scheme Versatility <= 4/10 or FM-2/FM-6 flagged as primary bust mode. Landing spot is the entire evaluation.', 0, 32),
  (9,  'Development Bet',  'informational', 'blue',  'system',
   'Tier 3 translation confidence + Dev Trajectory >= 7. Upside play with development-dependent timeline.', 0, 33),
  (10, 'Floor Play',       'informational', 'blue',  'system',
   'APEX Solid tier + all floor gates passed + Eval Confidence Tier A. Safe selection, low variance.', 0, 34);

-- ── TIER 2: ANALYST TAGS ────────────────────────────────────────────────────

INSERT OR IGNORE INTO tag_definitions
  (tag_def_id, tag_name, tag_category, tag_color, tag_source_type, description, note_required, display_order)
VALUES
  -- Green: Positive conviction
  (20, 'Want',              'conviction',    'green', 'analyst',
   'Personal conviction — would draft this player. Attach note explaining the thesis.', 0, 50),
  (21, 'Top 5 NextGen',    'conviction',    'green', 'analyst',
   'Personal high-conviction call: this prospect will be a top-5 player at his position within 3 years.', 1, 51),
  (22, 'Sleeper',           'conviction',    'green', 'analyst',
   'Undervalued by consensus. You see something the market is missing.', 1, 52),
  (23, 'Great Combine',     'editorial',     'green', 'analyst',
   'Pre-draft workout standout. Combine performance exceeded expectations.', 0, 53),
  (24, 'Great Pro Day',     'editorial',     'green', 'analyst',
   'Pro Day performance exceeded expectations or confirmed combine results.', 0, 54),

  -- Red: Risk conviction
  (30, 'Do Not Want',       'conviction',    'red',   'analyst',
   'Personal conviction — would not draft regardless of value. Note strongly recommended.', 1, 60),
  (31, 'Possible Bust',     'conviction',    'red',   'both',
   'Predictive conviction call: the failure mode is visible now and the market has not priced it in. MANDATORY: name the FM code and mechanism in note. Sharpest post-draft audit metric.', 1, 61),
  (32, 'Off-Field Concerns','risk',          'red',   'analyst',
   'Character intel beyond C1/C2/C3 scoring — incidents, reports, or patterns that inform risk.', 1, 62),
  (33, 'Injury Risk',       'risk',          'red',   'analyst',
   'Analyst-level injury concern beyond system Injury Flag. Specific to medical intel or film observation.', 0, 63),
  (34, 'Terrible RAS',      'risk',          'red',   'analyst',
   'Analyst emphasis on poor athletic testing. Stacks with system Poor RAS for double-flag visibility.', 0, 64),

  -- Gold: High-conviction editorial
  (40, 'Trade-Up Target',   'editorial',     'gold',  'analyst',
   'Worth moving up for. The value justifies spending additional draft capital.', 1, 70),
  (41, 'Film Favorite',     'editorial',     'gold',  'analyst',
   'Tape grades higher than production or consensus suggests. Your eyes see more than the numbers.', 1, 71),
  (42, 'Film Concern',      'editorial',     'gold',  'analyst',
   'Production or consensus grades higher than tape supports. The numbers are lying.', 1, 72),
  (43, 'Value Zone',        'editorial',     'gold',  'analyst',
   'Will be available where capital efficiency is highest. Optimal pick-value intersection.', 0, 73),

  -- Blue: Informational analyst
  (50, 'Scheme Fit',        'informational', 'blue',  'analyst',
   'Specific team/scheme landing spot match identified. Name the team and scheme in the note.', 1, 80),
  (51, 'Riser',             'informational', 'blue',  'both',
   'Stock trending up — APEX rescore crossed a tier boundary or consensus rank improved significantly.', 0, 81),
  (52, 'Faller',            'informational', 'blue',  'both',
   'Stock trending down — APEX rescore dropped a tier or consensus rank declined significantly.', 0, 82);


-- =============================================================================
-- SEED DATA: TAG TRIGGER RULES
-- =============================================================================
-- Each rule defines the condition that fires an auto-recommendation.
-- The scoring engine evaluates these after each APEX run or data update.
-- =============================================================================

INSERT OR IGNORE INTO tag_trigger_rules
  (rule_id, tag_def_id, rule_name, rule_expression, rule_description, priority)
VALUES
  -- RAS-based triggers
  (1,  1,  'elite_ras',
   '{"field": "ras_total", "operator": ">=", "value": 9.0}',
   'RAS total score at or above 9.0 — elite athletic profile.', 1),

  (2,  2,  'great_ras',
   '{"field": "ras_total", "operator": ">=", "value": 7.0, "and": {"field": "ras_total", "operator": "<", "value": 9.0}}',
   'RAS total score 7.0 to 8.99 — above-average athletic profile.', 2),

  (3,  3,  'poor_ras',
   '{"field": "ras_total", "operator": "<", "value": 4.0}',
   'RAS total score below 4.0 — athleticism floor gate at risk.', 1),

  -- APEX-derived triggers
  (4,  6,  'compression_flag',
   '{"field": "apex_archetype_gap", "operator": "<", "value": 5}',
   'Gap between best and second-best archetype match < 5 pts. Tweener signal.', 1),

  (5,  7,  'divergence_alert_positive',
   '{"field": "apex_consensus_divergence", "operator": ">", "value": 15}',
   'APEX 15+ pts above consensus implied score. Potential market undervaluation.', 1),

  (6,  7,  'divergence_alert_negative',
   '{"field": "apex_consensus_divergence", "operator": "<", "value": -15}',
   'APEX 15+ pts below consensus implied score. Potential market overvaluation.', 1),

  -- Trait vector triggers
  (7,  4,  'injury_flag',
   '{"field": "trait_injury_durability", "operator": "<=", "value": 4}',
   'Injury & Durability trait vector at or below 4/10. Elevated FM-4 risk.', 1),

  (8,  5,  'character_watch',
   '{"field": "trait_character_composite", "operator": "<", "value": 5}',
   'Character composite below 5/10 or Smith Rule active. Elevated FM-5 risk.', 1),

  (9,  8,  'scheme_dependent',
   '{"field": "trait_scheme_versatility", "operator": "<=", "value": 4}',
   'Scheme Versatility at or below 4/10. FM-2 or FM-6 primary bust mode likely.', 1),

  (10, 9,  'development_bet',
   '{"field": "translation_confidence", "operator": "=", "value": 3, "and": {"field": "trait_dev_trajectory", "operator": ">=", "value": 7}}',
   'Tier 3 translation confidence + Dev Trajectory >= 7. Development-dependent upside.', 2),

  (11, 10, 'floor_play',
   '{"field": "apex_tier", "operator": "=", "value": "Solid", "and": {"field": "floor_gates_passed", "operator": "=", "value": true, "and": {"field": "eval_confidence", "operator": "=", "value": "A"}}}',
   'APEX Solid + all floor gates passed + Eval Confidence A. Safe, low-variance pick.', 3),

  -- Possible Bust: system auto-recommends when market loves him, model doesn't
  (12, 31, 'possible_bust_system',
   '{"field": "apex_tier", "operator": "=", "value": "Archetype Miss", "and": {"field": "consensus_rank", "operator": "<=", "value": 64}}',
   'APEX Archetype Miss (below 40) + consensus Round 1-2. Classic bust setup.', 1),

  -- Riser / Faller state-change triggers
  (13, 51, 'riser_tier_jump',
   '{"field": "apex_tier_change", "operator": "=", "value": "up"}',
   'APEX rescore moved prospect up at least one tier.', 2),

  (14, 52, 'faller_tier_drop',
   '{"field": "apex_tier_change", "operator": "=", "value": "down"}',
   'APEX rescore moved prospect down at least one tier.', 2);


-- =============================================================================
-- REFERENCE QUERIES (not executed — documentation for UI/API layer)
-- =============================================================================

/*
-- Board view: all active tags on a single prospect
SELECT pt.ptag_id, td.tag_name, td.tag_color, td.tag_category,
       pt.source, pt.note, u.display_name AS tagged_by, pt.created_at
FROM prospect_tags pt
JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
JOIN users u ON u.user_id = pt.user_id
WHERE pt.prospect_id = ? AND pt.is_active = 1
ORDER BY td.display_order;

-- Filter view: all prospects with a specific tag
SELECT p.full_name, p.position_group, p.school_canonical, pt.note, pt.created_at
FROM prospect_tags pt
JOIN prospects p ON p.prospect_id = pt.prospect_id
JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
WHERE td.tag_name = 'Want' AND pt.user_id = ? AND pt.is_active = 1
ORDER BY pt.created_at DESC;

-- Stacked filter: APEX >= 70 + Want + Elite RAS + NOT Injury Risk
SELECT p.full_name, p.position_group, mo.score AS apex_score, mo.tier AS apex_tier
FROM prospects p
JOIN model_outputs mo ON mo.prospect_id = p.prospect_id
WHERE mo.score >= 70
  AND EXISTS (SELECT 1 FROM prospect_tags pt JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
              WHERE pt.prospect_id = p.prospect_id AND td.tag_name = 'Want'
                AND pt.user_id = ? AND pt.is_active = 1)
  AND EXISTS (SELECT 1 FROM prospect_tags pt JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
              WHERE pt.prospect_id = p.prospect_id AND td.tag_name = 'Elite RAS'
                AND pt.is_active = 1)
  AND NOT EXISTS (SELECT 1 FROM prospect_tags pt JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
                  WHERE pt.prospect_id = p.prospect_id AND td.tag_name = 'Injury Risk'
                    AND pt.is_active = 1)
ORDER BY mo.score DESC;

-- Recommendation inbox: pending system tag recommendations
SELECT r.rec_id, p.full_name, p.position_group, td.tag_name, td.tag_color,
       td.description, r.triggered_value, tr.rule_description, r.created_at
FROM prospect_tag_recommendations r
JOIN prospects p ON p.prospect_id = r.prospect_id
JOIN tag_definitions td ON td.tag_def_id = r.tag_def_id
JOIN tag_trigger_rules tr ON tr.rule_id = r.rule_id
WHERE r.status = 'pending'
ORDER BY td.display_order, r.created_at DESC;

-- Tag conflict detection: positive conviction vs. risk signal on same prospect
SELECT p.full_name, p.position_group,
       GROUP_CONCAT(td.tag_name, ' | ') AS conflicting_tags
FROM prospect_tags pt
JOIN prospects p ON p.prospect_id = pt.prospect_id
JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
WHERE pt.is_active = 1 AND pt.user_id = ?
  AND td.tag_name IN ('Want', 'Top 5 NextGen', 'Trade-Up Target')
  AND pt.prospect_id IN (
      SELECT pt2.prospect_id FROM prospect_tags pt2
      JOIN tag_definitions td2 ON td2.tag_def_id = pt2.tag_def_id
      WHERE pt2.is_active = 1
        AND td2.tag_name IN ('Character Watch', 'Possible Bust', 'Injury Flag', 'Do Not Want'))
GROUP BY p.prospect_id;

-- Draft Night Mode: compact board — AVAILABLE prospects only, with tag shorthand
SELECT p.full_name, p.position_group, p.board_status,
       mo.score AS apex_score, mo.tier AS apex_tier,
       GROUP_CONCAT(
         CASE td.tag_color WHEN 'green' THEN '🟢 ' WHEN 'red' THEN '🔴 '
              WHEN 'blue' THEN '🔵 ' WHEN 'gold' THEN '🟡 ' END || td.tag_name,
         '  •  ') AS active_tags
FROM prospects p
JOIN model_outputs mo ON mo.prospect_id = p.prospect_id
LEFT JOIN prospect_tags pt ON pt.prospect_id = p.prospect_id
  AND pt.is_active = 1 AND pt.user_id = ?
LEFT JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
WHERE p.season_id = ? AND p.board_status = 'available'
GROUP BY p.prospect_id
ORDER BY mo.score DESC;

-- Draft Night: toggle prospect to drafted (run when pick is announced)
-- UPDATE prospects SET board_status = 'drafted', updated_at = datetime('now')
-- WHERE prospect_id = ?;

-- Draft Night: log the pick (fires alongside the board_status update)
-- INSERT INTO draft_results
--   (prospect_id, season_id, pick_overall, pick_round, pick_in_round,
--    team_name, team_abbrev, apex_score_at_draft, apex_tier_at_draft,
--    consensus_rank_at_draft, divergence_at_draft)
-- SELECT ?, ?, ?, ?, ?, ?, ?,
--        mo.score, mo.tier, ?, ?
-- FROM model_outputs mo
-- JOIN models m ON m.model_id = mo.model_id
-- WHERE mo.prospect_id = ? AND m.model_key = 'apex_v2';

-- Draft Night: who's been picked so far (live draft tracker)
SELECT dr.pick_overall, dr.pick_round, dr.pick_in_round,
       dr.team_abbrev, p.full_name, p.position_group,
       dr.apex_tier_at_draft, dr.divergence_at_draft,
       CASE WHEN dr.divergence_at_draft > 15 THEN 'APEX >> CONSENSUS'
            WHEN dr.divergence_at_draft < -15 THEN 'APEX << CONSENSUS'
            ELSE 'ALIGNED' END AS divergence_signal
FROM draft_results dr
JOIN prospects p ON p.prospect_id = dr.prospect_id
WHERE dr.season_id = ?
ORDER BY dr.pick_overall;

-- Post-draft audit: Possible Bust accuracy rate
SELECT p.full_name, pt.note AS bust_thesis,
       dr.pick_overall, dr.team_abbrev,
       dr.apex_tier_at_draft, dr.divergence_at_draft,
       dr.career_outcome,
       CASE WHEN dr.career_outcome IN ('bust', 'underperformed')
            THEN 'CORRECT' ELSE 'INCORRECT' END AS bust_call_accuracy
FROM prospect_tags pt
JOIN prospects p ON p.prospect_id = pt.prospect_id
JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
LEFT JOIN draft_results dr ON dr.prospect_id = pt.prospect_id
WHERE td.tag_name = 'Possible Bust' AND pt.user_id = ?
ORDER BY dr.pick_overall;

-- Post-draft audit: APEX accuracy by tier
SELECT dr.apex_tier_at_draft,
       COUNT(*) AS total_picks,
       SUM(CASE WHEN dr.career_outcome IN ('hit', 'starter') THEN 1 ELSE 0 END) AS hits,
       ROUND(100.0 * SUM(CASE WHEN dr.career_outcome IN ('hit', 'starter') THEN 1 ELSE 0 END) / COUNT(*), 1) AS hit_rate_pct,
       AVG(dr.divergence_at_draft) AS avg_divergence
FROM draft_results dr
WHERE dr.season_id = ? AND dr.career_outcome IS NOT NULL
GROUP BY dr.apex_tier_at_draft
ORDER BY hit_rate_pct DESC;
*/
