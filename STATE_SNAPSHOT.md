# DraftOS State Snapshot

Last Updated (UTC): 2026-03-12T07:41:23.362601+00:00

---

## Active Season

- 2026 (season_id=1)

## Last Completed Milestone (Session 12 addendum — DATABASE REBUILD)

- Session 12: Emergency database rebuild from corrupt 33MB DB → clean 11MB DB.
  - Root cause: corrupt DB had 39 sources (36 is_active) including spamml/garbage sources injecting junk
  - All source data, scripts, APEX batch JSONs intact on disk — pipeline is deterministic
  - Rebuild used only 11 canonical active sources (no spamml)
  - Bootstrap: 3495 prospects total (1018 active after universe apply = 861 unique × ~1.18x position factor)
  - Consensus rebuilt: 586 rows (clean-source achievable max — 798 old count required spamml coverage)
  - Consensus top: Fernando Mendoza QB 98.56 ✓, Caleb Downs S 96.80 ✓, Rueben Bain EDGE 95.13 ✓
  - 75 APEX scores loaded (50 top-50 + 12 calibration, overlap resolved by name+position lookup)
  - Divergence recalibrated: ALIGNED=12, APEX_HIGH=16, APEX_LOW_PVC_STRUCTURAL=20, APEX_LOW=3
  - snapshot_id=1 (2026-03-10): rows=586, coverage=586, confidence=586 — OK
  - Confidence: High=4, Medium=53, Low=529
  - DB size: 11MB (was 33MB corrupt)
  - Two fixes applied: 0002_board_snapshots FK references (id→model_id/season_id/prospect_id);
    migrate.py _apply_sql_file_tolerant() for duplicate-column idempotency on fresh rebuild
  - APEX batch JSON IDs re-resolved for new DB: apex_calibration_batch_patched.json + apex_top50_batch_patched.json
  - Rebuild deviations from spec (by design):
    * consensus 586 not 798 — clean sources have less late-round coverage (correct)
    * prospects_active 1018 not ~1376 — fewer position dup artifacts with 11 vs 39 sources
    * source_canonical_map empty — no duplicates to canonicalize (correct)
    * bootstrap ran with min-source-count=1 (needed for jfosterfilm unranked-row coverage)
    * 322 universe players inserted directly (unranked jfosterfilm + RAS-only, no ranking data)

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

## Last Completed Milestone (Session 10 addendum)

- Session 10: Divergence engine recalibration — rank-relative method.
  - Migration 0035: adds divergence_rank_delta (INTEGER), divergence_raw_delta (REAL), position_tier (TEXT) to divergence_flags
  - New --batch divergence mode: recomputes all scored prospects using consensus_rank vs apex_ovr_rank instead of raw score delta
  - Scale artifact eliminated: ALIGNED 2→20, APEX_LOW 59→0 (active board), APEX_LOW_PVC_STRUCTURAL 12
  - Flag logic: non-premium APEX LOW → APEX_LOW_PVC_STRUCTURAL (structural PVC discount, not actionable)
  - Premium APEX_HIGH (actionable — APEX rates higher than consensus): 15 prospects
    Top: Dillon Thieneman S rank_delta=+28, Akheem Mesidor EDGE +22, D'Angelo Ponds CB +17, Keldric Faulk EDGE +14
  - 0 premium APEX_LOW on active board — APEX scores are in agreement or above consensus for all premium positions
  - writer.py updated: position_tier and divergence_raw_delta propagated on per-prospect scoring runs
  - snapshot_id=9 (2026-03-10): rows=1000, coverage=1000, confidence=1000 — OK (unchanged)
  - Board exported: board_2026_v1_default.csv

## Last Completed Milestone (Session 13)

