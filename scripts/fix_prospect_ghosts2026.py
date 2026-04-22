"""
fix_prospect_ghosts2026.py
Dry-run classifier for prospect ghost / duplicate PIDs — season_id=1 (2026).
Read-only. No writes. Safe to run at any time.

Usage:
    python -m scripts.fix_prospect_ghosts2026
    python -m scripts.fix_prospect_ghosts2026 --name "Treydan Stukes"
    python -m scripts.fix_prospect_ghosts2026 --summary

Classification categories
--------------------------
DEDUP_GHOST        __dedup_* or __ghost_* school_canonical — always non-canonical markers.
                   Action plan: DEACTIVATE (if active) + REMOVE_FROM_SNAPSHOTS.

INACTIVE_SNAPSHOT  is_active=0, real school, still present in prospect_board_snapshot_rows.
                   Action plan: REMOVE_FROM_SNAPSHOTS only.

MULTI_ACTIVE       Same (display_name, school_canonical), both real schools, >1 active PID.
                   Action plan: REQUIRES_MANUAL_REVIEW.
                   Suggested canonical = lowest prospect_id.

CLEAN              No issues detected. No action required.
"""

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path("data/edge/draftos.sqlite")
SEASON_ID = 1


# ---------------------------------------------------------------------------
# Core classification logic (shared with apply script)
# ---------------------------------------------------------------------------

def _load_dedup_ghost(cur, season_id: int) -> list[dict]:
    """Prospects with __dedup_* or __ghost_* school_canonical."""
    cur.execute(
        """
        SELECT
            p.prospect_id,
            p.display_name,
            p.school_canonical,
            p.position_group,
            p.is_active
        FROM prospects p
        WHERE p.season_id = ?
          AND (
                p.school_canonical LIKE '__dedup_%'
             OR p.school_canonical LIKE '__ghost_%'
          )
        ORDER BY p.display_name, p.prospect_id
        """,
        (season_id,),
    )
    rows = cur.fetchall()
    result = []
    for row in rows:
        snap_rows = _snapshot_rows_for(cur, row["prospect_id"])
        result.append(
            {
                "category": "DEDUP_GHOST",
                "prospect_id": row["prospect_id"],
                "display_name": row["display_name"],
                "school_canonical": row["school_canonical"],
                "position_group": row["position_group"],
                "is_active": row["is_active"],
                "snapshot_rows": snap_rows,
                "planned_actions": _plan_dedup_ghost(row["is_active"], snap_rows),
            }
        )
    return result


def _load_inactive_in_snapshot(cur, season_id: int) -> list[dict]:
    """Inactive prospects (real school) still present in snapshot rows."""
    cur.execute(
        """
        SELECT DISTINCT
            p.prospect_id,
            p.display_name,
            p.school_canonical,
            p.position_group,
            p.is_active
        FROM prospects p
        JOIN prospect_board_snapshot_rows r ON r.prospect_id = p.prospect_id
        WHERE p.season_id = ?
          AND p.is_active = 0
          AND p.school_canonical NOT LIKE '__dedup_%'
          AND p.school_canonical NOT LIKE '__ghost_%'
        ORDER BY p.display_name, p.prospect_id
        """,
        (season_id,),
    )
    rows = cur.fetchall()
    result = []
    for row in rows:
        snap_rows = _snapshot_rows_for(cur, row["prospect_id"])
        result.append(
            {
                "category": "INACTIVE_SNAPSHOT",
                "prospect_id": row["prospect_id"],
                "display_name": row["display_name"],
                "school_canonical": row["school_canonical"],
                "position_group": row["position_group"],
                "is_active": row["is_active"],
                "snapshot_rows": snap_rows,
                "planned_actions": [
                    {
                        "action": "delete_snapshot_row",
                        "snapshot_id": sid,
                        "rank_overall": rank,
                        "reason": "inactive_prospect_in_snapshot",
                    }
                    for sid, rank in snap_rows
                ],
            }
        )
    return result


