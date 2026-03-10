# DraftOS State Snapshot

Last Updated (UTC): 2026-03-10T04:20:09.335753+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

- APEX v2.2 engine built and calibrated (Session 3). New package draftos/apex/ (engine.py, prompts.py, writer.py). Scripts: run_apex_scoring_2026.py (Claude API orchestrator, requires ANTHROPIC_API_KEY) and import_apex_batch_json.py (API-key-free batch import path). 12 calibration prospects scored, all 6 validation targets PASS: Hunter=ELITE(91.2)+Two-Way, Schwesinger=APEX(73.1)+CRUSH+Walk-On, Sanders=SOLID(67.0)+TierC, Membou=APEX(76.0), Emmanwori=APEX(74.7)+SOSGate, Etienne=DEVELOPMENTAL(45.8)+NO_FIT. apex_scores=12, divergence_flags=12. get_big_board updated with APEX LEFT JOIN (apex_v2.2). app.py updated with APEX Score/Tier/Archetype columns (ELITE=gold, APEX=green, SOLID=blue, DEVELOPMENTAL=grey).

## Last Completed Milestone (Session 4 addendum)

- Top-50 batch scored (62 total apex_scores: 12 calibration + 50 top50). Tier distribution: ELITE=6, APEX=32, SOLID=22, DEVELOPMENTAL=2. Skip logic confirmed idempotent.
- Calibration divergence_flags corrected: 12 false APEX HIGH flags → 0. Root cause: DB consensus ranks inflated (190–680) due to source coverage gaps. Fix: scripts/fix_calibration_divergence_2026.py uses hardcoded known ranks (CALIBRATION_KNOWN_RANKS also added to run_apex_scoring_2026.py for future runs). Hunter=ALIGNED(-8.4), Schwesinger=APEX LOW rank=33 delta=-20.3.

## Next Milestone (Single Target)

- Session 5: Add positional archetype libraries to prompts.py (QB, EDGE, CB, OT, S, IDL, TE). Re-score Gunnar Helm (pid=842) with --force after TE library added.

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
- RAS join in get_big_board() uses AND r.ras_total IS NOT NULL instead of season_id filter. Temporary workaround for two-generation ras data (172 rows season_id=NULL with real data, 336 rows season_id=1 mostly empty). Revert to season_id join after RAS re-ingest post pro days.

---

## Divergence Flags (Manual Evaluation Needed)

- SONNY STYLES (LB, Ohio State): jfosterfilm_2026 ranks #1 overall; consensus rank is outside top 10 (#14, score=80.29). Significant source disagreement — worth manual evaluation to determine if jfosterfilm reflects a strong contrarian view or a data artifact.

---

## APEX v2.2 Engine Notes

- CALIBRATION_OVERRIDES in run_apex_scoring_2026.py maps name -> {prospect_id, position, school}
  Required because DB has multiple duplicate entries per prospect (position normalization artifacts)
  Best prospect_id = highest consensus score entry for that name
- Position overrides: Schwesinger=ILB, Membou=OT, Ratledge=OG, Emmanwori=S, Williams=IDL, Paul/Wilson=C
- run_apex_scoring_2026.py requires ANTHROPIC_API_KEY env var to make live API calls
- Fallback: import_apex_batch_json.py accepts pre-evaluated JSON (no API key needed)
- data/apex_calibration_batch.json contains the calibration evaluations (APEX v2.2 direct eval)
- CALIBRATION_KNOWN_RANKS in run_apex_scoring_2026.py maps name -> (consensus_rank, tier) for correct divergence computation. DB ranks for calibration prospects are inflated (190–680) — these override at scoring time.
- Gunnar Helm (pid=842): 2025 draftee — ghost row in 2026 DB introduced via spamml sources (TEN NFL player rows) and stale PFF list. apex_scores row force-deleted in Session 6. Do NOT re-score — cross-season contamination. Remove from calibration re-score sequence. Calibration batch contains 12 total 2025 draftees; their apex_scores are engine validation artifacts only, not 2026 board signal.
- APEX LOW on non-premium positions (ILB, OG, C, TE, RB) is structural PVC behavior, not actionable divergence. PVC suppression for these positions means apex_composite will routinely fall below consensus-implied. Monitor APEX LOW MAJOR only on premium positions (QB, CB, EDGE, OT, S) where PVC=0.90–1.0 and the gap reflects genuine framework judgment rather than position discount.

## Ordered TODOs

1. ~~Session 4: APEX top-50 batch scoring~~ COMPLETE 2026-03-10 (62 rows, ELITE=6, APEX=32, SOLID=22, DEV=2)
2. ~~Session 5: Add positional archetype libraries to prompts.py (QB, EDGE, CB, OT, S, IDL, TE)~~ COMPLETE 2026-03-10
3. ~~Session 6: RAS join fix, ghost prospect audit~~ COMPLETE 2026-03-10
4. Session 7 first action: restore API credits, run calibration --force, top50 --force. GEN- target = 0.
5. Additional source ingest (source universe stable — dedup complete, weights defined)
6. Full clean weekly pipeline run end-to-end
7. Review queue cleanup — filter spamml/fantasy sources, focus on legit draft sources
8. RAS re-ingest after pro days complete — re-run ingest_ras_2026.py with updated file, fully idempotent
9. ~~Expand school_aliases — add long-form variants (Southern California, Louisiana State, etc.)~~ COMPLETE 2026-03-08 (23 aliases added, 147→170, RAS matched 447→461)
10. ~~Fix corrupted school_aliases entries (Oklahoma → Colorado pattern)~~ COMPLETE 2026-03-08
