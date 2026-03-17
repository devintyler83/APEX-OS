-- Migration 0046: Add pre_draft_signal to historical_comps
-- Extends the FM reference population with the highest-value field
-- in the FM library: the observable pre-draft indicator that was
-- missed or ignored. Nullable for backward compatibility with
-- existing 80 position comp rows.
--
-- Also adds is_fm_reference flag for clean separation of
-- positional comps vs. cross-position FM reference records.

-- Add pre_draft_signal column (nullable — existing rows stay NULL)
ALTER TABLE historical_comps ADD COLUMN pre_draft_signal TEXT;

-- Add is_fm_reference flag (guard: applied idempotently in Python runner)
ALTER TABLE historical_comps ADD COLUMN is_fm_reference INTEGER NOT NULL DEFAULT 0;

-- Log migration
INSERT OR IGNORE INTO meta_migrations (name, applied_at)
VALUES ('0046_historical_comps_fm_seed', datetime('now'));
