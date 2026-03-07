# DraftOS State Snapshot

Last Updated (UTC): 2026-03-07T04:50:10.958494+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

- Source deduplication complete. source_canonical_map expanded from 2 → 17 entries. Active sources reduced from 36 → 10 canonical sources. Score compression eliminated (#1 score 81.27 → 98.87). Elite tier 0 → 9 prospects. Confidence bands now meaningful (19 High, 100 Medium). Orphan snapshots 1 and 2 deleted. DB clean with 4 valid snapshots (ids 3–6).

## Next Milestone (Single Target)

- Consensus math refinement: dispersion modeling, weighted source influence, confidence formula tuning post-dedup.

---

## Layer Status

RAW CSVs: 10 raw CSVs present in data/imports/rankings/raw/2026/

STAGING: Staged CSVs present per source under data/imports/rankings/staged/2026/

INGEST: Operational. 37 sources (10 active canonical), 10958 source_players, 21034 source_rankings ingested.

BOOTSTRAP: Operational. 4629 prospects bootstrapped.

CONSENSUS: Operational. prospect_consensus_rankings populated. Active sources = 10.

MODEL OUTPUTS: Operational. prospect_model_outputs populated (4629 rows).

SNAPSHOTS: Operational. 4 valid snapshots (ids 3–6). Latest: snapshot_id=6 (2026-03-07). Integrity clean: rows=4629, coverage=4629, confidence=4629.

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
- 10 canonical sources: pff_2026, nfldraftbuzz_2026_v2, bnbfootball_2026, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026, tankathon_2026, thedraftnetwork_2026, theringer_2026

---

## Ordered TODOs

1. Consensus math refinement — dispersion modeling, weighted source influence
2. Additional source ingest (after dedup stabilizes source universe)
3. Full clean weekly pipeline run end-to-end
