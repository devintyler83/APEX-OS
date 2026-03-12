# DraftOS State Snapshot

Last Updated (UTC): 2026-03-12T21:44:15.461852+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

Session 24 — Tag trigger evaluation engine built and activated. CI workflow removed.

- Built draftos/tags/evaluator.py: pure function library, no DB access.
  evaluate_rule(rule_expression, ctx) -> (bool, str). Never raises. Handles compound
  "and" chains recursively. Returns (False, "") on missing fields — no false positives.
- Built scripts/run_tag_triggers_2026.py: new engine with --apply/--prospect_id/--season.
  Imports from draftos.tags.evaluator. Backs up DB before writes.
  59 prospects evaluated, 14 rules checked, 65 recs already existed (idempotent), 0 new.
  4 unfireable rules documented: floor_play, possible_bust_system, riser_tier_jump, faller_tier_drop.
  74 non-premium divergence checks skipped (structural PVC — not actionable).
- Built scripts/accept_tag_recs_2026.py: new acceptance workflow with --action interface.
  --action list|accept|dismiss|accept-all-tag|dismiss-all-tag.
  --position filter added to list. Sorted by display_order ASC, position, name.
  Kilgore Divergence Alert (rec_id=48) accepted during verification (ptag_id=55, source=system).
- Removed .github/workflows/python-package-conda.yml — DraftOS is local-first, CI not applicable.
- Session infra fixes: end_session.py now validates STATE_SNAPSHOT + commits + pushes artifacts.
  CLAUDE.md tracked in git. STATE_SNAPSHOT.md updated to Session 23b clean state.
- Doctor: PASSED. Snapshot integrity: PASSED.
- Active tags post-S24: Development Bet=28, Compression Flag=13, Divergence Alert=7,
  Elite RAS=4, Poor RAS=1, Great RAS=1, Injury Flag=1. Rec status: accepted=55, dismissed=22, pending=0.

Prior sessions: 23b (source key correction), 23 (combine+NGS ingest), 21 (dev bet triage),
  20 (divergence triage), 19 (tag acceptance workflow), 18 (Kilgore re-score, trigger engine seed),
  16 (bleacherreport ingest), 15 (APEX board audit + override fix), 13b (school/archetype fix),
  13 (weekly pipeline), 12 (DB rebuild).

- Renamed source nflcom_2026 (source_id=28) → combine_ranks_2026. 735 ranking rows and all
  RAS measurables intact. Notes field updated. ras rows unaffected (stored by prospect_id).
- Ingested nflcom_2026 as new source (source_id=30, T2 1.0). NFL.com editorial big board.
  303 players. CSV columns: rank/name/school/pos. 92 new source_player_map entries from
  patch_name_normalization_2026.py.
- Deactivated ngs_2026 (source_id=29, is_active=0). Data preserved in grade column.
  Rule established: model-output scores (algorithmic composites) stored with is_active=0.
  Never feed consensus math. A model score is not a scout ranking. Deactivate at ingest time.
- Final source state: combine_ranks_2026 (28, active, 735 rows), ngs_2026 (29, inactive,
  312 rows), nflcom_2026 (30, active, 303 rows).
- Consensus: 849 rows. 14 active sources.
  Styles LB #1 confirmed genuine after NGS deactivation. jFoster#1, PFF#8, TDN#10, Ringer#12,
  14 sources total. House-effect hypothesis was incorrect. T1 sources all have him top-12.
- Doctor: PASSED (sources=30, sources_active=14, source_rankings=29947).
- Snapshot 3 (2026-03-12): rows=615, coverage=615, confidence=615 — PASSED.

Prior sessions on record: 12 (DB rebuild), 13 (weekly pipeline), 13b (school/archetype fix),
15 (APEX board audit + override correction), 16 (bleacherreport ingest), 18 (Kilgore re-score),
19 (tag acceptance workflow), 20 (divergence triage), 21 (dev bet + compression flag triage),
23 (combine + NGS ingest), 23b (source key correction).

## Next Milestone (Single Target)

- Full clean weekly pipeline run (18 steps) end-to-end to verify all layers pass cleanly
  post-session-23b source changes (combine_ranks_2026 rename, nflcom_2026 added, ngs deactivated).
  Run: python -m scripts.run_weekly_update --fast

---

## Layer Status

RAW CSVs: 15 raw CSVs present in data/imports/rankings/raw/2026/ (includes combine_2026.csv,
  nflcom_2026.csv, ngs_2026.csv).

