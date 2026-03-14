"""
Triage pending system tag recommendations.

Auto-accept or auto-dismiss all pending rows in prospect_tag_recommendations
based on deterministic data quality gates. Accepted tags are written into
prospect_tags (full accept flow -- authoritative table).

Gates:
  AUTO-DISMISS:
    - is_calibration_artifact = 1 on any apex_scores row for that prospect

  AUTO-ACCEPT:
    - Elite RAS, Great RAS, Poor RAS: always (RAS data is clean)
    - Injury Flag, Character Watch, Compression Flag, Scheme Dependent,
      Development Bet, Floor Play: only where prospect has apex_scores row
      with model_version = 'apex_v2.3'
    - Divergence Alert: only where prospect has >= 3 active source rankings
      (joined via source_player_map and sources.is_active = 1)

  LEAVE PENDING (no action):
    - Tags that fail their gate

Usage:
    python -m scripts.triage_pending_tags_2026 --apply 0   # dry run
    python -m scripts.triage_pending_tags_2026 --apply 1   # write

Idempotent: safe to re-run.
"""
from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from draftos.db.connect import connect
from draftos.config import PATHS

SEASON_ID = 1
USER_ID = 1  # devin

# Tags that fire on RAS only -- always trustworthy
RAS_TAGS = {"Elite RAS", "Great RAS", "Poor RAS"}

# Tags that require apex_v2.3 score on the prospect
V23_GATED_TAGS = {
    "Injury Flag",
    "Character Watch",
    "Compression Flag",
    "Scheme Dependent",
    "Development Bet",
    "Floor Play",
}

# Tags that require >= MIN_SOURCES active source rankings
SOURCE_GATED_TAGS = {"Divergence Alert"}

MIN_SOURCES = 3


def _backup_db() -> None:
    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"draftos.sqlite.backup.{ts}"
    shutil.copy2(PATHS.db, dest)
    print(f"  [backup] {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage pending system tag recommendations")
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    apply = bool(args.apply)

    with connect() as conn:

        # -- Build lookup sets -----------------------------------------------

        # Calibration artifact prospect_ids
        calib_pids = {
            r["prospect_id"] for r in conn.execute(
                "SELECT DISTINCT prospect_id FROM apex_scores "
                "WHERE is_calibration_artifact = 1 AND season_id = ?",
                (SEASON_ID,)
            ).fetchall()
        }

        # Prospects with at least one apex_v2.3 score
        v23_pids = {
            r["prospect_id"] for r in conn.execute(
                "SELECT DISTINCT prospect_id FROM apex_scores "
                "WHERE model_version = 'apex_v2.3' AND season_id = ?",
                (SEASON_ID,)
            ).fetchall()
        }

        # Prospects with >= MIN_SOURCES active source rankings.
        # source_rankings has no direct prospect_id — join through
        # source_player_map (source_player_id) and sources (is_active).
        source_counts: dict[int, int] = {}
        for r in conn.execute(
            """
            SELECT spm.prospect_id, COUNT(*) AS cnt
            FROM source_rankings sr
            JOIN source_player_map spm ON spm.source_player_id = sr.source_player_id
            JOIN sources s             ON s.source_id           = sr.source_id
            WHERE sr.season_id = ? AND s.is_active = 1
            GROUP BY spm.prospect_id
            """,
            (SEASON_ID,)
        ).fetchall():
            source_counts[r["prospect_id"]] = r["cnt"]

        sufficient_source_pids = {
            pid for pid, cnt in source_counts.items() if cnt >= MIN_SOURCES
        }

        # Already-actioned recs (idempotency guard)
        already_actioned = {
            r["rec_id"] for r in conn.execute(
                "SELECT rec_id FROM prospect_tag_recommendations "
                "WHERE status != 'pending'"
            ).fetchall()
        }

        # All pending recs with tag name
        pending = conn.execute(
            """
            SELECT r.rec_id, r.prospect_id, r.tag_def_id, r.rule_id,
                   r.triggered_value, td.tag_name
            FROM prospect_tag_recommendations r
            JOIN tag_definitions td ON td.tag_def_id = r.tag_def_id
            WHERE r.status = 'pending'
            ORDER BY r.rec_id
            """
        ).fetchall()

        # -- Triage ----------------------------------------------------------

        to_dismiss: list = []
        to_accept:  list = []
        to_skip:    list = []

        for rec in pending:
            if rec["rec_id"] in already_actioned:
                continue

            pid      = rec["prospect_id"]
            tag_name = rec["tag_name"]

            if pid in calib_pids:
                to_dismiss.append(rec)
                continue

            if tag_name in RAS_TAGS:
                to_accept.append(rec)
            elif tag_name in V23_GATED_TAGS:
                if pid in v23_pids:
                    to_accept.append(rec)
                else:
                    to_skip.append((rec, "no apex_v2.3 score"))
            elif tag_name in SOURCE_GATED_TAGS:
                if pid in sufficient_source_pids:
                    to_accept.append(rec)
                else:
                    to_skip.append(
                        (rec, f"only {source_counts.get(pid, 0)} active sources")
                    )
            else:
                to_skip.append((rec, "unrecognized tag -- manual review"))

        # -- Report ----------------------------------------------------------

        print(f"\n{'='*60}")
        print(f"TAG TRIAGE REPORT  (apply={apply})")
        print(f"{'='*60}")
        print(f"Pending recs:   {len(pending)}")
        print(f"Auto-dismiss:   {len(to_dismiss)}  (calibration artifacts)")
        print(f"Auto-accept:    {len(to_accept)}")
        print(f"Leave pending:  {len(to_skip)}")

        # Accept breakdown by tag
        accept_by_tag: dict[str, int] = defaultdict(int)
        for rec in to_accept:
            accept_by_tag[rec["tag_name"]] += 1
        print("\nAccept breakdown:")
        for tag, cnt in sorted(accept_by_tag.items()):
            print(f"  {tag}: {cnt}")

        # Skip breakdown
        if to_skip:
            print("\nLeft pending (reason):")
            skip_by_reason: dict[str, int] = defaultdict(int)
            for _, reason in to_skip:
                skip_by_reason[reason] += 1
            for reason, cnt in sorted(skip_by_reason.items()):
                print(f"  {reason}: {cnt}")

        if not apply:
            print("\n[DRY RUN] No writes. Run with --apply 1 to execute.")
            return

        # -- Write -----------------------------------------------------------

        _backup_db()
        now = datetime.now(timezone.utc).isoformat()

        # Dismiss calibration artifacts
        for rec in to_dismiss:
            conn.execute(
                "UPDATE prospect_tag_recommendations "
                "SET status='dismissed', actioned_by=?, actioned_at=? "
                "WHERE rec_id=?",
                (USER_ID, now, rec["rec_id"])
            )

        # Accept: update rec + insert into prospect_tags
        for rec in to_accept:
            conn.execute(
                "UPDATE prospect_tag_recommendations "
                "SET status='accepted', actioned_by=?, actioned_at=? "
                "WHERE rec_id=?",
                (USER_ID, now, rec["rec_id"])
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO prospect_tags
                  (prospect_id, tag_def_id, user_id, source, note,
                   rec_id, is_active, created_at)
                VALUES (?, ?, ?, 'system', NULL, ?, 1, ?)
                """,
                (rec["prospect_id"], rec["tag_def_id"], USER_ID,
                 rec["rec_id"], now)
            )

        conn.commit()
        print(
            f"\n[DONE] Dismissed={len(to_dismiss)} | "
            f"Accepted={len(to_accept)} | "
            f"Left pending={len(to_skip)}"
        )


if __name__ == "__main__":
    main()
