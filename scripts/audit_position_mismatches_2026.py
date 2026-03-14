"""
scripts/audit_position_mismatches_2026.py

Audit and fix incorrect position_group assignments in the prospects table
by comparing DB values against the RAS CSV (ground truth for position).

Root cause: the bootstrap script uses LB as a fallback position when
source_players.raw_position is missing or ambiguous. RAS CSV, which is
based on measurables data and has no position-guessing, is the corrective
source.

Usage:
    python scripts/audit_position_mismatches_2026.py --apply 0           # dry run (default)
    python scripts/audit_position_mismatches_2026.py --apply 1           # write fixes
    python scripts/audit_position_mismatches_2026.py --apply 0 --scored-only
    python scripts/audit_position_mismatches_2026.py --apply 0 --pid 3   # single prospect

NOTE: --apply 1 triggers a DB backup before any writes.
NOTE: does NOT rebuild consensus or snapshot — run those separately if needed.
NOTE: does NOT re-run APEX scoring — positions in apex_scores are archetype-keyed,
      not position-column-keyed (no position column exists in apex_scores).
"""

import argparse
import csv
import datetime
import re
import shutil
import sqlite3
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.positions import normalize_position

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEASON_ID = 1
DRAFT_YEAR = 2026
RAS_CSV = PATHS.imports / "rankings" / "raw" / str(DRAFT_YEAR) / "ras_2026.csv"

# Positions to skip — special teams and FB are not tracked in the universe
_SKIP_POSITIONS: frozenset[str] = frozenset({"ST", "FB"})

