"""
run_tag_trigger_engine_2026.py -- Automated Tag Trigger Engine (Session 22)

Deterministic engine that evaluates all active tag_trigger_rules against all
scored prospects and writes recommendations to prospect_tag_recommendations.

Replaces manual rec triage as the automation layer. After every APEX re-score
or RAS update, re-run this script to surface new recommendations.

Reads from:  apex_scores, ras, divergence_flags, prospects,
             prospect_consensus_rankings, tag_trigger_rules, tag_definitions
Writes to:   prospect_tag_recommendations (INSERT OR IGNORE -- pending rows only)
Scope:       is_active=1 prospects, is_calibration_artifact=0, season_id=1
Idempotent:  INSERT OR IGNORE on UNIQUE(prospect_id, tag_def_id, rule_id)
             Dismissed/accepted recs are NEVER overwritten.
Season:      season_id=1 (2026 draft only)

Usage:
    python -m scripts.run_tag_trigger_engine_2026 --apply 0   # dry run
    python -m scripts.run_tag_trigger_engine_2026 --apply 1   # write recs

Architecture:
  - No scoring logic -- reads derived data only (apex_scores, divergence_flags)
  - No UI logic -- writes to DB only
  - ENGINE FIRST: data layer script, not presentation layer
  - DB backup fires automatically on --apply 1
  - Rules without sufficient data (apex_tier_change, floor_gates_passed) are
    skipped cleanly -- zero false positives generated

Field mapping (rule_expression field -> DB column):
    ras_total                -> apex_scores.ras_score (primary)
                               fallback: MAX(ras.ras_total) WHERE NOT NULL
    apex_archetype_gap       -> apex_scores.archetype_gap
    apex_consensus_divergence -> divergence_flags.divergence_rank_delta
                               (model_version=apex_v2.2, season_id=1)
    trait_injury_durability  -> apex_scores.v_injury
    trait_character_composite -> apex_scores.v_character
    trait_scheme_versatility -> apex_scores.v_scheme_vers
    trait_dev_trajectory     -> apex_scores.v_dev_traj
    translation_confidence   -> derived: gap_label SOLID->3, TWEENER->2, NO_FIT->None
    apex_tier                -> apex_scores.apex_tier
    floor_gates_passed       -> None (not in schema; rule will not fire)
    apex_tier_change         -> None (requires historical comparison; will not fire)

Unfireable rules on current data (schema gap, not errors):
    floor_play (11)          -- floor_gates_passed not in schema
    possible_bust_system (12) -- apex_tier="Archetype Miss" not in our tier set
    riser_tier_jump (13)     -- apex_tier_change requires historical snapshot
    faller_tier_drop (14)    -- apex_tier_change requires historical snapshot

Divergence Alert rules (5, 6) only fire for PREMIUM_POSITIONS:
    QB, CB, EDGE, OT, S
    Non-premium APEX divergence is structural PVC discount -- not actionable.
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from draftos.config import PATHS
from draftos.db.connect import connect

SEASON_ID     = 1
MODEL_VERSION = "apex_v2.2"

# ---------------------------------------------------------------------------
# Premium positions -- divergence alerts actionable here only
# ---------------------------------------------------------------------------
PREMIUM_POSITIONS: frozenset[str] = frozenset({"QB", "CB", "EDGE", "OT", "S"})

# Divergence Alert rule IDs -- gate by position
_DIVERGENCE_RULE_IDS: frozenset[int] = frozenset({5, 6})

# Rules that cannot fire on current data (schema gap -- not errors)
_UNFIREABLE_RULES: frozenset[str] = frozenset({
    "floor_play",            # floor_gates_passed not in schema
    "possible_bust_system",  # apex_tier="Archetype Miss" not in tier set
    "riser_tier_jump",       # apex_tier_change requires historical comparison
    "faller_tier_drop",      # apex_tier_change requires historical comparison
})

# translation_confidence: gap_label -> numeric tier for development_bet rule
_GAP_LABEL_TO_TRANS_CONF: dict[str, int | None] = {
    "SOLID":   3,
    "TWEENER": 2,
    "NO_FIT":  None,
}


# ---------------------------------------------------------------------------
# DB backup
# ---------------------------------------------------------------------------

def _backup_db() -> None:
    """Back up the database before any write operation."""
    db_path  = PATHS.db
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_path = db_path.parent / f"{db_path.stem}.backup.trigger_engine_{ts}{db_path.suffix}"
    shutil.copy2(str(db_path), str(bak_path))
    print(f"  [backup] DB backed up -> {bak_path.name}")


# ---------------------------------------------------------------------------
# Rule condition evaluator
# ---------------------------------------------------------------------------

def evaluate_condition(condition: dict, field_values: dict) -> bool:
    """
    Evaluate a single condition object (including nested "and") against field_values.

    Returns True if the condition fires, False otherwise.
    If any required field is None -> False. No false positives on missing data.
    Operators: >=, <=, >, <, =, ==, !=
    """
    field    = condition.get("field")
    operator = condition.get("operator")
    value    = condition.get("value")

    actual = field_values.get(field)

    if actual is None:
        return False

    try:
        if operator in ("=", "=="):
            result = (actual == value)
        elif operator == "!=":
            result = (actual != value)
        elif operator == ">=":
            result = (float(actual) >= float(value))
        elif operator == "<=":
            result = (float(actual) <= float(value))
        elif operator == ">":
            result = (float(actual) > float(value))
        elif operator == "<":
            result = (float(actual) < float(value))
        else:
            return False  # Unknown operator -- never fire
    except (TypeError, ValueError):
        return False

    if not result:
        return False

    # Recurse into compound "and" clause
    and_cond = condition.get("and")
    if and_cond:
        return evaluate_condition(and_cond, field_values)

    return True


def _format_triggered_value(rule_name: str, data: dict[str, Any]) -> str:
    """Return a human-readable description of what fired the rule."""
    n = rule_name.lower()
    if n in ("elite_ras", "great_ras", "poor_ras"):
        v = data.get("ras_total")
        return f"RAS: {v:.2f}" if v is not None else "RAS: (unknown)"
    if n == "compression_flag":
        gap   = data.get("apex_archetype_gap")
        label = data.get("gap_label", "")
        return (f"archetype_gap: {gap:.1f} ({label})" if gap is not None
                else "archetype_gap: (unknown)")
    if n == "divergence_alert_positive":
        div = data.get("apex_consensus_divergence")
        return f"rank_delta: +{int(div)}" if div is not None else "rank_delta: (unknown)"
    if n == "divergence_alert_negative":
        div = data.get("apex_consensus_divergence")
        return f"rank_delta: {int(div):+d}" if div is not None else "rank_delta: (unknown)"
    if n == "injury_flag":
        v = data.get("trait_injury_durability")
        return f"trait_injury_durability: {v:.1f}" if v is not None else "trait_injury_durability: (unknown)"
    if n == "character_watch":
        v = data.get("trait_character_composite")
        return f"trait_character_composite: {v:.1f}" if v is not None else "trait_character_composite: (unknown)"
    if n == "scheme_dependent":
        v = data.get("trait_scheme_versatility")
        return f"trait_scheme_versatility: {v:.1f}" if v is not None else "trait_scheme_versatility: (unknown)"
    if n == "development_bet":
        dt = data.get("trait_dev_trajectory", "?")
        tc = data.get("translation_confidence", "?")
        gl = data.get("gap_label", "")
        return f"translation_confidence: {tc} ({gl}), trait_dev_trajectory: {dt}"
    if n in ("floor_play", "possible_bust_system"):
        tier = data.get("apex_tier", "?")
        cr   = data.get("consensus_rank", "?")
        return f"apex_tier: {tier}, consensus_rank: {cr}"
    if n in ("riser_tier_jump", "faller_tier_drop"):
        return f"apex_tier_change: {data.get('apex_tier_change', '(unavailable)')}"
    return rule_name


# ---------------------------------------------------------------------------
# Prospect data loader
# ---------------------------------------------------------------------------

def load_prospect_data(conn) -> list[dict]:
    """
    JOIN apex_scores + prospects + ras (fallback) + divergence_flags +
    prospect_consensus_rankings for all scored non-calibration prospects.

    Returns one dict per prospect with all evaluable fields populated (or None
    if absent). Keyed by rule_expression field names.
    """
    rows = conn.execute(
        """
        SELECT
            a.prospect_id,
            p.display_name,
            p.position_group,
            a.v_scheme_vers,
            a.v_character,
            a.v_dev_traj,
            a.v_injury,
            a.archetype_gap,
            a.gap_label,
            a.apex_composite,
            a.apex_tier,
            a.eval_confidence,
            a.matched_archetype,
            -- RAS: apex_scores.ras_score primary, fallback to ras table
            COALESCE(a.ras_score, r.ras_total) AS ras_total,
            d.divergence_rank_delta,
            c.consensus_rank
        FROM apex_scores a
        JOIN prospects p
          ON p.prospect_id = a.prospect_id
         AND p.season_id   = a.season_id
         AND p.is_active   = 1
        LEFT JOIN (
            SELECT prospect_id, MAX(ras_total) AS ras_total
            FROM ras
            WHERE ras_total IS NOT NULL
            GROUP BY prospect_id
        ) r ON r.prospect_id = a.prospect_id
        LEFT JOIN divergence_flags d
          ON d.prospect_id   = a.prospect_id
         AND d.season_id     = a.season_id
         AND d.model_version = a.model_version
        LEFT JOIN prospect_consensus_rankings c
          ON c.prospect_id = a.prospect_id
         AND c.season_id   = a.season_id
        WHERE a.season_id   = ?
          AND a.model_version = ?
          AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
        ORDER BY a.apex_composite DESC
        """,
        (SEASON_ID, MODEL_VERSION),
    ).fetchall()

    result = []
    for row in rows:
        gap_label  = (row["gap_label"] or "").upper()
        trans_conf = _GAP_LABEL_TO_TRANS_CONF.get(gap_label)

        data: dict[str, Any] = {
            # Rule-expression field names
            "ras_total":                 row["ras_total"],
            "apex_archetype_gap":        row["archetype_gap"],
            "apex_consensus_divergence": row["divergence_rank_delta"],
            "trait_injury_durability":   row["v_injury"],
            "trait_character_composite": row["v_character"],
            "trait_scheme_versatility":  row["v_scheme_vers"],
            "trait_dev_trajectory":      row["v_dev_traj"],
            "apex_composite":            row["apex_composite"],
            "apex_tier":                 row["apex_tier"],
            "eval_confidence":           row["eval_confidence"],
            "consensus_rank":            row["consensus_rank"],
            "translation_confidence":    trans_conf,
            # Schema gaps -- eval_condition returns False on None
            "floor_gates_passed":        None,
            "apex_tier_change":          None,
            # Display metadata (prefixed _ -- not rule fields)
            "_prospect_id":              row["prospect_id"],
            "_display_name":             row["display_name"],
            "_position_group":           row["position_group"],
            "_matched_archetype":        row["matched_archetype"],
            # gap_label for triggered_value formatting
            "gap_label":                 gap_label,
        }
        result.append(data)

    return result


# ---------------------------------------------------------------------------
# Rule loader
# ---------------------------------------------------------------------------

def _load_rules(conn) -> list[dict]:
    """Load all active trigger rules."""
    rows = conn.execute(
        """
        SELECT ttr.rule_id, ttr.tag_def_id, ttr.rule_name, ttr.rule_expression,
               td.tag_name
        FROM tag_trigger_rules ttr
        JOIN tag_definitions td ON td.tag_def_id = ttr.tag_def_id
        WHERE ttr.is_active = 1
        ORDER BY ttr.rule_id
        """
    ).fetchall()

    rules = []
    for row in rows:
        try:
            expr = json.loads(row["rule_expression"])
        except (json.JSONDecodeError, TypeError):
            print(f"  [WARN] Could not parse rule_expression for rule_id={row['rule_id']} "
                  f"({row['rule_name']}). Skipping.")
            continue
        rules.append({
            "rule_id":    row["rule_id"],
            "tag_def_id": row["tag_def_id"],
            "rule_name":  row["rule_name"],
            "tag_name":   row["tag_name"],
            "expression": expr,
        })
    return rules


# ---------------------------------------------------------------------------
# Existing recs loader -- for dry-run [SKIP -- EXISTS] reporting
# ---------------------------------------------------------------------------

def _load_existing_recs(conn) -> dict[tuple[int, int, int], str]:
    """
    Returns {(prospect_id, tag_def_id, rule_id): status} for all existing recs.
    """
    rows = conn.execute(
        "SELECT prospect_id, tag_def_id, rule_id, status FROM prospect_tag_recommendations"
    ).fetchall()
    return {(r["prospect_id"], r["tag_def_id"], r["rule_id"]): r["status"] for r in rows}


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

def run_engine(conn, apply: bool) -> dict:
    """
    Main evaluation loop.

    Returns summary dict:
      prospects_evaluated: int
      rules_active: int
      recs_new: int        (would insert / did insert)
      recs_skipped: int    (UNIQUE conflict -- already exists)
      null_skips: int      (rule skipped due to NULL field)
    """
    now        = datetime.now(timezone.utc).isoformat()
    rules      = _load_rules(conn)
    prospects  = load_prospect_data(conn)
    existing   = _load_existing_recs(conn)

    print(f"\n  Loaded {len(rules)} active rules.")
    print(f"  Loaded {len(prospects)} prospects (is_calibration_artifact=0).")
    print(f"  Existing recs in DB: {len(existing)}")

    # -----------------------------------------------------------------------
    # Evaluation pass
    # -----------------------------------------------------------------------
    # Each entry: (rule, data, triggered_value, already_exists_status_or_None)
    fired_new:      list[tuple[dict, dict, str]] = []
    fired_existing: list[tuple[dict, dict, str, str]] = []  # +status
    null_skips      = 0
    unfireable_seen: set[str] = set()
    non_premium_skips = 0

    for data in prospects:
        pos = data.get("_position_group") or ""
        for rule in rules:
            rule_name = rule["rule_name"]
            rule_id   = rule["rule_id"]

            if rule_name in _UNFIREABLE_RULES:
                unfireable_seen.add(rule_name)
                continue

            # Divergence Alert: premium positions only
            if rule_id in _DIVERGENCE_RULE_IDS and pos not in PREMIUM_POSITIONS:
                non_premium_skips += 1
                continue

            if not evaluate_condition(rule["expression"], data):
                # Check if it was a null-field skip or just didn't qualify
                # We count null skips by checking if the root field is None
                root_field = rule["expression"].get("field")
                if root_field and data.get(root_field) is None:
                    null_skips += 1
                continue

            tv  = _format_triggered_value(rule_name, data)
            pid = data["_prospect_id"]
            key = (pid, rule["tag_def_id"], rule_id)

            if key in existing:
                fired_existing.append((rule, data, tv, existing[key]))
            else:
                fired_new.append((rule, data, tv))

    # -----------------------------------------------------------------------
    # Dry run output
    # -----------------------------------------------------------------------
    if not apply:
        print(f"\n=== TAG TRIGGER ENGINE -- DRY RUN ===")
        print(f"Prospects evaluated: {len(prospects)}")
        print(f"Active rules: {len(rules)}")
        print()

        # Group by prospect for readable output
        by_pid_new: dict[int, list[tuple[dict, str]]] = defaultdict(list)
        for rule, data, tv in fired_new:
            by_pid_new[data["_prospect_id"]].append((rule, data, tv))

        by_pid_exist: dict[int, list[tuple[dict, str, str]]] = defaultdict(list)
        for rule, data, tv, status in fired_existing:
            by_pid_exist[data["_prospect_id"]].append((rule, data, tv, status))

        all_pids = sorted(set(list(by_pid_new.keys()) + list(by_pid_exist.keys())))

        for pid in all_pids:
            # Find display metadata
            pdata = None
            if pid in by_pid_new and by_pid_new[pid]:
                pdata = by_pid_new[pid][0][1]
            elif pid in by_pid_exist and by_pid_exist[pid]:
                pdata = by_pid_exist[pid][0][1]
            if pdata is None:
                continue
            pname = pdata["_display_name"]
            ppos  = pdata["_position_group"] or "?"

            for rule, data, tv in by_pid_new.get(pid, []):
                print(f"  [WOULD INSERT] {pname} ({ppos})")
                print(f"    Rule: {rule['rule_name']}  ->  Tag: {rule['tag_name']}")
                print(f"    triggered_value: {tv}")
                print()

            for rule, data, tv, status in by_pid_exist.get(pid, []):
                print(f"  [SKIP -- EXISTS] {pname} ({ppos})")
                print(f"    Rule: {rule['rule_name']}  ->  Tag: {rule['tag_name']}")
                print(f"    (already in recommendations table -- status: {status})")
                print()

        print(f"=== SUMMARY ===")
        print(f"New recs (would insert): {len(fired_new)}")
        print(f"Already exists (skip):   {len(fired_existing)}")
        print(f"NULL field skips:        {null_skips}")
        if unfireable_seen:
            print(f"Unfireable rules (schema gap): {sorted(unfireable_seen)}")
        print(f"Non-premium divergence skips: {non_premium_skips}")
        print()

        by_rule = Counter(r["rule_name"] for r, _, _ in fired_new)
        if by_rule:
            print("  Breakdown by rule (new only):")
            for rname, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
                print(f"    {rname}: {cnt}")

        return {
            "prospects_evaluated": len(prospects),
            "rules_active":        len(rules),
            "recs_new":            len(fired_new),
            "recs_skipped":        len(fired_existing),
            "null_skips":          null_skips,
        }

    # -----------------------------------------------------------------------
    # Apply: backup + INSERT OR IGNORE
    # -----------------------------------------------------------------------
    _backup_db()

    inserted = 0
    skipped  = 0

    for rule, data, tv in fired_new:
        pid        = data["_prospect_id"]
        tag_def_id = rule["tag_def_id"]
        rule_id    = rule["rule_id"]

        conn.execute(
            """
            INSERT OR IGNORE INTO prospect_tag_recommendations
              (prospect_id, tag_def_id, rule_id, status, triggered_value, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (pid, tag_def_id, rule_id, tv, now),
        )
        inserted += 1

    # fired_existing are all skipped (UNIQUE conflict / already actioned)
    skipped = len(fired_existing)

    conn.commit()

    total = inserted + skipped
    print(f"\n[OK] {total} rules fired total.")
    print(f"  New recs inserted: {inserted}")
    print(f"  Already existed (skip): {skipped}")
    print(f"  NULL field skips: {null_skips}")
    if unfireable_seen:
        print(f"  Unfireable rules (schema gap): {sorted(unfireable_seen)}")
    print(f"  Non-premium divergence skips: {non_premium_skips}")

    by_rule = Counter(r["rule_name"] for r, _, _ in fired_new)
    if by_rule:
        print("\n  Breakdown by rule (inserted):")
        for rname, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
            print(f"    {rname}: {cnt}")

    print("\n  Pending recommendations by tag:")
    tag_recs = conn.execute(
        """
        SELECT td.tag_name, COUNT(*) AS cnt
        FROM prospect_tag_recommendations rec
        JOIN tag_definitions td ON td.tag_def_id = rec.tag_def_id
        WHERE rec.status = 'pending'
        GROUP BY td.tag_name
        ORDER BY cnt DESC
        """
    ).fetchall()
    for row in tag_recs:
        print(f"    {row['tag_name']}: {row['cnt']}")

    return {
        "prospects_evaluated": len(prospects),
        "rules_active":        len(rules),
        "recs_new":            inserted,
        "recs_skipped":        skipped,
        "null_skips":          null_skips,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DraftOS Tag Trigger Engine -- Session 22"
    )
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        required=True,
        help="0=dry run (no writes), 1=write pending recs to DB",
    )
    args  = parser.parse_args()
    apply = bool(args.apply)

    print("=" * 60)
    print("DraftOS Tag Trigger Engine  |  Season 2026")
    print(f"Model:  {MODEL_VERSION}")
    print(f"Apply:  {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    print("=" * 60)

    with connect() as conn:
        summary = run_engine(conn, apply=apply)

    if not apply:
        print("\n[DRY RUN COMPLETE] Run with --apply 1 to write recommendations.")
    else:
        print(f"\n[DONE] Engine complete. {summary['recs_new']} new recs inserted.")


if __name__ == "__main__":
    main()