def _load_multi_active_clusters(cur, season_id: int) -> list[dict]:
    """Same (display_name, school_canonical) with >1 active PID, real schools."""
    cur.execute(
        """
        WITH active_real AS (
            SELECT
                prospect_id,
                display_name,
                school_canonical,
                position_group
            FROM prospects
            WHERE season_id = ?
              AND is_active = 1
              AND school_canonical NOT LIKE '__dedup_%'
              AND school_canonical NOT LIKE '__ghost_%'
        ),
        dupe_keys AS (
            SELECT display_name, school_canonical
            FROM active_real
            GROUP BY display_name, school_canonical
            HAVING COUNT(*) > 1
        )
        SELECT a.prospect_id, a.display_name, a.school_canonical, a.position_group
        FROM active_real a
        JOIN dupe_keys d
          ON a.display_name    = d.display_name
         AND a.school_canonical = d.school_canonical
        ORDER BY a.display_name, a.school_canonical, a.prospect_id
        """,
        (season_id,),
    )
    rows = cur.fetchall()

    # Group into clusters keyed by (display_name, school_canonical)
    clusters: dict[tuple, list] = {}
    for row in rows:
        key = (row["display_name"], row["school_canonical"])
        clusters.setdefault(key, []).append(
            {
                "prospect_id": row["prospect_id"],
                "position_group": row["position_group"],
            }
        )

    result = []
    for (name, school), members in clusters.items():
        sorted_members = sorted(members, key=lambda x: x["prospect_id"])
        canonical_pid = sorted_members[0]["prospect_id"]
        result.append(
            {
                "category": "MULTI_ACTIVE",
                "display_name": name,
                "school_canonical": school,
                "members": sorted_members,
                "suggested_canonical_pid": canonical_pid,
                "planned_actions": [
                    {
                        "action": "REQUIRES_MANUAL_REVIEW",
                        "reason": (
                            f"multiple active real-school PIDs for ({name}, {school}); "
                            f"suggested canonical = pid {canonical_pid}"
                        ),
                    }
                ],
            }
        )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snapshot_rows_for(cur, prospect_id: int) -> list[tuple[int, int]]:
    """Return [(snapshot_id, rank_overall)] for a prospect."""
    cur.execute(
        """
        SELECT snapshot_id, rank_overall
        FROM prospect_board_snapshot_rows
        WHERE prospect_id = ?
        ORDER BY snapshot_id
        """,
        (prospect_id,),
    )
    return [(r["snapshot_id"], r["rank_overall"]) for r in cur.fetchall()]


def _plan_dedup_ghost(is_active: int, snap_rows: list) -> list[dict]:
    actions = []
    if is_active == 1:
        actions.append(
            {
                "action": "deactivate_prospect",
                "reason": "dedup_or_ghost_school_canonical",
            }
        )
    for sid, rank in snap_rows:
        actions.append(
            {
                "action": "delete_snapshot_row",
                "snapshot_id": sid,
                "rank_overall": rank,
                "reason": "dedup_or_ghost_in_snapshot",
            }
        )
    return actions


