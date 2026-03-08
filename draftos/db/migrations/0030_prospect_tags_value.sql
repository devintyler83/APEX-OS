-- 0030_prospect_tags_value
-- Additive: add tag_value column to prospect_tags for storing typed tag values (e.g. apex ranks)
ALTER TABLE prospect_tags ADD COLUMN tag_value TEXT;
