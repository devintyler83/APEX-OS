-- ============================================================
-- DraftOS Migration 0044 — Historical Comp Database
-- File: draftos/db/migrations/0044_historical_comps.sql
-- Apply via: python migrate.py
-- Additive only — no drops, no modifications to existing tables
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS historical_comps (
    comp_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    player_name         TEXT    NOT NULL,
    position            TEXT    NOT NULL,
    archetype_code      TEXT    NOT NULL,
    mechanism           TEXT    NOT NULL,
    translation_outcome TEXT    NOT NULL CHECK(translation_outcome IN ('HIT','PARTIAL','MISS')),
    fm_code             TEXT,
    fm_mechanism        TEXT,
    outcome_summary     TEXT    NOT NULL,
    era_bracket         TEXT    NOT NULL,
    peak_years          TEXT,
    comp_confidence     TEXT    NOT NULL CHECK(comp_confidence IN ('A','B','C')),
    scheme_context      TEXT,
    signature_trait     TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_comps_unique   ON historical_comps(player_name, archetype_code);
CREATE INDEX        IF NOT EXISTS idx_comps_archetype ON historical_comps(archetype_code);
CREATE INDEX        IF NOT EXISTS idx_comps_position  ON historical_comps(position);
CREATE INDEX        IF NOT EXISTS idx_comps_outcome   ON historical_comps(translation_outcome);
CREATE INDEX        IF NOT EXISTS idx_comps_fm        ON historical_comps(fm_code);
