-- Schema snapshot note:
-- Canonical schema lives in: C:\DraftOS\draftos\db\schema.sql
-- Applied migrations list is stored in meta_migrations.

-- To snapshot actual live schema quickly:
-- sqlite3 C:\DraftOS\data\edge\draftos.sqlite ".schema" > SCHEMA_SNAPSHOT.sql

-- Known applied migrations (expected):
-- 0001_schema_v1
-- 0002_seed_2026
-- 0003_seed_v1_default_model
-- 0004_fix_seed_2026_and_model
-- 0005_sources_active_cols
-- 0006_deprecate_nfldraftbuzz_old