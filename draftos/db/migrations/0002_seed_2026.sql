-- Seed initial season (additive, idempotent)
INSERT OR IGNORE INTO seasons (draft_year, created_at)
VALUES (2026, datetime('now'));