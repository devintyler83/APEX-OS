"""
fix_apex_calibration_flags_s103.py

Fixes two apex_scores data integrity issues from stale pre-Session-101 rows:

ISSUE 1 — Calibration PIDs with wrong is_calibration_artifact flag (apex_v2.3 rows):
  11 known calibration artifact PIDs have is_calibration_artifact=0 in their v2.3
  apex_scores rows. These were scored in a prior session before the flag was correctly
  enforced. They are is_active=0 in prospects and must be excluded from any board query
  that filters is_calibration_artifact=0.
  Fix: UPDATE apex_scores SET is_calibration_artifact=1 for those PIDs.

ISSUE 2 — Dedup ghost PIDs with stale scored rows:
  3 PIDs with __dedup_*__ school_canonical (deactivated in Session 101 ghost fix) still
  have apex_scores + divergence_flags rows. These have no audit value.
  Fix: DELETE apex_scores + divergence_flags rows for PIDs 3559, 4318, 4323.

After this fix:
  apex_scores v2.3, is_calibration_artifact=0 → exactly 297 rows (the clean 2026 universe)
  apex_scores v2.3, is_calibration_artifact=1 → 12 rows (11 fixed + Treydan Stukes)

Usage:
    python -m scripts.fix_apex_calibration_flags_s103 --apply 0   # dry run
    python -m scripts.fix_apex_calibration_flags_s103 --apply 1   # execute
"""
from __future__ import annotations

import argparse
import sys

from draftos.apex.writer import backup_once
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Known calibration artifact PIDs — per CLAUDE.md and tag_calibration_artifacts_2026.py
# PIDs 230,304,455,504,880,1050,1278,1371,1391,1729,1925 have wrong is_calibration_artifact
# flag in their apex_v2.3 rows (was 0, should be 1).
# PID 313 (Gunnar Helm) has only a v2.2 row with flag already correct — not in this list.
# PID 3011 (Treydan Stukes) v2.3 row already has is_calibration_artifact=1 — not in this list.
# ---------------------------------------------------------------------------
CALIBRATION_PIDS_WRONG_FLAG = (
    230,   # Shedeur Sanders
    304,   # Trevor Etienne
    455,   # Travis Hunter
    504,   # Chris Paul
    880,   # Tate Ratledge
    1050,  # Tyleik Williams
    1278,  # Nick Emmanwori
    1371,  # Armand Membou
    1391,  # Jared Wilson
    1729,  # Donovan Ezeiruaku
    1925,  # Carson Schwesinger
)

# Dedup ghost PIDs — __dedup_*__ school_canonical, no audit value
DEDUP_GHOST_PIDS = (3559, 4318, 4323)  # Max Klare, Peter Woods (ghost), Akheem Mesidor (ghost)

MODEL_VERSION = "apex_v2.3"


def _dry_run(conn) -> None:
    cal_placeholders = ",".join("?" * len(CALIBRATION_PIDS_WRONG_FLAG))
    ghost_placeholders = ",".join("?" * len(DEDUP_GHOST_PIDS))

    rows = conn.execute(
        f"""
        SELECT a.prospect_id, p.display_name, a.apex_composite, a.apex_tier, a.is_calibration_artifact
        FROM apex_scores a
        JOIN prospects p ON p.prospect_id = a.prospect_id
        WHERE a.model_version = ?
          AND a.prospect_id IN ({cal_placeholders})
          AND a.is_calibration_artifact = 0
        ORDER BY a.apex_composite DESC
        """,
        (MODEL_VERSION, *CALIBRATION_PIDS_WRONG_FLAG),
    ).fetchall()

    print(f"\n[ISSUE 1] Calibration PIDs with wrong flag ({len(rows)} to fix):")
    for r in rows:
        print(f"  pid={r[0]:5d}  {r[1]:<25s}  composite={r[2]:.1f}  tier={r[3]}  "
              f"is_calibration_artifact={r[4]} -> would set to 1")

    ghost_apex = conn.execute(
        f"""
        SELECT a.prospect_id, p.display_name, a.apex_composite, a.model_version
        FROM apex_scores a
        JOIN prospects p ON p.prospect_id = a.prospect_id
        WHERE a.prospect_id IN ({ghost_placeholders})
        ORDER BY a.prospect_id
        """,
        DEDUP_GHOST_PIDS,
    ).fetchall()

    ghost_div = conn.execute(
        f"""
        SELECT df.prospect_id, p.display_name, df.divergence_flag, df.model_version
        FROM divergence_flags df
        JOIN prospects p ON p.prospect_id = df.prospect_id
        WHERE df.prospect_id IN ({ghost_placeholders})
        ORDER BY df.prospect_id
        """,
        DEDUP_GHOST_PIDS,
    ).fetchall()

    print(f"\n[ISSUE 2] Dedup ghost PIDs -- apex_scores rows to DELETE ({len(ghost_apex)}):")
    for r in ghost_apex:
        print(f"  pid={r[0]:5d}  {r[1]:<30s}  composite={r[2]:.1f}  model={r[3]}")

    print(f"\n[ISSUE 2] Dedup ghost PIDs -- divergence_flags rows to DELETE ({len(ghost_div)}):")
    for r in ghost_div:
        print(f"  pid={r[0]:5d}  {r[1]:<30s}  flag={r[2]}  model={r[3]}")

    print("\n[DRY RUN] No writes. Re-run with --apply 1 to execute.")

    # Post-fix universe projection
    active_non_cal = conn.execute(
        """
        SELECT COUNT(*) FROM apex_scores a
        JOIN prospects p ON p.prospect_id = a.prospect_id
        WHERE a.model_version = ? AND a.is_calibration_artifact = 0 AND p.is_active = 1
        """,
        (MODEL_VERSION,),
    ).fetchone()[0]
    print(f"\n[PROJECTION] Post-fix universe: {active_non_cal} rows with "
          f"is_active=1 AND is_calibration_artifact=0 (should be 297)")


