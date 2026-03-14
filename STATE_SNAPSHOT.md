# DraftOS State Snapshot

Last Updated (UTC): 2026-03-14T04:45:18.835429+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

Session 39 — APEX scoring expansion (ranks 51-150) + housekeeping + Igbinosun PAA re-score.

Session 39:
- APEX v2.3 scoring expansion: 99 prospects ranked 51-150 scored. Total v2.3 non-cal: 149.
  Batch used --prospect-ids (targeted, no --force). Dry run confirmed 99 prospects, 0 failed.
  Quality check: PASS. Backup: data/apex_51_150_session5_scored.json (563KB).
- Ghost deactivation (housekeeping): pid=3559 Max Klare TE (__dedup_3559__) is_active=0.
  pid=4369 Max Klare LB (__dedup_4369__) is_active=0. Both confirmed dedup artifacts.
  pid=4347 D'Angelo Ponds LB (Tankathon only) is_active=0 — canonical is pid=3236 CB Indiana.
  div_id=697 (stale v2.2 divergence row for Ponds) deleted — div_id=966 (v2.3) retained.
- Igbinosun re-score (pid=36, CB, Ohio State): PAA gate injection applied.
  Session 5 batch scored CB-2 Zone Architect 76.4 DAY1 without PAA findings — incorrect.
  PAA re-score: CB-3 Press Man Corner 68.4 DAY2, Tier B, FM-2 CONDITIONAL, R2 early–R3 top.
  ARCHETYPE_OVERRIDES[36] added to run_apex_scoring_2026.py with 8 confirmed gate results.
  Divergence: APEX_HIGH +48 MAJOR → +23 MODERATE. CB-2 was over-scoring by ~8 pts.
  Override logged: PAA gate injection + capital revision per doctrine.
- Monitor tag added: tag_def_id=54 (editorial, gray, note_required=1).
  Applied to Julian Neal (pid=109, CB, rank=70): 3-cone gate trigger, R2 vs R3 hinge.
  Do not re-score until combine 3-cone data ingested.
- Divergence recomputed (149 prospects): ALIGNED=25, APEX_HIGH=67, APEX_LOW=3,
  APEX_LOW_PVC_STRUCTURAL=54.
- Doctor: PASSED.

Prior: Session 38 — Tag description fix + gitignore cleanup.

Session 38: Minimal maintenance session.
- tag_definitions: Updated 'Top 5 NextGen' description to accurate NGS composite explanation.
  Tag Legend in app pulls description dynamically — no app.py change needed.
