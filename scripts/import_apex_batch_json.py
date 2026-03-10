"""
APEX v2.2 Batch JSON Importer.
Reads a JSON file of pre-evaluated prospect records and writes to apex_scores + divergence_flags.

Usage:
    python -m scripts.import_apex_batch_json --file <path_to_json> --apply 0|1

The JSON file must be a list of dicts. Each dict must match the apex_scores schema
and include a 'prospect_id' and 'position' field (position used for PVC computation).

Idempotent — safe to re-run. Uses INSERT OR REPLACE via UNIQUE constraints.
Backs up DB before first write per run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from draftos.db.connect import connect
from draftos.apex.engine import get_pvc, compute_apex_composite, compute_apex_tier, compute_divergence
from draftos.apex.writer import backup_once, upsert_apex_score, upsert_divergence_flag

MODEL_VERSION = "apex_v2.2"
SEASON_ID     = 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Import APEX batch JSON to DB")
    parser.add_argument("--file",  required=True, help="Path to JSON file")
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True,
                        help="0=dry run, 1=write to DB")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        sys.exit(1)

    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        print("[ERROR] JSON file must contain a list of records")
        sys.exit(1)

    print(f"Loaded {len(records)} records from {path}")
    print(f"Apply: {'YES' if args.apply else 'DRY RUN'}")
    print()

    backed_up      = False
    success_count  = 0
    fail_count     = 0

    with connect() as conn:
        for rec in records:
            pid      = rec.get("prospect_id")
            position = rec.get("position", "")
            name     = rec.get("prospect_name", f"pid={pid}")

            if pid is None:
                print(f"[SKIP] Missing prospect_id in record: {rec}")
                fail_count += 1
                continue

            # Pull consensus data from DB
            crow = conn.execute(
                "SELECT consensus_rank, score, tier FROM prospect_consensus_rankings WHERE prospect_id=? AND season_id=?",
                (pid, SEASON_ID),
            ).fetchone()

            if crow:
                consensus_rank  = int(crow["consensus_rank"])
                consensus_tier  = crow["tier"] or "Unknown"
                consensus_score = float(crow["score"])
            else:
                consensus_rank  = rec.get("consensus_rank", 9999)
                consensus_tier  = "Unknown"
                consensus_score = 0.0

            # Compute deterministic fields
            pvc            = get_pvc(position)
            raw_score      = float(rec.get("raw_score", 0))
            apex_composite = compute_apex_composite(raw_score, position)
            apex_tier      = compute_apex_tier(apex_composite)
            divergence     = compute_divergence(apex_composite, consensus_rank, apex_tier, consensus_tier)

            ras_row = conn.execute(
                "SELECT ras_total FROM ras WHERE prospect_id=? AND season_id=?",
                (pid, SEASON_ID),
            ).fetchone()
            ras_score = float(ras_row["ras_total"]) if ras_row and ras_row["ras_total"] is not None else None

            print(
                f"  {name:30} | {position:5} | raw={raw_score:.1f} pvc={pvc} "
                f"composite={apex_composite:.1f} tier={apex_tier:15} | "
                f"div={divergence['divergence_flag']}"
            )

            if not args.apply:
                success_count += 1
                continue

            backed_up = backup_once(backed_up)

            # Build apex_data dict from record (map JSON field names to DB column sources)
            apex_data = {
                "v_processing":    rec.get("v_processing"),
                "v_athleticism":   rec.get("v_athleticism"),
                "v_scheme_vers":   rec.get("v_scheme_vers"),
                "v_comp_tough":    rec.get("v_comp_tough"),
                "v_character":     rec.get("v_character"),
                "v_dev_traj":      rec.get("v_dev_traj"),
                "v_production":    rec.get("v_production"),
                "v_injury":        rec.get("v_injury"),
                "c1_public_record": rec.get("c1_public_record"),
                "c2_motivation":   rec.get("c2_motivation"),
                "c3_psych_profile": rec.get("c3_psych_profile"),
                "archetype":       rec.get("archetype"),
                "archetype_gap":   rec.get("archetype_gap"),
                "gap_label":       rec.get("gap_label"),
                "raw_score":       raw_score,
                "capital_base":    rec.get("capital_base"),
                "capital_adjusted": rec.get("capital_adjusted"),
                "eval_confidence": rec.get("eval_confidence"),
                "tags":            rec.get("tags", ""),
                "strengths":       rec.get("strengths", ""),
                "red_flags":       rec.get("red_flags", ""),
                "schwesinger_full": int(rec.get("schwesinger_full", 0)),
                "schwesinger_half": int(rec.get("schwesinger_half", 0)),
                "smith_rule":      int(rec.get("smith_rule", 0)),
                "two_way_premium": int(rec.get("two_way_premium", 0)),
            }

            upsert_apex_score(
                conn,
                prospect_id=pid,
                season_id=SEASON_ID,
                model_version=MODEL_VERSION,
                apex_data=apex_data,
                apex_composite=apex_composite,
                apex_tier=apex_tier,
                pvc=pvc,
                ras_score=ras_score,
            )

            upsert_divergence_flag(
                conn,
                prospect_id=pid,
                season_id=SEASON_ID,
                model_version=MODEL_VERSION,
                apex_composite=apex_composite,
                apex_tier=apex_tier,
                apex_capital=rec.get("capital_adjusted"),
                consensus_rank=consensus_rank,
                consensus_tier=consensus_tier,
                divergence=divergence,
            )

            success_count += 1

    print()
    print(f"Complete: {success_count} written, {fail_count} failed")

    if not args.apply:
        print("\n[DRY RUN] Run with --apply 1 to write to DB.")


if __name__ == "__main__":
    main()
