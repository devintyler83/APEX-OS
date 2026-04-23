"""
seed_cb1_comps_s108_batch2.py — Seed 10 CB-1 historical comp records.

Session 108 Batch 2:
  Tier 1: Sanders, Sherman, Law, Woodson, Ramsey
  Tier 2: Asomugha, Madison, Surtain II, Lattimore, Alexander

All 10 records confirmed by Sports Almanac Mode 4.

Migration 0059 (historical_comps_v2) is embedded in this script.
Applies: season_id, nfl_team, draft_year, outcome, primary_fm, secondary_fm,
         era_flag, pvc_eligible, position_note, notes columns.
Backfills: outcome=translation_outcome, primary_fm=fm_code for all existing rows.
Updates: unique index to (player_name, archetype_code, season_id).

KNOWN CONFLICT — Jalen Ramsey (comp_id=560):
  Existing record: translation_outcome=HIT, comp_confidence=A, fm_code=NULL
  Desired record:  outcome=PARTIAL, comp_confidence=B, primary_fm=FM-5
  INSERT OR IGNORE keeps existing. fm5 count = 1 (not 2). hits = 10 (not 8).
  Correction requires a separate UPDATE — not done here per additive-only rule.

Usage:
    python -m scripts.seed_cb1_comps_s108_batch2 --apply 0   # dry run
    python -m scripts.seed_cb1_comps_s108_batch2 --apply 1   # write

Idempotent: INSERT OR IGNORE on (player_name, archetype_code, season_id).
Backup before write.
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH     = Path(r"C:\DraftOS\data\edge\draftos.sqlite")
BACKUP_DIR  = Path(r"C:\DraftOS\backups")
MIGRATION_NAME = "0059_historical_comps_v2"

# CB-1 existing records to mark pvc_eligible=1 (modern-era, post-2004 cap era)
# Champ Bailey (1999 draft) excluded — pre-2004 cap era, pvc_eligible=0
MODERN_CB1_BACKFILL = [
    "Darrelle Revis",
    "Stephon Gilmore",
    "Jalen Ramsey",
    "Patrick Peterson",
]

# ---------------------------------------------------------------------------
# CB-1 SEED RECORDS — 10 records
# All: season_id=1, position='CB', archetype_code='CB-1', is_fm_reference=0
# INSERT OR IGNORE on (player_name, archetype_code, season_id)
# ---------------------------------------------------------------------------

CB1_RECORDS = [
    # ── TIER 1 ─────────────────────────────────────────────────────────────
    {
        "player_name":   "Deion Sanders",
        "draft_year":    1989,
        "nfl_team":      "ATL/SF/DAL/WAS/BAL",
        "outcome":       "HIT",
        "comp_confidence": "A",
        "primary_fm":    None,
        "secondary_fm":  None,
        "era_flag":      "pre2004",
        "pvc_eligible":  0,
        "position_note": None,
        "notes": (
            "Era: 1989-2005 | Peak: 1992-2000 | CB-1 dual-ceiling standard: only confirmed case "
            "of elite athleticism plus elite anticipatory processing operating simultaneously. "
            "53 career INTs. Hall of Fame. PVC excluded - pre-modern cap era. Mechanism anchor only."
        ),
        # Legacy NOT NULL columns
        "mechanism":       "CB-1 dual-ceiling standard: elite athleticism plus elite anticipatory processing simultaneously",
        "outcome_summary": "53 career INTs. Hall of Fame. PVC excluded - pre-modern cap era. Mechanism anchor only.",
        "era_bracket":     "1989-2005",
        "peak_years":      "1992-2000",
        "fm_mechanism":    None,
    },
    {
        "player_name":   "Richard Sherman",
        "draft_year":    2011,
        "nfl_team":      "SEA/SF",
        "outcome":       "HIT",
        "comp_confidence": "A",
        "primary_fm":    None,
        "secondary_fm":  None,
        "era_flag":      "modern",
        "pvc_eligible":  1,
        "position_note": None,
        "notes": (
            "Era: 2011-2021 | Peak: 2012-2016 | CB-1 zone-predator variant: QB-read anticipatory "
            "processing from off-coverage, long-arm catch-point dominance. 36 INTs + 113 PBUs. "
            "Scheme-transcendent SEA and SF. 3x All-Pro. Highest analytical leverage: confirms "
            "CB-1 achievable via zone-dominant pathway."
        ),
        "mechanism":       "CB-1 zone-predator variant: QB-read anticipatory processing from off-coverage",
        "outcome_summary": "36 INTs + 113 PBUs. 3x All-Pro. Scheme-transcendent SEA and SF. Zone-dominant pathway confirmed.",
        "era_bracket":     "2011-2021",
        "peak_years":      "2012-2016",
        "fm_mechanism":    None,
    },
    {
        "player_name":   "Ty Law",
        "draft_year":    1995,
        "nfl_team":      "NE/NYJ/KC/DEN/ARI",
        "outcome":       "HIT",
        "comp_confidence": "A",
        "primary_fm":    None,
        "secondary_fm":  None,
        "era_flag":      "pre2004",
        "pvc_eligible":  0,
        "position_note": None,
        "notes": (
            "Era: 1995-2009 | Peak: 1998-2004 | CB-1 pre-Revis mechanism anchor. Man-coverage "
            "anticipatory processing confirmed against Peyton Manning (3 INTs AFCCG 2003). "
            "5 Pro Bowls, 3 SBs. PVC excluded - pre-modern cap era. Mechanism signal intact "
            "post era-adjustment."
        ),
        "mechanism":       "CB-1 pre-Revis mechanism anchor: man-coverage anticipatory processing confirmed",
        "outcome_summary": "5 Pro Bowls, 3 SBs. 3 INTs vs Manning AFCCG 2003. PVC excluded - pre-modern cap era.",
        "era_bracket":     "1995-2009",
        "peak_years":      "1998-2004",
        "fm_mechanism":    None,
    },
    {
        "player_name":   "Charles Woodson",
        "draft_year":    1998,
        "nfl_team":      "OAK/GB/OAK",
        "outcome":       "HIT",
        "comp_confidence": "A",
        "primary_fm":    None,
        "secondary_fm":  None,
        "era_flag":      "pre2004",
        "pvc_eligible":  0,
        "position_note": (
            "CB/S dual-position: CB-1 classification at draft entry. Transitioned to S role "
            "years 7-12. First-team All-Pro at safety age 32 - CB-1 anticipatory processing "
            "confirmed transfer to S position at peak-career level. Only confirmed case "
            "in historical record."
        ),
        "notes": (
            "Era: 1998-2015 | Peak: 1998-2002 (CB), 2008-2012 (S) | CB-1 dual-peak standard. "
            "DPOY, 9 Pro Bowls across two positions, Hall of Fame. XP-4 aging curve confirmed "
            "at outer boundary. PVC excluded - pre-modern cap era."
        ),
        "mechanism":       "CB-1 dual-peak: anticipatory processing confirmed transfer from CB to S at peak-career level",
        "outcome_summary": "DPOY, 9 Pro Bowls across two positions, Hall of Fame. Only confirmed CB-1 dual-position peak.",
        "era_bracket":     "1998-2015",
        "peak_years":      "1998-2002 (CB), 2008-2012 (S)",
        "fm_mechanism":    None,
    },
    {
        "player_name":   "Jalen Ramsey",
        "draft_year":    2016,
        "nfl_team":      "JAX/LAR/MIA",
        "outcome":       "PARTIAL",
        "comp_confidence": "B",
        "primary_fm":    "FM-5",
        "secondary_fm":  None,
        "era_flag":      "modern",
        "pvc_eligible":  1,
        "position_note": None,
        "notes": (
            "Era: 2016-present | Peak: 2017-2020 | CB-1 versatility peak - scheme-transcendent "
            "across 5 coordinators and 3 franchises. 5 Pro Bowls in peak window. FM-5 activated "
            "post-2020 extension ($105M, 10.1% cap) - production compressed to CB2-level. "
            "Confirms Peterson FM-5 pattern: incentive achieved, investment declined. "
            "Active - update outcome post-career."
        ),
        "mechanism":       "CB-1 versatility peak - scheme-transcendent; FM-5 activated post-2020 contract extension",
        "outcome_summary": "5 Pro Bowls pre-extension. FM-5 post $105M deal. CB2-level production after.",
        "era_bracket":     "2016-present",
        "peak_years":      "2017-2020",
        "fm_mechanism":    "Motivation Cliff — incentive achieved post-$105M extension; investment declined to CB2 production level",
    },
    # ── TIER 2 ─────────────────────────────────────────────────────────────
    {
        "player_name":   "Nnamdi Asomugha",
        "draft_year":    2003,
        "nfl_team":      "OAK/PHI/SF",
        "outcome":       "PARTIAL",
        "comp_confidence": "A",
        "primary_fm":    "FM-6",
        "secondary_fm":  None,
        "era_flag":      "modern",
        "pvc_eligible":  1,
        "position_note": None,
        "notes": (
            "Era: 2003-2013 | Peak: 2006-2010 | CB-1 FM-6 XP-2 confirmation. Oakland press-man "
            "peak - targeted fewer times than any starting CB in league (2008). PHI $60M signing "
            "into zone scheme with no press-man infrastructure = FM-6 organizational collapse. "
            "Mechanism did not fail - activation conditions never provided. "
            "Confirms FM-6 is organizational at CB-1."
        ),
        "mechanism":       "CB-1 FM-6 organizational: press-man mechanism required specific activation conditions not provided at PHI",
        "outcome_summary": "OAK peak untargetable 2008. PHI $60M into zone scheme = FM-6 collapse. Mechanism intact; org failed.",
        "era_bracket":     "2003-2013",
        "peak_years":      "2006-2010",
        "fm_mechanism":    "Organizational Context Collapse — elite press-man mechanism transplanted into zone scheme without infrastructure; activation conditions absent",
    },
    {
        "player_name":   "Sam Madison",
        "draft_year":    1997,
        "nfl_team":      "MIA/NYG/PHI",
        "outcome":       "HIT",
        "comp_confidence": "A",
        "primary_fm":    None,
        "secondary_fm":  None,
        "era_flag":      "pre2004",
        "pvc_eligible":  0,
        "position_note": None,
        "notes": (
            "Era: 1997-2009 | Peak: 1999-2005 | CB-1 compact-frame proof (5-11 / 185lbs). "
            "Anticipatory processing primary - physical tools above-average not dominant. "
            "38 career INTs. System-transcendent MIA and NYG across different coordinators "
            "and scheme families. SB champion (NYG). 4 Pro Bowls. "
            "Most undervalued CB-1 in database. PVC excluded - pre-modern cap era."
        ),
        "mechanism":       "CB-1 compact-frame: anticipatory processing as primary mechanism over physical dominance",
        "outcome_summary": "38 career INTs. SB champion NYG. 4 Pro Bowls. System-transcendent. Most undervalued CB-1.",
        "era_bracket":     "1997-2009",
        "peak_years":      "1999-2005",
        "fm_mechanism":    None,
    },
    {
        "player_name":   "Patrick Surtain II",
        "draft_year":    2021,
        "nfl_team":      "DEN",
        "outcome":       "HIT",
        "comp_confidence": "B",
        "primary_fm":    None,
        "secondary_fm":  None,
        "era_flag":      "modern",
        "pvc_eligible":  1,
        "position_note": None,
        "notes": (
            "Era: 2021-present | Peak: 2022-present (TBD) | CB-1 fastest-confirmation case: "
            "mechanism fully formed at draft entry, CB-1 standard in Year 1. System-transcendent "
            "across 4 coordinators in 4 seasons. 9.4% of cap (2024) - market underpay relative "
            "to mechanism quality. No FM indicators active. Active - update outcome post-career."
        ),
        "mechanism":       "CB-1 fastest-confirmation: mechanism fully formed at draft entry, CB-1 standard Year 1",
        "outcome_summary": "CB-1 standard Year 1. System-transcendent 4 coordinators. No FM indicators. Active.",
        "era_bracket":     "2021-present",
        "peak_years":      "2022-present (TBD)",
        "fm_mechanism":    None,
    },
    {
        "player_name":   "Marshon Lattimore",
        "draft_year":    2017,
        "nfl_team":      "NO/WAS",
        "outcome":       "PARTIAL",
        "comp_confidence": "B",
        "primary_fm":    "FM-4",
        "secondary_fm":  None,
        "era_flag":      "modern",
        "pvc_eligible":  1,
        "position_note": None,
        "notes": (
            "Era: 2017-present | Peak: 2017, 2019-2020 | CB-1 FM-4 primary compression. "
            "Mechanism confirmed Week 3 Year 1 (blanked Mike Evans, 0 catches, 1 INT). "
            "Recurring soft tissue injuries - never played full season as starter. "
            "10.6% of cap (2021 ext) never returned at CB-1 level due to FM-4 snap compression. "
            "First CB-1 + FM-4 record. Active - update post-career."
        ),
        "mechanism":       "CB-1 FM-4 compression: mechanism confirmed Year 1, recurring soft tissue injuries blocked ceiling",
        "outcome_summary": "Blanked Evans Week 3 Year 1. Never played full season. First CB-1 + FM-4 record.",
        "era_bracket":     "2017-present",
        "peak_years":      "2017, 2019-2020",
        "fm_mechanism":    "Carry Accumulation Clock equivalent — snap compression from soft tissue cascade; never accumulated full-season volume to sustain CB-1 output",
    },
    {
        "player_name":   "Jaire Alexander",
        "draft_year":    2018,
        "nfl_team":      "GB",
        "outcome":       "PARTIAL",
        "comp_confidence": "B",
        "primary_fm":    "FM-4",
        "secondary_fm":  None,
        "era_flag":      "modern",
        "pvc_eligible":  1,
        "position_note": None,
        "notes": (
            "Era: 2018-present | Peak: 2019-2021 (pre-injury) | CB-1 FM-4 second case. "
            "Compact-frame (5-11/190). Mechanism confirmed pre-injury: 21 PBUs across "
            "3-season window, blanked Davante Adams in man-press with full film prep available. "
            "2021 shoulder injury = FM-4 compression event. Technique maintenance degraded due "
            "to reduced healthy reps - not motivation deficit (FM-5 excluded). "
            "2022 ext (10.1% cap) not returned at CB-1 level post-injury. Second CB-1 FM-4 "
            "confirms durability as underidentified ceiling compressor. Active - single "
            "franchise (GB) limits cross-system confirmation. Update post-career."
        ),
        "mechanism":       "CB-1 FM-4 second case: compact-frame mechanism confirmed pre-injury; 2021 shoulder = compression event",
        "outcome_summary": "21 PBUs pre-injury. Blanked Adams in man-press. 2021 shoulder = FM-4. Second CB-1 FM-4 case.",
        "era_bracket":     "2018-present",
        "peak_years":      "2019-2021 (pre-injury)",
        "fm_mechanism":    "Carry Accumulation Clock equivalent — shoulder injury 2021 compressed healthy rep accumulation; technique degraded from reduced volume, not motivation (FM-5 excluded)",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def migration_applied(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM meta_migrations WHERE name = ?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None


def index_has_season_id(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_comps_unique'"
    ).fetchone()
    if not row:
        return False
    return "season_id" in (row["sql"] or "")


def backup_db() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"draftos_pre_cb1_batch2_{ts}.sqlite"
    shutil.copy2(DB_PATH, dest)
    return dest


# ---------------------------------------------------------------------------
# Migration 0059 — apply (idempotent)
# ---------------------------------------------------------------------------

NEW_COLUMNS = [
    ("season_id",     "INTEGER NOT NULL DEFAULT 1"),
    ("nfl_team",      "TEXT"),
    ("draft_year",    "INTEGER"),
    ("outcome",       "TEXT"),
    ("primary_fm",    "TEXT"),
    ("secondary_fm",  "TEXT"),
    ("era_flag",      "TEXT"),
    ("pvc_eligible",  "INTEGER NOT NULL DEFAULT 0"),
    ("position_note", "TEXT"),
    ("notes",         "TEXT"),
]


def apply_migration(conn: sqlite3.Connection, apply: bool) -> None:
    already_applied = migration_applied(conn)

    if apply:
        for col_name, col_def in NEW_COLUMNS:
            if not column_exists(conn, "historical_comps", col_name):
                conn.execute(
                    f"ALTER TABLE historical_comps ADD COLUMN {col_name} {col_def}"
                )
                print(f"  APPLY: Added column {col_name} {col_def}")
            else:
                print(f"  SKIP:  Column {col_name} already exists")

        # Backfill alias columns from legacy columns
        conn.execute("UPDATE historical_comps SET outcome = translation_outcome WHERE outcome IS NULL")
        conn.execute("UPDATE historical_comps SET primary_fm = fm_code WHERE primary_fm IS NULL")
        print("  APPLY: Backfilled outcome=translation_outcome, primary_fm=fm_code")

        # Backfill pvc_eligible for known modern-era CB-1 records
        placeholders = ",".join("?" * len(MODERN_CB1_BACKFILL))
        conn.execute(
            f"UPDATE historical_comps SET pvc_eligible = 1 "
            f"WHERE archetype_code = 'CB-1' AND player_name IN ({placeholders})",
            MODERN_CB1_BACKFILL,
        )
        print(f"  APPLY: pvc_eligible=1 set for {MODERN_CB1_BACKFILL}")

        # Update unique index to include season_id
        if not index_has_season_id(conn):
            conn.execute("DROP INDEX IF EXISTS idx_comps_unique")
            conn.execute(
                "CREATE UNIQUE INDEX idx_comps_unique "
                "ON historical_comps(player_name, archetype_code, season_id)"
            )
            print("  APPLY: Unique index updated to (player_name, archetype_code, season_id)")
        else:
            print("  SKIP:  Unique index already includes season_id")

        if not already_applied:
            conn.execute(
                "INSERT OR IGNORE INTO meta_migrations (name, applied_at) VALUES (?, datetime('now'))",
                (MIGRATION_NAME,),
            )
            conn.commit()
            print(f"  APPLY: Migration {MIGRATION_NAME} logged in meta_migrations")
        else:
            conn.commit()
            print(f"  SKIP:  Migration {MIGRATION_NAME} already logged")

    else:
        # Dry-run report
        missing = [c for c, _ in NEW_COLUMNS if not column_exists(conn, "historical_comps", c)]
        present = [c for c, _ in NEW_COLUMNS if column_exists(conn, "historical_comps", c)]
        if missing:
            print(f"  [DRY RUN] Would ADD columns: {missing}")
        if present:
            print(f"  [DRY RUN] Already present: {present}")
        has_idx = index_has_season_id(conn)
        if not has_idx:
            print("  [DRY RUN] Would update unique index to (player_name, archetype_code, season_id)")
        else:
            print("  [DRY RUN] Unique index already includes season_id")
        if not already_applied:
            print(f"  [DRY RUN] Would log {MIGRATION_NAME} in meta_migrations")
        else:
            print(f"  [DRY RUN] {MIGRATION_NAME} already logged")


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------

def seed_records(conn: sqlite3.Connection, apply: bool) -> None:
    inserted = 0
    skipped  = 0
    conflicts = []

    has_season_id = column_exists(conn, "historical_comps", "season_id")

    for rec in CB1_RECORDS:
        # Check for existing record (season_id may not exist yet in dry-run before migration)
        if has_season_id:
            existing = conn.execute(
                "SELECT comp_id, translation_outcome, comp_confidence, fm_code "
                "FROM historical_comps "
                "WHERE player_name=? AND archetype_code='CB-1' AND season_id=1",
                (rec["player_name"],),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT comp_id, translation_outcome, comp_confidence, fm_code "
                "FROM historical_comps "
                "WHERE player_name=? AND archetype_code='CB-1'",
                (rec["player_name"],),
            ).fetchone()

        if not apply:
            # Dry-run: print record and flag conflicts
            print(f"\n  [{rec['player_name']}]")
            print(f"    outcome={rec['outcome']}  confidence={rec['comp_confidence']}  "
                  f"primary_fm={rec['primary_fm']}  era_flag={rec['era_flag']}  "
                  f"pvc_eligible={rec['pvc_eligible']}")
            print(f"    draft_year={rec['draft_year']}  nfl_team={rec['nfl_team']}")
            print(f"    notes (first 80 chars): {rec['notes'][:80]}...")

            if existing:
                ex_outcome = existing["translation_outcome"]
                ex_conf    = existing["comp_confidence"]
                ex_fm      = existing["fm_code"]
                print(f"    *** CONFLICT — comp_id={existing['comp_id']} already exists ***")
                print(f"        existing: outcome={ex_outcome}, confidence={ex_conf}, fm_code={ex_fm}")
                print(f"        desired:  outcome={rec['outcome']}, confidence={rec['comp_confidence']}, "
                      f"primary_fm={rec['primary_fm']}")
                if ex_outcome != rec["outcome"] or ex_fm != rec["primary_fm"]:
                    print(f"        ACTION: INSERT OR IGNORE — existing record KEPT (desired values differ)")
                    conflicts.append(rec["player_name"])
                else:
                    print(f"        ACTION: INSERT OR IGNORE — already matches, no change needed")
                skipped += 1
            else:
                print(f"    ACTION: Will INSERT")
                inserted += 1
            continue

        # Apply mode
        notes_truncated = rec["notes"][:1000]
        conn.execute(
            """
            INSERT OR IGNORE INTO historical_comps (
                player_name, position, archetype_code,
                mechanism, translation_outcome, fm_code, fm_mechanism,
                outcome_summary, era_bracket, peak_years,
                comp_confidence, scheme_context, signature_trait,
                is_fm_reference,
                season_id, nfl_team, draft_year,
                outcome, primary_fm, secondary_fm,
                era_flag, pvc_eligible, position_note, notes
            ) VALUES (
                :player_name, 'CB', 'CB-1',
                :mechanism, :outcome, :primary_fm, :fm_mechanism,
                :outcome_summary, :era_bracket, :peak_years,
                :comp_confidence, NULL, NULL,
                0,
                1, :nfl_team, :draft_year,
                :outcome, :primary_fm, :secondary_fm,
                :era_flag, :pvc_eligible, :position_note, :notes_truncated
            )
            """,
            {**rec, "notes_truncated": notes_truncated},
        )
        changed = conn.execute("SELECT changes()").fetchone()[0]
        if changed > 0:
            inserted += 1
        else:
            existing_row = conn.execute(
                "SELECT comp_id, translation_outcome, comp_confidence, fm_code "
                "FROM historical_comps "
                "WHERE player_name=? AND archetype_code='CB-1' AND season_id=1",
                (rec["player_name"],),
            ).fetchone()
            ex_outcome = existing_row["translation_outcome"] if existing_row else "?"
            ex_fm      = existing_row["fm_code"] if existing_row else "?"
            if ex_outcome != rec["outcome"] or ex_fm != rec["primary_fm"]:
                conflicts.append(rec["player_name"])
            skipped += 1

    if apply:
        conn.commit()

    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n[{mode}] inserted={inserted}  skipped(duplicate)={skipped}  total={len(CB1_RECORDS)}")

    if conflicts:
        print(f"\n*** CONFLICTS — {len(conflicts)} records kept existing values (INSERT OR IGNORE): ***")
        for name in conflicts:
            ex = conn.execute(
                "SELECT comp_id, translation_outcome, comp_confidence, fm_code "
                "FROM historical_comps WHERE player_name=? AND archetype_code='CB-1'",
                (name,),
            ).fetchone()
            desired = next(r for r in CB1_RECORDS if r["player_name"] == name)
            print(f"  {name}: existing outcome={ex['translation_outcome']}/conf={ex['comp_confidence']}/"
                  f"fm={ex['fm_code']} — desired outcome={desired['outcome']}/conf="
                  f"{desired['comp_confidence']}/fm={desired['primary_fm']}")
        print("  NOTE: To correct, run a targeted UPDATE outside this script.")


# ---------------------------------------------------------------------------
# Verification query
# ---------------------------------------------------------------------------

VERIFICATION_SQL = """
SELECT
    archetype_code,
    COUNT(*) as total,
    SUM(pvc_eligible) as pvc_eligible_n,
    SUM(CASE WHEN comp_confidence='A' THEN 1 ELSE 0 END) as high_conf_n,
    SUM(CASE WHEN outcome='HIT'     THEN 1 ELSE 0 END) as hits,
    SUM(CASE WHEN outcome='PARTIAL' THEN 1 ELSE 0 END) as partials,
    SUM(CASE WHEN outcome='TBD'     THEN 1 ELSE 0 END) as tbd,
    SUM(CASE WHEN primary_fm='FM-4' THEN 1 ELSE 0 END) as fm4_count,
    SUM(CASE WHEN primary_fm='FM-5' THEN 1 ELSE 0 END) as fm5_count,
    SUM(CASE WHEN primary_fm='FM-6' THEN 1 ELSE 0 END) as fm6_count,
    SUM(CASE WHEN era_flag='pre2004' THEN 1 ELSE 0 END) as pre2004_n
