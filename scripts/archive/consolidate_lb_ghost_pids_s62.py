from __future__ import annotations

# --- sys.path bootstrap ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

"""
consolidate_lb_ghost_pids_s62.py
Session 62 — Fix LB ghost PID splits for 6 premium prospects.

Problem: Early sources ingested EDGE/QB/S players with position_group=LB.
Bootstrap created LB PIDs (small IDs 7,9,16,18,39,309). Later correct-position
sources triggered creation of new 3xxx ghost PIDs (EDGE/QB/CB). APEX scored on
the correct-position ghost while most sources (12-15) mapped to the LB keep.
Result: fake divergence deltas (+80-170 ranks) because APEX and consensus are
on different PIDs for the same player.

Pairs (keep_pid ← ghost_pid):
  Arvell Reese      16 LB ← 1058 EDGE  | ghost has correct EDGE archetype score
  R Mason Thomas     7 LB ← 3538 EDGE  | ghost has correct EDGE archetype score
  Gabe Jacas        18 LB ← 3542 EDGE  | ghost has correct EDGE archetype score
  Ty Simpson         9 LB ← 3531 QB    | ghost has correct QB archetype score
  Mansoor Delane    39 CB ← 3509 CB    | keep has higher/correct score, ghost discarded
  Jalon Kilgore    309  S ← 449  CB    | ghost has S-3 score (re-scored S18), no apex on keep

Per-pair actions:
  EDGE/QB pairs (Reese/Thomas/Jacas/Simpson):
    - UPDATE source_player_map: reroute ghost rows to keep_pid
    - DELETE keep's wrong-library APEX score (LB/ILB archetype)
    - UPDATE ghost's APEX row prospect_id → keep_pid (correct archetype preserved)
    - UPDATE prospects.position_group on keep_pid to correct position
    - DELETE divergence_flags for ghost
    - DELETE prospect_consensus_rankings for ghost
    - UPDATE prospects SET is_active=0 for ghost
  Delane:
    - UPDATE source_player_map: reroute ghost rows to keep_pid
    - DELETE ghost's APEX score (keep's score is canonical)
    - DELETE divergence_flags for ghost
    - DELETE prospect_consensus_rankings for ghost
    - UPDATE prospects SET is_active=0 for ghost
  Kilgore:
    - UPDATE source_player_map: reroute ghost rows to keep_pid
    - UPDATE ghost's APEX row prospect_id → keep_pid (S-3 score migrates to S entry)
    - DELETE divergence_flags for ghost
    - DELETE prospect_consensus_rankings for ghost
    - UPDATE prospects SET is_active=0 for ghost
  All:
    - INSERT override_log entries documenting each change

Idempotent: all operations are safe to re-run (checks existence before acting).
Usage:
    python scripts/consolidate_lb_ghost_pids_s62.py --apply 0   # dry run
    python scripts/consolidate_lb_ghost_pids_s62.py --apply 1   # write
"""

import argparse
import shutil
from datetime import datetime, timezone
from typing import Optional

from draftos.config import PATHS
from draftos.db.connect import connect

SEASON_ID = 1
SCRIPT_NAME = "consolidate_lb_ghost_pids_s62"

# Calibration artifact PIDs — never touch
CALIBRATION_PIDS = {230, 304, 313, 455, 504, 880, 1050, 1278, 1371, 1391, 1729, 1925}

