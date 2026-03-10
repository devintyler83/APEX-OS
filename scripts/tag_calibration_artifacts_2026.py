"""
Tag calibration artifact rows in apex_scores.

Sets is_calibration_artifact=1 for all apex_scores rows belonging to the 11
calibration prospects (2025 draftees whose rows are engine validation artifacts,
not 2026 board signal).

Usage:
    python -m scripts.tag_calibration_artifacts_2026 --apply 0   # dry run
    python -m scripts.tag_calibration_artifacts_2026 --apply 1   # write

Idempotent: safe to re-run. Already-tagged rows are not double-counted.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.db.connect import connect
from draftos.config import PATHS

SEASON_ID = 1

# Canonical display_names of calibration prospects (2025 draftees / engine
# validation artifacts). These names must match prospects.display_name exactly
# for the best-ranked DB entry per player (the pid used in CALIBRATION_OVERRIDES).
CALIBRATION_NAMES: list[str] = [
    "Carson Schwesingerucla",   # pid=1464 — best-ranked entry
    "Travis Hunter",            # pid=885
    "Shedeur Sanders",          # pid=813
    "Armand Membou",            # pid=1717
    "Tate Ratledge",            # pid=1254
    "Trevor Etienne",           # pid=838
    "Nick Emmanwori",           # pid=1591
    "Donovan Ezeiruakuboston",  # pid=1420 — best-ranked entry
    "Tyleik Williams",          # pid=1405
    "Chris Paul",               # pid=916 — DB stores as 'Chris Paul', not 'Chris Paul Jr.'
    "Jared Wilson",             # pid=1736
]


def _backup_db() -> Path:
    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.{ts}"
    shutil.copy2(PATHS.db, backup_path)
    print(f"  [backup] {backup_path}")
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tag calibration artifact rows in apex_scores"
    )
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        required=True,
        help="0=dry run, 1=write",
    )
    args = parser.parse_args()
    apply = bool(args.apply)

    with connect() as conn:
        # Resolve prospect_ids for calibration names
        placeholders = ",".join("?" for _ in CALIBRATION_NAMES)
        pid_rows = conn.execute(
            f"""
            SELECT prospect_id, display_name
            FROM prospects
            WHERE display_name IN ({placeholders})
              AND season_id = ?
            """,
            (*CALIBRATION_NAMES, SEASON_ID),
        ).fetchall()

        pids = [r["prospect_id"] for r in pid_rows]
        resolved_names = [r["display_name"] for r in pid_rows]

        print(f"Resolved {len(pids)} prospect_ids from {len(CALIBRATION_NAMES)} calibration names:")
        for r in pid_rows:
            print(f"  pid={r['prospect_id']}  name={r['display_name']}")

        unresolved = set(CALIBRATION_NAMES) - set(resolved_names)
        if unresolved:
            print(f"  [WARNING] Names not found in DB: {sorted(unresolved)}")

        if not pids:
            print("[ERROR] No prospect_ids resolved. Aborting.")
            return

        # Count currently tagged
        pid_placeholders = ",".join("?" for _ in pids)
        already_tagged = conn.execute(
            f"""
            SELECT COUNT(*) FROM apex_scores
            WHERE is_calibration_artifact = 1
              AND prospect_id IN ({pid_placeholders})
              AND season_id = ?
            """,
            (*pids, SEASON_ID),
        ).fetchone()[0]

        # Count rows that would be tagged (not yet tagged)
        to_tag = conn.execute(
            f"""
            SELECT COUNT(*) FROM apex_scores
            WHERE is_calibration_artifact = 0
              AND prospect_id IN ({pid_placeholders})
              AND season_id = ?
            """,
            (*pids, SEASON_ID),
        ).fetchone()[0]

        total_apex = conn.execute(
            f"""
            SELECT COUNT(*) FROM apex_scores
            WHERE prospect_id IN ({pid_placeholders})
              AND season_id = ?
            """,
            (*pids, SEASON_ID),
        ).fetchone()[0]

        print(f"\napex_scores rows for calibration prospects: {total_apex}")
        print(f"  already tagged (is_calibration_artifact=1): {already_tagged}")
        print(f"  will be tagged (is_calibration_artifact=0): {to_tag}")

        if not apply:
            print(f"\n[DRY RUN] Would set is_calibration_artifact=1 on {to_tag} rows.")
            print("Run with --apply 1 to write.")
            return

        if to_tag == 0:
            print("\n[COMPLETE] All calibration rows already tagged. Nothing to do.")
            return

        _backup_db()

        conn.execute(
            f"""
            UPDATE apex_scores
            SET is_calibration_artifact = 1
            WHERE is_calibration_artifact = 0
              AND prospect_id IN ({pid_placeholders})
              AND season_id = ?
            """,
            (*pids, SEASON_ID),
        )
        conn.commit()

        # Verify
        after = conn.execute(
            f"""
            SELECT COUNT(*) FROM apex_scores
            WHERE is_calibration_artifact = 1
              AND prospect_id IN ({pid_placeholders})
              AND season_id = ?
            """,
            (*pids, SEASON_ID),
        ).fetchone()[0]

        print(f"\n[OK] Tagged {after} rows as is_calibration_artifact=1.")


if __name__ == "__main__":
    main()
