-- ============================================================
-- DraftOS Migration 0037 — Seed bleacherreport_2026 source
-- File: draftos/db/migrations/0037_seed_bleacherreport_2026.sql
-- Apply via: python -m draftos.db.migrate
-- Additive only — INSERT OR IGNORE, no existing rows modified
-- ============================================================

PRAGMA foreign_keys = ON;

-- source_id=27 reserved for Bleacher Report 2026 big board.
-- Brent Sobleski / B/R NFL Scouting Dept. post-combine rankings.
-- T2 weight (1.0). analyst_grade = Sobleski score (0-10 float scale).
-- Added Session 16.
INSERT OR IGNORE INTO sources (
    source_id,
    source_name,
    source_type,
    notes,
    is_active
) VALUES (
    27,
    'bleacherreport_2026',
    'ranking',
    'B/R NFL Scouting Dept. post-combine big board. Brent Sobleski. Original scouting, T2 weight (1.0). analyst_grade column = Sobleski prospect score (0-10 float scale). 250 ranked prospects. Added Session 16.',
    1
);
