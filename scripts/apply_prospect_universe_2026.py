from __future__ import annotations

# --- sys.path bootstrap so "python scripts\..." always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
import re
import shutil
from datetime import datetime, timezone

from draftos.config import PATHS
from draftos.db.connect import connect

# Suffix order matters — put longer alternates first to avoid partial matches.
_SUFFIX_RE = re.compile(
    r"\s+(?:jr\.?|sr\.?|iv|viii|vii|vi|iii|ii|v)\s*$",
    re.IGNORECASE,
)


def strip_periods(norm: str) -> str:
    """Remove all periods (handles T.J. → TJ initials variants)."""
    return norm.replace(".", "")


def normalize_name(n: str) -> str:
    n = n.replace("\xa0", " ").strip()
    n = n.lower()
    n = re.sub(r"[^a-z0-9 '.\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def strip_suffix(norm: str) -> str:
    """Remove trailing generational suffix (Jr., Sr., II, III, IV …) from a normalized name."""
    return _SUFFIX_RE.sub("", norm).strip()


def backup_db() -> Path:
    src     = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst     = out_dir / f"draftos_{ts}_apply_universe.sqlite"
    shutil.copy2(src, dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(description="Soft-deprecate prospects outside canonical 2026 universe.")
    ap.add_argument("--apply", type=int, default=0, help="0=dry run, 1=write")
    args = ap.parse_args()

    universe_path = PATHS.root / "data" / "universe" / "prospect_universe_2026.csv"
    if not universe_path.exists():
        raise SystemExit(
            f"FAIL: Universe CSV not found: {universe_path}\n"
            "Run build_prospect_universe_2026 first."
        )

    # ── Load universe ─────────────────────────────────────────────────────────
    # Multiple lookup sets for suffix-aware and period-aware matching:
    #   universe_names          — exact normalized names from CSV
    #   universe_names_nosuffix — suffix-stripped variants
    #   universe_names_noperiod — period-stripped variants (handles T.J. → TJ)
    #   universe_names_np_ns    — period-stripped then suffix-stripped
    universe_names:          set[str] = set()
    universe_names_nosuffix: set[str] = set()
    universe_names_noperiod: set[str] = set()
    universe_names_np_ns:    set[str] = set()

    with open(universe_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            norm   = row["normalized_name"]
            norm_s = strip_suffix(norm)
            norm_p = strip_periods(norm)
            norm_ps = strip_suffix(norm_p)
            universe_names.add(norm)
            universe_names_nosuffix.add(norm_s)
            universe_names_noperiod.add(norm_p)
            universe_names_np_ns.add(norm_ps)

    print(f"Universe size: {len(universe_names)} normalized names ({len(universe_names_nosuffix)} suffix-stripped, {len(universe_names_noperiod)} period-stripped variants)")

    if args.apply == 1:
        b = backup_db()
        print(f"DB BACKUP: {b}")
    else:
        print("DRY RUN: no DB writes")

    with connect() as conn:
        # Guard: is_active column must exist
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(prospects)").fetchall()]
        if "is_active" not in cols:
            raise SystemExit(
                "FAIL: prospects.is_active column not found. "
                "Run `python -m draftos.db.migrate` first."
            )

        # Fetch all prospects for season_id=1
        prospects = conn.execute(
            "SELECT prospect_id, full_name FROM prospects WHERE season_id = 1"
        ).fetchall()

        matched:   list[int] = []  # prospect_ids in universe
        unmatched: list[int] = []  # prospect_ids NOT in universe

        # Track all normalized forms seen in DB for coverage-gap report
        db_norms_exact:     set[str] = set()
        db_norms_nosuffix:  set[str] = set()

        for p in prospects:
            norm    = normalize_name(p["full_name"] or "")
            norm_s  = strip_suffix(norm)
            norm_p  = strip_periods(norm)
            norm_ps = strip_suffix(norm_p)
            db_norms_exact.add(norm)
            db_norms_nosuffix.add(norm_s)

            in_universe = (
                norm    in universe_names or
                norm    in universe_names_nosuffix or
                norm_s  in universe_names or
                norm_s  in universe_names_nosuffix or
                norm_p  in universe_names_noperiod or
                norm_p  in universe_names_np_ns or
                norm_ps in universe_names_noperiod or
                norm_ps in universe_names_np_ns
            )

            if in_universe:
                matched.append(int(p["prospect_id"]))
            else:
                unmatched.append(int(p["prospect_id"]))

        # Universe names with no DB match (suffix-aware + period-aware)
        db_norms_noperiod  = {strip_periods(n) for n in db_norms_exact}
        db_norms_np_ns     = {strip_suffix(n) for n in db_norms_noperiod}

        unmatched_universe: list[str] = []
        for nm in sorted(universe_names):
            nm_s  = strip_suffix(nm)
            nm_p  = strip_periods(nm)
            nm_ps = strip_suffix(nm_p)
            if (
                nm    not in db_norms_exact and
                nm    not in db_norms_nosuffix and
                nm_s  not in db_norms_exact and
                nm_s  not in db_norms_nosuffix and
                nm_p  not in db_norms_noperiod and
                nm_p  not in db_norms_np_ns and
                nm_ps not in db_norms_noperiod and
                nm_ps not in db_norms_np_ns
            ):
                unmatched_universe.append(nm)

        print(f"\nMatched to universe   (is_active=1): {len(matched)}")
        print(f"Not in universe       (is_active=0): {len(unmatched)}")
        print(f"Universe names with no DB match:     {len(unmatched_universe)}")

        if unmatched_universe:
            print(f"\nUniverse names with NO DB match (all {len(unmatched_universe)}):")
            for nm in unmatched_universe:
                print(f"  {nm}")

        # Gate: if matched < 750, something is wrong — stop and report
        if len(matched) < 750:
            print(
                f"\nGATE FAILURE: only {len(matched)} prospects matched to universe "
                f"(minimum expected: 750). Investigate unmatched names above before proceeding."
            )
            raise SystemExit(1)

        if args.apply != 1:
            print("\nDRY RUN complete. Rerun with --apply 1 to write.")
            return

        # ── Write ─────────────────────────────────────────────────────────────
        for pid in matched:
            conn.execute(
                "UPDATE prospects SET is_active = 1 WHERE prospect_id = ? AND season_id = 1",
                (pid,),
            )

        for pid in unmatched:
            conn.execute(
                "UPDATE prospects SET is_active = 0 WHERE prospect_id = ? AND season_id = 1",
                (pid,),
            )

        conn.commit()
        print(f"\nOK: {len(matched)} prospects set is_active=1")
        print(f"OK: {len(unmatched)} prospects set is_active=0")


if __name__ == "__main__":
    main()
