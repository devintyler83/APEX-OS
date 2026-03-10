# DraftOS Claude Memory

## Key Files
- DB: C:\DraftOS\data\edge\draftos.sqlite
- Migrations: draftos/db/migrations/ (0001–0033 applied)
- Scripts: scripts/ — run as `python -m scripts.<name>`
- Config: draftos/config.py — PATHS object

## Session Start Protocol
1. Read CLAUDE.md fully
2. Read STATE_SNAPSHOT.md
3. `python scripts/doctor.py`
4. Confirm Next Milestone

## Session End Protocol
```
git add . && git commit -m "..."
python scripts/end_session.py
```
Copy BOOTSTRAP_PACKET.txt for next session.

## Pipeline Order
RAW CSVs → stage → ingest → bootstrap → canonicalize → consensus → model_outputs → snapshot → exports → packets

## Critical Conventions
- --season arg on scripts = draft_year (2026), NOT season_id (1)
- Migration path: draftos/db/migrations/ NOT migrations/
- jfosterfilm_2026.csv encoding: latin-1 (not utf-8)
- compute_source_snapshot_metrics must run BEFORE compute_snapshot_confidence
- Pipeline for full snapshot refresh: build_consensus → snapshot_board → compute_snapshot_metrics → compute_source_snapshot_metrics → compute_snapshot_confidence → verify_snapshot_integrity

## Session 8 Changes (Universe Migration)
- Migration 0033: prospects.is_active + prospect_consensus_rankings.is_active (default 1)
- data/universe/prospect_universe_2026.csv: 861 unique players (RAS ∪ jfosterfilm)
- apply_prospect_universe uses suffix-aware + period-aware name matching (Jr./II/TJ patterns)
- 1376 active prospect rows (= 861 unique players × ~1.6 position dups)
- 3760 inactive, 0 universe names unmatched
- consensus: 798 rows (full replace on each rebuild, not upsert)
- snapshot_board.py filters to is_active=1 via JOIN
- All query files (consensus.py, model_outputs.py) filter AND p.is_active=1

## Score Improvement Post-Universe
- Before: max score 81.3, Elite=0, Strong=2
- After: max score 98.5, Elite=12, Strong=11
- Confidence: High=11, Medium=63, Low=926 (snapshot_id=9)