def _apply(conn) -> None:
    cal_placeholders = ",".join("?" * len(CALIBRATION_PIDS_WRONG_FLAG))
    ghost_placeholders = ",".join("?" * len(DEDUP_GHOST_PIDS))

    # Issue 1: fix calibration flag
    result = conn.execute(
        f"""
        UPDATE apex_scores
        SET is_calibration_artifact = 1
        WHERE model_version = ?
          AND prospect_id IN ({cal_placeholders})
          AND is_calibration_artifact = 0
        """,
        (MODEL_VERSION, *CALIBRATION_PIDS_WRONG_FLAG),
    )
    updated = result.rowcount
    print(f"[ISSUE 1] Updated is_calibration_artifact=1 for {updated} calibration rows")

    # Issue 2: delete dedup ghost apex_scores (all model versions)
    r2a = conn.execute(
        f"DELETE FROM apex_scores WHERE prospect_id IN ({ghost_placeholders})",
        DEDUP_GHOST_PIDS,
    )
    print(f"[ISSUE 2] Deleted {r2a.rowcount} apex_scores rows for dedup ghost PIDs")

    # Issue 2: delete dedup ghost divergence_flags (all model versions)
    r2b = conn.execute(
        f"DELETE FROM divergence_flags WHERE prospect_id IN ({ghost_placeholders})",
        DEDUP_GHOST_PIDS,
    )
    print(f"[ISSUE 2] Deleted {r2b.rowcount} divergence_flags rows for dedup ghost PIDs")

    conn.commit()

    # Verification
    active_non_cal = conn.execute(
        """
        SELECT COUNT(*) FROM apex_scores a
        JOIN prospects p ON p.prospect_id = a.prospect_id
        WHERE a.model_version = ? AND a.is_calibration_artifact = 0 AND p.is_active = 1
        """,
        (MODEL_VERSION,),
    ).fetchone()[0]

    total_v23 = conn.execute(
        "SELECT COUNT(*) FROM apex_scores WHERE model_version = ?",
        (MODEL_VERSION,),
    ).fetchone()[0]

    cal_rows = conn.execute(
        "SELECT COUNT(*) FROM apex_scores WHERE model_version = ? AND is_calibration_artifact = 1",
        (MODEL_VERSION,),
    ).fetchone()[0]

    print(f"\n[VERIFICATION]")
    print(f"  Total v2.3 apex_scores rows:          {total_v23}")
    print(f"  is_calibration_artifact=0, is_active=1: {active_non_cal}  (expected 297)")
    print(f"  is_calibration_artifact=1:              {cal_rows}")

    if active_non_cal == 297:
        print("\n[PASS] Clean 2026 universe confirmed: 297 rows.")
    else:
        print(f"\n[WARN] Expected 297 active non-cal rows, got {active_non_cal}. Investigate.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix apex_scores calibration flag + delete dedup ghost rows (S103)"
    )
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True,
                        help="0=dry run, 1=execute writes")
    args = parser.parse_args()

    apply = bool(args.apply)

    print("=" * 60)
    print("fix_apex_calibration_flags_s103")
    print(f"Apply: {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    print("=" * 60)

    with connect() as conn:
        if not apply:
            _dry_run(conn)
            return

        backup_once(False)

        _apply(conn)
        print("\n[DONE] Re-run with --apply 0 to verify idempotency.")


if __name__ == "__main__":
    main()
