-- draftos/db/migrations/0003_snapshot_metrics.sql
-- Add snapshot-derived metrics (momentum + volatility) without recomputing consensus/model logic.

BEGIN;

CREATE TABLE IF NOT EXISTS prospect_board_snapshot_metrics (
  metric_id            INTEGER PRIMARY KEY AUTOINCREMENT,

  snapshot_id          INTEGER NOT NULL,
  season_id            INTEGER NOT NULL,
  model_id             INTEGER NOT NULL,
  prospect_id          INTEGER NOT NULL,

  window_n             INTEGER NOT NULL,

  -- Momentum (net change over window: oldest -> current)
  momentum_rank        INTEGER,         -- positive means improved rank (moved up)
  momentum_score       REAL,            -- current_score - oldest_score

  -- Volatility over window (adjacent movements)
  volatility_rank_mad  REAL,            -- mean absolute delta rank across adjacent snapshots
  volatility_rank_std  REAL,            -- std dev of ranks across window

  -- Chips (deterministic labels)
  momentum_chip        TEXT,            -- "Rising" | "Falling" | "Stable"
  volatility_chip      TEXT,            -- "Volatile" | "Calm"

  computed_at_utc      TEXT NOT NULL,

  UNIQUE(snapshot_id, prospect_id, window_n)
);

CREATE INDEX IF NOT EXISTS idx_psm_snapshot
  ON prospect_board_snapshot_metrics(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_psm_season_model
  ON prospect_board_snapshot_metrics(season_id, model_id, window_n);

CREATE INDEX IF NOT EXISTS idx_psm_prospect
  ON prospect_board_snapshot_metrics(prospect_id);

COMMIT;