- Session 13: Full clean weekly pipeline run — all 18 steps pass cleanly.
  - patch_source_canonicalization_2026.py: hardcoded source IDs updated for rebuilt DB (1-26, was 1-38)
  - compute_snapshot_metrics.py: graceful SKIP (exit 0) when <2 snapshots; WARN when <window
  - run_weekly_update.py --fast: all 18 steps completed successfully
  - Step 9 (snapshot_metrics) correctly SKIPs with 1 snapshot — expected for fresh DB
  - Consensus: 609 rows (up from 586 post-rebuild — additional mappings resolved)
  - source_canonical_map: 4 entries (espn (1), pff (1), pfsn-consensus-*, theringer)
  - Board export: board_2026_v1_default.csv produced
  - Doctor: PASSED
  - Note: prospects_active=2005 (was 1018 post-rebuild) — weekly ingest picks up inactive source
    staged files, bootstrap creates is_active=1 prospects from those; universe apply not in weekly
    pipeline. Board quality unaffected (consensus still uses only 11 active sources).

## Last Completed Milestone (Session 13b — CRITICAL FIX)

- Session 13b: Two data quality fixes — schools and APEX archetypes.
  - ISSUE 1 (school_canonical): 611 active prospects updated from universe CSV.
    - Match strategy: exact name_norm lookup + name_norm_and_key(display_name) fallback
    - Conflict resolution: deactivates name_norm=NULL duplicate rows blocking updates
    - Remaining unknowns: 2 (Travis Kelce calibration ghost + Travis Hunter not in universe CSV)
    - Also fixed 96 mismatch rows: USC→Southern California, LSU→Louisiana State, etc.
  - ISSUE 2 (GEN archetypes): 64 apex_scores rows reclassified to positional archetypes.
    - Local weight-table matching — no API calls, no network, fully deterministic
    - Uses APEX v2.2 weight tables from prompts.py with archetype-specific bumps
    - Only updates matched_archetype, archetype_gap, gap_label — scores preserved
    - Tie-break: first-defined archetype wins (EDGE-1 > EDGE-4, S-1 > S-5)
    - Remaining GEN: 2 (Younghoe Koo ST + Kaimi Fairbairn ST — no positional library)
    - Spot checks: Caleb Downs→S-1 Centerfielder, Rueben Bain→EDGE-1 Every-Down Disruptor,
      Travis Hunter→CB-3 Athletic Freak, Fernando Mendoza→QB-1 (unchanged), Carson Schwesinger→ILB-1 (unchanged)
  - Divergence recomputed: ALIGNED=12, APEX_HIGH=16, APEX_LOW=3, APEX_LOW_PVC_STRUCTURAL=20
  - Board re-exported: board_2026_v1_default.csv (609 rows, top: Fernando Mendoza QB 98.56)
  - Doctor: PASSED
  - Note: most local-matched archetypes have gap=0.0, gap_label=NO_FIT — GEN trait vectors
    are uniform, so within-position differentiation requires API re-scoring. NO_FIT label signals
    uncertainty correctly. True positional archetype depth requires API re-score when available.
  - Known remaining: Travis Hunter school=Unknown (not in universe CSV), Tate Ratledge position_group=TE
    (should be OG per CALIBRATION_OVERRIDES — pre-existing data quality issue in prospects table)

## Last Completed Milestone (Session 15 — APEX BOARD AUDIT + OVERRIDE CORRECTION)

