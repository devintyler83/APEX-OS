-- draftos/db/migrations/0005_prospect_snapshot_confidence.sql
-- Prospect-level confidence signals derived from snapshot rows + per-source snapshot metrics.
-- Additive, deterministic, snapshot-scoped.

BEGIN;

CREATE TABLE IF NOT EXISTS prospect_board_snapshot_confidence (
  confidence_id            INTEGER PRIMARY KEY AUTOINCREMENT,

  snapshot_id              INTEGER NOT NULL,
  season_id                INTEGER NOT NULL,
  model_id                 INTEGER NOT NULL,
  prospect_id              INTEGER NOT NULL,

  active_sources           INTEGER NOT NULL DEFAULT 0,
  sources_present          INTEGER NOT NULL DEFAULT 0,
  coverage_pct             REAL NOT NULL DEFAULT 0.0,

  sources_healthy_present  INTEGER NOT NULL DEFAULT 0,
  sources_noisy_present    INTEGER NOT NULL DEFAULT 0,
  sources_thin_present     INTEGER NOT NULL DEFAULT 0,
  sources_stale_present    INTEGER NOT NULL DEFAULT 0,

  rank_std                 REAL,
  rank_mad                 REAL,

  confidence_score         REAL NOT NULL DEFAULT 0.0,   -- 0..100
  confidence_band          TEXT NOT NULL,               -- High | Medium | Low
  confidence_reasons_json  TEXT NOT NULL,               -- JSON array of short reason strings

  computed_at_utc          TEXT NOT NULL,

  UNIQUE(snapshot_id, prospect_id)
);

CREATE INDEX IF NOT EXISTS idx_psc_snapshot
  ON prospect_board_snapshot_confidence(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_psc_season_model
  ON prospect_board_snapshot_confidence(season_id, model_id);

COMMIT;