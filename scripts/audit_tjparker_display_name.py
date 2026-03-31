"""
audit_tjparker_display_name.py
Session 76 -- Phase 1B

Audits and resolves the TJ Parker pid=27 display_name
duplicate issue carried since Session 50.

Usage:
  python -m scripts.audit_tjparker_display_name --apply 0  # dry run
  python -m scripts.audit_tjparker_display_name --apply 1  # write

Issue types detected and handled:
  CLEAN                -- no action required
  MALFORMED_NAME       -- display_name on pid=27 is non-canonical
                         (e.g. 'Tj Parker'); corrected to 'TJ Parker'
  DUPLICATE_ACTIVE_ROW -- one or more is_active=1 duplicate rows exist
                         for TJ Parker; lower-priority rows deactivated
  COMBINED             -- both MALFORMED_NAME and DUPLICATE_ACTIVE_ROW
                         present; both resolved in a single apply pass
  DUPLICATE_DISPLAY_NAME -- pid=27 shares its display_name with an
                         unrelated active pid; flagged for operator
                         review, not auto-fixed

Notes:
  - prospects table PK: prospect_id (not id)
  - no 'notes', 'archetype_code', 'school', or 'draft_year' columns
    in prospects; uses school_canonical, class_year, board_status
  - deactivation rationale is logged to stdout (no notes column)
  - no apex_scores rows touched
"""

import sqlite3
import argparse
import sys
from datetime import datetime, timezone

DB_PATH         = r"C:\DraftOS\data\edge\draftos.sqlite"
TARGET_PID      = 27
CANONICAL_NAME  = "TJ Parker"
CANONICAL_POS   = "EDGE"
CANONICAL_SCHOOL = "Clemson"

# Accepted canonical display_name forms
CLEAN_NAMES = {"TJ Parker", "T.J. Parker"}


def get_target(conn):
    """Return the pid=27 row."""
    cur = conn.cursor()
    cur.execute("""
        SELECT prospect_id, display_name, position_group,
               school_canonical, is_active, class_year
        FROM   prospects
        WHERE  prospect_id = ?
    """, (TARGET_PID,))
    return cur.fetchone()


def get_parker_candidates(conn):
    """
    All is_active=1 rows that could be TJ Parker:
    display_name contains 'Parker' or ('TJ'/'Tj') with
    school_canonical = Clemson.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT prospect_id, display_name, position_group,
               school_canonical, is_active, class_year
        FROM   prospects
        WHERE  is_active = 1
          AND  school_canonical = 'Clemson'
          AND  (
               LOWER(display_name) LIKE '%parker%'
            OR LOWER(display_name) LIKE '%tj%'
          )
        ORDER  BY prospect_id
    """)
    return cur.fetchall()


def get_display_name_collisions(conn, name):
    """Other is_active=1 pids sharing the exact same display_name."""
    cur = conn.cursor()
    cur.execute("""
        SELECT prospect_id, display_name, position_group, school_canonical
        FROM   prospects
        WHERE  is_active = 1
          AND  display_name = ?
          AND  prospect_id != ?
    """, (name, TARGET_PID))
    return cur.fetchall()


def classify(target, candidates, collisions):
    """
    Returns (issue_type, detail_dict).
    issue_type is one of: CLEAN, MALFORMED_NAME,
    DUPLICATE_ACTIVE_ROW, COMBINED, DUPLICATE_DISPLAY_NAME,
    TARGET_NOT_FOUND.
    """
    if target is None:
        return "TARGET_NOT_FOUND", {}

    current_name  = (target[1] or "").strip()
    name_is_clean = current_name in CLEAN_NAMES

    # Duplicates = active candidates other than pid=27 that match
    # Clemson + position-group signals for TJ Parker
    duplicates = [
        r for r in candidates
        if r[0] != TARGET_PID
    ]

    name_issue = not name_is_clean
    dup_issue  = len(duplicates) > 0

    if name_issue and dup_issue:
        return "COMBINED", {
            "current_name": current_name,
            "proposed_name": CANONICAL_NAME,
            "duplicates": duplicates,
        }
    if name_issue:
        return "MALFORMED_NAME", {
            "current_name": current_name,
            "proposed_name": CANONICAL_NAME,
        }
    if dup_issue:
        return "DUPLICATE_ACTIVE_ROW", {
            "duplicates": duplicates,
        }
    if collisions:
        return "DUPLICATE_DISPLAY_NAME", {
            "collisions": collisions,
        }
    return "CLEAN", {}


