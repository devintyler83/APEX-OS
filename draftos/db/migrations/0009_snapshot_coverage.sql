CREATE TABLE IF NOT EXISTS prospect_board_snapshot_coverage (
  snapshot_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,
  coverage_count INTEGER NOT NULL,
  source_ids_json TEXT NOT NULL,          -- canonical sources that covered
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (snapshot_id, prospect_id),
  FOREIGN KEY (snapshot_id) REFERENCES prospect_board_snapshots(id),
  FOREIGN KEY (prospect_id) REFERENCES prospects(prospect_id)
);