# (keep_pid, ghost_pid, display_name, correct_position, apex_strategy)
# apex_strategy:
#   "move_ghost"  — delete keep's APEX, move ghost's APEX to keep_pid
#   "keep_only"   — delete ghost's APEX, keep's APEX is canonical
PAIRS = [
    (16,  1058, "Arvell Reese",    "EDGE", "move_ghost"),
    (7,   3538, "R Mason Thomas",  "EDGE", "move_ghost"),
    (18,  3542, "Gabe Jacas",      "EDGE", "move_ghost"),
    (9,   3531, "Ty Simpson",      "QB",   "move_ghost"),
    (39,  3509, "Mansoor Delane",  "CB",   "keep_only"),
    (309, 449,  "Jalon Kilgore",   "S",    "move_ghost"),
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def backup_db() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = PATHS.db.parent / f"draftos_pre_s62_consolidation_{ts}.sqlite"
    shutil.copy2(PATHS.db, backup_path)
    return backup_path


def log_override(
    conn,
    apply: bool,
    prospect_id: int,
    override_type: str,
    field_changed: str,
    old_value: Optional[str],
    new_value: Optional[str],
    rationale: str,
    magnitude: Optional[float] = None,
    model_version: str = "apex_v2.3",
) -> None:
    if not apply:
        return
    conn.execute(
        """
        INSERT INTO override_log
            (prospect_id, season_id, model_version, override_type, field_changed,
             old_value, new_value, magnitude, rationale, applied_at, applied_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prospect_id, SEASON_ID, model_version, override_type, field_changed,
            old_value, new_value, magnitude, rationale, utcnow_iso(),
            SCRIPT_NAME,
        ),
    )


def consolidate_pair(
    conn,
    keep_pid: int,
    ghost_pid: int,
    display_name: str,
    correct_position: str,
    apex_strategy: str,
    apply: bool,
) -> dict:
    """Execute all consolidation steps for one pair. Returns summary dict."""
    result = {
        "name": display_name,
        "keep_pid": keep_pid,
        "ghost_pid": ghost_pid,
        "spm_rerouted": 0,
        "position_updated": False,
        "apex_keep_deleted": False,
        "apex_ghost_moved": False,
        "apex_ghost_deleted": False,
        "divergence_deleted": 0,
        "consensus_deleted": 0,
        "tags_deleted": 0,
        "ghost_deactivated": False,
        "overrides_logged": 0,
        "errors": [],
    }

    # Safety: never touch calibration artifacts
    if keep_pid in CALIBRATION_PIDS or ghost_pid in CALIBRATION_PIDS:
        result["errors"].append(f"ABORT: calibration artifact PID in pair {keep_pid}/{ghost_pid}")
        return result

    # Verify both PIDs exist and are currently active
    keep_row = conn.execute(
        "SELECT prospect_id, display_name, full_name, school_canonical, position_group, is_active FROM prospects WHERE prospect_id=?",
        (keep_pid,),
    ).fetchone()
    ghost_row = conn.execute(
        "SELECT prospect_id, display_name, full_name, school_canonical, position_group, is_active FROM prospects WHERE prospect_id=?",
        (ghost_pid,),
    ).fetchone()

    if not keep_row:
        result["errors"].append(f"keep_pid={keep_pid} not found in prospects")
        return result
    if not ghost_row:
        result["errors"].append(f"ghost_pid={ghost_pid} not found in prospects")
        return result
    if ghost_row["is_active"] == 0:
        result["errors"].append(f"ghost_pid={ghost_pid} already inactive — skipping (idempotent)")
        return result

    print(f"\n  {display_name} | keep={keep_pid}({keep_row['position_group']}) ghost={ghost_pid}({ghost_row['position_group']})")

    # ── Step 1: Reroute source_player_map ────────────────────────────────────
    # source_player_id is UNIQUE so each ghost SPM row maps to exactly one source_player.
    # Simple UPDATE: point ghost rows to keep_pid.
    ghost_spm_rows = conn.execute(
        "SELECT map_id, source_player_id FROM source_player_map WHERE prospect_id=?",
        (ghost_pid,),
    ).fetchall()

    print(f"    SPM: {len(ghost_spm_rows)} ghost rows to reroute to keep_pid={keep_pid}")
    for row in ghost_spm_rows:
        if apply:
            conn.execute(
                "UPDATE source_player_map SET prospect_id=?, match_notes=COALESCE(match_notes,'') || ' [rerouted from ghost pid=" + str(ghost_pid) + " by s62]' WHERE map_id=?",
                (keep_pid, row["map_id"]),
            )
        result["spm_rerouted"] += 1

    log_override(
        conn, apply, keep_pid, "spm_consolidation", "source_player_map.prospect_id",
        str(ghost_pid), str(keep_pid),
        f"Rerouted {result['spm_rerouted']} SPM entries from ghost pid={ghost_pid} ({ghost_row['position_group']}) "
        f"to keep pid={keep_pid}. Ghost was LB/wrong-position bootstrap artifact.",
    )
    result["overrides_logged"] += 1

    # ── Step 2: Position group update on keep ────────────────────────────────
    # prospects has UNIQUE(season_id, full_name, school_canonical, position_group).
    # If ghost already holds the correct position slot, we must clear it first by
    # stamping ghost's position_group with a __ghost__ marker before updating keep.
    current_pos = keep_row["position_group"]
    if current_pos != correct_position:
        print(f"    Position: {current_pos} -> {correct_position} on keep_pid={keep_pid}")
        if apply:
            # Check if a conflicting row exists (ghost holds the target position slot)
            conflict = conn.execute(
                "SELECT prospect_id FROM prospects "
                "WHERE season_id=? AND full_name=? AND school_canonical=? AND position_group=? "
                "AND prospect_id != ?",
                (SEASON_ID, keep_row["full_name"], keep_row["school_canonical"],
                 correct_position, keep_pid),
            ).fetchone()
            if conflict:
                # Stamp ghost's position_group to free the unique slot
                ghost_marker = f"__ghost_{conflict['prospect_id']}__"
                print(f"    Position: clearing conflict on pid={conflict['prospect_id']} -> {ghost_marker}")
                conn.execute(
                    "UPDATE prospects SET position_group=?, updated_at=? WHERE prospect_id=?",
                    (ghost_marker, utcnow_iso(), conflict["prospect_id"]),
                )
            conn.execute(
                "UPDATE prospects SET position_group=?, updated_at=? WHERE prospect_id=?",
                (correct_position, utcnow_iso(), keep_pid),
            )
        log_override(
            conn, apply, keep_pid, "position_correction", "position_group",
            current_pos, correct_position,
            f"Position corrected from {current_pos} to {correct_position}. "
            f"Early sources mislabeled this prospect as {current_pos}. "
            f"Ghost pid={ghost_pid} was the correct-position entry.",
        )
        result["position_updated"] = True
        result["overrides_logged"] += 1
    else:
        print(f"    Position: already {correct_position} on keep_pid={keep_pid} - no change needed")

    # ── Step 3: APEX score handling ───────────────────────────────────────────
    # Fetch ALL apex rows (keep may have v2.2 + v2.3; ghost typically has one)
    keep_apex_rows = conn.execute(
        "SELECT apex_id, apex_composite, matched_archetype, model_version FROM apex_scores WHERE prospect_id=?",
        (keep_pid,),
    ).fetchall()
    ghost_apex_rows = conn.execute(
        "SELECT apex_id, apex_composite, matched_archetype, model_version FROM apex_scores WHERE prospect_id=?",
        (ghost_pid,),
    ).fetchall()
    # Use latest model version from each set for logging
    keep_apex = keep_apex_rows[-1] if keep_apex_rows else None
    ghost_apex = ghost_apex_rows[-1] if ghost_apex_rows else None

    if apex_strategy == "move_ghost":
        # Delete ALL of keep's wrong-archetype scores (may include v2.2 and v2.3),
        # then move ghost's correct-archetype score to keep_pid.
        if keep_apex_rows:
            keep_summary = "; ".join(
                f"{r['apex_composite']} {r['matched_archetype']} ({r['model_version']})"
                for r in keep_apex_rows
            )
            print(f"    APEX: DELETE {len(keep_apex_rows)} keep={keep_pid} scores [wrong archetype]: {keep_summary}")
            if apply:
                conn.execute("DELETE FROM apex_scores WHERE prospect_id=?", (keep_pid,))
            log_override(
                conn, apply, keep_pid, "apex_deletion", "apex_scores.prospect_id",
                keep_summary, None,
                f"Deleted {len(keep_apex_rows)} wrong-archetype APEX score(s) from keep_pid={keep_pid}. "
                f"Scores used wrong positional library ({keep_apex_rows[0]['matched_archetype'] if keep_apex_rows else ''}). "
                f"Ghost pid={ghost_pid} had correct {correct_position} archetype score.",
                model_version=keep_apex_rows[0]["model_version"] if keep_apex_rows else "apex_v2.2",
            )
            result["apex_keep_deleted"] = True
            result["overrides_logged"] += 1

        if ghost_apex_rows:
            ghost_summary = "; ".join(
                f"{r['apex_composite']} {r['matched_archetype']} ({r['model_version']})"
                for r in ghost_apex_rows
            )
            print(f"    APEX: MOVE {len(ghost_apex_rows)} ghost={ghost_pid} score(s) -> keep_pid={keep_pid}: {ghost_summary}")
            if apply:
                conn.execute(
                    "UPDATE apex_scores SET prospect_id=? WHERE prospect_id=?",
                    (keep_pid, ghost_pid),
                )
            log_override(
                conn, apply, keep_pid, "apex_migration", "apex_scores.prospect_id",
                str(ghost_pid), str(keep_pid),
                f"Migrated {len(ghost_apex_rows)} APEX score(s) ({ghost_summary}) "
                f"from ghost pid={ghost_pid} to keep pid={keep_pid}. "
                f"Score used correct {correct_position} positional library.",
                magnitude=ghost_apex["apex_composite"] if ghost_apex else None,
                model_version=ghost_apex["model_version"] if ghost_apex else "apex_v2.3",
            )
            result["apex_ghost_moved"] = True
            result["overrides_logged"] += 1
        else:
            print(f"    APEX: ghost={ghost_pid} has no apex score - nothing to move")

    elif apex_strategy == "keep_only":
        # Delete ALL ghost APEX scores, keep's scores are canonical
        if ghost_apex_rows:
            ghost_summary = "; ".join(
                f"{r['apex_composite']} {r['matched_archetype']} ({r['model_version']})"
                for r in ghost_apex_rows
            )
            keep_summary = "; ".join(
                f"{r['apex_composite']} {r['matched_archetype']} ({r['model_version']})"
                for r in keep_apex_rows
            ) if keep_apex_rows else "N/A"
            print(f"    APEX: DELETE {len(ghost_apex_rows)} ghost={ghost_pid} score(s) [ghost discarded]: {ghost_summary}")
            if apply:
                conn.execute("DELETE FROM apex_scores WHERE prospect_id=?", (ghost_pid,))
            log_override(
                conn, apply, ghost_pid, "apex_deletion", "apex_scores.prospect_id",
                ghost_summary, None,
                f"Deleted {len(ghost_apex_rows)} ghost APEX score(s) from pid={ghost_pid}. "
                f"Keep pid={keep_pid} has the canonical score(s) ({keep_summary}). "
                f"Ghost was created by early source position mislabeling.",
                model_version=ghost_apex["model_version"],
            )
            result["apex_ghost_deleted"] = True
            result["overrides_logged"] += 1
        else:
            print(f"    APEX: ghost={ghost_pid} has no apex score - nothing to delete")

    # ── Step 4: Divergence flags cleanup ─────────────────────────────────────
    ghost_div = conn.execute(
        "SELECT COUNT(*) FROM divergence_flags WHERE prospect_id=?", (ghost_pid,)
    ).fetchone()[0]
    if ghost_div > 0:
        print(f"    Divergence: DELETE {ghost_div} rows for ghost_pid={ghost_pid}")
        if apply:
            conn.execute("DELETE FROM divergence_flags WHERE prospect_id=?", (ghost_pid,))
        result["divergence_deleted"] = ghost_div

    # Also delete keep's divergence (will be recomputed after consensus rebuild)
    keep_div = conn.execute(
        "SELECT COUNT(*) FROM divergence_flags WHERE prospect_id=?", (keep_pid,)
    ).fetchone()[0]
    if keep_div > 0:
        print(f"    Divergence: DELETE {keep_div} stale rows for keep_pid={keep_pid} (will recompute)")
        if apply:
            conn.execute("DELETE FROM divergence_flags WHERE prospect_id=?", (keep_pid,))
        result["divergence_deleted"] += keep_div

    # ── Step 5: Consensus rankings cleanup ───────────────────────────────────
    ghost_cons = conn.execute(
        "SELECT COUNT(*) FROM prospect_consensus_rankings WHERE prospect_id=? AND season_id=?",
        (ghost_pid, SEASON_ID),
    ).fetchone()[0]
    if ghost_cons > 0:
        print(f"    Consensus: DELETE {ghost_cons} rows for ghost_pid={ghost_pid}")
        if apply:
            conn.execute(
                "DELETE FROM prospect_consensus_rankings WHERE prospect_id=? AND season_id=?",
                (ghost_pid, SEASON_ID),
            )
        result["consensus_deleted"] = ghost_cons

    # ── Step 6: Tag cleanup for ghost ────────────────────────────────────────
    # Order: prospect_tag_history (FK->ptag_id) must be deleted before prospect_tags.
    # Then prospect_tag_recommendations.
    ghost_tag_rows = conn.execute(
        "SELECT ptag_id FROM prospect_tags WHERE prospect_id=?", (ghost_pid,)
    ).fetchall()
    ghost_tags = len(ghost_tag_rows)
    ghost_ptag_ids = [r["ptag_id"] for r in ghost_tag_rows]

    if ghost_ptag_ids:
        placeholders = ",".join("?" * len(ghost_ptag_ids))
        ghost_tag_history = conn.execute(
            f"SELECT COUNT(*) FROM prospect_tag_history WHERE ptag_id IN ({placeholders})",
            ghost_ptag_ids,
        ).fetchone()[0]
        if ghost_tag_history > 0:
            print(f"    Tag history: DELETE {ghost_tag_history} history rows for ghost_pid={ghost_pid} ptag_ids")
            if apply:
                conn.execute(
                    f"DELETE FROM prospect_tag_history WHERE ptag_id IN ({placeholders})",
                    ghost_ptag_ids,
                )

    if ghost_tags > 0:
        print(f"    Tags: DELETE {ghost_tags} prospect_tags for ghost_pid={ghost_pid}")
        if apply:
            conn.execute("DELETE FROM prospect_tags WHERE prospect_id=?", (ghost_pid,))

    ghost_tag_recs = conn.execute(
        "SELECT COUNT(*) FROM prospect_tag_recommendations WHERE prospect_id=?", (ghost_pid,)
    ).fetchone()[0]
    if ghost_tag_recs > 0:
        print(f"    Tag recs: DELETE {ghost_tag_recs} recommendations for ghost_pid={ghost_pid}")
        if apply:
            conn.execute("DELETE FROM prospect_tag_recommendations WHERE prospect_id=?", (ghost_pid,))
    result["tags_deleted"] = ghost_tags + ghost_tag_recs

    # ── Step 7: Deactivate ghost ──────────────────────────────────────────────
    print(f"    Ghost: SET is_active=0 for pid={ghost_pid} ({ghost_row['display_name']})")
    if apply:
        conn.execute(
            "UPDATE prospects SET is_active=0, updated_at=? WHERE prospect_id=?",
            (utcnow_iso(), ghost_pid),
        )
    log_override(
        conn, apply, ghost_pid, "deactivation", "prospects.is_active",
        "1", "0",
        f"Deactivated ghost PID={ghost_pid} ({ghost_row['position_group']}) after consolidating into "
        f"keep PID={keep_pid} ({correct_position}). Ghost was a bootstrap artifact from "
        f"early LB mis-labeling. All {result['spm_rerouted']} SPM entries migrated to keep.",
    )
    result["ghost_deactivated"] = True
    result["overrides_logged"] += 1

    return result


def run(apply: bool) -> None:
    if apply:
        backup_path = backup_db()
        print(f"Backup: {backup_path}")
    else:
        print("DRY RUN — no writes will occur")

    print(f"\nMode: {'APPLY' if apply else 'DRY RUN'}")
    print(f"Pairs: {len(PAIRS)}")

    all_results = []

    with connect() as conn:
        for keep_pid, ghost_pid, display_name, correct_position, apex_strategy in PAIRS:
            result = consolidate_pair(
                conn, keep_pid, ghost_pid, display_name,
                correct_position, apex_strategy, apply,
            )
            all_results.append(result)

        if apply:
            conn.commit()
            print("\nCommitted.")

    print()
    print(f"=== CONSOLIDATION S62 {'— DRY RUN' if not apply else '— APPLIED'} ===")
    print()

    total_spm = 0
    total_errors = 0

    for r in all_results:
        status = "ERROR" if r["errors"] else "OK"
        print(f"  [{status}] {r['name']} | keep={r['keep_pid']} ghost={r['ghost_pid']}")
        if r["errors"]:
            for e in r["errors"]:
                print(f"         ERROR: {e}")
            total_errors += len(r["errors"])
            continue
        print(f"         SPM rerouted={r['spm_rerouted']}  pos_updated={r['position_updated']}")
        print(f"         apex_keep_del={r['apex_keep_deleted']}  apex_moved={r['apex_ghost_moved']}  apex_ghost_del={r['apex_ghost_deleted']}")
        print(f"         div_deleted={r['divergence_deleted']}  cons_deleted={r['consensus_deleted']}  tags_deleted={r['tags_deleted']}")
        print(f"         ghost_deactivated={r['ghost_deactivated']}  overrides_logged={r['overrides_logged']}")
        total_spm += r["spm_rerouted"]

    print()
    print(f"  Total SPM rows rerouted: {total_spm}")
    print(f"  Total errors: {total_errors}")
    print()

    if not apply:
        print("DRY RUN complete. Rerun with --apply 1 to write.")
        print()
        print("After applying, run in order:")
        print("  1. python scripts/build_consensus_2026.py --apply 1")
        print("  2. python scripts/run_apex_scoring_2026.py --batch divergence --apply 1")
        print("  3. python scripts/evaluate_tag_triggers_2026.py --apply 1")
        print("  4. python scripts/doctor.py")
    else:
        print("APPLY complete.")
        print()
        print("Next steps:")
        print("  1. python scripts/build_consensus_2026.py --apply 1")
        print("  2. python scripts/run_apex_scoring_2026.py --batch divergence --apply 1")
        print("  3. python scripts/evaluate_tag_triggers_2026.py --apply 1")
        print("  4. python scripts/doctor.py")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Consolidate LB ghost PIDs into canonical keep PIDs for 6 premium prospects."
    )
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