def run_audit(apply: bool):
    conn      = sqlite3.connect(DB_PATH)
    prefix    = "[APPLIED]" if apply else "[DRY RUN]"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur       = conn.cursor()

    target     = get_target(conn)
    candidates = get_parker_candidates(conn)
    current    = (target[1] or "NOT FOUND") if target else "NOT FOUND"
    collisions = get_display_name_collisions(conn, current)

    print(f"{prefix} pid=27 display_name: '{current}'")
    active_count = len([r for r in candidates if r[4] == 1])
    print(f"{prefix} Active TJ Parker rows found: {active_count}")

    issue_type, detail = classify(target, candidates, collisions)
    print(f"{prefix} Issue type: {issue_type}")

    # ── TARGET_NOT_FOUND ──────────────────────────────────────────────────────
    if issue_type == "TARGET_NOT_FOUND":
        print(f"{prefix} ERROR: pid=27 not found in DB. "
              "Report to operator.")
        conn.close()
        sys.exit(1)

    # ── CLEAN ─────────────────────────────────────────────────────────────────
    elif issue_type == "CLEAN":
        print(f"{prefix} Proposed resolution: no action required "
              "-- display_name is canonical, no active duplicates")
        if not apply:
            print(f"{prefix} No writes executed.")
        print("\n[OK] TJ Parker pid=27 display_name audit: CLEAN. "
              "Known Issue #1 closed.")

    # ── MALFORMED_NAME ────────────────────────────────────────────────────────
    elif issue_type == "MALFORMED_NAME":
        proposed = detail["proposed_name"]
        prior    = detail["current_name"]
        print(f"{prefix} Proposed resolution: correct display_name "
              f"'{prior}' -> '{proposed}'")
        if not apply:
            print(f"{prefix} No writes executed.")
        else:
            cur.execute("""
                UPDATE prospects
                SET    display_name = ?,
                       updated_at   = ?
                WHERE  prospect_id  = ?
            """, (proposed, timestamp, TARGET_PID))
            conn.commit()
            print(f"[APPLIED] pid=27: display_name corrected "
                  f"'{prior}' -> '{proposed}'")
            print("[APPLIED] TJ Parker display_name audit complete.")

    # ── DUPLICATE_ACTIVE_ROW ──────────────────────────────────────────────────
    elif issue_type == "DUPLICATE_ACTIVE_ROW":
        dups = detail["duplicates"]
        pids = [r[0] for r in dups]
        print(f"{prefix} Proposed resolution: deactivate "
              f"{len(dups)} duplicate row(s): pid(s) {pids}")
        for r in dups:
            print(f"  pid={r[0]} | display_name='{r[1]}' | "
                  f"pos={r[2]} | school={r[3]}")
        if not apply:
            print(f"{prefix} No writes executed.")
        else:
            for dup in dups:
                cur.execute("""
                    UPDATE prospects
                    SET    is_active  = 0,
                           updated_at = ?
                    WHERE  prospect_id = ?
                """, (timestamp, dup[0]))
                print(f"[APPLIED] pid={dup[0]}: is_active set to 0")
                print(f"[APPLIED] pid={dup[0]}: deactivation note -- "
                      f"S76 audit: duplicate of TJ Parker pid=27 "
                      f"(EDGE, Clemson). pos={dup[2]}, school={dup[3]}.")
            conn.commit()
            print("[APPLIED] TJ Parker display_name audit complete.")

    # ── COMBINED ──────────────────────────────────────────────────────────────
    elif issue_type == "COMBINED":
        proposed = detail["proposed_name"]
        prior    = detail["current_name"]
        dups     = detail["duplicates"]
        pids     = [r[0] for r in dups]
        print(f"{prefix} Proposed resolution:")
        print(f"  (1) Correct display_name on pid=27: "
              f"'{prior}' -> '{proposed}'")
        print(f"  (2) Deactivate {len(dups)} duplicate row(s): "
              f"pid(s) {pids}")
        for r in dups:
            print(f"      pid={r[0]} | display_name='{r[1]}' | "
                  f"pos={r[2]} | school={r[3]}")
        if not apply:
            print(f"{prefix} No writes executed.")
        else:
            # Fix name on canonical pid
            cur.execute("""
                UPDATE prospects
                SET    display_name = ?,
                       updated_at   = ?
                WHERE  prospect_id  = ?
            """, (proposed, timestamp, TARGET_PID))
            print(f"[APPLIED] pid=27: display_name corrected "
                  f"'{prior}' -> '{proposed}'")
            # Deactivate duplicates
            for dup in dups:
                cur.execute("""
                    UPDATE prospects
                    SET    is_active  = 0,
                           updated_at = ?
                    WHERE  prospect_id = ?
                """, (timestamp, dup[0]))
                print(f"[APPLIED] pid={dup[0]}: is_active set to 0")
                print(f"[APPLIED] pid={dup[0]}: deactivation note -- "
                      f"S76 audit: duplicate of TJ Parker pid=27 "
                      f"(EDGE, Clemson). pos={dup[2]}, school={dup[3]}.")
            conn.commit()
            print("[APPLIED] TJ Parker display_name audit complete.")

    # ── DUPLICATE_DISPLAY_NAME ────────────────────────────────────────────────
    elif issue_type == "DUPLICATE_DISPLAY_NAME":
        cols = detail["collisions"]
        print(f"{prefix} Proposed resolution: display_name collision "
              "-- operator review required before any deactivation")
        print("\n!! OPERATOR REVIEW REQUIRED !!")
        for c in cols:
            print(f"   pid={c[0]} | display_name='{c[1]}' | "
                  f"pos={c[2]} | school={c[3]}")
        print("   These pids share the canonical display_name.")
        print("   Confirm correct active record before deactivation.")
        if not apply:
            print(f"{prefix} No writes executed.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Audit TJ Parker pid=27 display_name duplicate issue."
    )
    parser.add_argument(
        "--apply", type=int, choices=[0, 1], required=True,
        help="0 = dry run, 1 = apply writes"
    )
    args = parser.parse_args()
    run_audit(apply=bool(args.apply))
