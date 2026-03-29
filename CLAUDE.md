# CLAUDE.md — DraftOS Persistent Instructions

This file is the authoritative instruction set for all Claude Code sessions on this project.
Read this file completely before writing any code, running any scripts, or making any architectural decisions.

---

## What This System Is

DraftOS is a deterministic, local-first NFL Draft analytics engine.
Current scope: 2026 NFL Draft (season_id=1, draft_year=2026).
Python package: `draftos` | Python requirement: >=3.12 | Version: 0.1.0
Canonical DB: `C:\DraftOS\data\edge\draftos.sqlite`
Repo: `C:\DraftOS` (Git-tracked, branch: main)
Dev environment: Windows, Claude Code CLI in terminal

This is a long-lived production system. Every decision must prioritize determinism, auditability, and continuity over speed or convenience.

---

## Core Design Principles (Non-Negotiable)

These rules govern every decision. Any suggestion that violates them must be rejected.

- **DETERMINISTIC ONLY** — Same input always produces same output. No probabilistic scoring without explicit versioning.
- **ADDITIVE MIGRATIONS ONLY** — Never destructive schema changes. Never modify historical data. Always backup before write operations.
- **SEASON SCOPED** — All queries must be season-aware (season_id=1 for 2026). No cross-season contamination.
- **ACTIVE SOURCES ONLY** — All ranking math must respect `sources.is_active=1`. Use `source_canonical_map` to resolve duplicates. Never count all is_active rows as distinct sources.
- **IDEMPOTENT SCRIPTS** — Running any script twice must not duplicate data. Upserts only. All scripts use `--apply 0` (dry run) and `--apply 1` (write).
- **FULL FILE REPLACEMENTS** — No partial edits. Always provide complete file content when modifying scripts. Never provide diffs only.
- **ENGINE FIRST** — No UI logic inside engine scripts. Model outputs are a contract layer. Streamlit app is a stub — do not build into engine.
- **BACKUP BEFORE WRITE** — Every DB-write operation backs up the database first.
- **MECHANISM OVER OPTICS** — APEX archetypes describe how players win, not what they look like.
- **BUST VALIDATION REQUIRED** — Every positional library includes hit AND bust cases with FM mechanism.
- **OVERRIDES ARE VISIBLE** — Every analyst override logged with rationale. No silent adjustments.

---

## Pipeline Architecture (Non-Negotiable)

```
RAW CSVs          (data/imports/rankings/raw/{season}/)
-> STAGING        stage_rankings_csv.py -> data/imports/rankings/staged/{season}/
-> INGEST         ingest_rankings_staged.py -> sources, source_players, source_rankings
-> BOOTSTRAP      bootstrap_prospects_from_sources_2026.py -> prospects, source_player_map
-> UNIVERSE APPLY apply_prospect_universe_2026.py -> enforces is_active filter
-> CANONICALIZATION patch_source/school/prospect_canonicalization_2026.py -> canonical maps
-> CONSENSUS      build_consensus_2026.py -> prospect_consensus_rankings
-> MODEL OUTPUTS  build_model_outputs_v1_default_2026.py -> prospect_model_outputs
-> SNAPSHOTS      snapshot_board.py + compute_snapshot_*.py -> prospect_board_snapshot_*
-> EXPORTS        export_*.py -> exports/
-> PACKET         build_snapshot_packet.py + verify + publish -> exports/packets/
-> TAG TRIGGERS   run_tag_triggers_2026.py -> prospect_tag_recommendations (Step 19)
```

Each layer has exactly one responsibility. No layer may recompute logic that belongs to another layer.

Weekly orchestrator: `run_weekly_update.py` (19 steps). Universe apply runs as Step 3b — after bootstrap, before source canonicalization. Step 19 evaluates tag_trigger_rules.

---

## Prospect Universe — CRITICAL

**The canonical universe is 861 unique prospects.** Source of truth: `data/universe/prospect_universe_2026.csv`

Built from: RAS (630) ∪ jfosterfilm_2026 (735). Approximately 257 of the 2026 class are drafted.

