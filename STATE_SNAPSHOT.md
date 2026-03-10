# DraftOS State Snapshot

Last Updated (UTC): 2026-03-10T06:10:00+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

- Session 8: Prospect universe migration — most consequential data quality fix in the project.
  - Migration 0033: prospects.is_active + prospect_consensus_rankings.is_active (additive, default 1)
  - data/universe/prospect_universe_2026.csv: 861 canonical players from RAS (630) ∪ jfosterfilm (735)
  - 3760 garbage rows soft-deprecated (is_active=0) — spamml, fantasy, cross-season contamination
  - 1376 active rows (861 unique players × ~1.6 position-dup factor from normalization artifacts)
  - 0 universe names unmatched — suffix-aware (Jr./II/III) + period-aware (T.J.→TJ) matching
  - All 50 APEX top-50 scored prospects confirmed in active universe (0 false negatives)
  - Consensus rebuilt: 798 rows (full replace), build_consensus now does DELETE+INSERT not upsert
  - Score range: max 98.5 (was 81.3). Elite tier: 12 (was 0). Strong: 11 (was 2)
  - snapshot_id=9 (2026-03-10): rows=1000, coverage=1000, confidence=1000 — OK
  - Confidence: High=11, Medium=63, Low=926
  - Query layer updated: consensus.py, model_outputs.py, snapshot_board.py all filter AND p.is_active=1

## Last Completed Milestone (Session 9 addendum)

