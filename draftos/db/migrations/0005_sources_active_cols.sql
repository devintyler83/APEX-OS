-- Add soft-deprecation controls for sources.
    -- Additive, idempotent.
    ALTER TABLE sources ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE sources ADD COLUMN superseded_by_source_id INTEGER;
