"""
scripts/expand_school_aliases_2026.py
--------------------------------------
Expand school_aliases with 25 missing mappings for the 2026 season.

Covers:
  - Long-form college names (Southern California → USC, etc.)
  - Self-canonical long-forms (Appalachian State → Appalachian State, etc.)
  - Louisiana-Monroe encoding variants (UL Monroe, corrupted U+FFFD form)
  - HTML entity alias safety entries (Texas A&M, Florida A&M — already present,
    INSERT OR IGNORE will skip them)

Also repairs:
  - source_players: any rows where raw_school = 'Texas A&M' / 'Florida A&M'
    but school_canonical is not set correctly (catches any pre-alias-ingest rows)
  - ras_staging: sets college_canonical on unmatched UL Monroe / Louisiana-Monroe
    rows so they are ready for the next RAS ingest run

Usage:
  python -m scripts.expand_school_aliases_2026 --apply 0   # dry run
  python -m scripts.expand_school_aliases_2026 --apply 1   # write

SAFETY:
  - INSERT OR IGNORE on all alias inserts — never overwrites existing aliases
  - Idempotent: safe to re-run
  - Backup written before any writes
"""
from __future__ import annotations

import argparse
import io
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output so U+FFFD and other non-cp1252 chars print correctly
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB_PATH = Path(r"C:\DraftOS\data\edge\draftos.sqlite")
BACKUP_DIR = Path(r"C:\DraftOS\data\backups")


# ---------------------------------------------------------------------------
# Aliases to add
# Each tuple: (school_alias, school_canonical)
# ---------------------------------------------------------------------------

# Long-form → common abbreviation
LONG_FORM_ABBREV = [
    ("Southern California", "USC"),
    ("Louisiana State",     "LSU"),
    ("Texas Christian",     "TCU"),
    ("Central Florida",     "UCF"),
]

# Self-canonicals: long form IS the canonical school name in prospects
SELF_CANONICALS = [
    ("Appalachian State",  "Appalachian State"),
    ("Jackson State",      "Jackson State"),
    ("Virginia State",     "Virginia State"),
    ("Norfolk State",      "Norfolk State"),
    ("NC Central",         "NC Central"),
    ("Howard",             "Howard"),
    ("Dartmouth",          "Dartmouth"),
    ("Liberty",            "Liberty"),
    ("Hawaii",             "Hawaii"),
    ("Tulsa",              "Tulsa"),
    ("Temple",             "Temple"),
    ("North Texas",        "North Texas"),
    ("Missouri State",     "Missouri State"),
    ("Middle Tennessee",   "Middle Tennessee"),
    ("Villanova",          "Villanova"),
    ("Central Oklahoma",   "Central Oklahoma"),
]

# Louisiana-Monroe variants (UL Monroe is the common CSV form; U+FFFD is a
# corrupted dash from a bad CSV encoding)
LOUISIANA_MONROE_VARIANTS = [
    ("UL Monroe",                "Louisiana-Monroe"),
    ("Louisiana-Monroe",         "Louisiana-Monroe"),
    ("Louisiana\ufffdMonroe",    "Louisiana-Monroe"),   # U+FFFD replacement char
]

# HTML entity safety entries — the canonical clean forms. INSERT OR IGNORE
# will silently skip these if they already exist.
HTML_ENTITY_SAFETY = [
    ("Texas A&M",   "Texas A&M"),
    ("Florida A&M", "Florida A&M"),
]

ALL_ALIASES = (
    LONG_FORM_ABBREV
    + SELF_CANONICALS
    + LOUISIANA_MONROE_VARIANTS
    + HTML_ENTITY_SAFETY
)

# school_canonical values that need source_players.school_canonical fixed
# (any rows where raw_school matches but school_canonical is wrong/NULL)
SP_CANONICAL_REPAIRS = [
    # (raw_school values to match, correct_canonical)
    (["Texas A&M",   "Texas A&amp;M"],  "Texas A&M"),
    (["Florida A&M", "Florida A&amp;M"], "Florida A&M"),
]

