"""
accept_tag_recommendations_2026.py — Tag Recommendation Acceptance Workflow (Session 19)

CLI tool to accept or dismiss tag recommendations and write to prospect_tags +
prospect_tag_history.

Reads from:  prospect_tag_recommendations, prospects, tag_definitions
Writes to:   prospect_tag_recommendations (status), prospect_tags, prospect_tag_history
Season:      season_id=1 (2026 draft only)
Idempotent:  accepting an already-accepted rec is a no-op with warning

Design notes:
  - prospect_tag_history.ptag_id is NOT NULL with FK to prospect_tags(ptag_id).
    For DISMISS actions (no prospect_tag row created), only the rec status is updated.
    The prospect_tag_recommendations row (status='dismissed' + actioned_by + actioned_at)
    IS the audit trail for dismissals. No history row is written on dismiss.
  - prospect_tags has UNIQUE(prospect_id, tag_def_id, user_id). INSERT OR IGNORE
    handles re-accept of the same tag gracefully (no duplicate tag rows).
  - All --apply 1 runs backup the DB first.

Usage:
    python -m scripts.accept_tag_recommendations_2026 --list
    python -m scripts.accept_tag_recommendations_2026 --list --tag "Divergence Alert"
    python -m scripts.accept_tag_recommendations_2026 --accept 12 [--note "reason"] --apply 0|1
    python -m scripts.accept_tag_recommendations_2026 --dismiss 12 [--note "reason"] --apply 0|1
    python -m scripts.accept_tag_recommendations_2026 --accept-all --tag "Elite RAS" --apply 0|1
    python -m scripts.accept_tag_recommendations_2026 --dismiss-all --tag "Development Bet" --apply 0|1
"""
from __future__ import annotations

import argparse
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect

SEASON_ID = 1
USER_ID   = 1   # devin (admin)

# ---------------------------------------------------------------------------
# DB backup helper
# ---------------------------------------------------------------------------

def _backup_db() -> None:
    """Back up the database before any write operation."""
    db_path  = PATHS.db
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_path = db_path.parent / f"{db_path.stem}.backup.tags_{ts}{db_path.suffix}"
    shutil.copy2(str(db_path), str(bak_path))
    print(f"  [backup] DB backed up -> {bak_path.name}")


# ---------------------------------------------------------------------------
# Shared data loaders
# ---------------------------------------------------------------------------

def _load_rec(conn, rec_id: int) -> dict | None:
    """Load a single recommendation row."""
    row = conn.execute(
        """
        SELECT r.rec_id, r.prospect_id, r.tag_def_id, r.rule_id, r.status,
               r.triggered_value, td.tag_name, p.display_name, p.position_group
        FROM prospect_tag_recommendations r
        JOIN tag_definitions td ON td.tag_def_id = r.tag_def_id
        JOIN prospects p ON p.prospect_id = r.prospect_id
        WHERE r.rec_id = ?
        """,
        (rec_id,),
    ).fetchone()
    return dict(row) if row else None


def _load_pending_recs(conn, tag_name: str | None = None) -> list[dict]:
    """Load all pending recommendations, optionally filtered by tag_name."""
    base = """
        SELECT r.rec_id, r.prospect_id, r.tag_def_id, r.rule_id, r.status,
               r.triggered_value, td.tag_name, p.display_name, p.position_group
        FROM prospect_tag_recommendations r
        JOIN tag_definitions td ON td.tag_def_id = r.tag_def_id
        JOIN prospects p ON p.prospect_id = r.prospect_id
        WHERE r.status = 'pending'
    """
    if tag_name:
        rows = conn.execute(base + " AND td.tag_name = ? ORDER BY p.display_name", (tag_name,)).fetchall()
    else:
        rows = conn.execute(base + " ORDER BY p.display_name, td.tag_name").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# --list command
# ---------------------------------------------------------------------------

def cmd_list(conn, tag_filter: str | None) -> None:
    """Print all pending recommendations grouped by prospect."""
    recs = _load_pending_recs(conn, tag_filter)

    if not recs:
        tag_msg = f" for tag '{tag_filter}'" if tag_filter else ""
        print(f"  No pending recommendations{tag_msg}.")
        return

    # Group by prospect
    by_prospect: dict[int, list[dict]] = defaultdict(list)
    for rec in recs:
        by_prospect[rec["prospect_id"]].append(rec)

    tag_msg = f" (tag filter: '{tag_filter}')" if tag_filter else ""
    print(f"\n  {len(recs)} pending recommendations across {len(by_prospect)} prospects{tag_msg}:\n")

    for pid, entries in sorted(by_prospect.items(), key=lambda x: x[1][0]["display_name"]):
        pname = entries[0]["display_name"]
        ppos  = entries[0]["position_group"] or "?"
        print(f"  [pid={pid}] {pname} ({ppos}) — {len(entries)} pending:")
        for rec in entries:
            tv = rec["triggered_value"] or "(no value)"
            print(f"    rec_id={rec['rec_id']:<5}  {rec['tag_name']:<22}  triggered: {tv}")
        print()


