-- Migration 0029: Seed jfosterfilm_2026 as a new expert board source
-- JFosterFilm independent big board 2026 — 293 ranked prospects. Tier 2 source.

INSERT OR IGNORE INTO sources (source_name, source_type, notes, is_active)
VALUES (
    'jfosterfilm_2026',
    'expert_board',
    'JFosterFilm independent big board 2026 — 293 ranked prospects. Tier 2 source.',
    1
);