- Session 9: Top-50 APEX re-score against updated post-universe consensus ranks. 50/50 scored, 0 failed.
  - Tier: ELITE=4, APEX=28, SOLID=18  (ELITE threshold = composite ≥ 85.0)
  - ELITE: Rueben Bain EDGE 91.2 (#4), Fernando Mendoza QB 89.3 (#1), David Bailey EDGE 88.4 (#7), Rueben Bain dup 85.9 (#12)
  - Only ALIGNED: Rueben Bain #4 (delta=-8.0). All other 49 show APEX LOW.
  - APEX LOW MAJOR top gaps: Jeremiyah Love RB -41.1, Kenyon Sadiq TE -34.7, Lee Hunter LB -33.6, Olaivavega Ioane OG -32.6
  - Structural note: systematic APEX LOW is a scale artifact. Consensus now runs 65–99 (post-universe); APEX composites run 55–91. Divergence was calibrated to old compressed scale (40–82). Divergence thresholds need recalibration.
  - APEX tier thresholds confirmed: ELITE≥85, APEX≥70, SOLID≥55, DEVELOPMENTAL≥40

## Next Milestone (Single Target)

- Divergence formula recalibration. Consensus scale shift (40–82 → 65–99) makes nearly all prospects show APEX LOW. Two options:
  1. Recalibrate divergence_score to rank-relative comparison (apex_rank vs consensus_rank) instead of raw score delta
  2. Accept APEX LOW prevalence as meaningful — APEX intentionally discounts non-premium positions via PVC; most APEX LOW MAJOR are OG/C/RB/TE which is correct PVC behavior
  Decision determines whether to update divergence engine or annotate the current output as-is.

---

## Layer Status

RAW CSVs: 12 raw CSVs present in data/imports/rankings/raw/2026/ (including ras_2026.csv)

STAGING: Staged CSVs present per source under data/imports/rankings/staged/2026/

INGEST: Operational. 39 sources (11 active canonical), 15135 source_players, 30542 source_rankings ingested.

BOOTSTRAP: Operational. 5136 prospects total (1376 active / 3760 inactive after Session 8 universe apply).

UNIVERSE: Operational. data/universe/prospect_universe_2026.csv (861 players). Migration 0033 applied.

CONSENSUS: Operational. 798 rows (active-universe-only rebuild). Top score: 98.5328 (Fernando Mendoza QB).

MODEL OUTPUTS: Operational. prospect_model_outputs: 4756 rows (1000 for active prospects).

SNAPSHOTS: Operational. Latest: snapshot_id=9 (2026-03-10). Integrity clean: rows=1000, coverage=1000, confidence=1000.

EXPORTS: board_2026_v1_default.csv produced (may be stale — re-export not yet run post-Session 8).

---

## Known Decisions

- Deterministic only
- Additive migrations only
- Season scoped only
- Active sources only (sources.is_active = 1 enforced in math)
- Active prospects only (prospects.is_active = 1 enforced in all downstream queries post-Session 8)
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
- RAS join in get_big_board() uses AND r.ras_total IS NOT NULL instead of season_id filter. Temporary workaround for two-generation ras data (172 rows season_id=NULL with real data, 336 rows season_id=1 mostly empty). Revert to season_id join after RAS re-ingest post pro days.
- build_consensus_2026.py does full DELETE + INSERT (not upsert) to guarantee clean row count after universe apply. Safe because consensus is derived data, always rebuilt from sources.
- snapshot_board.py filters prospect_model_outputs via JOIN to prospects WHERE is_active=1. jfosterfilm_2026.csv encoding is latin-1.
- Universe name matching: normalize_name() → suffix-strip (Jr./Sr./II/III/IV) → period-strip (T.J.→TJ). All 861 universe names matched to DB with 0 gaps.
- Active prospect count is 1376 DB rows for 861 unique players — the ~1.6x factor is position normalization duplicate artifact (pre-existing, not introduced in Session 8).

---

## Divergence Flags (Manual Evaluation Needed)

- SONNY STYLES (LB, Ohio State): jfosterfilm_2026 ranks #1 overall; new consensus rank is #6 (score=94.30). Source disagreement reduced post-universe but still significant — worth evaluating whether jfoster reflects genuine contrarian view.
- ALL TOP-50 APEX divergence_deltas are stale post-Session 8 — computed against pre-universe consensus ranks. Re-score with --force in Session 9 to update.

---

## APEX v2.2 Engine Notes

- CALIBRATION_OVERRIDES in run_apex_scoring_2026.py maps name -> {prospect_id, position, school}
  Required because DB has multiple duplicate entries per prospect (position normalization artifacts)
  Best prospect_id = highest consensus score entry for that name
- Position overrides: Schwesinger=ILB, Membou=OT, Ratledge=OG, Emmanwori=S, Williams=IDL, Paul/Wilson=C
- run_apex_scoring_2026.py requires ANTHROPIC_API_KEY env var to make live API calls
- Fallback: import_apex_batch_json.py accepts pre-evaluated JSON (no API key needed)
- data/apex_calibration_batch.json contains the calibration evaluations (APEX v2.2 direct eval)
- CALIBRATION_KNOWN_RANKS in run_apex_scoring_2026.py maps name -> (consensus_rank, tier) for correct divergence computation. These hardcoded ranks will need updating after Session 9 re-score.
- Gunnar Helm (pid=842): 2025 draftee — ghost row in 2026 DB introduced via spamml sources. apex_scores row force-deleted in Session 6. Do NOT re-score — cross-season contamination. Correctly remains in active universe (pid=842 is in jfosterfilm) — this is a known ghost but the universe CSV catch was correct to include him as jfoster ranked him. Monitor.
- APEX LOW on non-premium positions (ILB, OG, C, TE, RB) is structural PVC behavior, not actionable divergence. Monitor APEX LOW MAJOR only on premium positions (QB, CB, EDGE, OT, S).

---

## Ordered TODOs

1. ~~Session 4: APEX top-50 batch scoring~~ COMPLETE 2026-03-10 (62 rows, ELITE=6, APEX=32, SOLID=22, DEV=2)
2. ~~Session 5: Add positional archetype libraries to prompts.py (QB, EDGE, CB, OT, S, IDL, TE)~~ COMPLETE 2026-03-10
3. ~~Session 6: RAS join fix, ghost prospect audit~~ COMPLETE 2026-03-10
4. ~~Session 7: top-50 force re-score (positional archetypes), calibration artifact tagging (migration 0032)~~ COMPLETE 2026-03-10 (50 top-50 scored, GEN-=0, 11 cal tagged)
5. ~~Session 8: Prospect universe migration (migration 0033, is_active, consensus rebuild)~~ COMPLETE 2026-03-10
6. ~~Session 9: Re-score top-50 APEX with --force against updated consensus ranks~~ COMPLETE 2026-03-10 (50/50, ELITE=4, APEX=28, SOLID=18)
7. Additional source ingest (source universe stable — dedup complete, weights defined)
8. Full clean weekly pipeline run end-to-end
9. Review queue cleanup — filter spamml/fantasy sources, focus on legit draft sources
10. RAS re-ingest after pro days complete — re-run ingest_ras_2026.py with updated file, fully idempotent
11. ~~Expand school_aliases — add long-form variants (Southern California, Louisiana State, etc.)~~ COMPLETE 2026-03-08 (23 aliases added, 147→170, RAS matched 447→461)
12. ~~Fix corrupted school_aliases entries (Oklahoma → Colorado pattern)~~ COMPLETE 2026-03-08
