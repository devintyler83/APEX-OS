-- Migration 0047: prospect_comps table
-- Stores analyst-curated comp cards per prospect (card v2 display layer).
-- Separate from historical_comps (archetype library) — these are prospect-specific overrides.
-- Populated via accept_comps workflow or direct upsert from scoring runs.

CREATE TABLE IF NOT EXISTS prospect_comps (
    comp_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id    INTEGER NOT NULL,
    season_id      INTEGER NOT NULL DEFAULT 1,
    comp_type      TEXT    NOT NULL CHECK(comp_type IN ('hit','partial','miss')),
    type_label     TEXT    NOT NULL,          -- e.g. "Archetype Ceiling", "FM Risk Comp"
    player_name    TEXT    NOT NULL,
    description    TEXT    NOT NULL,
    years          TEXT,                      -- e.g. "2017 – Present"
    sort_order     INTEGER NOT NULL DEFAULT 0,-- lower = shown first on card
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(prospect_id, season_id, player_name),
    FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
);

CREATE INDEX IF NOT EXISTS idx_prospect_comps_pid
    ON prospect_comps(prospect_id, season_id);

CREATE INDEX IF NOT EXISTS idx_prospect_comps_type
    ON prospect_comps(comp_type);