# ---------------------------------------------------------------------------
# --accept single rec
# ---------------------------------------------------------------------------

def cmd_accept(conn, rec_id: int, note: str | None, apply: bool) -> None:
    """Accept a single recommendation."""
    rec = _load_rec(conn, rec_id)
    if not rec:
        print(f"  [ERROR] rec_id={rec_id} not found.")
        sys.exit(1)

    pname    = rec["display_name"]
    tag_name = rec["tag_name"]
    status   = rec["status"]

    print(f"\n  Accepting rec_id={rec_id}: {pname} — {tag_name}")
    print(f"  Current status: {status}")
    if note:
        print(f"  Note: {note}")

    if status == "accepted":
        print(f"  [SKIP] Already accepted. No-op.")
        return
    if status == "dismissed":
        print(f"  [WARN] rec_id={rec_id} was previously dismissed. Re-accepting.")

    if not apply:
        print(f"  [DRY RUN] Would:")
        print(f"    1. UPDATE prospect_tag_recommendations SET status='accepted' WHERE rec_id={rec_id}")
        print(f"    2. INSERT OR IGNORE INTO prospect_tags (pid={rec['prospect_id']}, tag={tag_name})")
        print(f"    3. INSERT INTO prospect_tag_history (action='attached')")
        return

    _backup_db()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Update rec status
    conn.execute(
        """
        UPDATE prospect_tag_recommendations
        SET status='accepted', actioned_by=?, actioned_at=?
        WHERE rec_id=?
        """,
        (USER_ID, now, rec_id),
    )

    # 2. Insert into prospect_tags (INSERT OR IGNORE for idempotency on UNIQUE constraint)
    conn.execute(
        """
        INSERT OR IGNORE INTO prospect_tags
          (prospect_id, tag_def_id, user_id, source, note, rec_id, is_active, created_at)
        VALUES (?, ?, ?, 'system', ?, ?, 1, ?)
        """,
        (rec["prospect_id"], rec["tag_def_id"], USER_ID, note, rec_id, now),
    )

    # 3. Write history entry (only if a new prospect_tag row was actually created)
    ptag_id = conn.execute(
        "SELECT ptag_id FROM prospect_tags WHERE prospect_id=? AND tag_def_id=? AND user_id=?",
        (rec["prospect_id"], rec["tag_def_id"], USER_ID),
    ).fetchone()

    if ptag_id:
        conn.execute(
            """
            INSERT INTO prospect_tag_history
              (ptag_id, prospect_id, tag_def_id, user_id, action, new_note, timestamp)
            VALUES (?, ?, ?, ?, 'attached', ?, ?)
            """,
            (ptag_id["ptag_id"], rec["prospect_id"], rec["tag_def_id"], USER_ID, note, now),
        )

    conn.commit()
    print(f"  [OK] Accepted: {pname} — {tag_name} (rec_id={rec_id})")


# ---------------------------------------------------------------------------
# --dismiss single rec
# ---------------------------------------------------------------------------

def cmd_dismiss(conn, rec_id: int, note: str | None, apply: bool) -> None:
    """Dismiss a single recommendation (soft delete — status='dismissed')."""
    rec = _load_rec(conn, rec_id)
    if not rec:
        print(f"  [ERROR] rec_id={rec_id} not found.")
        sys.exit(1)

    pname    = rec["display_name"]
    tag_name = rec["tag_name"]
    status   = rec["status"]

    print(f"\n  Dismissing rec_id={rec_id}: {pname} — {tag_name}")
    print(f"  Current status: {status}")
    if note:
        print(f"  Note: {note}")

    if status == "dismissed":
        print(f"  [SKIP] Already dismissed. No-op.")
        return
    if status == "accepted":
        print(f"  [WARN] rec_id={rec_id} was previously accepted. Dismissal only clears the rec "
              f"— the prospect_tag row is NOT removed. Use --deactivate to remove the tag.")

    if not apply:
        print(f"  [DRY RUN] Would:")
        print(f"    1. UPDATE prospect_tag_recommendations SET status='dismissed' WHERE rec_id={rec_id}")
        print(f"    (No prospect_tag_history row — no ptag_id to reference for dismiss action)")
        return

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
    print(f"  [OK] Dismissed: {pname} — {tag_name} (rec_id={rec_id})")


# ---------------------------------------------------------------------------
# --accept-all --tag TAG_NAME
# ---------------------------------------------------------------------------

