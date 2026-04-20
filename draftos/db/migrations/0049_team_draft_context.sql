-- Migration 0049: team_draft_context
-- Additive only. Idempotent (CREATE TABLE IF NOT EXISTS).
-- Season-scoped (season_id=1). No destructive changes.
--
-- NOTE: Table uses composite PK (team_id, season_id). No autoincrement id column.
-- premium_needs_json / depth_chart_pressure_json / draft_capital_json are NOT NULL
-- with JSON-literal defaults. updated_at tracks last modification.

CREATE TABLE IF NOT EXISTS team_draft_context (
    team_id                   TEXT    NOT NULL,           -- e.g. "KC", "PHI"
    season_id                 INTEGER NOT NULL DEFAULT 1,
    team_name                 TEXT    NOT NULL,           -- e.g. "Kansas City Chiefs"
    development_timeline      TEXT,                       -- "win_now" | "rebuild" | "balanced"
    risk_tolerance            TEXT,                       -- "high" | "medium" | "low"
    primary_offense_family    TEXT,                       -- e.g. "spread_RPO", "pro_style"
    primary_defense_family    TEXT,                       -- e.g. "4-3_pressure", "3-4_zone"
    coverage_bias             TEXT,                       -- e.g. "man", "zone", "quarters", "mixed"
    man_rate_tolerance        TEXT,                       -- "high" | "medium" | "low"
    premium_needs_json        TEXT    NOT NULL DEFAULT '[]',   -- JSON array: ["CB","EDGE"]
    depth_chart_pressure_json TEXT    NOT NULL DEFAULT '{}',   -- JSON object: {"CB": "high"}
    draft_capital_json        TEXT    NOT NULL DEFAULT '{}',   -- JSON object: {"pick_1": 32}
    notes                     TEXT,
    is_active                 INTEGER NOT NULL DEFAULT 1,
    created_at                TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, season_id)
);

CREATE INDEX IF NOT EXISTS idx_team_draft_context_season_team
    ON team_draft_context (season_id, team_id);

-- Verify
SELECT 'migration_0049_applied' AS status,
       COUNT(*) AS tables_present
FROM sqlite_master
WHERE type='table' AND name='team_draft_context';