# RAS CSV uses some position codes that normalize_position handles incorrectly.
# Pre-process these before calling normalize_position.
_RAS_REMAP: dict[str, str] = {
    "OC": "C",     # Center — normalize_position("OC") -> LB (bug)
    "ED": "DE",    # Edge Defender — normalize to DE -> EDGE
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def norm_name(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ras_to_group(raw_pos: str) -> str | None:
    """
    Convert a RAS CSV position code to a canonical position_group.
    Returns None for special teams / positions we do not track.
    Applies pre-processing to fix known normalize_position() mismatches.
    """
    pos = raw_pos.strip().upper().lstrip("|")  # strip pipe prefix (|S, |K, |P)
    pos = _RAS_REMAP.get(pos, pos)             # fix OC->C, ED->DE
    try:
        group = normalize_position(pos).group
    except Exception:
        return None
    return None if group in _SKIP_POSITIONS else group


def load_ras_map() -> dict[str, tuple[str, str]]:
    """
    Load ras_2026.csv.
    Returns {norm_name: (raw_pos, norm_group)} for all rows with a non-None group.
    """
    result: dict[str, tuple[str, str]] = {}
    with open(RAS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row.get("Name", "").strip()
            raw_pos = row.get("Pos", "").strip()
            if not name or not raw_pos:
                continue
            group = ras_to_group(raw_pos)
            if group is None:
                continue
            result[norm_name(name)] = (raw_pos, group)
    return result


def backup_db() -> Path:
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    dst = PATHS.db.parent / f"draftos_backup_pre_position_fix_{stamp}.sqlite"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PATHS.db, dst)
    print(f"BACKUP: {dst}")
    return dst


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def audit(
    apply: bool,
    scored_only: bool,
    single_pid: int | None,
) -> None:
    ras_map = load_ras_map()
    print(f"RAS CSV loaded: {len(ras_map)} trackable players")

    with connect() as conn:
        # Load prospects
        if single_pid is not None:
            prospects = conn.execute(
                "SELECT prospect_id, display_name, position_group FROM prospects "
                "WHERE prospect_id = ? AND is_active = 1 AND season_id = ?",
                (single_pid, SEASON_ID),
            ).fetchall()
        elif scored_only:
            prospects = conn.execute(
                """
                SELECT p.prospect_id, p.display_name, p.position_group
                FROM prospects p
                JOIN apex_scores a ON a.prospect_id = p.prospect_id
                  AND a.season_id = p.season_id
                  AND a.is_calibration_artifact = 0
                WHERE p.is_active = 1 AND p.season_id = ?
                """,
                (SEASON_ID,),
            ).fetchall()
        else:
            prospects = conn.execute(
                "SELECT prospect_id, display_name, position_group FROM prospects "
                "WHERE is_active = 1 AND season_id = ?",
                (SEASON_ID,),
            ).fetchall()

        # Scored pids for flagging (always load for annotation)
        scored_pids: set[int] = set(
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT prospect_id FROM apex_scores "
                "WHERE season_id = ? AND is_calibration_artifact = 0",
                (SEASON_ID,),
            ).fetchall()
        )

        print(f"Prospects checked: {len(prospects)}")
        print()

        confirmed: list[tuple[int, str, str, str, str]] = []  # pid, name, db_pos, ras_raw, ras_norm
        unmatched: list[tuple[int, str, str]] = []             # pid, name, db_pos

        for row in prospects:
            pid = row["prospect_id"]
            name = row["display_name"]
            db_pos = row["position_group"]
            nn = norm_name(name)

            if nn not in ras_map:
                unmatched.append((pid, name, db_pos))
                continue

            ras_raw, ras_norm = ras_map[nn]
            if ras_norm != db_pos:
                confirmed.append((pid, name, db_pos, ras_raw, ras_norm))

        # ---------------------------------------------------------------------------
        # Print report
        # ---------------------------------------------------------------------------

        if confirmed:
            print(f"=== CONFIRMED MISMATCHES: {len(confirmed)} ===")
            for pid, name, db_pos, ras_raw, ras_norm in sorted(confirmed, key=lambda x: x[2]):
                scored_flag = " [SCORED]" if pid in scored_pids else ""
                print(
                    f"  pid={pid:5d}  {name:30s}  DB={db_pos:6s}  RAS={ras_raw}->{ras_norm}{scored_flag}"
                )
        else:
            print("No confirmed mismatches found.")

        scored_mm = [x for x in confirmed if x[0] in scored_pids]
        print()
        print(f"Scored prospects with mismatches: {len(scored_mm)}")
        for pid, name, db_pos, ras_raw, ras_norm in scored_mm:
            print(f"  pid={pid:5d}  {name:30s}  DB={db_pos:6s}  RAS={ras_raw}->{ras_norm}")

        if not scored_only:
            print()
            print(f"Unmatched (no RAS entry — no action): {len(unmatched)}")

        print()

        # ---------------------------------------------------------------------------
        # Apply fixes
        # ---------------------------------------------------------------------------

        if not apply:
            print("DRY RUN — no changes written. Re-run with --apply 1 to apply fixes.")
            return

        if not confirmed:
            print("Nothing to fix.")
            return

        backup_db()

        updated = 0
        deactivated = 0
        skipped = 0
        for pid, name, db_pos, ras_raw, ras_norm in confirmed:
            scored_flag = " [SCORED]" if pid in scored_pids else ""
            try:
                conn.execute(
                    "UPDATE prospects SET position_group = ?, updated_at = datetime('now') "
                    "WHERE prospect_id = ? AND season_id = ?",
                    (ras_norm, pid, SEASON_ID),
                )
                updated += 1
                print(f"  FIXED     pid={pid:5d}  {name}  {db_pos} -> {ras_norm}{scored_flag}")
            except sqlite3.IntegrityError:
                # A row with the correct position already exists for this (name, school).
                # Deactivate this duplicate incorrect-position row instead of updating it.
                conn.execute(
                    "UPDATE prospects SET is_active = 0, updated_at = datetime('now') "
                    "WHERE prospect_id = ? AND season_id = ?",
                    (pid, SEASON_ID),
                )
                deactivated += 1
                print(f"  DEACT     pid={pid:5d}  {name}  {db_pos} (duplicate — correct {ras_norm} row exists){scored_flag}")

        conn.commit()
        print()
        print(f"Updated {updated} prospect position_group values.")
        print(f"Deactivated {deactivated} duplicate rows (correct-position row already existed.")
        if skipped:
            print(f"Skipped {skipped} rows.")
        print()
        print("NOTE: Consensus and snapshot are NOT automatically rebuilt.")
        print("      Run build_consensus_2026.py and snapshot_board if needed.")
        print("NOTE: apex_scores has no position column — no apex_scores update required.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and fix prospect position mismatches from RAS CSV.")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1],
                        help="0=dry run (default), 1=write fixes")
    parser.add_argument("--scored-only", action="store_true",
                        help="Only audit prospects with an APEX score")
    parser.add_argument("--pid", type=int, default=None,
                        help="Audit a single prospect by prospect_id")
    args = parser.parse_args()

    print("=== audit_position_mismatches_2026.py ===")
    print(f"apply={args.apply}  scored_only={args.scored_only}  pid={args.pid}")
    print()

    audit(
        apply=bool(args.apply),
        scored_only=args.scored_only,
        single_pid=args.pid,
    )


if __name__ == "__main__":
    main()
