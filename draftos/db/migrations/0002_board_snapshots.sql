-- draftos/db/migrations/0002_board_snapshots.sql
-- Add weekly (date-scoped) board snapshots + snapshot rows for delta tracking.
-- Additive + idempotent: safe to run multiple times.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS prospect_board_snapshots (
  id                INTEGER PRIMARY KEY,
  season_id          INTEGER NOT NULL,
  model_id           INTEGER NOT NULL,

  -- Deterministic idempotency anchor for reruns:
  -- one snapshot per UTC date per season+model.
  snapshot_date_utc  TEXT NOT NULL,   -- 'YYYY-MM-DD'
  created_at_utc     TEXT NOT NULL,   -- ISO-8601 UTC timestamp

  note              TEXT,

  UNIQUE (season_id, model_id, snapshot_date_utc),
  FOREIGN KEY (season_id) REFERENCES seasons(id),
  FOREIGN KEY (model_id)  REFERENCES models(id)
);

CREATE INDEX IF NOT EXISTS idx_pbs_season_model_date
  ON prospect_board_snapshots (season_id, model_id, snapshot_date_utc);

CREATE TABLE IF NOT EXISTS prospect_board_snapshot_rows (
  id                INTEGER PRIMARY KEY,
  snapshot_id        INTEGER NOT NULL,
  season_id          INTEGER NOT NULL,
  model_id           INTEGER NOT NULL,

  prospect_id        INTEGER NOT NULL,

  position           TEXT,
  rank_overall       INTEGER,         -- 1..N
  score              REAL,            -- model score
  tier               INTEGER,
  reason_chips_json  TEXT,            -- JSON string or NULL
  coverage_count     INTEGER,         -- number of active sources that ranked this player (or nearest equivalent)

  created_at_utc     TEXT NOT NULL,   -- ISO-8601 UTC timestamp

  UNIQUE (snapshot_id, prospect_id),

  FOREIGN KEY (snapshot_id) REFERENCES prospect_board_snapshots(id),
  FOREIGN KEY (season_id)   REFERENCES seasons(id),
  FOREIGN KEY (model_id)    REFERENCES models(id),
  FOREIGN KEY (prospect_id) REFERENCES prospects(id)
);

CREATE INDEX IF NOT EXISTS idx_pbsr_snapshot_rank
  ON prospect_board_snapshot_rows (snapshot_id, rank_overall);

CREATE INDEX IF NOT EXISTS idx_pbsr_prospect
  ON prospect_board_snapshot_rows (prospect_id);

CREATE INDEX IF NOT EXISTS idx_pbsr_season_model
  ON prospect_board_snapshot_rows (season_id, model_id);