FROM historical_comps
WHERE archetype_code = 'CB-1'
  AND season_id = 1
GROUP BY archetype_code
"""

EXPECTED = {
    "total": 14,
    "pvc_eligible_n": 8,
    "high_conf_n": 8,
    "fm4_count": 2,
    "fm5_count": 1,   # Note: 2 if Ramsey conflict resolved; 1 with existing HIT/A record
    "fm6_count": 1,
    "pre2004_n": 4,
}

# Note: hits/partials differ from prompt targets due to Ramsey existing HIT/A record.
# Target: hits=8, partials=5. Actual (with Ramsey=HIT kept): hits=10, partials=4.
# Requires separate Ramsey UPDATE to reach prompt targets.


def print_verification(conn: sqlite3.Connection) -> None:
    row = conn.execute(VERIFICATION_SQL).fetchone()
    if not row:
        print("\nVERIFICATION: No CB-1 rows found — something is wrong.")
        return

    print("\nCB-1 VERIFICATION RESULTS:")
    print(f"  total:          {row['total']:>3}   (target: 14)")
    print(f"  pvc_eligible_n: {row['pvc_eligible_n']:>3}   (gate: >=8)")
    print(f"  high_conf_n:    {row['high_conf_n']:>3}   (gate: >=8)")
    print(f"  hits:           {row['hits']:>3}   (expected 10 — 8 per prompt, +2 from Ramsey HIT conflict)")
    print(f"  partials:       {row['partials']:>3}   (expected 4 — 5 per prompt, -1 from Ramsey conflict)")
    print(f"  tbd:            {row['tbd']:>3}   (target: 0)")
    print(f"  fm4_count:      {row['fm4_count']:>3}   (target: 2)")
    print(f"  fm5_count:      {row['fm5_count']:>3}   (target: 1 actual / 2 per prompt if Ramsey corrected)")
    print(f"  fm6_count:      {row['fm6_count']:>3}   (target: 1)")
    print(f"  pre2004_n:      {row['pre2004_n']:>3}   (target: 4)")

    gates_pass = (
        row["total"] == 14
        and row["pvc_eligible_n"] >= 8
        and row["high_conf_n"] >= 8
    )
    print(f"\n  PVC GATES: total=14 OK  pvc_eligible_n>=8 OK  high_conf_n>=8 OK"
          if gates_pass else
          f"\n  PVC GATES: FAILED -- total={row['total']}, pvc_eligible_n={row['pvc_eligible_n']}, "
          f"high_conf_n={row['high_conf_n']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed CB-1 historical comps batch 2 (Session 108)"
    )
    parser.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="0=dry run (default), 1=write to DB"
    )
    args = parser.parse_args()
    apply = bool(args.apply)

    if apply:
        bak = backup_db()
        print(f"Backup: {bak}\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        mode = "APPLY" if apply else "DRY RUN"
        print(f"=== seed_cb1_comps_s108_batch2 [{mode}] ===\n")

        print("--- Migration 0059 ---")
        apply_migration(conn, apply)

        print("\n--- CB-1 Seed Records ---")
        seed_records(conn, apply)

        if apply:
            print_verification(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