# ras_staging college_canonical pre-fills for unmatched Monroe variants
RAS_MONROE_REPAIRS = [
    "UL Monroe",
    "Louisiana-Monroe",
    "Louisiana\ufffdMonroe",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = BACKUP_DIR / f"draftos_pre_expand_aliases_{ts}.sqlite"
    shutil.copy2(DB_PATH, dst)
    print(f"[BACKUP] {dst}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Dry-run audit
# ---------------------------------------------------------------------------

def audit(conn: sqlite3.Connection) -> None:
    current_count = conn.execute("SELECT COUNT(*) FROM school_aliases").fetchone()[0]
    print()
    print("=" * 65)
    print(f"DRY RUN AUDIT — expand_school_aliases_2026")
    print(f"Current school_aliases count: {current_count}")
    print("=" * 65)

    print()
    print("PART A — Aliases to insert (INSERT OR IGNORE)")
    print("-" * 65)
    already_present = 0
    will_insert = 0
    for alias, canonical in ALL_ALIASES:
        exists = conn.execute(
            "SELECT 1 FROM school_aliases WHERE school_alias = ?", (alias,)
        ).fetchone()
        if exists:
            print(f"  SKIP (exists): '{alias}' -> '{canonical}'")
            already_present += 1
        else:
            print(f"  INSERT:        '{alias}' -> '{canonical}'")
            will_insert += 1

    print()
    print(f"  Total in list:     {len(ALL_ALIASES)}")
    print(f"  Will insert:       {will_insert}")
    print(f"  Already present:   {already_present}")
    print(f"  Expected new count: {current_count + will_insert}")

    print()
    print("PART B — source_players school_canonical repairs")
    print("-" * 65)
    for raw_schools, correct_canonical in SP_CANONICAL_REPAIRS:
        placeholders = ",".join("?" for _ in raw_schools)
        count = conn.execute(
            f"""SELECT COUNT(*) FROM source_players
                WHERE raw_school IN ({placeholders})
                AND (school_canonical IS NULL OR school_canonical != ?)""",
            raw_schools + [correct_canonical],
        ).fetchone()[0]
        already_correct = conn.execute(
            f"""SELECT COUNT(*) FROM source_players
                WHERE raw_school IN ({placeholders})
                AND school_canonical = ?""",
            raw_schools + [correct_canonical],
        ).fetchone()[0]
        print(f"  raw_school IN {raw_schools}:")
        print(f"    rows needing update: {count}")
        print(f"    already correct:     {already_correct}")

    print()
    print("PART C — ras_staging college_canonical pre-fills (unmatched Monroe variants)")
    print("-" * 65)
    placeholders = ",".join("?" for _ in RAS_MONROE_REPAIRS)
    ras_count = conn.execute(
        f"""SELECT COUNT(*) FROM ras_staging
            WHERE college_raw IN ({placeholders})
            AND matched_prospect_id IS NULL
            AND (college_canonical IS NULL OR college_canonical != 'Louisiana-Monroe')""",
        RAS_MONROE_REPAIRS,
    ).fetchone()[0]
    print(f"  Unmatched Monroe rows to pre-fill college_canonical: {ras_count}")
    # Show the raw values present
    rows = conn.execute(
        f"""SELECT college_raw, COUNT(*) as cnt
            FROM ras_staging
            WHERE college_raw IN ({placeholders})
            AND matched_prospect_id IS NULL
            GROUP BY college_raw""",
        RAS_MONROE_REPAIRS,
    ).fetchall()
    for r in rows:
        print(f"    [{r['college_raw']}]  cnt={r['cnt']}")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_aliases(conn: sqlite3.Connection) -> int:
    print()
    print("=" * 65)
    print("PART A — Inserting aliases")
    print("=" * 65)
    inserted = 0
    skipped = 0
    for alias, canonical in ALL_ALIASES:
        conn.execute(
            "INSERT OR IGNORE INTO school_aliases (school_alias, school_canonical) VALUES (?, ?)",
            (alias, canonical),
        )
        n = conn.execute("SELECT changes()").fetchone()[0]
        if n > 0:
            print(f"  INSERTED: '{alias}' -> '{canonical}'")
            inserted += 1
        else:
            print(f"  SKIPPED (exists): '{alias}'")
            skipped += 1
    print(f"\n  Inserted: {inserted}  |  Skipped: {skipped}")
    return inserted


def apply_sp_repairs(conn: sqlite3.Connection) -> int:
    print()
    print("=" * 65)
    print("PART B — source_players school_canonical repairs")
    print("=" * 65)
    total = 0
    now = utcnow()
    for raw_schools, correct_canonical in SP_CANONICAL_REPAIRS:
        placeholders = ",".join("?" for _ in raw_schools)
        conn.execute(
            f"""UPDATE source_players
                SET school_canonical = ?
                WHERE raw_school IN ({placeholders})
                AND (school_canonical IS NULL OR school_canonical != ?)""",
            [correct_canonical] + raw_schools + [correct_canonical],
        )
        n = conn.execute("SELECT changes()").fetchone()[0]
        print(f"  '{correct_canonical}': {n} source_players rows updated")
        total += n
    return total


def apply_ras_monroe_repairs(conn: sqlite3.Connection) -> int:
    print()
    print("=" * 65)
    print("PART C — ras_staging Monroe pre-fills")
    print("=" * 65)
    now = utcnow()
    placeholders = ",".join("?" for _ in RAS_MONROE_REPAIRS)
    conn.execute(
        f"""UPDATE ras_staging
            SET college_canonical = 'Louisiana-Monroe',
                updated_at = ?
            WHERE college_raw IN ({placeholders})
            AND matched_prospect_id IS NULL
            AND (college_canonical IS NULL OR college_canonical != 'Louisiana-Monroe')""",
        [now] + RAS_MONROE_REPAIRS,
    )
    n = conn.execute("SELECT changes()").fetchone()[0]
    print(f"  ras_staging Monroe rows pre-filled: {n}")
    return n


def verify(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("VERIFICATION")
    print("=" * 65)
    total = conn.execute("SELECT COUNT(*) FROM school_aliases").fetchone()[0]
    print(f"  school_aliases total: {total}")

    spot_checks = [
        "Southern California", "Louisiana State", "Texas Christian",
        "Central Florida", "UL Monroe", "Louisiana-Monroe",
        "Texas A&M", "Florida A&M",
    ]
    print()
    print("  Spot-check aliases:")
    for alias in spot_checks:
        row = conn.execute(
            "SELECT school_canonical FROM school_aliases WHERE school_alias = ?",
            (alias,),
        ).fetchone()
        state = f"'{row['school_canonical']}'" if row else "(NOT FOUND)"
        print(f"    '{alias}' -> {state}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expand school_aliases with 25 missing mappings for 2026."
    )
    parser.add_argument(
        "--apply", type=int, choices=[0, 1], required=True,
        help="0=dry run, 1=write"
    )
    args = parser.parse_args()
    apply = bool(args.apply)

    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n{'=' * 65}")
    print(f"expand_school_aliases_2026  [{mode}]")
    print(f"{'=' * 65}")

    conn = connect()
    audit(conn)

    if not apply:
        print()
        print("DRY RUN COMPLETE — no changes written.")
        print("Re-run with --apply 1 to execute.")
        conn.close()
        return

    # Backup before any writes
    backup()

    try:
        n_aliases = apply_aliases(conn)
        n_sp = apply_sp_repairs(conn)
        n_ras = apply_ras_monroe_repairs(conn)
        conn.commit()
        print("\n[COMMIT OK]")
        print(f"  Aliases inserted:           {n_aliases}")
        print(f"  source_players updated:     {n_sp}")
        print(f"  ras_staging Monroe updated: {n_ras}")
    except Exception as e:
        conn.rollback()
        print(f"\n[ROLLBACK] Error: {e}")
        raise

    verify(conn)
    conn.close()
    print()
    print("expand_school_aliases_2026 complete.")


if __name__ == "__main__":
    main()
