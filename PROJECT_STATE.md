\# DraftOS Project State (Checkpoint)



Date: 2026-02-25 to 2026-02-26

Repo Root: C:\\DraftOS

Canonical DB: C:\\DraftOS\\data\\edge\\draftos.sqlite



\## Current Phase

Phase 1, engine only. No Streamlit Big Board work yet.



\## What Works

\- Deterministic DB path resolution via draftos/config.py.

\- Migration runner works and is additive, logs APPLY/SKIP, backs up DB before applying new migrations.

\- Doctor gate passes (python -m scripts.doctor).

\- Rank ingest scaffold works:

&#x20; - draftos.ingest.rankings.loader parses CSV

&#x20; - draftos.ingest.rankings.writer writes to sources, source\_players, source\_rankings

&#x20; - backs up DB before bulk ingest

&#x20; - idempotent via UNIQUE constraints

\- Multi-source ingest proven:

&#x20; - PFF ingested (448 rows).

&#x20; - NFLDraftBuzz scraped via Playwright due to 403 blocking non-browser.

&#x20; - NFLDraftBuzz v2 CSV fixed fields (school, position, etc).

\- Soft deprecation implemented:

&#x20; - sources table now has is\_active and superseded\_by\_source\_id.

&#x20; - Old NFLDraftBuzz marked inactive and superseded by NFLDraftBuzz\_v2.

&#x20; - Doctor now prints sources\_active.



\## Current Data State (Expected)

\- sources: 3 total

&#x20; - PFF (active)

&#x20; - NFLDraftBuzz (inactive, superseded\_by NFLDraftBuzz\_v2)

&#x20; - NFLDraftBuzz\_v2 (active)

\- sources\_active: 2

\- seasons: 1 (2026)

\- models: 1 (v1\_default seeded for 2026)

\- prospects: 0 (not built yet)

\- source\_players/source\_rankings include historical inactive rows, total count around 1416.



\## Core Decision

We keep old source ingests for audit, but only active sources are used for matching, aggregation, and UI.



\## Next Steps (Engine Only)

1\) Canonical position taxonomy aligned to NFL.com and ESPN:

&#x20;  Canonical codes: QB, RB, WR, TE, FB, OT, OG, C, DT, LB, EDGE, CB, S, LS, PK, P.

&#x20;  Build deterministic mapping from source raw positions (HB, SAF, DE/ED, LB/ED, etc) to canonical.

&#x20;  Derive position\_group deterministically from canonical.



2\) Add active-only query seam in domain layer:

&#x20;  All matching and aggregation must filter sources.is\_active = 1 by default.



3\) Implement deterministic prospect\_key generator and identity bootstrap:

&#x20;  - Normalize name, suffix stripping, punctuation removal.

&#x20;  - Normalize school via aliases table (school\_aliases) with safe fallback.

&#x20;  - Use canonical position and position\_group.

&#x20;  - Create prospects and source\_player\_map deterministically for active sources only.

&#x20;  - No UI. No Big Board.



4\) After matching is stable:

&#x20;  - Build master aggregated ranking (active sources only).

&#x20;  - Later add APEX custom ranking layer.



\## Blockers

None. Need to implement identity + matching and canonical position mapping.



\## Files Modified/Added Recently (High Value)

\- draftos/db/migrate.py hardened (name validation + logging).

\- scripts/doctor.py runnable and now prints sources\_active.

\- draftos/ingest/rankings/loader.py robust CSV parsing (utf8-lossy, truncate ragged lines).

\- draftos/ingest/rankings/writer.py ingest pipeline.

\- scripts/scrape\_nfldraftbuzz\_2026\_playwright.py Playwright scraper for NFLDraftBuzz, bypasses 403.

\- scripts/patch\_0005\_0006\_soft\_deprecate\_nfldraftbuzz.py one-time patch creator for migrations 0005/0006 and doctor/schema updates.

\- draftos/db/migrations:

&#x20; - 0002\_seed\_2026.sql

&#x20; - 0003\_seed\_v1\_default\_model.sql

&#x20; - 0004\_fix\_seed\_2026\_and\_model.sql

&#x20; - 0005\_sources\_active\_cols.sql

&#x20; - 0006\_deprecate\_nfldraftbuzz\_old.sql

