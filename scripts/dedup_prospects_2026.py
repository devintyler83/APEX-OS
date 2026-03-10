"""
scripts/dedup_prospects_2026.py

Soft-deprecate known duplicate prospect rows for the 2026 season.
Sets is_active=0 on the lower-scored duplicate for each pair.
Does NOT delete any rows. Does NOT touch apex_scores, divergence_flags,
or consensus_rankings — those rows are retained for audit trail.

Idempotent: re-running is safe (UPDATE WHERE is a no-op if already 0).

Usage:
  python -m scripts.dedup_prospects_2026 --apply 0   # dry run
  python -m scripts.dedup_prospects_2026 --apply 1   # write
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone

from draftos.config import PATHS
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Known duplicate pairs — (name, keep_pid, deprecate_pid)
# keep_pid  = higher consensus_score row to preserve
# deprecate_pid = lower-scored duplicate to soft-delete
# ---------------------------------------------------------------------------
DUPLICATE_PAIRS: list[tuple[str, int, int]] = [
    ("Rueben Bain",     449, 4658),
    ("Francis Mauigoa", 450, 4659),
    ("Jermod McCoy",    12,  4661),
    ("Akheem Mesidor",  457, 4662),
    ("Kayden McDonald", 452, 4660),
]

DEPRECATE_PIDS: list[int] = [pair[2] for pair in DUPLICATE_PAIRS]

SEASON_ID = 1


def _backup_db() -> None:
    if not PATHS.db.exists():
        return
    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.dedup_{ts}"
    shutil.copy2(PATHS.db, backup_path)
    print(f"  [backup] {backup_path.name}")


def _fetch_row(conn, pid: int) -> dict | None:
    row = conn.execute(
        """
        SELECT p.prospect_id, p.display_name, p.school_canonical,
               p.is_active, pcr.score, pcr.consensus_rank
        FROM prospects p
        LEFT JOIN prospect_consensus_rankings pcr
            ON pcr.prospect_id = p.prospect_id AND pcr.season_id = ?
        WHERE p.prospect_id = ?
        """,
        (SEASON_ID, pid),
    ).fetchone()
    return dict(row) if row else None


def run(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n=== dedup_prospects_2026 [{mode}] ===\n")

    with connect() as conn:
        if apply:
            _backup_db()

        for name, keep_pid, dep_pid in DUPLICATE_PAIRS:
            print(f"--- {name} ---")
            keep_row = _fetch_row(conn, keep_pid)
            dep_row  = _fetch_row(conn, dep_pid)

            if keep_row is None:
                print(f"  ERROR: keep pid={keep_pid} not found — skipping")
                continue
            if dep_row is None:
                print(f"  ERROR: deprecate pid={dep_pid} not found — skipping")
                continue

            print(
                f"  KEEP      pid={keep_pid:5d}  "
                f"school={keep_row['school_canonical']:<20s}  "
                f"score={keep_row['score']:.4f}  "
                f"rank={keep_row['consensus_rank']}  "
                f"is_active={keep_row['is_active']}"
            )
            print(
                f"  DEPRECATE pid={dep_pid:5d}  "
                f"school={dep_row['school_canonical']:<20s}  "
                f"score={dep_row['score']:.4f}  "
                f"rank={dep_row['consensus_rank']}  "
                f"is_active={dep_row['is_active']}"
            )

            if dep_row["is_active"] == 0:
                print(f"  -> already is_active=0, no-op")
            elif apply:
                conn.execute(
                    "UPDATE prospects SET is_active=0 WHERE prospect_id=? AND season_id=?",
                    (dep_pid, SEASON_ID),
                )
                conn.commit()
                print(f"  -> SET is_active=0 on pid={dep_pid}")
            else:
                print(f"  -> [DRY RUN] would SET is_active=0 on pid={dep_pid}")

        print()
        active_count = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE is_active=1 AND season_id=?",
            (SEASON_ID,),
        ).fetchone()[0]
        print(f"Active prospects (season_id={SEASON_ID}): {active_count}")

        print()
        print("=== Deprecate pid status ===")
        rows = conn.execute(
            f"SELECT prospect_id, display_name, school_canonical, is_active "
            f"FROM prospects "
            f"WHERE prospect_id IN ({','.join('?' * len(DEPRECATE_PIDS))})",
            DEPRECATE_PIDS,
        ).fetchall()
        for r in rows:
            print(f"  {dict(r)}")

    if apply:
        print(f"\n[OK] Dedup applied. {len(DEPRECATE_PIDS)} pids soft-deprecated.")
    else:
        print(f"\n[DRY RUN complete] Re-run with --apply 1 to write.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Soft-deprecate duplicate prospect rows.")
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        required=True,
        help="0 = dry run, 1 = write",
    )
    args = parser.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
