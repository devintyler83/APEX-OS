# DraftOS State Snapshot

Last Updated (UTC): 2026-03-07T05:37:57.582137+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

- Consensus math refinement complete. Source quality weighting added (T1=1.3, T2=1.0, T3=0.7); weighted_base_score stored in DB (migration 0025). Dispersion-aware confidence bands implemented: hard caps at std_dev>0.20 (Low) and std_dev>0.10 (Medium cap); dispersion_cap_applied flag stored per row (migration 0026). 55 prospects capped. Final confidence distribution: High=12, Medium=58, Low=4559. Doctor clean. snapshot_id=6 rebuilt end-to-end.

## Next Milestone (Single Target)

- Additional source ingest: identify and ingest 2–3 high-quality new sources to expand coverage (target: move more prospects from Low to Medium/High confidence).

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
- SOURCE_WEIGHTS: T1 (pff_2026, thedraftnetwork_2026, theringer_2026) = 1.3; T2 (nfldraftbuzz_2026_v2, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026) = 1.0; T3 (bnbfootball_2026, tankathon_2026) = 0.7
- Confidence dispersion caps: std_dev > 0.20 → Low; std_dev > 0.10 → cap at Medium (normalized rank std_dev, range 0–1)

---

## Ordered TODOs

1. Additional source ingest (source universe stable — dedup complete, weights defined)
2. Full clean weekly pipeline run end-to-end
3. Review queue cleanup — filter spamml/fantasy sources, focus on legit draft sources
