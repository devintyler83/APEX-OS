"""
fix_caleb_downs_capital_s113.py

Targeted fix: update capital_base and capital_adjusted for Caleb Downs (pid=28)
in apex_scores where model_version='apex_v2.3'.

Context (Session 113):
  - Score after S112 full board re-score: apex_composite=98.5, apex_tier=ELITE
  - ARCHETYPE_OVERRIDES capital_range was written in Session 82 when score was ~73 (DAY1)
  - Stale text: "R1 Late / R2 Early -- scheme-confirmed landing spot required"
  - Correct text (ELITE-consistent, scheme-constrained): matches updated ARCHETYPE_OVERRIDES

Usage:
    python -m scripts.fix_caleb_downs_capital_s113 --apply 0   # dry run
    python -m scripts.fix_caleb_downs_capital_s113 --apply 1   # write
"""

import argparse

from draftos.db.connect import connect
from draftos.apex.writer import backup_once

PROSPECT_ID   = 28
MODEL_VERSION = "apex_v2.3"
NEW_CAPITAL   = "R1 Picks 12-22 -- zone-dominant landing spot required (FM-2/FM-6 caps top-5 upside)"
OLD_CAPITAL   = "R1 Late / R2 Early -- scheme-confirmed landing spot required"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], default=0)
    args = parser.parse_args()

    with connect() as conn:
        row = conn.execute(
            """
            SELECT apex_id, prospect_id, model_version, apex_tier, apex_composite,
                   capital_base, capital_adjusted
            FROM apex_scores
            WHERE prospect_id = ? AND model_version = ?
            """,
            (PROSPECT_ID, MODEL_VERSION),
        ).fetchone()

    if row is None:
        print(f"[ERROR] No apex_scores row for pid={PROSPECT_ID} model_version={MODEL_VERSION}")
        return

    d = dict(row)
    print(f"Prospect ID:      {d['prospect_id']}")
    print(f"Model:            {d['model_version']}")
    print(f"Tier:             {d['apex_tier']}")
    print(f"Composite:        {d['apex_composite']}")
    print(f"capital_base:     {d['capital_base']}")
    print(f"capital_adjusted: {d['capital_adjusted']}")
    print()

    if d["capital_base"] == NEW_CAPITAL and d["capital_adjusted"] == NEW_CAPITAL:
        print("[OK] Capital text already current -- no change needed.")
        return

    if d["capital_base"] != OLD_CAPITAL and d["capital_adjusted"] != OLD_CAPITAL:
        print("[WARN] Capital text is not the expected stale value. Review before applying.")
        print(f"  Expected old: {OLD_CAPITAL}")

    print(f"[PLAN] capital_base    : {d['capital_base']!r}")
    print(f"        -> {NEW_CAPITAL!r}")
    print(f"[PLAN] capital_adjusted: {d['capital_adjusted']!r}")
    print(f"        -> {NEW_CAPITAL!r}")
    print()

    if args.apply == 0:
        print("[DRY RUN] No writes. Rerun with --apply 1 to apply.")
        return

    backup_once(False)

    with connect() as conn:
        conn.execute(
            """
            UPDATE apex_scores
               SET capital_base     = ?,
                   capital_adjusted = ?
             WHERE prospect_id = ?
               AND model_version = ?
            """,
            (NEW_CAPITAL, NEW_CAPITAL, PROSPECT_ID, MODEL_VERSION),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT capital_base, capital_adjusted FROM apex_scores WHERE prospect_id=? AND model_version=?",
            (PROSPECT_ID, MODEL_VERSION),
        ).fetchone()

    print("[WRITE] capital_base and capital_adjusted updated.")
    print(f"[VERIFY] capital_base:     {updated['capital_base']}")
    print(f"[VERIFY] capital_adjusted: {updated['capital_adjusted']}")
    if updated["capital_base"] == NEW_CAPITAL and updated["capital_adjusted"] == NEW_CAPITAL:
        print("[PASS] Capital text update verified.")
    else:
        print("[FAIL] Verification failed -- check DB.")


if __name__ == "__main__":
    main()
