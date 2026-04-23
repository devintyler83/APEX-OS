"""
Ingest OTC contract history CSVs into contract_history table.

Usage:
    python -m scripts.ingest_contract_history --apply 0   # dry run
    python -m scripts.ingest_contract_history --apply 1   # execute

Constraints:
- Filters to year_signed >= 2016
- Parses dollar strings ($X,XXX,XXX) and cap_pct (XX.X%) to float
- Derives position_group from source filename
- Idempotent: uses INSERT OR IGNORE on (player, team, year_signed, position_group)
- Backs up DB before any write
"""

import argparse
import csv
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from draftos.config import PATHS

SEASON_ID = 1
MIN_YEAR = 2016

CSV_DIR = Path("C:/DraftOS/otc_contract_history")
BACKUP_DIR = Path("C:/DraftOS/backups")

# Filename stem -> position_group mapping
POSITION_MAP = {
    "cornerback_contract_history":              "CB",
    "edge_rusher_contract_history":             "EDGE",
    "quarterback_contract_history":             "QB",
    "wide_receiver_contract_history":           "WR",
    "safety_contract_history":                  "S",
    "linebacker_contract_history":              "LB",
    "interior_defensive_line_contract_history": "IDL",
    "left_tackle_contract_history":             "OT",
    "right_tackle_contract_history":            "OT",
    "left_guard_contract_history":              "OG",
    "right_guard_contract_history":             "OG",
    "center_contract_history":                  "C",
    "running_back_contract_history":            "RB",
    "tight_end_contract_history":               "TE",
}

# Expected CSV column indices (0-based) — all 14 columns, blank spacers at 4, 8, 10
COL_PLAYER     = 0
COL_TEAM       = 1
COL_YEAR       = 2
COL_YEARS      = 3
# col 4 blank
COL_VALUE      = 5
COL_APY        = 6
COL_GUARANTEED = 7
# col 8 blank
COL_CAP_PCT    = 9
# col 10 blank
COL_INF_VALUE  = 11
COL_INF_APY    = 12
COL_INF_GUAR   = 13


def _parse_dollar(raw: str) -> float | None:
    """'$55,000,000' -> 55000000.0; empty/missing -> None."""
    s = raw.strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_pct(raw: str) -> float | None:
    """'24.5%' -> 24.5; empty -> None."""
    s = raw.strip().replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(raw: str) -> int | None:
    s = raw.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _backup_db(db_path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"pre_0058_backup_{ts}.sqlite"
    shutil.copy2(db_path, dest)
    print(f"[backup] DB backed up to {dest}")
    return dest


def _load_csv(csv_path: Path, position_group: str) -> list[dict]:
    rows = []
    with open(csv_path, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if len(header) < 14:
            print(f"  [WARN] {csv_path.name}: unexpected column count {len(header)}, skipping")
            return rows
        for raw in reader:
            if len(raw) < 14:
                continue
            year_raw = raw[COL_YEAR].strip()
            if not year_raw.isdigit():
                continue
            year = int(year_raw)
            if year < MIN_YEAR:
                continue
            rows.append({
                "player":              raw[COL_PLAYER].strip(),
                "team":                raw[COL_TEAM].strip() or None,
                "year_signed":         year,
                "contract_years":      _parse_int(raw[COL_YEARS]),
                "value_dollars":       _parse_dollar(raw[COL_VALUE]),
                "apy_dollars":         _parse_dollar(raw[COL_APY]),
                "guaranteed_dollars":  _parse_dollar(raw[COL_GUARANTEED]),
                "cap_pct":             _parse_pct(raw[COL_CAP_PCT]),
                "inflated_value":      _parse_dollar(raw[COL_INF_VALUE]),
                "inflated_apy":        _parse_dollar(raw[COL_INF_APY]),
                "inflated_guaranteed": _parse_dollar(raw[COL_INF_GUAR]),
                "position_group":      position_group,
            })
    return rows


INSERT_SQL = """
INSERT OR IGNORE INTO contract_history (
    player, team, year_signed, contract_years,
    value_dollars, apy_dollars, guaranteed_dollars, cap_pct,
    inflated_value, inflated_apy, inflated_guaranteed,
    position_group, season_id
) VALUES (
    :player, :team, :year_signed, :contract_years,
    :value_dollars, :apy_dollars, :guaranteed_dollars, :cap_pct,
    :inflated_value, :inflated_apy, :inflated_guaranteed,
    :position_group, :season_id
)
"""

# Uniqueness guard lives on (player, team, year_signed, position_group).
# We add a UNIQUE index to enforce this at the DB level when the table is fresh.
UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ch_unique
ON contract_history(player, team, year_signed, position_group)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], default=0,
                        help="0=dry run, 1=execute writes")
    args = parser.parse_args()
    apply = bool(args.apply)

    db_path = PATHS.db
    if not db_path.exists():
        print(f"[ERROR] DB not found: {db_path}")
        sys.exit(1)

    csv_files = sorted(CSV_DIR.glob("*_contract_history.csv"))
    if not csv_files:
        print(f"[ERROR] No CSVs found in {CSV_DIR}")
        sys.exit(1)

    # Collect all rows across files
    all_batches: list[tuple[str, list[dict]]] = []
    grand_total = 0
    for csv_path in csv_files:
        stem = csv_path.stem  # e.g. "quarterback_contract_history"
        position_group = POSITION_MAP.get(stem)
        if position_group is None:
            print(f"  [WARN] No position mapping for {stem} — skipping")
            continue
        rows = _load_csv(csv_path, position_group)
        print(f"  {csv_path.name:50s}  pos={position_group:4s}  rows={len(rows)}")
        grand_total += len(rows)
        all_batches.append((position_group, rows))

    print(f"\n  Grand total rows (2016+): {grand_total}")

    if not apply:
        print("\n[DRY RUN] No writes performed. Re-run with --apply 1 to execute.")
        return

    # Backup before any write
    _backup_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        # Ensure unique index exists (idempotent — IF NOT EXISTS)
        conn.execute(UNIQUE_INDEX_SQL)
        conn.commit()

        inserted_total = 0
        skipped_total = 0

        for position_group, rows in all_batches:
            if not rows:
                continue
            for row in rows:
                row["season_id"] = SEASON_ID

            before = conn.execute("SELECT changes()").fetchone()[0]
            conn.executemany(INSERT_SQL, rows)
            conn.commit()

            # Count via inserted changes — re-query position count
            count = conn.execute(
                "SELECT COUNT(*) FROM contract_history WHERE position_group=?",
                (position_group,)
            ).fetchone()[0]

            inserted = conn.execute("SELECT changes()").fetchone()[0]
            print(f"  [{position_group:4s}] {len(rows):5d} rows attempted  "
                  f"db_count={count}")
            inserted_total += len(rows)

        final_count = conn.execute("SELECT COUNT(*) FROM contract_history").fetchone()[0]
        print(f"\n[OK] contract_history total rows: {final_count}")

        # Position breakdown
        print("\nPosition breakdown:")
        for pos, cnt in conn.execute(
            "SELECT position_group, COUNT(*) FROM contract_history "
            "GROUP BY position_group ORDER BY position_group"
        ):
            print(f"  {pos:6s}: {cnt}")

    finally:
        conn.close()

    print("\n[DONE] Ingest complete.")


if __name__ == "__main__":
    main()
