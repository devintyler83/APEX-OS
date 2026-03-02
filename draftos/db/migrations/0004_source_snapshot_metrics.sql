-- draftos/db/migrations/0004_source_snapshot_metrics.sql
-- Snapshot-scoped source health metrics (coverage + drift + staleness).
-- Additive, deterministic, season/model scoped.

BEGIN;

CREATE TABLE IF NOT EXISTS source_board_snapshot_metrics (
  metric_id            INTEGER PRIMARY KEY AUTOINCREMENT,

  snapshot_id          INTEGER NOT NULL,
  season_id            INTEGER NOT NULL,
  model_id             INTEGER NOT NULL,
  source_id            INTEGER NOT NULL,

  ranking_date_used    TEXT,            -- MAX(ranking_date) <= snapshot_date_utc
  players_ranked       INTEGER NOT NULL DEFAULT 0,
  coverage_pct         REAL NOT NULL DEFAULT 0.0,

  avg_rank_diff        REAL,            -- mean(source_overall_rank - snapshot_rank_overall)
  mad_rank_diff        REAL,            -- mean(abs(source_overall_rank - snapshot_rank_overall))

  stale_flag           INTEGER NOT NULL DEFAULT 0,  -- 1 if ranking_date too old or missing
  health_chip          TEXT NOT NULL,               -- Healthy | Thin Coverage | Noisy | Stale

  computed_at_utc      TEXT NOT NULL,

  UNIQUE(snapshot_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_sbs_metrics_snapshot
  ON source_board_snapshot_metrics(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_sbs_metrics_source
  ON source_board_snapshot_metrics(source_id);

CREATE INDEX IF NOT EXISTS idx_sbs_metrics_season_model
  ON source_board_snapshot_metrics(season_id, model_id);

COMMIT;