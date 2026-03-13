# DraftOS State Snapshot

Last Updated (UTC): 2026-03-13T19:11:17.205045+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

Sessions 34–36 — Prospect detail expander, unified detail panel, clickable rows, UI polish.

Session 34: APEX Board prospect detail expander.
- draftos/queries/apex.py: get_apex_detail() added. JOINs apex_scores+prospects, returns full
  trait vector dict. two_way_premium derived from apex_scores.tags comma field.
- app.py: _render_apex_detail() helper added. Inspect selectbox under APEX Board → expander.

Session 35: Unified prospect detail panel + clickable board rows.
- Streamlit 1.53.0 → Plan A (on_select="rerun", selection_mode="single-row").
- Big Board and APEX Board both use on_select. Row click writes selected_pid to session_state.
- Row alignment: _bb_prospect_ids / _apex_prospect_ids lists pre-captured before display builds.
- Old "Prospect Detail Drawer" (250-line inline render) removed.
- Old Session 34 "apex_inspect_select" selectbox removed.
- _render_consensus_card() added for unscored prospects. _ON_SELECT_AVAILABLE constant added.
- Single unified "📋 Prospect Detail" panel at page bottom.

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

- Session 37: APEX top-50 re-score with positional archetype libraries.
  Detail panel and tabbed boards are fully wired. Every trait vector currently shows generic
  ~8.5–9.5 placeholder values from the pre-library scoring pass. Re-score will produce
  differentiated, position-specific trait vectors that make the detail card meaningful.
  Command: python -m scripts.run_apex_scoring_2026 --batch top50 --force --apply 1
  Always export after: sqlite3 .\data\edge\draftos.sqlite ".mode json" ".output data/apex_top50_rescored_session37.json" "SELECT * FROM apex_scores;"

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

APEX: Operational. 59 active 2026 scored prospects (50 top-consensus re-scored Session 26) +
  12 calibration artifacts (is_calibration_artifact=1, excluded from board).
  Tiers (active non-cal): ELITE=3, DAY1=23, DAY2=31, DAY3=5.
  Divergence: ALIGNED=16, APEX_HIGH=26, APEX_LOW=0, APEX_LOW_PVC_STRUCTURAL=20.
  Latest backup: data/apex_top50_rescored_session29.json (147KB).
  Love (pid=61): RB-1 59.8 DAY2 Tier A v_injury=9.0 (carry clock CLEAR, Session 21).
  Ramsey (pid=148): S-3 Multiplier Safety 61.4 DAY2. Re-scored Session 29 (was S-1 61.2).
    FM-2 Scheme Ghost + FM-3 Processing Wall. Tier B. R3. APEX_HIGH MODERATE +29.
  CALIBRATION_OVERRIDES: all 11 PIDs corrected Session 26.
  Max Klare (pid=6): position_group corrected LB→TE (Session 27). Re-scored TE-5 51.3 DAY3.
  Migrations applied: 0001–0039. Next migration: 0040.
  NOTE: All scores now use positional archetype library trait vectors (Session 26 re-score complete).

TAGS: Operational. Session 24 trigger engine built and active.
  Scripts: run_tag_triggers_2026.py (engine), accept_tag_recs_2026.py (workflow),
    draftos/tags/evaluator.py (pure function library).
  Schema: tag_definitions=27, tag_trigger_rules=14.
  Rec status: accepted=57, dismissed=29, pending=0.
  Active tags: Development Bet=28, Compression Flag=14, Divergence Alert=8, Elite RAS=4,
    Poor RAS=1, Great RAS=1, Injury Flag=1.
  Session 27 accepted: Josephs EDGE Compression Flag, Ramsey S Divergence Alert.
  Session 27 dismissed: Iheanachor Compression, Ponds Divergence, Howell/Faulk/Mcdonald/
    Cooper/Rutledge Dev Bet (all consensus rank <75, market priced).

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
32. **Session 37: APEX top-50 re-score — real trait vectors needed** ← NEXT
33. Post-draft audit framework activation (after April 2026 draft)

---

## APEX Status

- Version: v2.2
- Active 2026 scored: 59 (is_active=1, is_calibration_artifact=0, top 50 re-scored Session 26)
- Calibration artifacts: 12 (PIDs: 230,304,313,455,504,880,1050,1278,1371,1391,1729,1925)
  All re-scored Session 26 with correct PIDs and positions.
- Tier dist (active non-cal): ELITE=3, DAY1=23, DAY2=31, DAY3=5
- Divergence: ALIGNED=16, APEX_HIGH=26, APEX_LOW=0, APEX_LOW_PVC_STRUCTURAL=20
- Top APEX_HIGH (premium positions, actionable):
    Devin Moore CB: MAJOR +33 (previously MINOR — now the strongest actionable CB signal)
    Kamari Ramsey S: MODERATE +29 (S-3 re-score Session 29 — S-1→S-3 archetype corrected)
    Colton Hood CB: MODERATE +26
    Joshua Josephs EDGE: MODERATE +22
    Keith Abney CB: MODERATE +22
    Dillon Thieneman S: MINOR +8 (was MAJOR +23 — signal compressed after real trait vectors)
    Akheem Mesidor EDGE: ALIGNED +4 (was APEX_HIGH +16 — consensus was right, signal resolved)
- CRITICAL: TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py
  corrected Session 15. CALIBRATION_OVERRIDES corrected Session 26.
  If DB is ever rebuilt, re-verify ALL prospect_ids in ALL THREE dicts before running.
- APEX LOW on non-premium positions (ILB, OLB, OG, C, TE, RB) is structural PVC, not
  actionable. Monitor APEX_HIGH on premium positions (QB, CB, EDGE, OT, S) only.

---

## Divergence Status

- DEVIN MOORE CB (pid=37): APEX_HIGH MAJOR +33 — strongest actionable premium signal post Session 26.
  Was MINOR in prior sessions; re-score elevated. Review CB PAA before acting.
- KAMARI RAMSEY S (pid=148): APEX_HIGH MODERATE +29 — S-3 re-score Session 29. Premium. Actionable.
  S-3 Multiplier Safety confirmed. Zone-dominant production. Processing 7.0 — S-1 ruled out.
  FM-2 Scheme Ghost primary. FM-3 Processing Wall secondary. Tier B. R3 capital.
  Divergence Alert rec accepted (rec_id=85, Session 27).
- COLTON HOOD CB (pid=72): APEX_HIGH MODERATE +26 — persistent signal. CB-3 confirmed.
- JALON KILGORE CB (pid=449): APEX_HIGH MAJOR +260 — divergence artifact (CB entry for Safety).
  Re-scored to S-3 DAY2 63.1 Session 18. Divergence Alert rec held pending combine
  man-coverage confirmation. Do NOT cite as signal until resolved.
- D'ANGELO PONDS CB (pid=3236): APEX_HIGH MAJOR +95 — no consensus rank row. Non-blocking.
- KYRON DRONES QB (pid=1420, consensus=351): QB-5 DAY3 49.1, APEX_HIGH MAJOR +369.
  Very low consensus rank. Artifact.
- JALEN CATALON S (pid=1464): APEX_HIGH MAJOR +283 — artifact, very low consensus coverage.
- DILLON THIENEMAN S (pid=29): APEX_HIGH MINOR +8 — compressed from +23 after real trait vectors.
  Still positive signal but substantially less aggressive than prior sessions.

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