STAGING: Staged CSVs present per source under data/imports/rankings/staged/2026/.

INGEST: Operational. 30 sources (14 active canonical), source_players: 8916,
  source_rankings: 29947.
  analyst_grade column active on source_rankings (migration 0038). Populated for
  bleacherreport_2026 only.
  combine_2026.csv → combine_ranks_2026 (source_id=28): 735 rows. Also writes
    hand_size/arm_length/wingspan to ras (migration 0039).
  nflcom_2026.csv → nflcom_2026 (source_id=30, T2 1.0): 303 rows. NFL.com editorial big board.
  ngs_2026.csv → ngs_2026 (source_id=29, is_active=0): 312 rows. ngs_score in grade column.
    Not in consensus — model score, not scout ranking.

BOOTSTRAP: Operational. prospects: 4482 total (active managed by is_active flag).

UNIVERSE: Operational. data/universe/prospect_universe_2026.csv (861 players).
  Migration 0033 applied.

CONSENSUS: Operational. 849 rows (14 active sources, Session 23b).
  Top: Sonny Styles LB | Fernando Mendoza QB | Caleb Downs S.
  Styles #1 is genuine multi-source convergence — confirmed after NGS deactivation.

MODEL OUTPUTS: Operational. 615 rows (Session 16 rebuild).
  Not yet rebuilt for Session 23 consensus expansion.

SNAPSHOTS: Operational. Latest: snapshot_id=3 (2026-03-12). rows=615, coverage=615,
  confidence=615 — PASSED.
  Full pipeline: build_consensus → snapshot_board → compute_snapshot_metrics →
  compute_source_snapshot_metrics → compute_snapshot_coverage →
  compute_snapshot_confidence → verify_snapshot_integrity

APEX: Operational. 58 active 2026 scored prospects + 12 calibration artifacts
  (is_active=0, is_calibration_artifact=1, excluded from board).
  Tiers: ELITE=3, DAY1=21, DAY2=30, DAY3=4.
  Divergence: ALIGNED=17, APEX_HIGH=23, APEX_LOW=0, APEX_LOW_PVC_STRUCTURAL=18.
  Latest backup: data/apex_top50_rescored_session15.json.
  Love (pid=61): RB-1 59.8 DAY2 Tier A v_injury=9.0 (carry clock CLEAR, Session 21).
  Migrations applied: 0001–0039. Next migration: 0040.
  NOTE: Current APEX scores use pre-archetype trait vectors from Session 4. Top-50 re-score
  with positional libraries is pending.

TAGS: Operational. Session 24 trigger engine built and active.
  Scripts: run_tag_triggers_2026.py (engine), accept_tag_recs_2026.py (workflow),
    draftos/tags/evaluator.py (pure function library).
  Schema: tag_definitions=27, tag_trigger_rules=14.
  Rec status: accepted=55, dismissed=22, pending=0.
  Active tags: Development Bet=28, Compression Flag=13, Divergence Alert=7, Elite RAS=4,
    Poor RAS=1, Great RAS=1, Injury Flag=1.

EXPORTS: board_2026_v1_default.csv last produced Session 21. Current for that snapshot.

---

## Ordered TODOs