- .gitignore: Added patterns to cover DB backup files (draftos.backup.*, *.sqlite.backup.*),
  data/*.json session exports, data/edge/ directory, and *.docx files.
  This unblocked end_session.py which requires a clean working directory.
- No DB schema changes. No migrations. No script changes.
- Doctor: PASSED. No pipeline changes.

Prior: Session 37 — APEX top-50 re-score with positional archetype libraries + UI tag/detail card overhaul.

Session 37: APEX top-50 re-score (50 prospects) + UI fixes.
- app/app.py: Unified tag rendering. Board Tags column and Tagged expander pills now use same
  _render_tag_pill() function and same _TAGS_DISPLAY_MAP lookup. Root cause was _TAG_LABEL_MAP
  (emoji-short) vs _TAGS_DISPLAY_MAP (full label) divergence — both now use _TAGS_DISPLAY_MAP.
  _TAG_COLOR_MAP removed. New _TAG_PILL_COLORS 3-tuple dict (bg/border/text) covers all 32 tags.
- app/app.py: Prospect detail card redesigned. Colored HTML trait bars via _trait_bar_html().
  APEX tier badge with fill color (_APEX_TIER_BADGE dict). Position badge (_POS_BADGE_COLORS dict).
  Dynamic bullet points from _generate_bullets() — threshold-based from trait scores, not echoing
  summary text. Radio toggle preserved (Summary / Bullet Points) namespaced by prospect_id.
- run_apex_scoring_2026.py: pid=136 (Keylan Rutledge, position_raw='G') added to
  TOP50_POSITION_OVERRIDES as "OG". 'G' not in _CLEAN_POSITIONS → would have scored as OL.
- APEX top-50 batch: 50 prospects scored, 0 failed. All positional archetype libraries applied.
  Notable: Fernando Mendoza QB-1 86.4 ELITE | David Bailey EDGE-1 88.4 ELITE | Rueben Bain 87.1
  Caleb Downs S-1 81.4 DAY1 | Jermod McCoy CB-1 82.1 DAY1 (FM-4 Medical Flag Active).
  5 new prospects scored: Concepcion ILB-3 59.8, Trotter ILB-3 62.7, Simpson ILB-3 61.0,
  Ioane OG-1 59.0, Rutledge OG-3 54.6 DAY3.
- Divergence recomputed (59 active non-cal): ALIGNED=20, APEX_HIGH=26, APEX_LOW=0, APEX_LOW_PVC_STRUCTURAL=16.
- Backup: data/apex_top50_rescored_session37.json (144KB).
- Doctor: PASSED. No schema changes. No migrations.

Prior: Sessions 34–36 — Prospect detail expander, unified detail panel, clickable rows, UI polish.

Session 36: Tabbed boards, tag display overhaul, detail card polish, color disambiguation.
- Tabbed boards: st.tabs(["📋 Big Board", "⚡ APEX Board — N scored"]).
  Tagged prospects expander inside Big Board tab. APEX Board inside APEX tab.
  Free-standing tier legend captions removed — content moved into Column Guide expander.
- Tags: _TAGS_DISPLAY_MAP expanded to all 28 DB tag_names. "APE" bug fixed —
  _fmt_tags_text was using t[:3].upper() fallback → now uses _TAGS_DISPLAY_MAP + raw tag_name.
  Both _fmt_tags and _fmt_tags_text use two-space separator.
- Color disambiguation: "Tier" column renamed "Consensus" in display DataFrame.
  _style_consensus_tier() added (text-color only). APEX Tier keeps background-fill badge.
  Visual contract: Consensus = text color · APEX Tier = filled badge.
- Detail card (_render_apex_detail):
  Character sub-scores → plain English (Off-field record / Motor & drive / Mental makeup).
  Schwesinger/Smith rule badges → plain English descriptions, one per line.
  Archetype gap → "Archetype fit: N pts — [Clean/Solid/Tweener context]".
  Strengths/Red Flags → radio toggle Summary vs Bullet Points (key namespaced by prospect_id).
- No DB changes. No migrations. No query changes. app.py only.
- Doctor: PASSED (no pipeline changes).

Prior: Session 29 — RAS re-ingest (pro day scores) + Kamari Ramsey S-3 re-score.

- Tag pills: "Tags" column added to main board dataframe. Emoji text labels per tag type
  (⚡ DIV, 📈 DEV, ⚖ COMP, 🔥 ERAS, ✓ GRAS, ⚠ PRAS, 🩹 INJ). 44 tagged prospects visible.
- Tag filter: sidebar checkboxes (7 tag types), OR logic. Selecting any tag collapses board
  to matching prospects. Uncheck all = full board restored.
- Tagged prospects expander: colored HTML pill badges (amber/blue/purple/green/teal/red/orange)
  rendered via st.markdown unsafe_allow_html. Each tagged row shows rank + APEX + pills.
- Coverage fix: get_big_board() now LEFT JOINs prospect_board_snapshot_coverage on
  snapshot_id + prospect_id. prospect_board_snapshot_rows.coverage_count was always NULL.
  Sadiq now shows coverage=14 (was NULL/0). All 995 board rows fixed.
- APEX tier sort: _apex_tier_sort integer key added (ELITE=0, DAY1=1 ... UDFA=5).
  Hidden from display. APEX scores panel now pre-sorted ELITE→DAY1→DAY2→DAY3.
- Em dash: APEX and Δ APEX cells show — instead of blank for unscored prospects.
- Tag legend: collapsible sidebar expander below tag checkboxes. Describes all 7 tag types.
- Column guide: collapsible expander above the board. Markdown table defining all 14 columns.
- Files changed: app/app.py, draftos/queries/model_outputs.py.
- Doctor: PASSED. No schema changes. No pipeline changes.

Prior: Session 27 — Max Klare position fix (LB→TE) + tag rec triage (9 pending → 0 pending).

- Max Klare (pid=6): position_group updated LB→TE. Two inactive duplicate rows deactivated
  (pid=3559 TE Ohio State, pid=4369 LB dedup) after UNIQUE constraint blocked direct update.
  pid=3559 school_canonical set to __dedup_3559__ to free unique slot. Re-scored as TE-5
  Raw Projection, 51.3 DAY3. Divergence recomputed (no change in distribution).
- Tag rec triage: 9 pending → 0 pending.
  Accepted (2): Josephs EDGE Compression Flag (TWEENER +4.2), Ramsey S Divergence Alert (+28).
  Dismissed (7): Iheanachor LB Compression (SOLID not tweener), Ponds CB Divergence (artifact),
  all 5 Dev Bet recs (Howell/Faulk/Mcdonald/Cooper/Rutledge — consensus ranks 18–47, market
  has priced development trajectory, Dev Bet requires rank >75 to be informative).
- Rec status: accepted=57, dismissed=29, pending=0.
- Doctor: PASSED. Snapshot integrity: PASSED.

Prior: Session 26 — APEX full re-score: calibration batch (11) + top-50 batch (50) with positional libraries.

- CRITICAL FIX: CALIBRATION_OVERRIDES prospect_ids were all stale pre-rebuild PIDs (e.g.,
  Schwesinger=1464/Jalen Catalon, Hunter=885/Travis Kelce, Ezeiruaku=1420/Kyron Drones).
  All 11 corrected to post-rebuild PIDs: Schwesinger=1925, Hunter=455, Sanders=230,
  Membou=1371, Ratledge=880, Etienne=304, Emmanwori=1278, Ezeiruaku=1729,
  Williams=1050, Paul=504, Wilson=1391. Session 26 annotations added.
- Calibration batch (11 prospects): all re-scored with correct players and correct positions.
  Key changes: Sanders DAY2 67.0→DAY1 78.9 (was scoring Tyler Allgeier), Etienne DAY3→DAY2 57.7
  (was scoring Kaimi Fairbairn), Emmanwori ILB-1 DAY1→S-2 DAY2 (correct position now),
  Hunter ELITE 91.2→DAY1 84.8 CB-3 (correct player), Ratledge now OG-1 (was TE-4).
- Top-50 batch: 50 prospects re-scored with --force. All positional archetype libraries applied.
  Notable changes: David Bailey EDGE-1 82.1→88.7 ELITE (largest upgrade), Mesidor APEX_HIGH +16
  resolved to ALIGNED +4 (consensus was right), Thieneman divergence compressed +23→+8.
- New signals: Devin Moore CB APEX_HIGH MAJOR +33, Kamari Ramsey S APEX_HIGH MODERATE +28.
- Divergence recomputed (62 prospects): ALIGNED=16, APEX_HIGH=26, APEX_LOW=0, APEX_LOW_PVC_STRUCTURAL=20.
- Tag triggers: 9 new pending recs (5 Dev Bet, 2 Compression, 2 Divergence Alert).
  Pending: Josephs EDGE/Iheanachor LB (Compression), Howell EDGE/Mcdonald DT/Faulk EDGE/
  Rutledge OL/Cooper LB (Dev Bet), Ponds CB/Ramsey S (Divergence Alert).
- Backup: data/apex_top50_rescored_session26.json (147KB).
- Doctor: PASSED. Snapshot integrity: PASSED (snapshot_id=3, rows=995).

Prior sessions: 27 (Klare fix + tag triage), 26 (APEX full re-score, CALIBRATION_OVERRIDES fix), 25 (weekly pipeline),
  24 (tag trigger engine), 23b (source key correction), 23 (combine+NGS ingest),
  21 (dev bet triage), 20 (divergence triage), 19 (tag acceptance workflow),
  18 (Kilgore re-score, trigger engine seed), 16 (bleacherreport ingest),
  15 (APEX board audit + override fix), 13b (school/archetype fix), 13 (weekly pipeline),
  12 (DB rebuild).

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

- Session 40: Score ranks 151-250 (same pattern — build target PID list, dry run, live score).
  Then: tag trigger re-run against all 149 v2.3 scores (new scores may fire new recs).
  Then: triage any new pending recs. Neal MONITOR tag — hold until combine 3-cone data.
  Commands:
    python -m scripts.evaluate_tag_triggers_2026 --apply 1
    python -m scripts.accept_tag_recs_2026 --list

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

CONSENSUS: Operational. 995 rows (14 active sources, Session 25 rebuild).
  Top: Sonny Styles LB | Fernando Mendoza QB | Caleb Downs S.
  Styles #1 is genuine multi-source convergence — confirmed after NGS deactivation.

MODEL OUTPUTS: Operational. 999 rows (Session 25 rebuild — grew from 615 with 14 active sources).

SNAPSHOTS: Operational. Latest: snapshot_id=3 (2026-03-12). rows=995, coverage=995,
  confidence=995 — PASSED (Session 25 rebuild).
  Full pipeline: build_consensus → snapshot_board → compute_snapshot_metrics →
  compute_source_snapshot_metrics → compute_snapshot_coverage →
  compute_snapshot_confidence → verify_snapshot_integrity

APEX: Operational. 149 active 2026 scored prospects (non-cal, v2.3) + 12 calibration artifacts.
  Scored coverage: ranks 1-150 (with some gaps — targeted PID list method).
  Tiers (v2.3 active non-cal): ELITE=3, DAY1=28, DAY2=73, DAY3=40, UDFA-P=5 (Session 39).
  Divergence (149 prospects, Session 39): ALIGNED=25, APEX_HIGH=67, APEX_LOW=3,
    APEX_LOW_PVC_STRUCTURAL=54.
  Latest backup: data/apex_51_150_session5_scored.json (563KB).
  Igbinosun (pid=36): CB-3 Press Man Corner 68.4 DAY2, Tier B, FM-2 CONDITIONAL, R2 early–R3 top.
    PAA gate injection applied Session 39. Prior score (CB-2 76.4) corrected. Delta: +23 MODERATE.
  Love (pid=61): RB-1 59.8 DAY2 Tier A v_injury=9.0 (carry clock CLEAR, Session 21).
  Ramsey (pid=148): S-3 72.6 DAY2 Tier B R3. APEX_HIGH MODERATE +29 (Session 39 divergence).
  Neal (pid=109): MONITOR tag active — 3-cone gate pending. Do not re-score until combine data.
  CALIBRATION_OVERRIDES: all 11 PIDs corrected Session 26.
  Max Klare (pid=6): position_group corrected LB→TE (Session 27). Re-scored TE-5 51.3 DAY3.
  Keylan Rutledge (pid=136): TOP50_POSITION_OVERRIDES OG added Session 37 (position_raw='G' fix).
  Igbinosun (pid=36): ARCHETYPE_OVERRIDES[36] added Session 39 with PAA gate findings.
  Ghost cleanup (Session 39): pid=3559, 4369 (Klare dups) is_active=0. pid=4347 (Ponds LB) is_active=0.
  Migrations applied: 0001–0039. Next migration: 0040.
  Tag trigger re-run pending — 149 v2.3 scores not yet evaluated against trigger rules.

TAGS: Operational. Session 24 trigger engine built and active.
  Scripts: run_tag_triggers_2026.py (engine), accept_tag_recs_2026.py (workflow),
    draftos/tags/evaluator.py (pure function library).
  Schema: tag_definitions=28 (added Monitor id=54 Session 39), tag_trigger_rules=14.
  Rec status: accepted=57, dismissed=29, pending=0.
  Active tags: Development Bet=28, Compression Flag=14, Divergence Alert=8, Elite RAS=4,
    Poor RAS=1, Great RAS=1, Injury Flag=1, Monitor=1 (Neal pid=109).
  Monitor tag (id=54, Session 39): editorial, gray, note_required=1.
    Applied to Julian Neal CB — 3-cone gate pending.
  Tag trigger re-run NOT yet executed against 149 v2.3 scores — will fire Session 40.

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
21. ~~Session 25: Full clean weekly pipeline run end-to-end (18 steps)~~ COMPLETE
22. ~~Session 26: APEX full re-score — calibration (11) + top-50 (50), CALIBRATION_OVERRIDES PIDs fixed~~ COMPLETE
23. ~~Session 27: Max Klare LB→TE fix + 9 pending tag recs triaged~~ COMPLETE
24. ~~Session 28: Tag UI live — pills, filter, coverage fix, APEX sort, legend, column guide~~ COMPLETE
25. ~~Session 29: RAS re-ingest (814 rows, 95 scored) + Ramsey S-3 re-score~~ COMPLETE
26. ~~Session 29: Kamari Ramsey S-3 re-score — APEX_HIGH MODERATE +29~~ COMPLETE
27. ~~Session 30–31: Prospect detail drawer + UI polish (score fmt, gap labels, column alignment)~~ COMPLETE
28. ~~Session 32–33: Auto-APEX-Rank + APEX Board v2.2 + tag filter~~ COMPLETE
29. ~~Session 34: APEX Board prospect detail expander (get_apex_detail, _render_apex_detail)~~ COMPLETE
30. ~~Session 35: Unified detail panel, clickable board rows, on_select API~~ COMPLETE
31. ~~Session 36: Tabbed boards, tag overhaul, detail card polish, color disambiguation~~ COMPLETE
32. ~~Session 37: APEX top-50 re-score — real trait vectors, UI tag/detail card overhaul~~ COMPLETE
33. ~~Session 38: Minimal maintenance — Top 5 NextGen tag description fix + gitignore cleanup~~ COMPLETE
34. ~~Session 39: APEX ranks 51-150 scoring expansion (99 prospects) + Igbinosun PAA re-score~~ COMPLETE
35. **Session 40: Score ranks 151-250 + tag trigger re-run against all 149 v2.3 scores** ← NEXT
36. Post-draft audit framework activation (after April 2026 draft)

---

## APEX Status

- Version: v2.2 (scorer engine) / v2.3 (model_version written to DB)
- Active 2026 scored: 149 (v2.3, is_active=1, is_calibration_artifact=0)
- Calibration artifacts: 12 (PIDs: 230,304,313,455,504,880,1050,1278,1371,1391,1729,1925)
  All re-scored Session 26 with correct PIDs and positions.
- Tier dist (v2.3 active non-cal, Session 39): ELITE=3, DAY1=28, DAY2=73, DAY3=40, UDFA-P=5
- Divergence (Session 39, 149 prospects): ALIGNED=25, APEX_HIGH=67, APEX_LOW=3,
  APEX_LOW_PVC_STRUCTURAL=54
- Notable Session 39 additions:
    Davison Igbinosun CB: PAA-corrected 68.4 DAY2 CB-3, Tier B, FM-2 CONDITIONAL, +23 MODERATE
    Julian Neal CB: MONITOR tag active — 3-cone gate pending (sub-6.9s = R2, above = R3)
- Top APEX_HIGH premium signals (actionable — Session 39 divergence):
    Domani Jackson CB +88 MAJOR | Mansoor Delane CB +63 MAJOR | Romello Height EDGE +49 MAJOR
    Tacario Davis CB +49 MAJOR | Julian Neal CB +48 MAJOR | Jadon Canady CB +48 MAJOR
    Jaishawn Barham EDGE +53 MAJOR | Chandler Rivers CB +36 MAJOR | Jude Bowry EDGE +41 MAJOR
    Michael Taaffe S +36 MAJOR | Garrett Nussmeier QB +37 MAJOR | Kamari Ramsey S +29 MODERATE
    Davison Igbinosun CB +23 MODERATE | Keyron Crawford EDGE +22 MODERATE | Derrick Moore EDGE +21 MODERATE
  (D'Angelo Ponds CB +91 is artifact — duplicate divergence source, exclude)
  (Jalon Kilgore S +38 held — combine man-coverage gate pending)
- CRITICAL: TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py
  corrected Session 15. CALIBRATION_OVERRIDES corrected Session 26.
  Rutledge (pid=136) OG added to TOP50_POSITION_OVERRIDES Session 37.
  Igbinosun (pid=36) PAA gate injection added to ARCHETYPE_OVERRIDES Session 39.
  If DB is ever rebuilt, re-verify ALL prospect_ids in ALL THREE dicts before running.
- APEX LOW on non-premium positions (ILB, OLB, OG, C, TE, RB) is structural PVC, not
  actionable. Monitor APEX_HIGH on premium positions (QB, CB, EDGE, OT, S) only.

---

## Divergence Status

Current recompute: Session 39 (149 v2.3 prospects). Total APEX_HIGH=67, APEX_LOW=3.

Premium actionable signals (confirmed, non-artifact):
- DOMANI JACKSON CB (pid=108): APEX_HIGH MAJOR +88 — rank #150. New signal from 51-150 batch.
- JAISHAWN BARHAM EDGE (pid=258): APEX_HIGH MAJOR +53 — rank #122. New from batch.
- ROMELLO HEIGHT EDGE (pid=43): APEX_HIGH MAJOR +49 — rank #68. New from batch.
- TACARIO DAVIS CB (pid=159): APEX_HIGH MAJOR +49 — rank #123. New from batch.
- JULIAN NEAL CB (pid=109): APEX_HIGH MAJOR +48 — rank #70. MONITOR tag active (3-cone gate).
- JADON CANADY CB (pid=252): APEX_HIGH MAJOR +48 — rank #139. New from batch.
- JUDE BOWRY EDGE (pid=115): APEX_HIGH MAJOR +41 — rank #144. New from batch.
- KAMARI RAMSEY S (pid=148): APEX_HIGH MODERATE +29 — S-3 confirmed. R3 capital.
- DAVISON IGBINOSUN CB (pid=36): APEX_HIGH MODERATE +23 — PAA-corrected Session 39. CB-3 68.4.
- COLTON HOOD CB (pid=72): APEX_HIGH MODERATE +26 — persistent. CB-3 confirmed.
- KEYRON CRAWFORD EDGE (pid=116): APEX_HIGH MODERATE +22 — rank #101. New from batch.
- DERRICK MOORE EDGE (pid=81): APEX_HIGH MODERATE +21 — rank #59. New from batch.
- MANSOOR DELANE CB (pid=3509): APEX_HIGH MAJOR +63 — rank #96. New from batch.
- CHANDLER RIVERS CB (pid=34): APEX_HIGH MAJOR +36 — rank #80. Confirmed from batch.
- MICHAEL TAAFFE S (pid=310): APEX_HIGH MAJOR +36 — rank #140. New from batch.
- GARRETT NUSSMEIER QB (pid=58): APEX_HIGH MAJOR +37 — rank #115. New from batch.
- DEVIN MOORE CB (pid=37): Prior APEX_HIGH — verify with tag triage post-batch.
- DILLON THIENEMAN S (pid=29): APEX_HIGH MINOR +12 — minor signal.

Artifacts / held:
- D'ANGELO PONDS CB (pid=3236): +91 MAJOR — artifact (dup divergence source; pid=4347 deactivated S39).
- JALON KILGORE S (pid=309): +38 MAJOR — held pending combine man-coverage confirmation.
- JALON KILGORE CB (pid=449): large delta — CB entry for Safety; position artifact.
- KYRON DRONES QB (pid=1420, rank=351): +369 — very low consensus rank artifact.
- JALEN CATALON S (pid=1464): large delta — very low consensus coverage artifact.

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
