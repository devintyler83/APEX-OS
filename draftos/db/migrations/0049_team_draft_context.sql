BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS team_draft_context (
    team_id TEXT NOT NULL,
    season_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,

    development_timeline TEXT,
    risk_tolerance TEXT,

    primary_offense_family TEXT,
    primary_defense_family TEXT,
    coverage_bias TEXT,
    man_rate_tolerance TEXT,

    premium_needs_json TEXT NOT NULL DEFAULT '[]',
    depth_chart_pressure_json TEXT NOT NULL DEFAULT '{}',
    draft_capital_json TEXT NOT NULL DEFAULT '{}',

    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (team_id, season_id),
    FOREIGN KEY (season_id) REFERENCES seasons(season_id)
);

CREATE INDEX IF NOT EXISTS idx_team_draft_context_season
    ON team_draft_context (season_id);

CREATE INDEX IF NOT EXISTS idx_team_draft_context_active
    ON team_draft_context (is_active);

INSERT OR IGNORE INTO metamigrations (name, applied_at)
VALUES ('0049teamdraftcontext', CURRENT_TIMESTAMP);

COMMIT;