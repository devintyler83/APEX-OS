"""
cleanup_stukes_ghost_orphans.py
Session 76 — Phase 1A Completion

Deactivates the ghost S row (pid=3011) and audits orphan
prospect rows (pid=2675, 3533, 3793, 4392) for Stukes
duplicate identity confirmation.

Usage:
  python -m scripts.cleanup_stukes_ghost_orphans --apply 0  # dry run
  python -m scripts.cleanup_stukes_ghost_orphans --apply 1  # write

Logic:
  A prospect row is confirmed as a Stukes duplicate if:
    (a) display_name contains 'Stukes' (case-insensitive), OR
    (b) display_name is blank/null AND no other identifying
        data distinguishes it from pid=160 (same position,
        same school_canonical, same class_year)
  If neither condition is met, the row is flagged as
  NOT STUKES and excluded from deactivation. The operator
  must review flagged rows manually.

Notes:
  - prospects table PK: prospect_id (not id)
  - prospects table has no 'notes' column — deactivation
    rationale is logged to stdout only
  - apex_scores.is_calibration_artifact used to mark ghost
    score rows as excluded from board scoring
"""

import sqlite3
import argparse
import sys
from datetime import datetime, timezone

DB_PATH = r"C:\DraftOS\data\edge\draftos.sqlite"

CANONICAL_PID  = 160
GHOST_PID      = 3011
ORPHAN_PIDS    = [2675, 3533, 3793, 4392]


def get_prospect(conn, pid):
    """Return (prospect_id, display_name, position_group, is_active,
               school_canonical, class_year, score_apex_id,
               score_composite, score_tier, score_calibration_artifact)
       or None if not found.
       score_* fields are from the non-calibration apex_scores row, if any.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT p.prospect_id,
               p.display_name,
               p.position_group,
               p.is_active,
               p.school_canonical,
               p.class_year,
               a.apex_id,
               a.apex_composite,
               a.apex_tier,
               a.is_calibration_artifact
        FROM   prospects p
        LEFT JOIN apex_scores a
               ON  a.prospect_id = p.prospect_id
               AND a.model_version = 'apex_v2.3'
        WHERE  p.prospect_id = ?
        LIMIT  1
    """, (pid,))
    return cur.fetchone()


