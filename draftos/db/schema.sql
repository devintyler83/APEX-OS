PRAGMA foreign_keys = ON;

-- ===== meta =====
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
  notes TEXT
  is_active INTEGER NOT NULL DEFAULT 1,
  superseded_by_source_id INTEGER,
);

CREATE TABLE IF NOT EXISTS seasons (
  season_id INTEGER PRIMARY KEY,
  draft_year INTEGER NOT NULL UNIQUE, -- 2026
  created_at TEXT NOT NULL
);

-- ===== canonical prospects =====
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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(season_id, full_name, school_canonical, position_group)
);

-- ===== aliasing + normalization dictionaries =====
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

-- ===== raw source rows (staging-like but persisted) =====
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

-- ===== mapping: source player -> canonical prospect =====
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

-- ===== rankings from sources =====
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

-- ===== measurables/testing =====
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

-- ===== production (simple v1) =====
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

-- ===== RAS =====
CREATE TABLE IF NOT EXISTS ras (
  ras_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL UNIQUE,
  ras_total REAL,
  ras_json TEXT,
  source_id INTEGER,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ===== tags + archetypes + notes =====
CREATE TABLE IF NOT EXISTS tags (
  tag_id INTEGER PRIMARY KEY,
  tag TEXT NOT NULL UNIQUE,           -- "Big Slot", "Press Man", "Wide-9"
  tag_type TEXT NOT NULL              -- archetype, trait, flag
);

CREATE TABLE IF NOT EXISTS prospect_tags (
  prospect_id INTEGER NOT NULL,
  tag_id INTEGER NOT NULL,
  weight REAL DEFAULT 1.0,            -- optional strength
  notes TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY(prospect_id, tag_id),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id),
  FOREIGN KEY(tag_id) REFERENCES tags(tag_id)
);

CREATE TABLE IF NOT EXISTS notes (
  note_id INTEGER PRIMARY KEY,
  prospect_id INTEGER NOT NULL,
  note_type TEXT NOT NULL,            -- scout, medical, character, scheme
  note TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ===== your model definitions + outputs =====
CREATE TABLE IF NOT EXISTS models (
  model_id INTEGER PRIMARY KEY,
  season_id INTEGER NOT NULL,
  model_key TEXT NOT NULL,            -- "v1_default", "devin_v1"
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
  tier TEXT,                          -- Elite/Strong/Playable/Watch
  reasons_json TEXT,                  -- compact reason codes
  explain_json TEXT,                  -- feature contributions
  created_at TEXT NOT NULL,
  UNIQUE(model_id, prospect_id),
  FOREIGN KEY(model_id) REFERENCES models(model_id),
  FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

-- ===== indexes =====
CREATE INDEX IF NOT EXISTS idx_prospects_season_pos ON prospects(season_id, position_group);
CREATE INDEX IF NOT EXISTS idx_rankings_source_date ON source_rankings(source_id, ranking_date);
CREATE INDEX IF NOT EXISTS idx_map_prospect ON source_player_map(prospect_id);