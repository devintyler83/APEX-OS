\# Patch Notes (since last checkpoint)



\## Engine and Safety

\- Fixed Python import issues when running scripts by file path by adding repo root to sys.path in scripts as needed.

\- Hardened migration runner:

&#x20; - strict migration filename validation

&#x20; - DB backup before applying each new migration

&#x20; - explicit APPLY/SKIP logs



\## Seeds and Doctor Gate

\- Ensured season 2026 and model v1\_default seeded.

\- Added doctor invariant checks and table counts.

\- Extended doctor to print sources\_active when schema supports it.



\## Ingest

\- Built rankings ingest pipeline:

&#x20; - loader.py uses robust polars CSV settings for messy inputs

&#x20; - writer.py writes only to sources/source\_players/source\_rankings

&#x20; - DB backup before bulk writes

\- Scraped NFLDraftBuzz with Playwright due to site blocking requests (403).

\- Produced corrected NFLDraftBuzz v2 CSV with proper school and position fields.

\- Ingested PFF and NFLDraftBuzz sources.



\## Soft Deprecation

\- Added sources.is\_active and sources.superseded\_by\_source\_id via migrations:

&#x20; - 0005\_sources\_active\_cols.sql

&#x20; - 0006\_deprecate\_nfldraftbuzz\_old.sql

\- Marked old NFLDraftBuzz inactive, superseded by NFLDraftBuzz\_v2.