- Session 15: Full APEX board audit, stale override ID fix, 9 priority re-scores, calibration tagging.

  ROOT CAUSE FOUND: Both TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py
  contained stale prospect_ids from the pre-Session-12 DB (the corrupt 33MB rebuild). After the
  Session 12 rebuild, prospect IDs changed but override dicts were never updated — causing wrong
  positional libraries and analyst overrides to be applied to different players.

  OVERRIDE FIXES (scripts/run_apex_scoring_2026.py):
  - TOP50_POSITION_OVERRIDES: rebuilt from scratch with verified current IDs (16 entries).
    Key corrections: pid=26 (Spencer Fano) was mapped to "LB" (Lee Hunter entry) → now OT.
    pid=18 (Gabe Jacas) was mapped to "OT" (Spencer Fano entry) → now ILB.
    pid=40 (Cashius Howell) was mapped to "ILB" (Anthony Hill entry) → entry removed (EDGE is correct).
  - ARCHETYPE_OVERRIDES: all 8 keys corrected.
    Critical: pid=12 (Omar Cooper) had Jerrod McCoy's CB-1 forced override → now correctly keyed 38.
    Critical: pid=16 (Arvell Reese) had Keldric Faulk's EDGE-3 forced override → now correctly keyed 42.

  9 RE-SCORES (all applied with --batch single --force --apply 1):
  - Kyron Drones QB (1420): QB-1 78.0 DAY1 → QB-5 49.1 DAY3. Contaminated vector (wrong player text).
  - Jalen Catalon S (1464): ILB-1 73.1 DAY1 → S-4 52.6 DAY3. Wrong library (ILB applied to S).
  - Spencer Fano OL (26): ILB-1 74.2 DAY1 → OT-1 76.8 DAY1. Stale override (pid=26→LB).
  - Omar Cooper LB (12): CB-1 69.0 DAY2 → ILB-2 66.4 DAY2. Stale override (pid=12→CB-1 McCoy).
  - Arvell Reese LB (16): EDGE-3 70.0 DAY1 → OLB-1 67.8 DAY2. Stale override (pid=16→EDGE-3 Faulk).
  - Gabe Jacas LB (18): OT-4 61.1 DAY2 → ILB-3 59.0 DAY2. Stale override (pid=18→OT).
  - Cashius Howell EDGE (40): ILB-3 59.8 DAY2 → EDGE-4 73.8 DAY1. Stale override (pid=40→ILB).
  - Max Klare LB (6): ILB-2 63.0 DAY2 → TE-5 49.1 DAY3. Contaminated vector (RB text); position=TE.
  - Joshua Josephs EDGE (114): EDGE-1 64.0 DAY2 → EDGE-3 67.8 DAY2. NO_FIT gap; clean re-score.

  CALIBRATION FIX (Migration 0036):
  - tag_calibration_artifacts_2026.py rebuilt — old script used corrupted display_names
    ("Carson Schwesingerucla", "Donovan Ezeiruakuboston"), missing Gunnar Helm (313) and
    Carson Schwesinger (1925) and Donovan Ezeiruaku (1729). Now uses explicit prospect_ids
    from apex_calibration_batch_patch.json (user-confirmed Session 15).
  - All 12 calibration artifacts tagged is_calibration_artifact=1 (were all 0).
  - All 12 confirmed is_active=0 in prospects — excluded from all active board joins.

  POST-SESSION 15 BOARD STATE:
  - Active 2026 scored prospects: 58 (all is_active=1, is_calibration_artifact=0)
  - Calibration artifacts: 12 (is_active=0, is_calibration_artifact=1) — excluded from board
  - Tiers: ELITE=3, DAY1=21, DAY2=30, DAY3=4
  - Divergence (active board): ALIGNED=15, APEX_HIGH=22, APEX_LOW_PVC_STRUCTURAL=19, APEX_LOW=2
  - Backup exported: data/apex_top50_rescored_session15.json (141KB)
  - Migrations applied: 0036_tag_calibration_artifacts
  - Doctor: PASSED

  PENDING (carried forward):
  - Kilgore CB-3 ELITE (90.0, consensus=210): FM-1 vs genuine find not resolved — needs CB PAA run.
  - Calibration batch API re-score: 12 calibration prospects still on generic trait vectors.
  - Kyron Drones QB (351): low consensus rank — genuine late-round talent or wrong player in DB?

## Last Completed Milestone (Session 16 — BLEACHERREPORT INGEST + ANALYST_GRADE CAPTURE)

- Session 16: bleacherreport_2026 ingested as 12th active canonical source (T2, weight 1.0).
  - Migration 0037: seeds source_id=27 (bleacherreport_2026, ranking, is_active=1)
  - Migration 0038: adds analyst_grade REAL (nullable) to source_rankings
  - stage_rankings_csv.py: B/R format detection + 3-variant parser
    Format A: "N. POS\xa0, School (grade)" — \xa0 after pos, player in col 2 (166 rows)
    Format B: "N. POS Player Name, School (grade)" — player embedded, col 2 empty (54 rows)
    Format C: "N. POS , School (grade)" — regular space, player in col 2 (30 rows)
    Detection: norm(fieldnames[0]) == "posschoolgrade"
  - ingest_rankings_staged.py: reads analyst_grade from staged CSV, writes to source_rankings.analyst_grade
    NULL-safe: column absent from non-B/R staged files → NULL, never errors
  - build_consensus_2026.py: bleacherreport_2026 added to SOURCE_WEIGHTS at 1.0 (T2)
  - Result: 250 B/R prospects ingested, 250 graded rows, grade range 5.7-9.3
  - Consensus: 615 rows (was 609), top 3 stable: Mendoza QB, Downs S, Bain EDGE
  - Confidence: High=4, Medium=55 (was 53), Low=556
  - PFF analyst_grade: 0 rows — correct, NULL for all non-B/R sources
  - snapshot_id=2 (2026-03-11): rows=615 — OK
  - Doctor: PASSED

