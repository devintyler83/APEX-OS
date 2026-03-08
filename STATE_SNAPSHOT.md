# DraftOS State Snapshot

Last Updated (UTC): 2026-03-08T06:11:55.865736+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

- jfosterfilm_2026 ingested and re-ingested (updated file). 293 ranked prospects. source_id=38, is_active=1, T2 weight=1.0. Migration 0029. 216/293 source_players auto-mapped. Rueben Bain Jr. correctly mapped to prospect_id=449 (Miami, EDGE) after fixing school_alias key collision (plain alias beats parenthetical on same key in load_school_alias_map). reingest_source_2026.py created as standard re-ingest script. snapshot_id=7 rebuilt end-to-end. Doctor clean. Confidence: High=11, Medium=54, Low=4564.

## Next Milestone (Single Target)

- Additional source ingest: identify and ingest 2–3 high-quality new sources to expand coverage (target: move more prospects from Low to Medium/High confidence).

---

## Layer Status

RAW CSVs: 11 raw CSVs present in data/imports/rankings/raw/2026/

STAGING: Staged CSVs present per source under data/imports/rankings/staged/2026/

INGEST: Operational. 38 sources (11 active canonical), 11251 source_players, 21327 source_rankings ingested.

BOOTSTRAP: Operational. 4629 prospects bootstrapped.

CONSENSUS: Operational. prospect_consensus_rankings populated. Active sources = 11.

MODEL OUTPUTS: Operational. prospect_model_outputs populated (4629 rows).

SNAPSHOTS: Operational. Latest: snapshot_id=7 (2026-03-08). Integrity clean: rows=4629, coverage=4629, confidence=4629.

EXPORTS: board_2026_v1_default.csv produced.

---

## Known Decisions

- Deterministic only
- Additive migrations only
- Season scoped only
- Active sources only (sources.is_active = 1 enforced in math)
- Idempotent scripts only
- Each layer has exactly one responsibility
- No layer may recompute logic belonging to another
- Raw ingest data is never deleted (soft deprecation only)
- Snapshot rows define the universe for coverage and confidence
- source_canonical_map has 17 entries — always use it for dedup, never count raw is_active
- 11 canonical sources: pff_2026, nfldraftbuzz_2026_v2, bnbfootball_2026, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026, tankathon_2026, thedraftnetwork_2026, theringer_2026, jfosterfilm_2026
- SOURCE_WEIGHTS: T1 (pff_2026, thedraftnetwork_2026, theringer_2026) = 1.3; T2 (nfldraftbuzz_2026_v2, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026, jfosterfilm_2026) = 1.0; T3 (bnbfootball_2026, tankathon_2026) = 0.7
- Confidence dispersion caps: std_dev > 0.20 → Low; std_dev > 0.10 → cap at Medium (normalized rank std_dev, range 0–1)
- reingest_source_2026.py is the standard script for all future source updates (clean replace of source_players, source_rankings, source_player_map, staged files; then re-runs staging → ingest → name normalization → bootstrap → prospect canonicalization). Usage: python -m scripts.reingest_source_2026 --source <name> --season <year> --apply 0|1
- school_alias key collision fix applied in patch_name_normalization_2026.py: plain alias (e.g. 'Miami') beats parenthetical alias (e.g. 'Miami (OH)') when both normalize to the same school_key

---

## Divergence Flags (Manual Evaluation Needed)

- SONNY STYLES (LB, Ohio State): jfosterfilm_2026 ranks #1 overall; consensus rank is outside top 10 (#14, score=80.29). Significant source disagreement — worth manual evaluation to determine if jfosterfilm reflects a strong contrarian view or a data artifact.

---

## Ordered TODOs

1. Additional source ingest (source universe stable — dedup complete, weights defined)
2. Full clean weekly pipeline run end-to-end
3. Review queue cleanup — filter spamml/fantasy sources, focus on legit draft sources
4. RAS re-ingest after pro days complete — re-run ingest_ras_2026.py with updated file, fully idempotent
5. ~~Expand school_aliases — add long-form variants (Southern California, Louisiana State, etc.)~~ COMPLETE 2026-03-08 (23 aliases added, 147→170, RAS matched 447→461)
6. ~~Fix corrupted school_aliases entries (Oklahoma → Colorado pattern)~~ COMPLETE 2026-03-08
