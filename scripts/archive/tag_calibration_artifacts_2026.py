"""
Tag calibration artifact rows in apex_scores.

Sets is_calibration_artifact=1 for the 12 calibration prospects — 2025 draftees
whose apex_scores rows exist solely as engine validation artifacts, not 2026 board
signal. These players have is_active=0 in prospects (soft-deprecated) but their
apex_scores rows were written with is_calibration_artifact=0 by earlier sessions.

Authoritative source: apex_calibration_batch_patch.json
Prospect IDs confirmed by user review Session 15.

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

# Canonical prospect_ids for calibration artifacts.
# Source of truth: apex_calibration_batch_patch.json (confirmed Session 15).
# These are 2025 draftees — NOT 2026 prospects. All have is_active=0 in prospects.
CALIBRATION_PIDS: dict[int, str] = {
    1925: "Carson Schwesinger",
    455:  "Travis Hunter",
    230:  "Shedeur Sanders",
    1371: "Armand Membou",
    880:  "Tate Ratledge",
    313:  "Gunnar Helm",
    304:  "Trevor Etienne",
    1278: "Nick Emmanwori",
    1729: "Donovan Ezeiruaku",
    1050: "Tyleik Williams",
    504:  "Chris Paul Jr.",
    1391: "Jared Wilson",
}


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

    pids = list(CALIBRATION_PIDS.keys())
    pid_placeholders = ",".join("?" for _ in pids)

    with connect() as conn:
        # Verify all PIDs exist in prospects (informational — is_active=0 is expected)
        rows = conn.execute(
            f"""
            SELECT prospect_id, display_name, is_active
            FROM prospects
            WHERE prospect_id IN ({pid_placeholders})
              AND season_id = ?
            ORDER BY prospect_id
            """,
            (*pids, SEASON_ID),
        ).fetchall()

        print("Calibration prospects — DB verification:")
        found_pids = set()
        for r in rows:
            active_flag = "is_active=0 (correct)" if not r["is_active"] else "WARNING: is_active=1"
            print(f"  pid={r['prospect_id']:5d}  {r['display_name']:<30s}  {active_flag}")
            found_pids.add(r["prospect_id"])

        missing = set(pids) - found_pids
        if missing:
            for pid in sorted(missing):
                print(f"  [WARNING] pid={pid} ({CALIBRATION_PIDS[pid]}) NOT FOUND in DB")

        # Count apex_scores rows already tagged vs needing tagging
        already_tagged = conn.execute(
            f"""
            SELECT COUNT(*) FROM apex_scores
            WHERE is_calibration_artifact = 1
              AND prospect_id IN ({pid_placeholders})
              AND season_id = ?
            """,
            (*pids, SEASON_ID),
        ).fetchone()[0]

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
        print(f"  to be tagged   (is_calibration_artifact=0): {to_tag}")

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

        # Record migration
        conn.execute(
            "INSERT OR IGNORE INTO meta_migrations (name, applied_at) VALUES (?, ?)",
            ("0036_tag_calibration_artifacts", datetime.now(timezone.utc).isoformat()),
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

        print(f"\n[OK] Tagged {after}/{total_apex} apex_scores rows as is_calibration_artifact=1.")
        print("     Migration 0036 recorded in meta_migrations.")


if __name__ == "__main__":
    main()
