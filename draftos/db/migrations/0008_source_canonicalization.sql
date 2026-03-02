-- 0008_source_canonicalization.sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_canonical_map (
  source_id INTEGER PRIMARY KEY,                 -- alias source row
  canonical_source_id INTEGER NOT NULL,          -- canonical source row
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  notes TEXT,
  CHECK (source_id <> canonical_source_id),
  FOREIGN KEY (source_id) REFERENCES sources(source_id),
  FOREIGN KEY (canonical_source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_canonical_map_canonical
  ON source_canonical_map(canonical_source_id);

-- Convenience view: every source_id resolves to a canonical id
CREATE VIEW IF NOT EXISTS v_sources_resolved AS
SELECT
  s.source_id,
  COALESCE(m.canonical_source_id, s.source_id) AS canonical_source_id,
  s.source_name,
  s.source_type,
  s.url,
  s.notes,
  s.is_active,
  s.superseded_by_source_id
FROM sources s
LEFT JOIN source_canonical_map m
  ON m.source_id = s.source_id;