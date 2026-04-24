-- Migration 0060: Add triage columns to divergence_flags
-- Enables analyst confirmation / dismissal workflow for divergence signals.
-- All columns nullable — existing rows have no triage status (NULL = untriaged).

ALTER TABLE divergence_flags ADD COLUMN status           TEXT;
ALTER TABLE divergence_flags ADD COLUMN triage_rationale TEXT;
ALTER TABLE divergence_flags ADD COLUMN triaged_by       TEXT;
ALTER TABLE divergence_flags ADD COLUMN triaged_at       TEXT;
