# DraftOS State Snapshot

Last Updated (UTC): 2026-03-16T01:01:25.867853+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone

Session 49 (apex_favors_text, PDF polish — FM legend, white text, bullet unclip) — Migration 0045 applied.

Session 49:
- Migration 0045: ALTER TABLE divergence_flags ADD COLUMN apex_favors_text TEXT.
  Populated at divergence-write time by run_apex_scoring_2026.py --batch divergence.
  APEX_HIGH/APEX_LOW_PVC_STRUCTURAL → mechanism name + " profile" (e.g. "Elite Pass Rusher profile").
  APEX_LOW → FM code + title-cased label + " risk" (e.g. "FM-2 Conditional risk").
  ALIGNED → NULL. 114/144 rows populated; 30 ALIGNED rows correctly NULL.
- run_apex_scoring_2026.py: _make_apex_favors_text() helper added. Divergence SELECT extended
  to include matched_archetype + failure_mode_primary from apex_scores (no extra join).
  apex_favors_text written to divergence_flags INSERT (19 columns → 19 values).
- generate_prospect_pdf_2026.py:
  1. FM legend: white 6.5pt monospace line below FM risk bar showing active FM names
     (e.g. "FM-3 Processing Wall  ·  FM-6 Role Mismatch"). No dict needed — name from stored string.
  2. overflow:hidden removed from .rp CSS — fixes sf-box bullet clipping in Chromium flex/grid layout.
     html,body overflow:hidden still enforces page boundary.
  3. Bullet char limit raised 165→360 — eliminates mid-sentence … truncation in strengths/red_flags.
  4. capital_context font-size 6.5px→8px, line-height 1.4→1.5 (readability on mobile).
  5. All grey text (#aaa, #bbb, #999, #666, #e0e0e0, #d0d0d0, #b8c4d8) → #ffffff.
  6. divergence_narrative: uses apex_favors_text from DB instead of fallback "mechanism traits".
- app/app.py: all grey text (#A0AEC0, #718096, #999, #666, #888, #bbb, #e0e0e0, #E2E8F0) → #ffffff.
- Doctor: PASSED. No pipeline changes. Sources/consensus/snapshot unchanged.
- KNOWN ISSUE (pending): pid=27 (TJ Parker EDGE Clemson) — duplicate active pids with stale
  display_name formatting. Audit query provided; fix deferred to next session.

Session 48 (PDF generator v4 — bullets fix, contrast pass, positional badge gate, Concepcion remediation) — No migrations. No schema changes. Code-only + one DB data fix (Concepcion).

Session 48:
- generate_prospect_pdf_2026.py v4: Full rebuild with four layers of fixes:
  1. Bullets fix: _bullets() was splitting on \n only — but APEX scoring pipeline stores
     strengths/red_flags as prose paragraphs (3 sentences, no newlines). Added sentence-boundary
     fallback: re.split(r'(?<=[.!?])\s+(?=[A-Z])', text) when no \n present. Now returns 3 bullets.
  2. Contrast pass (full): three-tier color hierarchy applied —
     #999 (least important: scarcity note, comp italic mech, PVC footnote, "Pending evaluation.")
     #aaa (secondary labels: footer, Eval Confidence, Divergence label, section nav labels,
           .slbl, .arch-code, radar SVG axis labels, comp era bracket, FM tag non-active, Archetype Pending)
     #bbb (muted body: trait labels .tl, .badge default, comp summary body text)
     FM inactive segment label: #888 (clearly "off" but legible)
  3. Positional rank badge gate: pos_rank_s only rendered when pos_rank != rank.
     Suppressed when both numbers are equal (e.g. #1 overall who is also #1 at position).
  4. Layout fixes from prior session: radar flex-wrap, sf-box min-height:0,
     divergence callout moved inside .comps-region, rp-footer margin-top removed, SVG 100%/viewBox.
- fix_concepcion_2026.py (new): KC Concepcion remediation — deactivated ghost pids 3516/4324,
  fixed display_name casing "Kc"→"KC", wiped 2 ILB apex_scores rows, wiped divergence_flags.
  Re-scored as WR: WR-1 Route Technician 66.1 DAY2.
- audit_position_overrides_2026.py (new): read-only audit of all 27 TOP50_POSITION_OVERRIDES
  against canonical DB position_group. All 27 clean post-Concepcion removal.
- run_apex_scoring_2026.py: removed stale TOP50_POSITION_OVERRIDES[3] ILB entry for Concepcion.
  Scoring priority: TOP50_POSITION_OVERRIDES → position_raw → position_group.
- KNOWN GAP (migration pending): divergence_flags.apex_favors is stored as INTEGER (0/1 boolean),
  not TEXT. Divergence narratives in PDF fall back to "mechanism traits" for all prospects.
  Migration needed: ALTER TABLE divergence_flags ADD COLUMN apex_favors_text TEXT;
  populate from run_apex_scoring_2026.py scoring pipeline at divergence-write time.
- Doctor: PASSED. No DB schema changes. No migrations.

Session 47 (PDF generator polish — viewport fix, tier palette alignment, comp flexbox, data fix) — No migrations. No schema changes. Code-only + one DB data fix.

Session 47:
- generate_prospect_pdf_2026.py: Four targeted fixes applied.
  1. Viewport fix: `await page.set_viewport_size({"width": 1056, "height": 816})` added before
     page.goto() — forces Chromium render viewport to match PDF canvas exactly, eliminating dead space.
  2. Trait color thresholds tightened: 5-level gradient (9.0+ teal, 8.0+ green, 6.5+ gold, 5.0+ orange, below red).
     Prior 4-level thresholds (8.5/7.0/5.5) were too loose for typical APEX score distributions.
  3. TIER_PALETTE updated to match Big Board exactly:
     ELITE dark gold #b8860b | DAY1 green #1a7a1a | DAY2 navy #005090 | DAY3 burnt orange #cc5500
     UDFA-P purple #6a1a8a | UDFA slate #455a64. tier-badge CSS uses badge_bg (not raw tc hex).
  4. comp_block header: replaced table layout with flexbox div row — eliminates player name centering
     artifact. All four header elements (role label / player name / outcome / era) left-aligned in flex row.
- historical_comps DB fix: comp_id=22 "Adrian Peterson (CB)" corrected to "Patrick Peterson" on CB-1.
  Was causing wrong comp name on McCoy and other CB-1 prospects.
- debug_render.html added to .gitignore.
- No pipeline changes. No doctor required (no DB schema changes).

Prior: Session 46 (historical comp layer + PDF generator rebuild) — Migration 0044 applied. 80 historical comp records seeded (QB/CB/EDGE/WR). PDF generator rebuilt from ReportLab → Playwright HTML→PDF. Streamlit asyncio/NotImplementedError fixed via threading + WindowsProactorEventLoopPolicy.

Session 46:
- Migration 0044: historical_comps table created (UNIQUE idx on player_name+archetype_code, 4 additional indexes).
- seed_historical_comps.py: 80 records seeded (18 QB, 20 CB, 18 EDGE, 24 WR). INSERT OR IGNORE idempotent.
- draftos/queries/historical_comps.py: get_historical_comps(), get_archetype_translation_rate(), _extract_archetype_code() regex helper.
- app.py: Historical Comps section added to _render_apex_detail() — translation rate badge + comp pills with HIT/PARTIAL/MISS icons + expandable comp details.
- generate_prospect_pdf_2026.py: full rebuild abandoning ReportLab Platypus. New: HTML→PDF via Playwright (Chromium), dark theme, landscape 11"×8.5", two-panel CSS grid. Comp block integrated.
- PDF Streamlit fix: replaced subprocess.run (NotImplementedError on Windows SelectorEventLoop) with threading.Thread + asyncio.WindowsProactorEventLoopPolicy inside thread. Doctor: PASSED.

Prior: Session 45 (full 144-prospect re-score against corrected v2.3 archetype library) — All 99 non-top-50 stale prospects re-scored. 0 GEN- labels remain. All 144 active non-cal prospects now carry canonical v2.3 archetype names.

Session 45:
- Re-scored 99 non-top-50 prospects (stale pre-Session-44 archetype names: DT-3 Scheme Fit,
  ILB-4 Raw Projection, OG-4 Chess Piece, S-3 Versatile Weapon, S-4 Raw Projection,
  EDGE-2 Speed Rusher, EDGE-4 Toolbox, TE-4 Chess Piece, OT-4 Developmental Athletic, etc.).
  All replaced with canonical v2.3 names.
- Two-pass run: 76/99 first pass (23 rate-limited), then 23/23 retry run — all 99 complete.
- 0 GEN- archetypes remaining across all 144 active non-cal v2.3 rows.
- Divergence recomputed (144 prospects): ALIGNED=30, APEX_HIGH=59, APEX_LOW=4,
  APEX_LOW_PVC_STRUCTURAL=51.
- Tier dist (all 144 v2.3 active non-cal): ELITE=3, DAY1=30, DAY2=74, DAY3=34, UDFA-P=3.
- Doctor: PASSED.

Prior: Session 44 (archetype library rebuild + top-50 re-score):

Session 44:
- prompts.py Section B fully rebuilt from 14 canonical .docx library files (Session 28).
  All 14 positions have their own section (C and OLB restored as separate sections).
  Archetype names corrected: EDGE-2 Speed-Bend Specialist, EDGE-3 Power-Counter Technician,
  EDGE-4 Athletic Dominator, CB-1 Anticipatory Lockdown, CB-2 Zone Architect,
  CB-3 Press Man Corner, S-3 Multiplier Safety, S-4 Coverage Safety (new), S-5 Raw Projection,
  ILB-3 Run-First Enforcer, ILB-4 Hybrid Chess Piece, ILB-5 Raw Projection (new),
  WR-6 Complete Outside Weapon (new archetype).
- POSITION_PAA_GATES aligned to canonical names. OLB and C gates added.
  _normalize_position_for_gate: OLB→OLB, C→C routing corrected.
- ARCHETYPE_OVERRIDES stale labels fixed (pid=72/71 CB-3, pid=38 CB-1, pid=35 CB-2, pid=3236).
- archetype_canonical_reference.json created at draftos/docs/apex/archetype_canonical_reference.json.
- Weight table audit (Session 28B): 5 base table errors confirmed (RB/OT/ILB/OLB/CB Injury
  arithmetic typos). All corrected in prompts.py. WR-3 Character=4% and WR-5 Injury=2% added.
- MODEL_VERSION bumped to apex_v2.3 in run_apex_scoring_2026.py.
- Migrations 0042+0043: Board views (v_board, v_divergence_board, v_position_board) updated
  from apex_v2.2 → apex_v2.3 AND from stale consensus_rankings (0 rows) →
  prospect_consensus_rankings (1007 rows). All three views now return live data.
- Top-50 re-score: 50/50 scored, 0 failed, 0 GEN- labels.
  Tier distribution (fresh 50): ELITE=3, DAY1=26, DAY2=20, DAY3=1.
  All 50 assigned canonical v2.3 archetype names. Section E compliance confirmed (3 spot-checks).
- Divergence recomputed (149 prospects): ALIGNED=29, APEX_HIGH=65, APEX_LOW=3,
  APEX_LOW_PVC_STRUCTURAL=52.
- Doctor: PASSED. Snapshot integrity: 1007==1007==1007.

Prior: Session 43 — Weekly pipeline first clean run + tag triage + end_session.py hardening.

Session 43:
- triage_pending_tags_2026.py (new): auto-accept/dismiss all 147 pending system tag recs.
  Gates: RAS tags always accept; V23_GATED_TAGS require apex_v2.3 score; Divergence Alert
  requires >= 3 active source rankings (joined via source_player_map + sources.is_active=1).
  Calibration artifacts auto-dismissed. All 147 accepted (0 dismissed, 0 left pending).
  prospect_tags now has 211 system-source rows. Rec status: accepted=204, dismissed=30, pending=0.
  INSERT OR IGNORE idempotency. rec_id backlink populated on each prospect_tags row.
- Weekly pipeline (run_weekly_update.py): first clean 18-step run post-Session 42.
  All steps completed with exit code 0. Final line: OK: weekly pipeline completed successfully.
  Snapshot_id=5 (2026-03-14): rows=1007, coverage=1007, confidence=1007 — PASSED.
  Tag trigger re-run: 0 new recs (all 185 existing recs already in DB — idempotent).
  prospects: 4555 (post-bootstrap), source_rankings: 42143, sources_active=14. Doctor: PASSED.
  ngs_2026.csv and ras_2026.csv skipped by stage step — expected (non-standard format).
- end_session.py hardened (scripts/end_session.py):
  CURRENT_SESSION constant added — developer increments each session before running.
  print_pre_run_checklist(): ASCII box + 5-second abort window fires at startup.
  validate_state_snapshot_content(): new stale-session check — FAIL if Last Completed
    Milestone references Session N < CURRENT_SESSION.
  Post-packet confirmation: prints Next Milestone + 3-second abort window before commit.
  Reminder comment documents next-session update protocol.

Prior: Session 42 — Position audit + UX polish (Fix 3.2, Sessions 5.3/5.4/41).

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

- Session 50: TJ Parker duplicate pid audit + display_name fix (query result in hand).
  Additional source ingest deferred to post-pro-days (closer to April).
  Neal MONITOR tag — hold until combine 3-cone data ingested.

---

## Layer Status

RAW CSVs: 15 raw CSVs present in data/imports/rankings/raw/2026/ (includes combine_2026.csv,
  nflcom_2026.csv, ngs_2026.csv).

STAGING: Staged CSVs present per source under data/imports/rankings/staged/2026/.

INGEST: Operational. 31 sources (14 active canonical), source_players: 9919,
  source_rankings: 42143.
  analyst_grade column active on source_rankings (migration 0038). Populated for
  bleacherreport_2026 only.
  combine_2026.csv → combine_ranks_2026 (source_id=28): 735 rows. Also writes
    hand_size/arm_length/wingspan to ras (migration 0039).
  nflcom_2026.csv → nflcom_2026 (source_id=30, T2 1.0): 303 rows. NFL.com editorial big board.
  ngs_2026.csv → ngs_2026 (source_id=29, is_active=0): 312 rows. ngs_score in grade column.
    Not in consensus — model score, not scout ranking.

BOOTSTRAP: Operational. prospects: 4555 total (active managed by is_active flag).

UNIVERSE: Operational. data/universe/prospect_universe_2026.csv (861 players).
  Migration 0033 applied.

CONSENSUS: Operational. 849 rows (14 active sources, Session 42 rebuild).
  Top: Fernando Mendoza QB 98.32 | Jeremiyah Love RB 95.80 | David Bailey EDGE 94.96.
  Styles LB dropped from #1 after Session 42 consensus rebuild (position audit changed weighting).

MODEL OUTPUTS: Operational. 1003 rows (Session 42 rebuild).

SNAPSHOTS: Operational. Latest: snapshot_id=5 (2026-03-14). rows=1007, coverage=1007,
  confidence=1007 — PASSED (Session 43 weekly pipeline clean run).
  Full pipeline: build_consensus → snapshot_board → compute_snapshot_metrics →
  compute_source_snapshot_metrics → compute_snapshot_coverage →
  compute_snapshot_confidence → verify_snapshot_integrity

APEX: Operational. 144 v2.3 active non-cal scored + 12 calibration artifacts. 0 GEN- archetypes.
  All 144 carry canonical v2.3 archetype names (Session 45 full re-score complete).
  Tiers (v2.3 active non-cal, post Session 45): ELITE=3, DAY1=30, DAY2=74, DAY3=34, UDFA-P=3.
  Divergence (current, post Session 45): ALIGNED=30, APEX_HIGH=59, APEX_LOW=4,
    APEX_LOW_PVC_STRUCTURAL=51.
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
  Migrations applied: 0001–0045. Next migration: 0046.
    Migration 0040 (apex_v23_mechanism_fields): failure_mode_primary, failure_mode_secondary,
      signature_play, translation_risk columns added to apex_scores — APPLIED. All 149 v2.3 rows populated.
    Migration 0041 (apex_bust_warning): bust_warning column added — APPLIED.
    Migration 0042 (views_bump_to_v23): v_board, v_divergence_board, v_position_board updated
      model_version filter apex_v2.2 → apex_v2.3 — APPLIED.
    Migration 0043 (views_fix_consensus_table): Views updated to JOIN prospect_consensus_rankings
      (1007 rows) instead of stale consensus_rankings (0 rows). Column aliases corrected — APPLIED.
  Tag trigger re-run executed post-Session 42 — 147 pending recs generated (see TAGS).

TAGS: Operational. Session 24 trigger engine built and active.
  Scripts: run_tag_triggers_2026.py (engine), accept_tag_recs_2026.py (workflow),
    draftos/tags/evaluator.py (pure function library).
  Schema: tag_definitions=28 (added Monitor id=54 Session 39), tag_trigger_rules=14.
  Rec status: accepted=204, dismissed=30, pending=0.
    All 147 pending recs triaged Session 43 via triage_pending_tags_2026.py (all accepted).
  Active tags (211 total system prospect_tags rows): Development Bet=70, Elite RAS=45,
    Compression Flag=32, Divergence Alert=31, Great RAS=18, Top 5 NextGen=7,
    Scheme Dependent=6, Poor RAS=1, Injury Flag=1, Monitor=1 (Neal pid=109).
  Monitor tag (id=54, Session 39): editorial, gray, note_required=1.
    Applied to Julian Neal CB — 3-cone gate pending.

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
35. ~~Session 40-42: UX polish (FM text, compare panel, divergence narrative, tag filter) + position audit~~ COMPLETE
36. ~~Session 43: Tag triage (147 recs → 204 accepted) + weekly pipeline clean run (rows=1007) + end_session.py hardening~~ COMPLETE
37. ~~Session 44 (archetype rebuild): prompts.py Section B rebuild, PAA gates, override fix, top-50 re-score, migrations 0042+0043~~ COMPLETE
38. ~~Session 45: Full 144-prospect APEX re-score — 99 non-top-50 stale archetypes corrected, 0 GEN- remaining~~ COMPLETE
39. **Session 46: Additional source ingest (2–3 sources) + tag trigger re-run** ← NEXT
40. Post-draft audit framework activation (after April 2026 draft)

---

## APEX Status

- Version: v2.3 (scorer engine + model_version written to DB — aligned Session 44)
- v2.3 mechanism fields applied (migration 0040): failure_mode_primary, failure_mode_secondary,
  signature_play, translation_risk. bust_warning added (migration 0041). All 144 v2.3 rows populated.
- Active 2026 scored: 144 v2.3 (is_active=1, is_calibration_artifact=0). 0 GEN- archetypes.
- Calibration artifacts: 12 (PIDs: 230,304,313,455,504,880,1050,1278,1371,1391,1729,1925)
  All re-scored Session 26 with correct PIDs and positions.
- Tier dist (v2.3 all 144, post Session 45): ELITE=3, DAY1=30, DAY2=74, DAY3=34, UDFA-P=3
- Divergence (current, post Session 45): ALIGNED=30, APEX_HIGH=59, APEX_LOW=4,
  APEX_LOW_PVC_STRUCTURAL=51
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

Current recompute: post-Session 45 (144 active scored prospects). Total APEX_HIGH=59, APEX_LOW=4.
(Note: divergence_flags table also contains stale rows in old space-format "APEX HIGH"/"APEX LOW" — ignore those.)

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
| 13 | pff_2026 | T1 | 1.3 |
| 24 | thedraftnetwork_2026 | T1 | 1.3 |
| 25 | theringer_2026 | T1 | 1.3 |
| 9  | nfldraftbuzz_2026_v2 | T2 | 1.0 |
| 3  | cbssports_2026 | T2 | 1.0 |
| 6  | espn_2026 | T2 | 1.0 |
| 10 | nytimes_2026 | T2 | 1.0 |
| 15 | pfsn_2026 | T2 | 1.0 |
| 1  | jfosterfilm_2026 | T2 | 1.0 |
| 2  | bnbfootball_2026 | T3 | 0.7 |
| 23 | tankathon_2026 | T3 | 0.7 |
| 27 | bleacherreport_2026 | T2 | 1.0 |
| 28 | combine_ranks_2026 | T2 | 1.0 |
| 30 | nflcom_2026 | T2 | 1.0 |

Inactive (data preserved): ngs_2026 (source_id=29, is_active=0) — model score, not ranking.