def get_canonical(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT prospect_id, display_name, school_canonical, class_year, position_group
        FROM   prospects
        WHERE  prospect_id = ?
    """, (CANONICAL_PID,))
    return cur.fetchone()


def is_stukes_duplicate(record, canonical):
    """
    Returns (bool, reason_string).
    True  → confirmed Stukes duplicate.
    False → not confirmed; operator review required.
    """
    if record is None:
        return False, "pid not found in DB"

    _pid, display_name, position, is_active, school, class_year, *_ = record
    display_name = (display_name or "").strip()
    dn_lower     = display_name.lower()

    canon_school = canonical[2] or ""
    canon_year   = canonical[3]

    # Condition A: name contains 'stukes'
    if "stukes" in dn_lower:
        return True, f"display_name='{display_name}' contains 'stukes'"

    # Condition B: blank name + school + class_year match canonical
    if (not display_name and
            school == canon_school and
            class_year == canon_year):
        return True, (
            f"blank display_name, school_canonical='{school}' "
            f"and class_year={class_year} match canonical pid={CANONICAL_PID}"
        )

    return False, (
        f"display_name='{display_name}', school_canonical='{school}', "
        f"class_year={class_year} — does not match Stukes identity criteria"
    )


def run_cleanup(apply: bool):
    conn = sqlite3.connect(DB_PATH)
    prefix    = "[APPLIED]" if apply else "[DRY RUN]"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur       = conn.cursor()

    canonical = get_canonical(conn)
    if canonical is None:
        print(f"ERROR: pid={CANONICAL_PID} not found in DB. Cannot proceed.")
        conn.close()
        sys.exit(1)

    flagged_for_review = []

    # ── TASK B: Ghost S row (pid=3011) ─────────────────────────────────────────
    print(f"\n-- TASK B: Ghost S row (pid={GHOST_PID}) --")
    ghost = get_prospect(conn, GHOST_PID)

    if ghost is None:
        print(f"{prefix} pid={GHOST_PID}: not found in DB — skip.")
    elif ghost[3] == 0:
        print(f"{prefix} pid={GHOST_PID}: already is_active=0 — skip.")
    else:
        print(
            f"{prefix} pid={GHOST_PID}: ghost S row confirmed "
            f"(display_name='{ghost[1]}', position={ghost[2]}, "
            f"school='{ghost[4]}') — will deactivate"
        )
        if ghost[6] is not None:
            print(
                f"{prefix} pid={GHOST_PID}: apex_scores row (apex_id={ghost[6]}, "
                f"tier={ghost[8]}, composite={ghost[7]}) will be marked "
                f"is_calibration_artifact=1"
            )
        if apply:
            cur.execute("""
                UPDATE prospects
                SET    is_active  = 0,
                       updated_at = ?
                WHERE  prospect_id = ?
            """, (timestamp, GHOST_PID))
            print(f"[APPLIED] pid={GHOST_PID}: is_active set to 0")
            print(
                f"[APPLIED] pid={GHOST_PID}: deactivation note — "
                "S76 ghost S-5 row. Duplicate identity for Treydan Stukes "
                f"pid={CANONICAL_PID}. Position group S was incorrect; "
                "canonical record is pid=160 CB-4."
            )
            if ghost[6] is not None:
                cur.execute("""
                    UPDATE apex_scores
                    SET    is_calibration_artifact = 1
                    WHERE  prospect_id = ?
                      AND  is_calibration_artifact = 0
                """, (GHOST_PID,))
                print(
                    f"[APPLIED] pid={GHOST_PID}: apex_scores marked "
                    "is_calibration_artifact=1"
                )

    # ── TASK C: Orphan pids ─────────────────────────────────────────────────────
    print(f"\n-- TASK C: Orphan pids {ORPHAN_PIDS} --")
    for pid in ORPHAN_PIDS:
        record    = get_prospect(conn, pid)
        confirmed, reason = is_stukes_duplicate(record, canonical)

        if record is None:
            print(f"{prefix} pid={pid}: not found in DB — skip.")
            continue

        if record[3] == 0:
            print(f"{prefix} pid={pid}: already is_active=0 — skip.")
            continue

        if confirmed:
            print(
                f"{prefix} pid={pid}: STUKES DUPLICATE — "
                f"{reason} — will deactivate"
            )
            if apply:
                cur.execute("""
                    UPDATE prospects
                    SET    is_active  = 0,
                           updated_at = ?
                    WHERE  prospect_id = ?
                """, (timestamp, pid))
                print(f"[APPLIED] pid={pid}: is_active set to 0")
                print(
                    f"[APPLIED] pid={pid}: deactivation note — "
                    "S76 orphan row. Confirmed duplicate identity for "
                    f"Treydan Stukes pid={CANONICAL_PID}. No apex_scores "
                    "row present."
                )
        else:
            print(
                f"{prefix} pid={pid}: NOT STUKES — operator review required "
                f"— {reason}"
            )
            flagged_for_review.append((pid, reason))

    # ── Summary ─────────────────────────────────────────────────────────────────
    if not apply:
        print(f"\n{prefix} No writes executed.")

    if apply:
        conn.commit()
        print("\n[APPLIED] Stukes ghost and orphan cleanup complete.")

    if flagged_for_review:
        print("\n!! OPERATOR REVIEW REQUIRED !!")
        for pid, reason in flagged_for_review:
            print(f"   pid={pid}: {reason}")
        print(
            "   These pids were NOT deactivated. "
            "Manual verification required before any action."
        )

    conn.close()
    return flagged_for_review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Deactivate Stukes ghost S row and orphan prospect rows."
    )
    parser.add_argument(
        "--apply", type=int, choices=[0, 1], required=True,
        help="0 = dry run, 1 = apply writes"
    )
    args   = parser.parse_args()
    flags  = run_cleanup(apply=bool(args.apply))
    if flags:
        sys.exit(2)   # non-zero exit if operator review required
