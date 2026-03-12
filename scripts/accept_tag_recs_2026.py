"""
accept_tag_recs_2026.py — Tag Recommendation Acceptance Workflow (Session 24)

CLI tool to accept or dismiss tag recommendations and write to prospect_tags +
prospect_tag_history.

Reads from:  prospect_tag_recommendations, prospects, tag_definitions, tag_trigger_rules
Writes to:   prospect_tag_recommendations (status), prospect_tags, prospect_tag_history
Season:      season_id=1 (2026 draft only)
Idempotent:  accepting an already-accepted rec is a no-op with message
             UNIQUE(prospect_id, tag_def_id, user_id) on prospect_tags prevents duplicates

Design notes:
    - prospect_tag_history.ptag_id is NOT NULL with FK to prospect_tags.
      For DISMISS actions (no prospect_tag row created), only rec status is updated.
      The prospect_tag_recommendations row (status='dismissed' + actioned_at) IS the
      audit trail for dismissals. No history row is written on dismiss.
    - prospect_tags has UNIQUE(prospect_id, tag_def_id, user_id). INSERT OR IGNORE
      handles re-accept of an already-tagged prospect gracefully.
    - All write operations (accept, dismiss) backup DB first.

Usage:
    python -m scripts.accept_tag_recs_2026 --action list
    python -m scripts.accept_tag_recs_2026 --action list --position CB
    python -m scripts.accept_tag_recs_2026 --action list --tag "Elite RAS"
    python -m scripts.accept_tag_recs_2026 --action accept --rec_id 1
    python -m scripts.accept_tag_recs_2026 --action dismiss --rec_id 1
    python -m scripts.accept_tag_recs_2026 --action accept-all-tag --tag "Elite RAS"
    python -m scripts.accept_tag_recs_2026 --action dismiss-all-tag --tag "Poor RAS"
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone

from draftos.config import PATHS
from draftos.db.connect import connect

USER_ID = 1  # devin (admin)

VALID_ACTIONS = {"list", "accept", "dismiss", "accept-all-tag", "dismiss-all-tag"}


# ---------------------------------------------------------------------------
# DB backup
# ---------------------------------------------------------------------------

def _backup_db() -> None:
    db_path = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_dir = db_path.parent / ".." / ".." / "exports" / "backups"
    bak_dir = bak_dir.resolve()
    bak_dir.mkdir(parents=True, exist_ok=True)
    dst = bak_dir / f"draftos_{ts}_tag_accept.sqlite"
    shutil.copy2(str(db_path), str(dst))
    print(f"  [backup] DB backed up -> {dst.name}")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_rec(conn, rec_id: int) -> dict | None:
    """Load a single recommendation row with prospect and tag context."""
    row = conn.execute(
        """
        SELECT r.rec_id, r.prospect_id, r.tag_def_id, r.rule_id, r.status,
               r.triggered_value, td.tag_name, tr.rule_name,
               p.display_name, p.position_group
        FROM prospect_tag_recommendations r
        JOIN tag_definitions td  ON td.tag_def_id = r.tag_def_id
        JOIN tag_trigger_rules tr ON tr.rule_id   = r.rule_id
        JOIN prospects p          ON p.prospect_id = r.prospect_id
        WHERE r.rec_id = ?
        """,
        (rec_id,),
    ).fetchone()
    return dict(row) if row else None


def _load_pending_recs(conn, tag_filter: str | None = None,
                       position_filter: str | None = None) -> list[dict]:
    """
    Load all pending recommendations sorted by tag priority ASC, position, name.
    Optionally filtered by tag_name and/or position_group.
    """
    sql = """
        SELECT r.rec_id, r.prospect_id, r.tag_def_id, r.rule_id, r.status,
               r.triggered_value, td.tag_name, tr.rule_name, td.display_order,
               p.display_name, p.position_group
        FROM prospect_tag_recommendations r
        JOIN tag_definitions td   ON td.tag_def_id  = r.tag_def_id
        JOIN tag_trigger_rules tr ON tr.rule_id      = r.rule_id
        JOIN prospects p           ON p.prospect_id  = r.prospect_id
        WHERE r.status = 'pending'
    """
    args: list = []
    if tag_filter:
        sql += " AND td.tag_name = ?"
        args.append(tag_filter)
    if position_filter:
        sql += " AND p.position_group = ?"
        args.append(position_filter)
    sql += " ORDER BY td.display_order ASC, p.position_group, p.display_name"

    rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list(conn, tag_filter: str | None, position_filter: str | None) -> None:
    """Print all pending recommendations as a formatted table."""
    recs = _load_pending_recs(conn, tag_filter, position_filter)

    filters = []
    if tag_filter:
        filters.append(f"tag='{tag_filter}'")
    if position_filter:
        filters.append(f"position='{position_filter}'")
    filter_msg = f" ({', '.join(filters)})" if filters else ""

    if not recs:
        print(f"  No pending recommendations{filter_msg}.")
        return

    print(f"\n  {len(recs)} pending recommendations{filter_msg}:\n")
    print(f"  {'rec_id':<8}  {'name':<28}  {'pos':<6}  {'tag':<22}  {'triggered_value':<35}  rule_name")
    print(f"  {'-'*8}  {'-'*28}  {'-'*6}  {'-'*22}  {'-'*35}  {'-'*20}")

    for rec in recs:
        tv   = (rec["triggered_value"] or "")[:35]
        pos  = (rec["position_group"] or "?")[:6]
        name = (rec["display_name"] or "")[:28]
        tag  = (rec["tag_name"] or "")[:22]
        rn   = (rec["rule_name"] or "")[:20]
        print(f"  {rec['rec_id']:<8}  {name:<28}  {pos:<6}  {tag:<22}  {tv:<35}  {rn}")
    print()


# ---------------------------------------------------------------------------
# accept single
# ---------------------------------------------------------------------------

def cmd_accept(conn, rec_id: int) -> None:
    """Accept a single recommendation: update status, write prospect_tag + history."""
    rec = _load_rec(conn, rec_id)
    if not rec:
        print(f"  [ERROR] rec_id={rec_id} not found.")
        sys.exit(1)

    pname    = rec["display_name"]
    tag_name = rec["tag_name"]
    status   = rec["status"]

    if status == "accepted":
        print(f"  [SKIP] rec_id={rec_id} ({pname} — {tag_name}) already accepted. No-op.")
        return
    if status == "dismissed":
        print(f"  [WARN] rec_id={rec_id} was previously dismissed. Re-accepting.")

    _backup_db()
    now = datetime.now(timezone.utc).isoformat()
    tv  = rec["triggered_value"]

    # 1. Update rec status
    conn.execute(
        """
        UPDATE prospect_tag_recommendations
        SET status='accepted', actioned_by=?, actioned_at=?
        WHERE rec_id=?
        """,
        (USER_ID, now, rec_id),
    )

    # 2. Insert prospect_tag (INSERT OR IGNORE — UNIQUE prevents duplicates)
    conn.execute(
        """
        INSERT OR IGNORE INTO prospect_tags
          (prospect_id, tag_def_id, user_id, source, note, rec_id, is_active, created_at)
        VALUES (?, ?, ?, 'system', ?, ?, 1, ?)
        """,
        (rec["prospect_id"], rec["tag_def_id"], USER_ID, tv, rec_id, now),
    )

    # 3. Write history entry (need ptag_id, which the IGNORE may have skipped inserting)
    ptag_row = conn.execute(
        "SELECT ptag_id FROM prospect_tags WHERE prospect_id=? AND tag_def_id=? AND user_id=?",
        (rec["prospect_id"], rec["tag_def_id"], USER_ID),
    ).fetchone()

    if ptag_row:
        conn.execute(
            """
            INSERT INTO prospect_tag_history
              (ptag_id, prospect_id, tag_def_id, user_id, action, new_note, timestamp)
            VALUES (?, ?, ?, ?, 'attached', ?, ?)
            """,
            (ptag_row["ptag_id"], rec["prospect_id"], rec["tag_def_id"], USER_ID, tv, now),
        )

    conn.commit()
    print(f"  [OK] Accepted rec_id={rec_id}: {pname} — {tag_name}  ({tv or 'no value'})")


# ---------------------------------------------------------------------------
# dismiss single
# ---------------------------------------------------------------------------

def cmd_dismiss(conn, rec_id: int) -> None:
    """Dismiss a single recommendation (soft delete — status='dismissed')."""
    rec = _load_rec(conn, rec_id)
    if not rec:
        print(f"  [ERROR] rec_id={rec_id} not found.")
        sys.exit(1)

    pname    = rec["display_name"]
    tag_name = rec["tag_name"]
    status   = rec["status"]

    if status == "dismissed":
        print(f"  [SKIP] rec_id={rec_id} ({pname} — {tag_name}) already dismissed. No-op.")
        return
    if status == "accepted":
        print(f"  [WARN] rec_id={rec_id} was previously accepted. Dismissal updates the rec "
              f"only — the prospect_tag row is NOT removed.")

    _backup_db()
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        UPDATE prospect_tag_recommendations
        SET status='dismissed', actioned_by=?, actioned_at=?
        WHERE rec_id=?
        """,
        (USER_ID, now, rec_id),
    )
    conn.commit()
    print(f"  [OK] Dismissed rec_id={rec_id}: {pname} — {tag_name}")