The `prospects` table contains additional soft-deprecated rows (`is_active=0`) from prior spamml/garbage ingest — retained for audit history only. These rows NEVER appear in any active query. All downstream pipeline layers enforce `is_active=1`.

**Never cite the raw `prospects` table row count as the prospect universe. That number is misleading.**

---

## Current System State (Post-Session 70)

### Database
- Size: ~19MB
- Migrations applied: 48 applied (0001–0048). Next migration: 0049.
- Git: clean, branch=main
- Doctor: PASSED (post-Session 70)

### Measurables Pipeline (Session 69)
- prospect_measurables table (Migration 0048): 716 rows. One row per prospect per season.
  Source: jfosterfilm_2026.csv expanded column set (OVR, POS, CON, AGE, HEIGHT, WEIGHT,
  ARM, WING, HAND, 10Y, 40Y, SHUTTLE, 3Cone, VRT, BRD, PROD, ATH, SIZE, SPEED, ACC, AGI).
  CON column (consensus_rank): stored for reference and APEX prompt injection only.
  Not injected into consensus build weights.
- APEX scoring prompt: _get_measurables_context() injected after RAS block in web_context.
  Graceful fallback — no-op if no measurables row exists for the prospect.
- Ingest script: scripts/ingest_jfosterfilm_measurables_2026.py (idempotent, INSERT OR REPLACE).

### Sources

**NGS RULE: Model-output/algorithmic composite scores (ngs_2026) stored with `is_active=0`. A model score is not a scout ranking. Deactivate at ingest time.**

**16 Active Canonical Scout Sources:**

| Tier | Sources | Weight |
|------|---------|--------|
| T1 | pff_2026, thedraftnetwork_2026, theringer_2026 | 1.3x |
| T2 | nfldraftbuzz_2026_v2, cbssports_2026, espn_2026, nytimes_2026, pfsn_2026, jfosterfilm_2026, nflcom_2026, combine_ranks_2026, bleacherreport_2026, fantasypros_2026 | 1.0x |
| T3 | bnbfootball_2026, tankathon_2026, drafttek_2026 | 0.7x |
| Inactive (model) | ngs_2026 (is_active=0) | — |
| Inactive (decommissioned) | combine_2026 (source_id=31, is_active=0) | — |

- `source_canonical_map` entries: resolve duplicates (espn, pff, pfsn-consensus-*, theringer)
- SOURCE NAMING RULE: source name must match file and methodology exactly. combine_2026.csv rankings → combine_ranks_2026. nflcom_2026.csv editorial board → nflcom_2026.
- **jfosterfilm_2026 expanded columns (Session 69):** source_id=1, T2, weight=1.0.
  Ranking columns (feed consensus): OVR rank, POS rank.
  Measurables columns (stored in prospect_measurables, NOT in consensus weights):
  CON (consensus rank, 700+ player coverage), AGE, HEIGHT, WEIGHT, ARM, WING, HAND,
  10Y, 40Y, SHUTTLE, 3Cone, VRT, BRD, PROD, ATH, SIZE, SPEED, ACC, AGI.
  Available in APEX scoring prompt via _get_measurables_context().
- **combine_2026 DECOMMISSIONED Session 69:** source_id=31, is_active=0. CSV removed from
  filesystem. Data superseded by prospect_measurables table (jfosterfilm measurables pipeline).
  ingest_combine_2026.py retained for audit history — prints decommission message and exits.

### Consensus
- Rows: 1001 (rebuilt Session 69)
- Top: #1 Fernando Mendoza QB | #2 Arvell Reese EDGE | #3 Caleb Downs S (per Session 69 rebuild)
- Build method: Full DELETE + INSERT on each rebuild (not upsert). Safe — consensus is derived data.
- Latest board snapshot: snapshot_id=6 (2026-03-18): rows=1001 — PASSED