def classify_all(db_path: Path) -> dict:
    """Return full classification dict. Read-only."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    result = {
        "dedup_ghost": _load_dedup_ghost(cur, SEASON_ID),
        "inactive_snapshot": _load_inactive_in_snapshot(cur, SEASON_ID),
        "multi_active": _load_multi_active_clusters(cur, SEASON_ID),
    }

    con.close()
    return result


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------

def _print_section_header(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _print_dedup_ghost(entries: list[dict], name_filter: str | None) -> None:
    _print_section_header("CATEGORY: DEDUP_GHOST (deactivate + remove from snapshots)")
    filtered = (
        [e for e in entries if name_filter.lower() in e["display_name"].lower()]
        if name_filter
        else entries
    )
    print(f"  Total matching records : {len(filtered)}")
    print()
    for e in filtered:
        status = "ACTIVE" if e["is_active"] else "already-inactive"
        print(
            f"  pid={e['prospect_id']:>6} | {e['display_name']:<30} | "
            f"{e['school_canonical']:<28} | {e['position_group']:<6} | {status}"
        )
        for act in e["planned_actions"]:
            if act["action"] == "deactivate_prospect":
                print(f"             -> DEACTIVATE  reason={act['reason']}")
            elif act["action"] == "delete_snapshot_row":
                print(
                    f"             -> DEL_SNAPSHOT  snap={act['snapshot_id']}  "
                    f"rank={act['rank_overall']}  reason={act['reason']}"
                )


def _print_inactive_snapshot(entries: list[dict], name_filter: str | None) -> None:
    _print_section_header("CATEGORY: INACTIVE_SNAPSHOT (remove from snapshots only)")
    filtered = (
        [e for e in entries if name_filter.lower() in e["display_name"].lower()]
        if name_filter
        else entries
    )
    print(f"  Total matching records : {len(filtered)}")
    print()
    for e in filtered:
        print(
            f"  pid={e['prospect_id']:>6} | {e['display_name']:<30} | "
            f"{e['school_canonical']:<28} | {e['position_group']:<6} | inactive"
        )
        for act in e["planned_actions"]:
            print(
                f"             -> DEL_SNAPSHOT  snap={act['snapshot_id']}  "
                f"rank={act['rank_overall']}  reason={act['reason']}"
            )


def _print_multi_active(clusters: list[dict], name_filter: str | None) -> None:
    _print_section_header("CATEGORY: MULTI_ACTIVE (requires manual review)")
    filtered = (
        [c for c in clusters if name_filter.lower() in c["display_name"].lower()]
        if name_filter
        else clusters
    )
    print(f"  Total clusters         : {len(filtered)}")
    print()
    for c in filtered:
        print(
            f"  {c['display_name']:<30} | school={c['school_canonical']:<28} | "
            f"suggested_canonical=pid {c['suggested_canonical_pid']}"
        )
        for m in c["members"]:
            marker = "<-- suggested canonical" if m["prospect_id"] == c["suggested_canonical_pid"] else ""
            print(
                f"       pid={m['prospect_id']:>6}  pos={m['position_group']:<6}  {marker}"
            )


def _print_summary(classification: dict) -> None:
    dg = classification["dedup_ghost"]
    ins = classification["inactive_snapshot"]
    ma = classification["multi_active"]

    dg_active = sum(1 for e in dg if e["is_active"] == 1)
    dg_snap_deletes = sum(
        sum(1 for a in e["planned_actions"] if a["action"] == "delete_snapshot_row")
        for e in dg
    )
    ins_snap_deletes = sum(len(e["planned_actions"]) for e in ins)

    _print_section_header("SUMMARY")
    print(f"  DEDUP_GHOST prospects            : {len(dg):>6}")
    print(f"    -> will deactivate (active now) : {dg_active:>6}")
    print(f"    -> snapshot rows to delete      : {dg_snap_deletes:>6}")
    print()
    print(f"  INACTIVE_SNAPSHOT prospects      : {len(ins):>6}")
    print(f"    -> snapshot rows to delete      : {ins_snap_deletes:>6}")
    print()
    print(f"  MULTI_ACTIVE clusters            : {len(ma):>6}  (manual review required)")
    print()
    print("  Total prospect deactivations     :", dg_active)
    print("  Total snapshot row deletions     :", dg_snap_deletes + ins_snap_deletes)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run ghost classifier for DraftOS 2026 prospects. Read-only."
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Filter output to a specific player name (substring match).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary counts only.",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        raise SystemExit(1)

    print(f"DraftOS Prospect Ghost Classifier — season_id={SEASON_ID} (2026)")
    print(f"DB : {DB_PATH.resolve()}")
    print(f"Mode: DRY RUN (read-only)")

    classification = classify_all(DB_PATH)

    if args.summary:
        _print_summary(classification)
        return

    _print_dedup_ghost(classification["dedup_ghost"], args.name)
    _print_inactive_snapshot(classification["inactive_snapshot"], args.name)
    _print_multi_active(classification["multi_active"], args.name)

    if not args.name:
        _print_summary(classification)


if __name__ == "__main__":
    main()
