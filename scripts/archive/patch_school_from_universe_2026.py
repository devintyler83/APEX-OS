"""
patch_school_from_universe_2026.py

Fixes prospects.school_canonical = 'Unknown' / '' / NULL by matching against
data/universe/prospect_universe_2026.csv (authoritative school source).

Matching strategy (two-pass):
  Pass 1: exact match on prospects.name_norm == universe.normalized_name
  Pass 2: name_norm_and_key(universe.display_name)[0] == prospects.name_norm
          (handles T.J./A.J. period-strip divergence between CSV and DB)

For ALL active prospects (not just Unknown), also enforces universe school as
authoritative if there is a mismatch.

Usage:
  python -m scripts.patch_school_from_universe_2026 --apply 0   # dry run
  python -m scripts.patch_school_from_universe_2026 --apply 1   # write
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

from draftos.config import PATHS
from draftos.normalize.names import name_norm_and_key

# ---------------------------------------------------------------------------
UNIVERSE_CSV = Path(PATHS.root) / "data" / "universe" / "prospect_universe_2026.csv"
SEASON_ID = 1


def build_universe_lookup(csv_path: Path) -> dict[str, str]:
    """
    Returns dict: name_norm (DB-style) -> school.
    Builds two variants per row:
      1. row['normalized_name'] as-is (may match DB name_norm directly)
      2. name_norm_and_key(row['display_name'])[0] — DB-pipeline equivalent
    Variant 2 takes priority (more accurate); variant 1 is fallback.
    """
    lookup: dict[str, str] = {}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            school = (row.get("school") or "").strip()
            if not school:
                continue

            raw_norm = (row.get("normalized_name") or "").strip()
            if raw_norm:
                lookup.setdefault(raw_norm, school)

            display = (row.get("display_name") or "").strip()
            if display:
                db_norm, _ = name_norm_and_key(display)
                if db_norm:
                    lookup[db_norm] = school  # overwrite — display-derived is authoritative

    return lookup


def run(apply: bool) -> None:
    db_path = PATHS.db
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    lookup = build_universe_lookup(UNIVERSE_CSV)
    print(f"Universe lookup built: {len(lookup)} entries")

    # Fetch all active prospects
    cur.execute("""
        SELECT prospect_id, full_name, name_norm, school_canonical
        FROM prospects
        WHERE is_active = 1
          AND season_id = ?
    """, (SEASON_ID,))
    prospects = cur.fetchall()
    print(f"Active prospects fetched: {len(prospects)}")

    fix_unknown: list[tuple[int, str, str, str]] = []   # (pid, full_name, old_school, new_school)
    fix_mismatch: list[tuple[int, str, str, str]] = []  # (pid, full_name, old_school, new_school)

    for row in prospects:
        pid       = row["prospect_id"]
        full_name = row["full_name"] or ""
        name_norm = (row["name_norm"] or "").strip()
        old_school = (row["school_canonical"] or "").strip()

        # Try to find universe school
        new_school: str | None = None
        if name_norm:
            new_school = lookup.get(name_norm)
        # Fallback: match by DB-pipeline normalization of full_name
        if new_school is None and full_name:
            db_norm, _ = name_norm_and_key(full_name)
            if db_norm:
                new_school = lookup.get(db_norm)

        if new_school is None:
            continue  # not in universe — skip

        is_unknown = old_school in ("", "Unknown") or not old_school
        is_mismatch = (not is_unknown) and (old_school != new_school)

        if is_unknown:
            fix_unknown.append((pid, full_name, old_school, new_school))
        elif is_mismatch:
            fix_mismatch.append((pid, full_name, old_school, new_school))

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print(f"\n[UNKNOWN school fixes] {len(fix_unknown)} prospects will be updated")
    for pid, name, old, new in fix_unknown[:20]:
        print(f"  pid={pid:5d}  {name:<35s}  '' -> {new}")
    if len(fix_unknown) > 20:
        print(f"  ... ({len(fix_unknown) - 20} more)")

    print(f"\n[MISMATCH school fixes] {len(fix_mismatch)} prospects will be updated")
    for pid, name, old, new in fix_mismatch[:20]:
        print(f"  pid={pid:5d}  {name:<35s}  '{old}' -> {new}")
    if len(fix_mismatch) > 20:
        print(f"  ... ({len(fix_mismatch) - 20} more)")

    total = len(fix_unknown) + len(fix_mismatch)
    print(f"\nTotal updates: {total}")

    if not apply:
        print("\n[DRY RUN] No changes written. Pass --apply 1 to commit.")
        conn.close()
        return

    # -----------------------------------------------------------------------
    # Apply
    # -----------------------------------------------------------------------
    all_fixes = fix_unknown + fix_mismatch
    updated = 0
    skipped = 0
    for pid, full_name, _, new_school in all_fixes:
        # Guard: only update if no existing row would become a duplicate.
        # Unique constraint: (season_id, full_name, school_canonical, position_group).
        # Get position_group for this pid first.
        cur.execute("""
            SELECT position_group FROM prospects WHERE prospect_id = ? AND season_id = ?
        """, (pid, SEASON_ID))
        row = cur.fetchone()
        if row is None:
            skipped += 1
            continue
        pos_group = row["position_group"]

        # Check for conflict
        cur.execute("""
            SELECT prospect_id, name_norm FROM prospects
             WHERE season_id        = ?
               AND full_name        = ?
               AND school_canonical = ?
               AND position_group   = ?
               AND prospect_id     != ?
        """, (SEASON_ID, full_name, new_school, pos_group, pid))
        conflict_rows = cur.fetchall()

        if conflict_rows:
            # Resolve: if the conflicting row has name_norm IS NULL (not bootstrapped/normalized),
            # it is a source-ingest artifact — deactivate it, then update the primary row.
            # If the conflicting row has name_norm populated, skip (ambiguous conflict).
            all_resolvable = all(r["name_norm"] is None for r in conflict_rows)
            if all_resolvable:
                for cr in conflict_rows:
                    # Deactivate and clear school_canonical (to a unique marker) so
                    # the unique constraint slot is freed for the primary row.
                    marker = f"__dedup_{cr['prospect_id']}__"
                    cur.execute("""
                        UPDATE prospects
                           SET is_active        = 0,
                               school_canonical = ?,
                               updated_at       = datetime('now')
                         WHERE prospect_id = ? AND season_id = ?
                    """, (marker, cr["prospect_id"], SEASON_ID))
            else:
                skipped += 1
                continue

        try:
            cur.execute("""
                UPDATE prospects
                   SET school_canonical = ?,
                       updated_at       = datetime('now')
                 WHERE prospect_id = ?
                   AND season_id   = ?
            """, (new_school, pid, SEASON_ID))
            updated += cur.rowcount
        except sqlite3.IntegrityError:
            # Remaining conflict — skip and log
            skipped += 1
            continue

    conn.commit()
    conn.close()
    print(f"\n[APPLIED] {updated} rows updated, {skipped} skipped (constraint conflict or not found).")

    # -----------------------------------------------------------------------
    # Verification
    # -----------------------------------------------------------------------
    print("\n--- Verification ---")
    conn2 = sqlite3.connect(str(db_path))
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT COUNT(*) FROM prospects
        WHERE is_active = 1
          AND season_id = ?
          AND (school_canonical IN ('', 'Unknown') OR school_canonical IS NULL)
    """, (SEASON_ID,))
    remaining = cur2.fetchone()[0]
    print(f"Remaining unknown/empty school (active): {remaining}")

    cur2.execute("""
        SELECT full_name, position_group, school_canonical
        FROM prospects
        WHERE is_active = 1 AND season_id = ?
        ORDER BY prospect_id
        LIMIT 20
    """, (SEASON_ID,))
    print("\nTop 20 active prospects:")
    for r in cur2.fetchall():
        print(f"  {r[0]:<35s} {r[1]:<6s} {r[2]}")
    conn2.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch school_canonical from universe CSV")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1],
                        help="0=dry run, 1=write (default: 0)")
    args = parser.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