### APEX Engine
- Version: v2.3
- Scored prospects: 140 active 2026 (is_active=1, is_calibration_artifact=0) + 12 calibration artifacts (excluded from board)
- **Canonical tier labels: ELITE (≥85), DAY1 (≥70), DAY2 (≥55), DAY3 (≥40), UDFA-P (≥28), UDFA (<28)**
  - `compute_apex_tier()` in `engine.py` emits all 6 labels. Board display script (`app/app.py`) recognizes all 6.
- Board tier dist (Session 70, top-50 re-scored): ELITE=3, DAY1=35*, DAY2=66*, DAY3=34, UDFA-P=2 (140 total)
  (*approx — only top 50 re-scored S70; full board re-score pending Session 71 gate)
  Top-50 subset post S70: ELITE=3, DAY1=26, DAY2=20, DAY3=1.
  Pre-S69 snapshot (Session 67): ELITE=4, DAY1=36, DAY2=64, DAY3=34, UDFA-P=2.
- PVC: QB/CB/EDGE=1.0x | OT/S/IDL=0.90x | ILB/OLB=0.85x | OG/TE/C=0.80x | RB=0.70x
- Divergence method: Rank-relative. `consensus_rank` vs `apex_ovr_rank` delta.
- Divergence dist (Session 70): ALIGNED=28, APEX_HIGH=63, APEX_LOW=4, STRUCTURAL=45
- Capital range derived from `apex_composite` (PVC-adjusted), not raw_score. Patched Session 65.
- **CRITICAL OVERRIDE NOTE**: TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES in run_apex_scoring_2026.py use prospect_ids. If DB is ever rebuilt, re-verify ALL prospect_ids in both dicts before running any batch scoring.
- Calibration artifacts: 12 players (PIDs: 230,304,313,455,504,880,1050,1278,1371,1391,1729,1925).
  All is_active=0 + is_calibration_artifact=1. Do NOT re-score. tag_calibration_artifacts_2026.py
  uses explicit PIDs (not display_name matching).

### Positional Archetype Libraries — All 13 Complete

| Position | Archetypes | Notes |
|----------|-----------|-------|
| QB | 6 (QB-1 through QB-6) | SAA mandatory. C2 base weight 11%. |
| EDGE | 5 | PAA. Ezeiruaku 2026 calibration. |
| CB | 5 | PAA. Hunter two-way origin case. |
| ILB | 5 | v2.2 weights. Schwesinger origin. |
| OLB | 5 | C. Paul Jr. 2026 calibration. |
| OT | 5 | PAA. Membou 2026 calibration. |
| IDL | 5 | Table A (Disruptor) + Table B (Anchor). |
| S | 5 | v2.2 SOS gate. Emmanwori calibration. |
| OG | 5 | PAA. Ratledge 2026 calibration. |
| C | 6 | PAA. Wilson Rimington validation. |
| TE | 5 | PAA. Helm 2026 calibration. |
| RB | 5 | PVC 0.70. Carry Accumulation Clock. |
| WR | 5 | PAA. Hunter two-way validation. |

---

## Tag System (Active as of Session 18)

- Schema: tag_definitions (27), tag_trigger_rules (14), prospect_tag_recommendations, prospect_tags, prospect_tag_history
- Step 19 in pipeline: `run_tag_triggers_2026.py` evaluates rules → writes recommendations
- Acceptance workflow: `accept_tag_recs_2026.py` (--list / --accept / --dismiss / --accept-all)
- Triage helper: `triage_pending_tags_2026.py` for batch review
- PREMIUM_POSITIONS = {QB, CB, EDGE, OT, S} for divergence rules only
- `prospect_tag_recommendations` has NO season_id column — do not filter by it
- `tag_trigger_rules` use `=` operator (not `==`) for equality; eval_condition handles both
- Current rec status (Session 64): accepted=224, dismissed=35, pending=0

---

## Snapshot Authority Hierarchy

When state is in conflict, resolve by this priority order (highest to lowest):

1. Database state
2. Migration history (meta_migrations)
3. Git commit state
4. STATE_SNAPSHOT.md
5. Conversation history

