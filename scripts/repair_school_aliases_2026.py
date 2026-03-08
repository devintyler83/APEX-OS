"""
scripts/repair_school_aliases_2026.py
--------------------------------------
Data integrity repair: fix 5 corrupted school_aliases entries,
delete 3 NFL abbreviation artifacts, and re-canonicalize affected
source_players and ras_staging rows.

CORRUPTION DISCOVERED 2026-03-07:
  Five aliases map well-known schools to completely wrong canonicals:
    Florida State  -> Colorado   (should be Florida State)
    Michigan State -> Georgia    (should be Michigan State)
    Oklahoma       -> Colorado   (should be Oklahoma)
    Purdue         -> Oregon     (should be Purdue)
    Southern Cal   -> Georgia    (should be USC)

  Three NFL team abbreviation artifacts in school_aliases:
    ATL -> Maryland     (should not exist)
    MIN -> Alabama      (should not exist)
    PHI -> Notre Dame   (should not exist)

SURGICAL GUARANTEE:
  Only source_players/ras_staging rows where raw_school/college_raw
  matches the alias AND school_canonical holds the wrong value are
  updated. Legitimate Colorado, Georgia, Oregon, Maryland, Alabama,
  Notre Dame rows are never touched.

Usage:
  python -m scripts.repair_school_aliases_2026 --apply 0   # dry run
  python -m scripts.repair_school_aliases_2026 --apply 1   # write
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(r"C:\DraftOS\data\edge\draftos.sqlite")
BACKUP_DIR = Path(r"C:\DraftOS\data\backups")

# (alias_key, wrong_canonical, correct_canonical)
# correct_canonical=None means delete the alias and NULL out source_players
ALIAS_CORRECTIONS = [
    ("Florida State",  "Colorado",    "Florida State"),
    ("Michigan State", "Georgia",     "Michigan State"),
    ("Oklahoma",       "Colorado",    "Oklahoma"),
    ("Purdue",         "Oregon",      "Purdue"),
    ("Southern Cal",   "Georgia",     "USC"),
]

NFL_ARTIFACTS = [
    ("ATL", "Maryland"),
    ("MIN", "Alabama"),
    ("PHI", "Notre Dame"),
]


def backup(apply: bool) -> None:
    if not apply:
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = BACKUP_DIR / f"draftos_pre_alias_repair_{ts}.sqlite"
    shutil.copy2(DB_PATH, dst)
    print(f"[BACKUP] {dst}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def audit_alias_repairs(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("PART A — CORRUPTED ALIAS REPAIRS")
    print("=" * 65)
    for alias, wrong, correct in ALIAS_CORRECTIONS:
        cur_row = conn.execute(
            "SELECT school_canonical FROM school_aliases WHERE school_alias = ?",
            (alias,),
        ).fetchone()
        cur_canonical = cur_row["school_canonical"] if cur_row else "(NOT FOUND)"

        sp_count = conn.execute(
            """SELECT COUNT(*) as n FROM source_players
               WHERE raw_school = ? AND school_canonical = ?""",
            (alias, wrong),
        ).fetchone()["n"]

        ras_count = conn.execute(
            """SELECT COUNT(*) as n FROM ras_staging
               WHERE college_raw = ? AND college_canonical = ?""",
            (alias, wrong),
        ).fetchone()["n"]

        print(f"\n  alias:              \"{alias}\"")
        print(f"  current canonical:  \"{cur_canonical}\"")
        print(f"  planned canonical:  \"{correct}\"")
        print(f"  source_players rows to fix: {sp_count}")
        print(f"  ras_staging rows to fix:    {ras_count}")


def audit_nfl_artifacts(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("PART B — NFL ABBREVIATION ARTIFACT DELETIONS")
    print("=" * 65)
    for alias, wrong in NFL_ARTIFACTS:
        cur_row = conn.execute(
            "SELECT school_canonical FROM school_aliases WHERE school_alias = ?",
            (alias,),
        ).fetchone()
        exists = cur_row is not None
        cur_canonical = cur_row["school_canonical"] if cur_row else "(NOT FOUND)"

        sp_count = conn.execute(
            """SELECT COUNT(*) as n FROM source_players
               WHERE raw_school = ? AND school_canonical = ?""",
            (alias, wrong),
        ).fetchone()["n"]

        print(f"\n  alias:              \"{alias}\" -> \"{cur_canonical}\"  exists={exists}")
        print(f"  action:             DELETE alias, set source_players.school_canonical = NULL")
        print(f"  source_players rows to NULL: {sp_count}")


def audit_colorado_georgia_oregon_safety(conn: sqlite3.Connection) -> None:
    """Confirm legitimate rows for Colorado/Georgia/Oregon/Maryland/Alabama/Notre Dame."""
    print()
    print("=" * 65)
    print("SAFETY CHECK — LEGITIMATE ROWS THAT MUST NOT BE TOUCHED")
    print("=" * 65)
    check = [
        ("Colorado",    "raw_school NOT IN ('Florida State','Oklahoma')"),
        ("Georgia",     "raw_school NOT IN ('Michigan State','Southern Cal')"),
        ("Oregon",      "raw_school != 'Purdue'"),
        ("Maryland",    "raw_school != 'ATL'"),
        ("Alabama",     "raw_school != 'MIN'"),
        ("Notre Dame",  "raw_school != 'PHI'"),
    ]
    for canonical, exclusion_filter in check:
        count = conn.execute(
            f"""SELECT COUNT(*) as n FROM source_players
                WHERE school_canonical = ? AND {exclusion_filter}""",
            (canonical,),
        ).fetchone()["n"]
        print(f"  school_canonical='{canonical}'  legitimate rows: {count}  (WILL NOT BE TOUCHED)")


# ---------------------------------------------------------------------------
# Apply helpers
# ---------------------------------------------------------------------------

def apply_alias_repairs(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("APPLYING PART A — ALIAS CORRECTIONS")
    print("=" * 65)

    for alias, wrong, correct in ALIAS_CORRECTIONS:
        # 1. Fix school_aliases
        conn.execute(
            "UPDATE school_aliases SET school_canonical = ? WHERE school_alias = ?",
            (correct, alias),
        )
        alias_rows = conn.execute(
            "SELECT changes() as n"
        ).fetchone()["n"]

        # 2. Fix source_players — surgical: only where raw_school = alias AND wrong canonical
        conn.execute(
            """UPDATE source_players
               SET school_canonical = ?
               WHERE raw_school = ? AND school_canonical = ?""",
            (correct, alias, wrong),
        )
        sp_rows = conn.execute("SELECT changes() as n").fetchone()["n"]

        # 3. Fix ras_staging — surgical: only where college_raw = alias AND wrong canonical
        conn.execute(
            """UPDATE ras_staging
               SET college_canonical = ?, updated_at = ?
               WHERE college_raw = ? AND college_canonical = ?""",
            (correct, datetime.now(timezone.utc).isoformat(), alias, wrong),
        )
        ras_rows = conn.execute("SELECT changes() as n").fetchone()["n"]

        print(f"  \"{alias}\" -> \"{correct}\"")
        print(f"    school_aliases updated: {alias_rows}")
        print(f"    source_players updated: {sp_rows}")
        print(f"    ras_staging updated:    {ras_rows}")


def apply_nfl_artifact_deletions(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("APPLYING PART B — NFL ARTIFACT DELETIONS")
    print("=" * 65)

    for alias, wrong in NFL_ARTIFACTS:
        # 1. Delete alias
        conn.execute(
            "DELETE FROM school_aliases WHERE school_alias = ?",
            (alias,),
        )
        del_rows = conn.execute("SELECT changes() as n").fetchone()["n"]

        # 2. NULL out source_players school_canonical — surgical
        conn.execute(
            """UPDATE source_players
               SET school_canonical = NULL
               WHERE raw_school = ? AND school_canonical = ?""",
            (alias, wrong),
        )
        sp_rows = conn.execute("SELECT changes() as n").fetchone()["n"]

        print(f"  alias \"{alias}\" -> \"{wrong}\"")
        print(f"    school_aliases deleted: {del_rows}")
        print(f"    source_players nulled:  {sp_rows}")


def verify_safety(conn: sqlite3.Connection) -> None:
    """After apply, confirm Colorado/Georgia/Oregon/Maryland/Alabama/Notre Dame unchanged."""
    print()
    print("=" * 65)
    print("POST-APPLY SAFETY VERIFICATION")
    print("=" * 65)
    checks = [
        ("Colorado",    "raw_school NOT IN ('Florida State','Oklahoma')",   "legitimate Colorado rows"),
        ("Georgia",     "raw_school NOT IN ('Michigan State','Southern Cal')", "legitimate Georgia rows"),
        ("Oregon",      "raw_school != 'Purdue'",                          "legitimate Oregon rows"),
        ("Maryland",    "raw_school != 'ATL'",                             "legitimate Maryland rows"),
        ("Alabama",     "raw_school != 'MIN'",                             "legitimate Alabama rows"),
        ("Notre Dame",  "raw_school != 'PHI'",                             "legitimate Notre Dame rows"),
    ]
    all_ok = True
    for canonical, exclusion_filter, label in checks:
        count = conn.execute(
            f"""SELECT COUNT(*) as n FROM source_players
                WHERE school_canonical = ? AND {exclusion_filter}""",
            (canonical,),
        ).fetchone()["n"]
        print(f"  {label}: {count}")
        if count == 0 and canonical in ("Colorado", "Georgia", "Oregon"):
            print(f"  WARNING: {canonical} count is 0 — investigate!")
            all_ok = False
    if all_ok:
        print("\n  [OK] All legitimate rows preserved.")
    else:
        print("\n  [WARN] Review counts above before proceeding.")


def verify_final_aliases(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("FINAL ALIAS STATE")
    print("=" * 65)
    aliases_to_check = [a for a, _, _ in ALIAS_CORRECTIONS] + [a for a, _ in NFL_ARTIFACTS]
    for alias in aliases_to_check:
        row = conn.execute(
            "SELECT school_canonical FROM school_aliases WHERE school_alias = ?",
            (alias,),
        ).fetchone()
        state = f"\"{row['school_canonical']}\"" if row else "(DELETED)"
        print(f"  \"{alias}\" -> {state}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Repair corrupted school_aliases and re-canonicalize source_players")
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True,
                        help="0=dry run, 1=write")
    args = parser.parse_args()
    apply = bool(args.apply)

    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n{'=' * 65}")
    print(f"repair_school_aliases_2026  [{mode}]")
    print(f"{'=' * 65}")

    conn = connect()

    # Always show full audit first
    audit_alias_repairs(conn)
    audit_nfl_artifacts(conn)
    audit_colorado_georgia_oregon_safety(conn)

    if not apply:
        print()
        print("DRY RUN COMPLETE — no changes written.")
        print("Re-run with --apply 1 to execute.")
        conn.close()
        return

    # Backup before any writes
    backup(apply=True)

    try:
        apply_alias_repairs(conn)
        apply_nfl_artifact_deletions(conn)
        conn.commit()
        print("\n[COMMIT OK]")
    except Exception as e:
        conn.rollback()
        print(f"\n[ROLLBACK] Error: {e}")
        raise

    verify_safety(conn)
    verify_final_aliases(conn)

    conn.close()
    print()
    print("repair_school_aliases_2026 complete.")


if __name__ == "__main__":
    main()
