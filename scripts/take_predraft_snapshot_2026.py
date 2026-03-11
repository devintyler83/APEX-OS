"""
take_predraft_snapshot_2026.py -- Pre-Draft Board Snapshot (Session 22)

One-time script that writes a frozen "Pre-Draft 2026" board state to
board_snapshots before picks are made. This snapshot is the foundation
for every post-draft audit comparison.

RUN NIGHT BEFORE ROUND 1. Prerequisites:
  - RAS re-ingest complete (post Pro Days)
  - run_tag_trigger_engine_2026 run (tags current)
  - Sources updated with latest rankings
  - Consensus rebuilt after latest source update
  - APEX re-scored with updated RAS data
  - Kilgore rec resolved (accept or dismiss after Pro Day)
  - doctor.py passes clean

Reads from:  apex_scores, prospects, prospect_consensus_rankings,
             divergence_flags, prospect_tags, tag_definitions
Writes to:   board_snapshots
Idempotent:  INSERT OR IGNORE on UNIQUE(snapshot_date, prospect_id)
             Re-running same day: skips existing rows.
             Re-running different day: new snapshot rows (both preserved).
Season:      season_id=1 (2026 draft only)

Usage:
    python -m scripts.take_predraft_snapshot_2026 --apply 0   # dry run
    python -m scripts.take_predraft_snapshot_2026 --apply 1   # write snapshot
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from draftos.config import PATHS
from draftos.db.connect import connect

SEASON_ID      = 1
MODEL_VERSION  = "apex_v2.2"
SNAPSHOT_LABEL = "Pre-Draft 2026"


# ---------------------------------------------------------------------------
# DB backup
# ---------------------------------------------------------------------------

def _backup_db() -> None:
    """Back up the database before any write operation."""
    db_path  = PATHS.db
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_path = db_path.parent / f"{db_path.stem}.backup.predraft_{ts}{db_path.suffix}"
    shutil.copy2(str(db_path), str(bak_path))
    print(f"  [backup] DB backed up -> {bak_path.name}")


# ---------------------------------------------------------------------------
# Snapshot universe loader
# ---------------------------------------------------------------------------

def load_snapshot_universe(conn) -> list[dict]:
    """
    Returns one dict per APEX-scored active non-calibration prospect with
    all fields needed for board_snapshots insert.

    Joins:
      apex_scores           -- composite, tier, capital
      prospects             -- display_name, position_group
      prospect_consensus_rankings -- consensus_rank, tier
      divergence_flags      -- divergence_score, divergence_flag, rank_delta
      prospect_tags         -- active tags as comma-separated string
    """
    rows = conn.execute(
        """
        SELECT
            a.prospect_id,
            p.display_name,
            p.position_group,
            a.apex_composite,
            a.apex_tier,
            a.capital_adjusted         AS apex_capital,
            c.consensus_rank,
            c.tier                     AS consensus_tier,
            d.divergence_score,
            d.divergence_flag,
            d.divergence_rank_delta,
            GROUP_CONCAT(td.tag_name, ', ') FILTER (
                WHERE pt.is_active = 1
            )                          AS tags
        FROM apex_scores a
        JOIN prospects p
          ON p.prospect_id = a.prospect_id
         AND p.season_id   = a.season_id
         AND p.is_active   = 1
        LEFT JOIN prospect_consensus_rankings c
          ON c.prospect_id = a.prospect_id
         AND c.season_id   = a.season_id
        LEFT JOIN divergence_flags d
          ON d.prospect_id   = a.prospect_id
         AND d.season_id     = a.season_id
         AND d.model_version = a.model_version
        LEFT JOIN prospect_tags pt
          ON pt.prospect_id = a.prospect_id
        LEFT JOIN tag_definitions td
          ON td.tag_def_id = pt.tag_def_id
        WHERE a.season_id     = ?
          AND a.model_version = ?
          AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
        GROUP BY a.prospect_id
        ORDER BY a.apex_composite DESC
        """,
        (SEASON_ID, MODEL_VERSION),
    ).fetchall()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Main snapshot logic
# ---------------------------------------------------------------------------

def take_snapshot(conn, apply: bool) -> dict:
    """
    Dry-run or write the pre-draft board snapshot.

    Returns:
      snapshot_date:           str  (UTC date of execution)
      prospects_in_universe:   int
      rows_written:            int
      rows_skipped:            int  (UNIQUE conflict)
    """
    snapshot_date = datetime.now(timezone.utc).date().isoformat()
    universe      = load_snapshot_universe(conn)

    print(f"\n  Snapshot label:  {SNAPSHOT_LABEL}")
    print(f"  Snapshot date:   {snapshot_date}")
    print(f"  Prospects:       {len(universe)}")

    # Determine which rows already exist (for skip counts and idempotency)
    rows = conn.execute(
        """
        SELECT prospect_id FROM board_snapshots
        WHERE snapshot_date = ? AND season_id = ?
        """,
        (snapshot_date, SEASON_ID),
    ).fetchall()
    existing = {r["prospect_id"] for r in rows}

    new_count  = sum(1 for p in universe if p["prospect_id"] not in existing)
    skip_count = len(existing)

    # -----------------------------------------------------------------------
    # Dry run output
    # -----------------------------------------------------------------------
    if not apply:
        print(f"\n=== PRE-DRAFT SNAPSHOT -- DRY RUN ===")
        print(f"Snapshot label: {SNAPSHOT_LABEL}")
        print(f"Snapshot date:  {snapshot_date}")
        print(f"Prospects in universe: {len(universe)}")
        print()

        for p in universe:
            div_str  = f"div={p['divergence_flag']:<18}" if p["divergence_flag"] else " " * 23
            tags_str = f"tags={p['tags']}" if p["tags"] else ""
            status   = "[EXISTS]" if p["prospect_id"] in existing else "[NEW]   "
            print(
                f"  {status} {p['display_name']:<25} {(p['position_group'] or '?'):<5} "
                f"apex={p['apex_composite'] or 'N/A':>5}  "
                f"tier={p['apex_tier'] or 'N/A':<8} "
                f"rank={str(p['consensus_rank'] or 'N/A'):<5} "
                f"{div_str} "
                f"{tags_str}"
            )

        print(f"\n=== SUMMARY (DRY RUN) ===")
        print(f"Rows to write:  {new_count}")
        print(f"Already exist:  {skip_count}")
        if new_count > 0:
            print("Run with --apply 1 to write.")
        else:
            print("All rows already exist for today. Nothing to write.")

        return {
            "snapshot_date":         snapshot_date,
            "prospects_in_universe": len(universe),
            "rows_written":          0,
            "rows_skipped":          skip_count,
        }

    # -----------------------------------------------------------------------
    # Apply: backup + INSERT OR IGNORE
    # -----------------------------------------------------------------------
    _backup_db()

    written      = 0
    skipped      = 0
    tier_counts: dict[str, int] = {}
    now          = datetime.now(timezone.utc).isoformat()

    for p in universe:
        result = conn.execute(
            """
            INSERT OR IGNORE INTO board_snapshots
              (season_id, snapshot_date, snapshot_label,
               prospect_id, apex_composite, apex_tier, apex_capital,
               consensus_rank, consensus_tier,
               divergence_score, divergence_flag, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SEASON_ID,
                snapshot_date,
                SNAPSHOT_LABEL,
                p["prospect_id"],
                p["apex_composite"],
                p["apex_tier"],
                p["apex_capital"],
                p["consensus_rank"],
                p["consensus_tier"],
                p["divergence_score"],
                p["divergence_flag"],
                p["tags"],
            ),
        )
        if result.rowcount > 0:
            written += 1
            t = p["apex_tier"] or "UNKNOWN"
            tier_counts[t] = tier_counts.get(t, 0) + 1
        else:
            skipped += 1

    conn.commit()

    print(f"\n[OK] Snapshot written.")
    print(f"  Rows written: {written}")
    print(f"  Rows skipped (already existed): {skipped}")

    if tier_counts:
        print("\n  Written by tier:")
        for tier in ("ELITE", "DAY1", "DAY2", "DAY3", "UDFA-P", "UDFA", "UNKNOWN"):
            if tier in tier_counts:
                print(f"    {tier}: {tier_counts[tier]}")

    return {
        "snapshot_date":         snapshot_date,
        "prospects_in_universe": len(universe),
        "rows_written":          written,
        "rows_skipped":          skipped,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DraftOS Pre-Draft Board Snapshot -- 2026"
    )
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        required=True,
        help="0=dry run (no writes), 1=write snapshot to DB",
    )
    args  = parser.parse_args()
    apply = bool(args.apply)

    print("=" * 60)
    print("DraftOS Pre-Draft Snapshot  |  Season 2026")
    print(f"Label:  {SNAPSHOT_LABEL}")
    print(f"Model:  {MODEL_VERSION}")
    print(f"Apply:  {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    print("=" * 60)

    with connect() as conn:
        summary = take_snapshot(conn, apply=apply)

    if not apply:
        print("\n[DRY RUN COMPLETE] Run with --apply 1 to write snapshot.")
    else:
        print(
            f"\n[DONE] Pre-Draft snapshot complete. "
            f"{summary['rows_written']} rows written, "
            f"{summary['rows_skipped']} skipped."
        )


if __name__ == "__main__":
    main()