Conversation is last and lowest authority. Never infer system state from chat history.

---

## Known Data Quirks

- **Travis Hunter school=Unknown** — Not in universe CSV. Known, non-blocking.
- **Tate Ratledge position_group=TE** — Should be OG per CALIBRATION_OVERRIDES. Pre-existing issue. Non-blocking.
- **APEX tier label migration** — Old labels (APEX/SOLID/DEVELOPMENTAL) replaced by DAY1/DAY2/DAY3 in Session 14. All rows standardized. Board display script (`app/app.py`) already has all 6 tier labels — no fix needed.
- **Jalon Kilgore (pid=309)** — Re-scored Session 18 from CB-3 ELITE 90.0 to S-3 Multiplier Safety DAY2. ARCHETYPE_OVERRIDES entry at pid=309. Combine gate cleared Session 64 (forty=4.40s, shuttle S-tier). Score: 64.1 DAY2, APEX_HIGH +23.
- **Calibration batch GEN traits** — 12 calibration prospects (is_calibration_artifact=1) still have generic trait vectors. Calibration-only — do not re-score for 2026 board signal.
- **Stale override IDs** — If DB is ever rebuilt, re-verify all prospect_ids in TOP50_POSITION_OVERRIDES and ARCHETYPE_OVERRIDES before running batch scoring.
- **RAS join workaround** — `get_big_board()` uses `AND r.ras_total IS NOT NULL` instead of season_id filter. Two-generation RAS data artifact. Revert to season_id join after RAS re-ingest post pro days.
- **jfosterfilm encoding** — `jfosterfilm_2026.csv` is latin-1 encoded. Stage script handles this.
- **jfosterfilm ranked vs unranked** — 293 ranked rows (rank=1..293) + 442 unranked. Ingest ingests ranked only. 322 unranked/RAS-only players inserted directly into prospects during rebuild.
- **TANKATHON + THERINGER** — Raw CSVs use combined Position,School column. `stage_rankings_csv.py` handles with column detection. Do NOT break this logic.
- **Gunnar Helm (pid=842)** — 2025 draftee, ghost row from spamml. `apex_scores` row force-deleted Session 6. Do NOT re-score. Cross-season contamination.
- **CALIBRATION_OVERRIDES position overrides** — Schwesinger=ILB, Membou=OT, Ratledge=OG, Emmanwori=S, Williams=IDL, Paul/Wilson=C
- **D'Angelo Ponds (pid=3236)** — No consensus ranking row; divergence batch skips him. Non-blocking.
- **LB ghost PID splits** — Root cause: early ingests labeled EDGE/QB players as LB → bootstrap LB PID → later correct-position PIDs. 6 cases consolidated Session 62 via consolidate_lb_ghost_pids_s62.py. If new coverage anomalies appear, check for ghost PID splits before acting on divergence signals.
- **The `APEX` board column showing `<NA>`** — This is `apex_rank` (analyst-assigned rank from `prospect_tags`), not the tier label. Expected when no analyst rank is set.

---

## APEX Engine Run Notes

```powershell
# Set API key
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Re-score top-50 (always use --force to overwrite)
python -m scripts.run_apex_scoring_2026 --batch top50 --force --apply 0   # dry run
python -m scripts.run_apex_scoring_2026 --batch top50 --force --apply 1   # execute

# Re-score calibration batch
python -m scripts.run_apex_scoring_2026 --batch calibration --force --apply 1

# Recompute divergence only (no API calls)
python -m scripts.run_apex_scoring_2026 --batch divergence --apply 1

# ALWAYS export after any re-score
sqlite3 .\data\edge\draftos.sqlite ".mode json" ".output data/apex_top50_rescored_sessionN.json" "SELECT * FROM apex_scores;"
```

APEX LOW on non-premium positions (ILB, OLB, OG, C, TE, RB) is structural PVC behavior, not actionable. Monitor APEX_HIGH on premium positions (QB, CB, EDGE, OT, S) only.

---

## Current Priorities (Ordered)