## Last Completed Milestone (Session 21 — DEV BET TRIAGE + LOVE RE-SCORE + COMPRESSION FLAGS)

- Session 21: Love re-score, Development Bet batch triage, Compression Flag batch accept.

  LOVE RE-SCORE (pid=61):
  - Carry Accumulation Clock audit complete: ~479 college carries (2022-2024) — CLEAR.
    Below 500-carry FM-4 threshold. v_injury cap lifted, scored at 9.0.
  - ARCHETYPE_OVERRIDES[61] updated in run_apex_scoring_2026.py.
  - Final: RB-1 Elite Workhorse | composite=59.8 | DAY2 | Tier A | v_injury=9.0
    FM-6/FM-4 co-primary in red_flags. gap=18.7 (CLEAN).

  DEVELOPMENT BET TRIAGE (38 recs → 0 pending):
  - 10 dismissed (Tier A): Bain, Downs, Terrell, Hood, Tate, Mauigoa, Woods, Hill, Reese, Love.
    Rationale: eval_confidence Tier A = finished products. High v_dev_traj on Tier A players
    is upward arc confirmation, not a projection requirement — tag mismatch.
    Love additionally dismissed as gap_label=CLEAN post-re-score (double ineligible).
  - 28 accepted (Tier B): all gap_label=SOLID with genuine developmental projection required.
    Key: David Bailey, Akheem Mesidor, Mansoor Delane, Spencer Fano, Devin Moore, Keith Abney,
    Germie Bernard, Dillon Thieneman, Max Iheanachor, Kenyon Sadiq, and 18 others.
  - 0 TWEENER rows — no holds from Dev Bet triage.

  COMPRESSION FLAG TRIAGE (13 recs → 0 pending):
  - All 13 accepted as system-generated information tags.
  - Kamari Ramsey (S, gap=0.0) and Connor Lew (OL, gap=0.14) are highest-ambiguity profiles.
  - Cluster of 10 at gap=4.2: Howell, Cooper, Simpson, Hunter, Thomas, Young, Trotter, Jacas,
    Klare, Catalon.
  - D'Angelo Ponds (rec_id=19, gap=0.31) accepted separately — excluded from audit JOIN due to
    missing consensus rank row.

  POST-SESSION 21 TAG STATE:
  - Rec status: accepted=54, dismissed=22, pending=1 (Kilgore Divergence Alert — held for combine)
  - Active tags: Development Bet=28, Compression Flag=13, Divergence Alert=6, Elite RAS=4,
    Poor RAS=1, Great RAS=1, Injury Flag=1
  - Board re-exported, snapshot_id=2 refreshed, doctor PASSED, integrity PASSED.

## Last Completed Milestone (Session 23 — COMBINE + NGS INGEST)

