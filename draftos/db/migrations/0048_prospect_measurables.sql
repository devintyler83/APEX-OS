-- Migration 0048: prospect_measurables table
-- Session 69 | 2026-03-28
-- Stores structured measurables from jfosterfilm_2026.csv expanded column set.
-- One row per prospect per season. All measurable columns nullable --
-- partial data is valid (a prospect may have measurables but no pro day agility).

CREATE TABLE IF NOT EXISTS prospect_measurables (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id     INTEGER NOT NULL REFERENCES prospects(prospect_id),
    season_id       INTEGER NOT NULL DEFAULT 1,

    -- jfosterfilm source columns
    jff_ovr_rank    INTEGER,   -- Column E: jfosterfilm overall rank
    jff_pos_rank    INTEGER,   -- Column F: jfosterfilm position rank
    consensus_rank  INTEGER,   -- Column G: consensus rank (700+ player coverage)

    -- Bio measurables
    age             REAL,
    height_in       INTEGER,   -- stored as raw inches (e.g. 73 = 6'1")
    weight_lbs      INTEGER,

    -- Arm/wing/hand (inches, decimal)
    arm_length      REAL,
    wingspan        REAL,
    hand_size       REAL,

    -- Speed and agility drills
    ten_yard_split  REAL,      -- 10Y
    forty_yard_dash REAL,      -- 40Y
    shuttle         REAL,
    three_cone      REAL,      -- 3Cone

    -- Explosiveness
    vertical_jump   REAL,      -- VRT (inches)
    broad_jump      INTEGER,   -- BRD (inches)

    -- jfosterfilm composite scores (0-100 scale assumed -- verify at ingest)
    prod_score      REAL,      -- PROD
    ath_score       REAL,      -- ATH
    size_score      REAL,      -- SIZE
    speed_score     REAL,      -- SPEED
    acc_score       REAL,      -- ACC
    agi_score       REAL,      -- AGI

    -- Metadata
    source          TEXT NOT NULL DEFAULT 'jfosterfilm_2026',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(prospect_id, season_id)
);

CREATE INDEX IF NOT EXISTS idx_pm_prospect
    ON prospect_measurables(prospect_id);
CREATE INDEX IF NOT EXISTS idx_pm_season
    ON prospect_measurables(season_id);
CREATE INDEX IF NOT EXISTS idx_pm_consensus
    ON prospect_measurables(consensus_rank);

INSERT OR IGNORE INTO meta_migrations(name, applied_at)
VALUES (
    '0048_prospect_measurables',
    CURRENT_TIMESTAMP
);