1. **Full batch re-score** — Session 71. Investigate Arvell Reese (#2, pid=16) ELITE→DAY1 drop
   (-8.8 pts, measurables context forty=4.46/ATH=86.6). If justified, run --batch all --force.
   Decision gate report: data/exports/s70_rescore_report.txt.
2. **prospect_comps expansion** — Migration 0047 applied. Seed historical comps for scored prospects.
3. **Post-draft audit framework** — APEX Framework Section 9. Activate after April 2026 draft.
4. **Pre-draft snapshot** — Already run Session 67 (140 rows). Re-run after full batch re-score.
5. **RAS re-ingest (post pro days)** — Already re-ingested S69 (post-combine). Re-run after April pro days.
6. **App UI** — Streamlit app is a stub; `surface_map.md` defines four rendering surfaces.

---

## Session Start Protocol (Required Every Session)

1. Read this file (CLAUDE.md) completely
2. Read STATE_SNAPSHOT.md
3. Run `python scripts/doctor.py` and review output
4. Confirm the Next Milestone before writing any code

If STATE_SNAPSHOT.md is missing or doctor fails — pause and resolve before proceeding.

---

## Session End Protocol (Required)

```bash
git add .
git commit -m "Milestone: <short description>"
python scripts/end_session.py
# REQUIRED: manually update STATE_SNAPSHOT.md with session milestone detail before committing
git add BOOTSTRAP_PACKET.txt STATE_SNAPSHOT.md && git commit -m "chore: end_session..."
```

Copy contents of BOOTSTRAP_PACKET.txt for next session handoff. No session may end without a clean snapshot.

---

## Files Updated Every Session (Mandatory)

| File | Who Updates | How |
|------|-------------|-----|
| STATE_SNAPSHOT.md | You (manually) | Write milestone block, layer status, next target BEFORE committing |
| BOOTSTRAP_PACKET.txt | end_session.py | Auto-generated. Copy contents for next session handoff |
| CLAUDE.md | You (every ~5 sessions) | Sync source list, migration count, priorities with STATE_SNAPSHOT.md |

STATE_SNAPSHOT.md must be updated BEFORE running `git commit`. end_session.py does NOT write
milestone detail — only you can write the narrative of what changed in the session.

---

## Trigger Phrases

- `"Initiate DraftOS Session Close."` → Stop all feature work. Walk through end-of-session steps exactly. Do not continue development.
- `"DRAFTOS CONTINUATION"` → Treat pasted artifacts as authoritative. Reconstruct state from artifacts only. Confirm Next Milestone before any code.

---

## Output Standards for All Changes

Every modification or addition must include:
- Full migration SQL file (if schema changes)
- Full script file — no partials
- Full updated script (if modifying existing)
- Explicit run order
- Verification command
- Dry-run first (`--apply 0`), then apply (`--apply 1`)

No summaries. No partial edits. No placeholders. No "you can add this yourself."

---

## Definition of Production Ready

A feature is production-ready only when ALL of the following are true:
- Idempotent (safe to re-run without data drift)
- Respects `is_active=1` AND `source_canonical_map` deduplication logic
- Writes through the correct pipeline layer
- Passes all doctor checks
- Survives re-run without data drift
- Integrated into `run_weekly_update.py`

---

## What Claude Must Never Do

- Modify historical data or snapshot rows after write
- Run destructive schema changes without a backup step
- Skip idempotency checks
- Write cross-season queries
- Include UI logic in engine scripts
- Provide partial file edits or diffs as the final deliverable
- Treat all `is_active` sources as distinct — always check `source_canonical_map`
- Cite the raw `prospects` table row count as the prospect universe (includes soft-deprecated garbage rows — the universe is 861 canonical prospects)
- Continue development after `"Initiate DraftOS Session Close."` is triggered
- Infer system state from conversation history instead of artifacts
- Score comps by optics instead of mechanism
- Apply generic bust risk ratings without naming the specific FM code
- Make archetype assignments based on size or position instead of winning mechanism