- Session 23: Two new T2 sources ingested + combine measurables layer added.

  MIGRATION 0039 (combine_measurables):
  - Adds hand_size REAL, arm_length REAL, wingspan REAL to ras table (all nullable).
  - Applied cleanly. Existing ras rows unaffected.

  INGEST: ingest_combine_2026.py
  - Phase A (Rankings): nflcom_2026 source (source_id=28), 735 source_players + source_rankings.
  - Phase B (Measurables): 235 existing ras rows updated, 393 new ras rows inserted with measurements.
    13 UDFA-range players unmatched (not in active universe — expected).
    School matching: added case-insensitive fallback (by_name_school_lower) since school_aliases
    only covers non-standard school name variants.
  - Fully idempotent: second run produces 0 new inserts, 628 updates (no-op on unchanged values).

  INGEST: ingest_ngs_2026.py
  - ngs_2026 source (source_id=29), 312 source_players + source_rankings.
  - overall_rank derived from ngs_score DESC order (1=highest score).
  - ngs_score stored in source_rankings.grade column (50-99 range).
  - ngs_position_rank stored in position_rank column.

  SOURCE_PLAYER_MAP:
  - patch_name_normalization_2026.py run: 511 conservative new mappings for new source_players.
  - 772 ambiguous players held (multiple active prospect rows — position dup artifacts).

  CONSENSUS REBUILD:
  - 615 → 850 rows (significant coverage expansion, 235 new prospects covered).
  - Key board shift: Sonny Styles LB now #1 (sources_covered=14, ngs_score=94 + NFL.com high).
  - Fernando Mendoza drops to #2 (unchanged from his perspective — Styles gained more coverage).
  - Most top prospects still show sources_covered=11-12 (ambiguous prospects can't be mapped conservatively).
  - Sources now: 14 active (added nflcom_2026 T2 1.0, ngs_2026 T2 1.0).

  SNAPSHOT: snapshot_id=3 (2026-03-12): rows=615, coverage=615, confidence=615 — PASSED.
  NOTE: Full snapshot pipeline is:
    build_consensus → snapshot_board → compute_snapshot_metrics →
    compute_source_snapshot_metrics → compute_snapshot_coverage → (NEW — was missing from protocol)
    compute_snapshot_confidence → verify_snapshot_integrity

  Board exported: board_2026_v1_default.csv (snapshot_id=3).
  Doctor: PASSED (sources=29, sources_active=14, source_rankings=29644).

## Next Milestone (Single Target)

- Calibration batch API re-score (12 prospects, generic trait vectors) or additional source ingest.
  See Ordered TODOs below.

---

## Layer Status

RAW CSVs: 14 raw CSVs present in data/imports/rankings/raw/2026/ (including combine_2026.csv, ngs_2026.csv)

STAGING: Staged CSVs present per source under data/imports/rankings/staged/2026/

INGEST: Operational. 29 sources (14 active canonical), source_players: 8613, source_rankings: 29644.
  analyst_grade column active on source_rankings (migration 0038). Populated for bleacherreport_2026 only.
  combine_2026.csv: 735 rows ingested as nflcom_2026 (source_id=28). Also writes hand/arm/wing to ras.
  ngs_2026.csv: 312 rows ingested as ngs_2026 (source_id=29). ngs_score in grade column.

BOOTSTRAP: Operational. prospects: 4482 total (active managed by is_active flag).

UNIVERSE: Operational. data/universe/prospect_universe_2026.csv (861 players). Migration 0033 applied.

CONSENSUS: Operational. 850 rows (Session 23). Top: Sonny Styles LB 91.75 | Fernando Mendoza QB 87.36 | Caleb Downs S 85.81.
  Styles shift to #1 driven by NGS 94.0 + NFL.com high rank; 14 sources covered.

MODEL OUTPUTS: Operational. 615 rows (Session 16 rebuild — not yet rebuilt for Session 23 consensus).

SNAPSHOTS: Operational. Latest: snapshot_id=3 (2026-03-12). rows=615, coverage=615, confidence=615 — OK.
  Full snapshot pipeline: build_consensus → snapshot_board → compute_snapshot_metrics →
  compute_source_snapshot_metrics → compute_snapshot_coverage → compute_snapshot_confidence → verify_snapshot_integrity

APEX: Operational. 58 active 2026 scored prospects + 12 calibration artifacts (tagged, excluded from board).
  Tiers: ELITE=3, DAY1=21, DAY2=30, DAY3=4. Latest backup: data/apex_top50_rescored_session15.json.
  Love (pid=61) re-scored Session 21: RB-1 59.8 DAY2 Tier A v_injury=9.0 (carry clock CLEAR).
  Migrations: 0001–0039 applied. Next migration: 0040.

TAGS: Operational. Session 21 triage complete.
  Rec status: accepted=54, dismissed=22, pending=1 (Kilgore Divergence Alert, held).
  Active tags: Development Bet=28, Compression Flag=13, Divergence Alert=6, Elite RAS=4, Poor RAS=1, Great RAS=1, Injury Flag=1.

EXPORTS: board_2026_v1_default.csv last produced Session 21. Current.

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
- source_canonical_map has 0 entries in rebuilt DB — no duplicates to canonicalize (all 15 non-canonical sources deactivated via UPDATE sources SET is_active=0 during rebuild). patch_source_canonicalization_2026.py uses hardcoded IDs from old DB — DO NOT run it without updating IDs first.
- 14 canonical sources: pff_2026, nfldraftbuzz_2026_v2, bnbfootball_2026, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026, tankathon_2026, thedraftnetwork_2026, theringer_2026, jfosterfilm_2026, bleacherreport_2026, nflcom_2026, ngs_2026
- analyst_grade column added to source_rankings (migration 0038). Nullable REAL, 0-10 scale. Currently populated for bleacherreport_2026 only (Sobleski grades). Never backfill other sources.
- SOURCE_WEIGHTS: T1 (pff_2026, thedraftnetwork_2026, theringer_2026) = 1.3; T2 (nfldraftbuzz_2026_v2, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026, jfosterfilm_2026, bleacherreport_2026, nflcom_2026, ngs_2026) = 1.0; T3 (bnbfootball_2026, tankathon_2026) = 0.7
- Confidence dispersion caps: std_dev > 0.20 → Low; std_dev > 0.10 → cap at Medium (normalized rank std_dev, range 0–1)
- reingest_source_2026.py is the standard script for all future source updates (clean replace of source_players, source_rankings, source_player_map, staged files; then re-runs staging → ingest → name normalization → bootstrap → prospect canonicalization). Usage: python -m scripts.reingest_source_2026 --source <name> --season <year> --apply 0|1
- school_alias key collision fix applied in patch_name_normalization_2026.py: plain alias (e.g. 'Miami') beats parenthetical alias (e.g. 'Miami (OH)') when both normalize to the same school_key
- RAS join in get_big_board() uses AND r.ras_total IS NOT NULL instead of season_id filter. Temporary workaround for two-generation ras data (172 rows season_id=NULL with real data, 336 rows season_id=1 mostly empty). Revert to season_id join after RAS re-ingest post pro days.
- build_consensus_2026.py does full DELETE + INSERT (not upsert) to guarantee clean row count after universe apply. Safe because consensus is derived data, always rebuilt from sources.
- snapshot_board.py filters prospect_model_outputs via JOIN to prospects WHERE is_active=1. jfosterfilm_2026.csv encoding is latin-1.
- Universe name matching: normalize_name() → suffix-strip (Jr./Sr./II/III/IV) → period-strip (T.J.→TJ). All 861 universe names matched to DB with 0 gaps.
- Active prospect count is 1018 DB rows for 861 unique players — ~1.18x factor (was 1376/~1.6x in old DB with more sources). Fewer position dup artifacts with 11 clean sources vs 39 dirty sources.
- jfosterfilm_2026 has 293 ranked rows (rank=1..293) + 442 unranked rows (rank=?). Ingest only ingests ranked rows. 322 unranked/RAS-only universe players inserted directly into prospects table during rebuild (no source_player_map entries, no consensus score). This is correct behavior.
- APEX batch JSON prospect_ids are DB-specific. Re-patched versions in data/apex_*_patched.json have correct IDs for rebuilt DB. Use patched files for any future re-import.
- Rebuild pipeline ordering correction: name normalization MUST run before bootstrap (bootstrap needs name_key populated on source_players). Rebuild spec had wrong order — bootstrap was listed before name normalization.

---

## Divergence Flags (Manual Evaluation Needed)

- JALON KILGORE CB (pid=449, consensus=210): CB-3 ELITE 90.0, APEX_HIGH +209. FM-1 Athleticism
  Mirage vs genuine APEX_HIGH not resolved. Needs full CB PAA run before accepting score.
  Do NOT cite this as a real APEX_HIGH signal until PAA clears.
- KYRON DRONES QB (pid=1420, consensus=351): QB-5 DAY3 49.1, APEX_HIGH +294. Consensus rank
  of 351 is very low for a scored prospect. Verify this is the correct player in DB before
  taking any action on this divergence.
- SONNY STYLES (LB, Ohio State): jfosterfilm_2026 ranks #1 overall; consensus rank now #9. Worth
  evaluating whether jfoster reflects genuine contrarian view.

---

## APEX v2.2 Engine Notes

- CRITICAL (Session 15): TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py
  used stale prospect_ids from pre-Session-12 DB rebuild. Both dicts were fully corrected Session 15.
  Any future re-score run will now use correct IDs. If DB is ever rebuilt again, BOTH dicts must be
  re-verified against the new prospect_ids before running any batch scoring.
- CALIBRATION_OVERRIDES in run_apex_scoring_2026.py maps name -> {prospect_id, position, school}
  Required because DB has multiple duplicate entries per prospect (position normalization artifacts)
  Best prospect_id = highest consensus score entry for that name
- TOP50_POSITION_OVERRIDES maps prospect_id -> correct APEX position (OT/OG/C/ILB/OLB/TE/IDL).
  Rebuilt Session 15 with verified current IDs. Covers OL sub-positions, DT→IDL, LB sub-types.
- ARCHETYPE_OVERRIDES maps prospect_id -> forced archetype + PAA findings. 8 entries, all keys
  corrected Session 15: Mesidor(80), Thieneman(29), Faulk(42), Hood(72), Cisse(71), McCoy(38),
  C.Johnson(35), Ponds(3236).
- Calibration artifacts: 12 prospects (is_active=0, is_calibration_artifact=1). All 2025 draftees.
  PIDs: 230, 304, 313, 455, 504, 880, 1050, 1278, 1371, 1391, 1729, 1925. Do NOT re-score.
  tag_calibration_artifacts_2026.py rebuilt Session 15 — now uses explicit PIDs not display_name matching.
- run_apex_scoring_2026.py requires ANTHROPIC_API_KEY env var to make live API calls
- Fallback: import_apex_batch_json.py accepts pre-evaluated JSON (no API key needed)
- data/apex_top50_rescored_session15.json: latest full apex_scores backup (141KB, post-Session 15)
- APEX LOW on non-premium positions (ILB, OLB, OG, C, TE, RB) is structural PVC behavior, not
  actionable divergence. Monitor APEX_HIGH only on premium positions (QB, CB, EDGE, OT, S).

---

## Ordered TODOs

1. ~~Session 4: APEX top-50 batch scoring~~ COMPLETE 2026-03-10
2. ~~Session 5: Add positional archetype libraries to prompts.py~~ COMPLETE 2026-03-10
3. ~~Session 6: RAS join fix, ghost prospect audit~~ COMPLETE 2026-03-10
4. ~~Session 7: top-50 force re-score (positional archetypes), calibration artifact tagging~~ COMPLETE 2026-03-10
5. ~~Session 8: Prospect universe migration (migration 0033, is_active, consensus rebuild)~~ COMPLETE 2026-03-10
6. ~~Session 9: Re-score top-50 APEX with --force against updated consensus ranks~~ COMPLETE 2026-03-10
7. Additional source ingest — bleacherreport_2026 ingested Session 16. 1-2 more sources still possible. ← PARTIAL
8. ~~Full clean weekly pipeline run end-to-end~~ COMPLETE 2026-03-10 (Session 13)
9. ~~Session 14: Top-50 re-score, APEX tier label standardization (DAY1/DAY2/DAY3), divergence~~ COMPLETE 2026-03-10
10. ~~Session 15: Full board audit, TOP50_POSITION_OVERRIDES + ARCHETYPE_OVERRIDES stale-ID fix,~~ COMPLETE 2026-03-11
    ~~9 priority re-scores, calibration artifact tagging (migration 0036, all 12 tagged)~~
11. Calibration batch API re-score — 12 prospects still on generic Session 4 trait vectors
12. Kilgore CB evaluation — CB-3 ELITE 90.0 consensus=210, FM-1 vs genuine find unresolved
13. RAS re-ingest after pro days complete — re-run ingest_ras_2026.py with updated file
14. Tag system activation — Layer 10+11 schema deployed, trigger evaluation engine needed