# ---------------------------------------------------------------------------
# accept-all-tag
# ---------------------------------------------------------------------------

def cmd_accept_all_tag(conn, tag_name: str) -> None:
    """Batch accept all pending recommendations for a specific tag."""
    recs = _load_pending_recs(conn, tag_filter=tag_name)

    if not recs:
        print(f"  No pending recommendations for tag '{tag_name}'.")
        return

    print(f"\n  Batch accept — tag: '{tag_name}'  ({len(recs)} pending recs)")
    for rec in recs:
        tv = rec["triggered_value"] or "(no value)"
        print(f"    rec_id={rec['rec_id']:<5}  {rec['display_name']:<30}  ({rec['position_group']})  {tv}")

    _backup_db()
    now      = datetime.now(timezone.utc).isoformat()
    accepted = 0
    skipped  = 0

    for rec in recs:
        conn.execute(
            """
            UPDATE prospect_tag_recommendations
            SET status='accepted', actioned_by=?, actioned_at=?
            WHERE rec_id=?
            """,
            (USER_ID, now, rec["rec_id"]),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO prospect_tags
              (prospect_id, tag_def_id, user_id, source, note, rec_id, is_active, created_at)
            VALUES (?, ?, ?, 'system', NULL, ?, 1, ?)
            """,
            (rec["prospect_id"], rec["tag_def_id"], USER_ID, rec["rec_id"], now),
        )

        ptag_row = conn.execute(
            "SELECT ptag_id FROM prospect_tags WHERE prospect_id=? AND tag_def_id=? AND user_id=?",
            (rec["prospect_id"], rec["tag_def_id"], USER_ID),
        ).fetchone()

        if ptag_row:
            try:
                conn.execute(
                    """
                    INSERT INTO prospect_tag_history
                      (ptag_id, prospect_id, tag_def_id, user_id, action, new_note, timestamp)
                    VALUES (?, ?, ?, ?, 'attached', NULL, ?)
                    """,
                    (ptag_row["ptag_id"], rec["prospect_id"], rec["tag_def_id"], USER_ID, now),
                )
                accepted += 1
            except Exception as e:
                print(f"    [WARN] History insert failed for rec_id={rec['rec_id']}: {e}")
                accepted += 1  # rec + tag row still written — non-fatal
        else:
            skipped += 1

    conn.commit()
    print(f"\n  [OK] Accepted {accepted} recommendations for '{tag_name}' "
          f"({skipped} skipped — tag already present).")


# ---------------------------------------------------------------------------
# dismiss-all-tag
# ---------------------------------------------------------------------------

def cmd_dismiss_all_tag(conn, tag_name: str) -> None:
    """Batch dismiss all pending recommendations for a specific tag."""
    recs = _load_pending_recs(conn, tag_filter=tag_name)

    if not recs:
        print(f"  No pending recommendations for tag '{tag_name}'.")
        return

    print(f"\n  Batch dismiss — tag: '{tag_name}'  ({len(recs)} pending recs)")
    for rec in recs:
        tv = rec["triggered_value"] or "(no value)"
        print(f"    rec_id={rec['rec_id']:<5}  {rec['display_name']:<30}  ({rec['position_group']})  {tv}")

    _backup_db()
    now       = datetime.now(timezone.utc).isoformat()
    dismissed = 0

    for rec in recs:
        conn.execute(
            """
            UPDATE prospect_tag_recommendations
            SET status='dismissed', actioned_by=?, actioned_at=?
            WHERE rec_id=?
            """,
            (USER_ID, now, rec["rec_id"]),
        )
        dismissed += 1

    conn.commit()
    print(f"\n  [OK] Dismissed {dismissed} recommendations for '{tag_name}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DraftOS Tag Acceptance Workflow — 2026"
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["list", "accept", "dismiss", "accept-all-tag", "dismiss-all-tag"],
        help="Action to perform",
    )
    parser.add_argument(
        "--rec_id",
        type=int,
        default=None,
        help="Recommendation ID (required for accept / dismiss)",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Tag name filter (required for accept-all-tag / dismiss-all-tag; optional for list)",
    )
    parser.add_argument(
        "--position",
        type=str,
        default=None,
        help="Position group filter (optional, for list only)",
    )
    args = parser.parse_args()

    # Validation
    if args.action in ("accept", "dismiss") and args.rec_id is None:
        parser.error(f"--rec_id is required for --action {args.action}")
    if args.action in ("accept-all-tag", "dismiss-all-tag") and not args.tag:
        parser.error(f"--tag is required for --action {args.action}")

    print("=" * 60)
    print("DraftOS Tag Acceptance Workflow  |  Season 2026")
    print(f"Action: {args.action}")
    print("=" * 60)

    with connect() as conn:
        if args.action == "list":
            cmd_list(conn, args.tag, args.position)

        elif args.action == "accept":
            cmd_accept(conn, args.rec_id)

        elif args.action == "dismiss":
            cmd_dismiss(conn, args.rec_id)

        elif args.action == "accept-all-tag":
            cmd_accept_all_tag(conn, args.tag)

        elif args.action == "dismiss-all-tag":
            cmd_dismiss_all_tag(conn, args.tag)


if __name__ == "__main__":
    main()