1. ~~Session 4: APEX top-50 batch scoring~~ COMPLETE
2. ~~Session 5: Add positional archetype libraries to prompts.py~~ COMPLETE
3. ~~Session 6: RAS join fix, ghost prospect audit~~ COMPLETE
4. ~~Session 7: Top-50 force re-score (positional archetypes), calibration artifact tagging~~ COMPLETE
5. ~~Session 8: Prospect universe migration (migration 0033, is_active, consensus rebuild)~~ COMPLETE
6. ~~Session 9: Re-score top-50 APEX with --force against updated consensus ranks~~ COMPLETE
7. ~~Session 10: Divergence engine recalibration (rank-relative method, migration 0035)~~ COMPLETE
8. ~~Session 12: Emergency database rebuild~~ COMPLETE
9. ~~Session 13: Full clean weekly pipeline run — all 18 steps~~ COMPLETE
10. ~~Session 13b: School canonicalization + GEN archetype reclassification~~ COMPLETE
11. ~~Session 14: APEX tier label standardization (DAY1/DAY2/DAY3)~~ COMPLETE
12. ~~Session 15: Full board audit, stale override ID fix, 9 re-scores, calibration tagging~~ COMPLETE
13. ~~Session 16: bleacherreport_2026 ingest (source_id=27, T2), analyst_grade capture~~ COMPLETE
14. ~~Session 18: Kilgore re-score (CB-3 ELITE → S-3 DAY2 63.1), tag trigger engine~~ COMPLETE
15. ~~Session 19: Tag acceptance workflow (accept_tag_recommendations_2026.py)~~ COMPLETE
16. ~~Session 20: Divergence Alert triage (6 accepted, 12 dismissed, 1 held)~~ COMPLETE
17. ~~Session 21: Love re-score (RB-1 59.8), Dev Bet triage (28 accepted), Compression Flag triage~~ COMPLETE
18. ~~Session 23: combine_ranks_2026 ingest (source_id=28), ngs_2026 ingest (source_id=29)~~ COMPLETE
19. ~~Session 23b: Source key correction, nflcom_2026 ingest (source_id=30), ngs deactivated~~ COMPLETE
20. ~~Session 24: Tag trigger engine built (evaluator.py, run_tag_triggers_2026, accept_tag_recs_2026)~~ COMPLETE
21. **Full clean weekly pipeline run end-to-end (18 steps)** ← NEXT
22. RAS re-ingest after pro days complete — run ingest_ras_2026.py with updated file
23. APEX top-50 re-score with positional archetype libraries (current use generic Session 4 vectors)
24. Post-draft audit framework activation (after April 2026 draft)

---

## APEX Status

- Version: v2.2
- Active 2026 scored: 58 (is_active=1, is_calibration_artifact=0)
- Calibration artifacts: 12 (PIDs: 230,304,313,455,504,880,1050,1278,1371,1391,1729,1925)
- Tier dist: ELITE=3, DAY1=21, DAY2=30, DAY3=4
- Divergence: ALIGNED=17, APEX_HIGH=23, APEX_LOW=0, APEX_LOW_PVC_STRUCTURAL=18
- Top APEX_HIGH (premium positions, actionable): Thieneman S +23, Mesidor EDGE +16,
  Josephs EDGE +26, Howell EDGE +8
- CRITICAL: TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py
  corrected Session 15. If DB is ever rebuilt, re-verify ALL prospect_ids in both dicts.
- Known issue: Akheem Mesidor shows EDGE-1 but correct eval is EDGE-4. Needs re-score.
- APEX LOW on non-premium positions (ILB, OLB, OG, C, TE, RB) is structural PVC, not
  actionable. Monitor APEX_HIGH on premium positions (QB, CB, EDGE, OT, S) only.

---

## Divergence Status

- JALON KILGORE CB (pid=449, consensus=210): CB-3 ELITE 90.0, APEX_HIGH +209.
  Re-scored to S-3 DAY2 63.1 Session 18. Divergence Alert rec held pending combine
  man-coverage confirmation. Do NOT cite as signal until resolved.
- KYRON DRONES QB (pid=1420, consensus=351): QB-5 DAY3 49.1, APEX_HIGH +294.
  Very low consensus rank. Verify correct player in DB before acting on divergence.
- D'Angelo Ponds (pid=3236): no consensus rank row — excluded from divergence recompute.
  Non-blocking.

---

## Source Registry (Active)

14 active canonical sources:

| ID | Key | Tier | Weight |
|----|-----|------|--------|
| 2  | pff_2026 | T1 | 1.3 |
| 3  | thedraftnetwork_2026 | T1 | 1.3 |
| 4  | theringer_2026 | T1 | 1.3 |
| 5  | nfldraftbuzz_2026_v2 | T2 | 1.0 |
| 6  | cbssports_2026 | T2 | 1.0 |
| 7  | espn_2026 | T2 | 1.0 |
| 8  | nytimes_2026 | T2 | 1.0 |
| 9  | pfsn_2026 | T2 | 1.0 |
| 10 | jfosterfilm_2026 | T2 | 1.0 |
| 25 | bnbfootball_2026 | T3 | 0.7 |
| 26 | tankathon_2026 | T3 | 0.7 |
| 27 | bleacherreport_2026 | T2 | 1.0 |
| 28 | combine_ranks_2026 | T2 | 1.0 |
| 30 | nflcom_2026 | T2 | 1.0 |

Inactive (data preserved): ngs_2026 (source_id=29, is_active=0) — model score, not ranking.
