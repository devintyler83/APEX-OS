-- Soft-deprecate the older NFLDraftBuzz ingest if both exist.
    -- Idempotent: safe to re-run.
    -- Policy:
    --   - NFLDraftBuzz_v2 is the active source
    --   - NFLDraftBuzz (old) becomes inactive and points to v2
    UPDATE sources
    SET is_active = 1
    WHERE source_name IN ('PFF', 'NFLDraftBuzz_v2');

    UPDATE sources
    SET is_active = 0,
        superseded_by_source_id = (
          SELECT s2.source_id FROM sources s2 WHERE s2.source_name = 'NFLDraftBuzz_v2'
        )
    WHERE source_name = 'NFLDraftBuzz'
      AND EXISTS (SELECT 1 FROM sources s2 WHERE s2.source_name = 'NFLDraftBuzz_v2');
