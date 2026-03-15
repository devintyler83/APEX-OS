"""
fix_concepcion_2026.py
Remediation script for KC Concepcion prospect record.

Situation (audited 2026-03-15):
  pid=3   'Kc Concepcion'  WR  is_active=1  consensus #32 (11 sources) ← CANONICAL
  pid=3516 'KC Concepcion' WR  is_active=1  consensus #173 (2 sources) ← ghost
  pid=4324 'KC Concepcion' LB  is_active=1  no consensus               ← ghost (wrong pos)
  pid=3148 'Kevin Concepcion' WR is_active=0  already inactive
  pid=4483 'Kevin Concepcion' WR is_active=0  already inactive

Actions:
  1. Fix display_name + full_name casing on canonical (pid=3): 'Kc' -> 'KC'
  2. Confirm position_group = WR on canonical (already correct, explicit set)
  3. Deactivate ghost rows: pid=3516, pid=4324
  4. Wipe apex_scores for canonical pid=3 (ILB-3 / ILB-1 — wrong position family)
  5. Wipe divergence_flags for canonical pid=3 (stale APEX_LOW_PVC_STRUCTURAL rows)

Idempotent — safe to re-run.

Usage:
    python scripts/fix_concepcion_2026.py --apply 0   # dry run
    python scripts/fix_concepcion_2026.py --apply 1   # apply
"""

import argparse
import datetime
import pathlib
import shutil
import sqlite3

DB_PATH = r"C:\DraftOS\data\edge\draftos.sqlite"

CANONICAL_PID = 3
GHOST_PIDS    = [3516, 4324]   # both active duplicates


def backup(db_path: str) -> None:
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = pathlib.Path(db_path).with_suffix(f".bak_{ts}.sqlite")
    shutil.copy2(db_path, dst)
    print(f"[BACKUP] {dst}")


def run(apply: bool) -> None:
    if apply:
        backup(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    mode = "[APPLIED]" if apply else "[DRY RUN]"
    changes: list[str] = []

    # ── 1. Fix display_name / full_name casing on canonical ──────────────────
    cur.execute(
        "SELECT display_name, full_name, position_group FROM prospects WHERE prospect_id = ?",
        (CANONICAL_PID,),
    )
    row = cur.fetchone()
    if row:
        dn, fn, pos = row
        changes.append(
            f"[NAME FIX]     pid={CANONICAL_PID} display_name='{dn}' -> 'KC Concepcion'"
        )
        changes.append(
            f"[NAME NOTE]    pid={CANONICAL_PID} full_name='{fn}' kept as-is "
            f"(unique constraint held by ghost pid=3516 — display_name fix sufficient)"
        )
        changes.append(
            f"[POSITION]     pid={CANONICAL_PID} position_group='{pos}' -> 'WR' (confirm)"
        )
        if apply:
            cur.execute(
                """UPDATE prospects
                   SET display_name   = 'KC Concepcion',
                       position_group = 'WR',
                       updated_at     = datetime('now')
                   WHERE prospect_id = ?""",
                (CANONICAL_PID,),
            )
    else:
        changes.append(f"[WARNING] Canonical pid={CANONICAL_PID} not found in prospects")

    # ── 2. Deactivate ghost rows ──────────────────────────────────────────────
    for ghost_pid in GHOST_PIDS:
        cur.execute(
            "SELECT display_name, position_group, is_active FROM prospects WHERE prospect_id = ?",
            (ghost_pid,),
        )
        grow = cur.fetchone()
        if grow:
            gdn, gpos, gactive = grow
            if gactive == 1:
                changes.append(
                    f"[GHOST DEACT]  pid={ghost_pid} '{gdn}' pos={gpos} is_active=1 -> 0"
                )
                if apply:
                    cur.execute(
                        "UPDATE prospects SET is_active = 0, updated_at = datetime('now') "
                        "WHERE prospect_id = ?",
                        (ghost_pid,),
                    )
            else:
                changes.append(
                    f"[GHOST SKIP]   pid={ghost_pid} '{gdn}' already is_active=0"
                )
        else:
            changes.append(f"[GHOST SKIP]   pid={ghost_pid} not found")

    # ── 3. Wipe invalid APEX scores on canonical ──────────────────────────────
    cur.execute(
        "SELECT apex_id, matched_archetype, apex_composite, model_version "
        "FROM apex_scores WHERE prospect_id = ?",
        (CANONICAL_PID,),
    )
    apex_rows = cur.fetchall()
    if apex_rows:
        for apex_id, arch, composite, mv in apex_rows:
            changes.append(
                f"[APEX WIPE]    pid={CANONICAL_PID} apex_id={apex_id} "
                f"archetype={arch} composite={composite} model={mv} -> DELETED"
            )
        if apply:
            cur.execute(
                "DELETE FROM apex_scores WHERE prospect_id = ?",
                (CANONICAL_PID,),
            )
    else:
        changes.append(f"[APEX SKIP]    pid={CANONICAL_PID} no apex_scores rows")

    # ── 4. Wipe stale divergence flags on canonical ───────────────────────────
    cur.execute(
        "SELECT COUNT(*), GROUP_CONCAT(divergence_flag) FROM divergence_flags "
        "WHERE prospect_id = ?",
        (CANONICAL_PID,),
    )
    drow = cur.fetchone()
    div_count, div_flags = drow if drow else (0, "")
    if div_count:
        changes.append(
            f"[DIV WIPE]     pid={CANONICAL_PID} {div_count} row(s) flags=[{div_flags}] -> DELETED"
        )
        if apply:
            cur.execute(
                "DELETE FROM divergence_flags WHERE prospect_id = ?",
                (CANONICAL_PID,),
            )
    else:
        changes.append(f"[DIV SKIP]     pid={CANONICAL_PID} no divergence_flags rows")

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n{mode} KC Concepcion remediation")
    print(f"  Canonical PID : {CANONICAL_PID}")
    print(f"  Ghost PIDs    : {GHOST_PIDS}")
    print()
    for ch in changes:
        print(f"  {ch}")

    if apply:
        conn.commit()
        print("\n  [COMMITTED]")
    else:
        print("\n  [NO CHANGES WRITTEN — pass --apply 1 to execute]")

    conn.close()
    print("[DONE]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix KC Concepcion prospect record")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1],
                        help="0=dry run (default), 1=apply")
    args = parser.parse_args()
    run(bool(args.apply))