def cmd_accept_all(conn, tag_name: str, apply: bool) -> None:
    """Batch accept all pending recommendations for a specific tag."""
    recs = _load_pending_recs(conn, tag_name)

    if not recs:
        print(f"  No pending recommendations for tag '{tag_name}'.")
        return

    print(f"\n  Batch accept — tag: '{tag_name}'  ({len(recs)} pending recs)")
    for rec in recs:
        tv = rec["triggered_value"] or "(no value)"
        print(f"    rec_id={rec['rec_id']:<5}  {rec['display_name']:<30}  {tv}")

    if not apply:
        print(f"\n  [DRY RUN] Would accept {len(recs)} recommendations.")
        print(f"  Run with --apply 1 to write.")
        return

    _backup_db()
    now      = datetime.now(timezone.utc).isoformat()
    accepted = 0
    skipped  = 0

    for rec in recs:
        # Update rec status
        conn.execute(
            """
            UPDATE prospect_tag_recommendations
            SET status='accepted', actioned_by=?, actioned_at=?
            WHERE rec_id=?
            """,
            (USER_ID, now, rec["rec_id"]),
        )

        # Insert prospect_tag
        conn.execute(
            """
            INSERT OR IGNORE INTO prospect_tags
              (prospect_id, tag_def_id, user_id, source, note, rec_id, is_active, created_at)
            VALUES (?, ?, ?, 'system', NULL, ?, 1, ?)
            """,
            (rec["prospect_id"], rec["tag_def_id"], USER_ID, rec["rec_id"], now),
        )

        # Write history
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
                accepted += 1  # rec + tag still written
        else:
            skipped += 1

    conn.commit()
    print(f"\n  [OK] Accepted {accepted} recommendations ({skipped} skipped — tag already present).")

    # Summary of what was written
    print(f"\n  Accepted tags for '{tag_name}':")
    written = conn.execute(
        """
        SELECT p.display_name, r.triggered_value
        FROM prospect_tag_recommendations r
        JOIN prospects p ON p.prospect_id = r.prospect_id
        JOIN tag_definitions td ON td.tag_def_id = r.tag_def_id
        WHERE td.tag_name = ? AND r.status = 'accepted'
        ORDER BY p.display_name
        """,
        (tag_name,),
    ).fetchall()
    for row in written:
        print(f"    {row['display_name']:<30}  {row['triggered_value'] or ''}")


# ---------------------------------------------------------------------------
# --dismiss-all --tag TAG_NAME
# ---------------------------------------------------------------------------

def cmd_dismiss_all(conn, tag_name: str, apply: bool) -> None:
    """Batch dismiss all pending recommendations for a specific tag."""
    recs = _load_pending_recs(conn, tag_name)

    if not recs:
        print(f"  No pending recommendations for tag '{tag_name}'.")
        return

    print(f"\n  Batch dismiss — tag: '{tag_name}'  ({len(recs)} pending recs)")
    for rec in recs:
        tv = rec["triggered_value"] or "(no value)"
        print(f"    rec_id={rec['rec_id']:<5}  {rec['display_name']:<30}  {tv}")

    if not apply:
        print(f"\n  [DRY RUN] Would dismiss {len(recs)} recommendations.")
        print(f"  Run with --apply 1 to write.")
        return

    _backup_db()
    now      = datetime.now(timezone.utc).isoformat()
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
    print(f"\n  [OK] Dismissed {dismissed} recommendations for tag '{tag_name}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DraftOS Tag Acceptance Workflow — 2026"
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list",        action="store_true", help="List pending recommendations")
    mode.add_argument("--accept",      type=int, metavar="REC_ID", help="Accept a recommendation by rec_id")
    mode.add_argument("--dismiss",     type=int, metavar="REC_ID", help="Dismiss a recommendation by rec_id")
    mode.add_argument("--accept-all",  action="store_true", help="Batch accept all pending for --tag")
    mode.add_argument("--dismiss-all", action="store_true", help="Batch dismiss all pending for --tag")

    parser.add_argument("--tag",   type=str, default=None, help="Tag name filter (for --list, --accept-all, --dismiss-all)")
    parser.add_argument("--note",  type=str, default=None, help="Analyst note / rationale (for --accept, --dismiss)")
    parser.add_argument("--apply", type=int, choices=[0, 1], default=None,
                        help="0=dry run, 1=write (required for accept/dismiss commands)")

    args = parser.parse_args()

    # --list doesn't need --apply
    if not args.list and args.apply is None:
        parser.error("--apply 0|1 is required for accept/dismiss commands")

    # batch commands require --tag
    if (args.accept_all or args.dismiss_all) and not args.tag:
        parser.error("--accept-all and --dismiss-all require --tag")

    apply = bool(args.apply) if args.apply is not None else False

    print("=" * 60)
    print("DraftOS Tag Acceptance Workflow  |  Season 2026")
    if not args.list:
        print(f"Apply:  {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    print("=" * 60)

    with connect() as conn:
        if args.list:
            cmd_list(conn, args.tag)

        elif args.accept is not None:
            cmd_accept(conn, args.accept, args.note, apply)

        elif args.dismiss is not None:
            cmd_dismiss(conn, args.dismiss, args.note, apply)

        elif args.accept_all:
            cmd_accept_all(conn, args.tag, apply)

        elif args.dismiss_all:
            cmd_dismiss_all(conn, args.tag, apply)


if __name__ == "__main__":
    main()
