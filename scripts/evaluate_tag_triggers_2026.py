"""
evaluate_tag_triggers_2026.py — Tag Trigger Evaluation Engine (Session 18)

Evaluates all active tag_trigger_rules against scored prospects and writes
recommendations to prospect_tag_recommendations.

Reads from:  apex_scores, ras, divergence_flags, prospects, prospect_consensus_rankings
Writes to:   prospect_tag_recommendations
Scope:       is_active=1 prospects + is_calibration_artifact=0 apex_scores only
Idempotent:  INSERT OR IGNORE on UNIQUE(prospect_id, tag_def_id, rule_id)
Season:      season_id=1 (2026 draft only)

Usage:
    python -m scripts.evaluate_tag_triggers_2026 --apply 0                    # dry run
    python -m scripts.evaluate_tag_triggers_2026 --apply 1                    # write recs
    python -m scripts.evaluate_tag_triggers_2026 --apply 1 --prospect-id 449  # single

Architecture:
  - No scoring logic — reads derived data only (apex_scores, divergence_flags)
  - No UI logic — writes to DB only
  - ENGINE FIRST: this is a data layer script, not a presentation layer
  - Rules without sufficient data (apex_tier_change, floor_gates_passed) are skipped
    with a SKIP notice and zero false positives generated

Field mapping (rule_expression field → DB column):
    ras_total               → MAX(ras.ras_total) WHERE ras_total IS NOT NULL
    apex_archetype_gap      → apex_scores.archetype_gap
    apex_consensus_divergence → divergence_flags.divergence_rank_delta
    trait_injury_durability → apex_scores.v_injury
    trait_character_composite → apex_scores.v_character
    trait_scheme_versatility → apex_scores.v_scheme_vers
    trait_dev_trajectory    → apex_scores.v_dev_traj
    apex_composite          → apex_scores.apex_composite
    apex_tier               → apex_scores.apex_tier
    eval_confidence         → apex_scores.eval_confidence
    translation_confidence  → derived: gap_label SOLID→3, TWEENER→2, NO_FIT→None (skip)
    consensus_rank          → prospect_consensus_rankings.consensus_rank
    floor_gates_passed      → None — not in schema; rules using this field will not fire
    apex_tier_change        → None — requires historical comparison; rules will not fire

Unfireable rules on current data (schema gap, not errors):
    floor_play (rule 11)      — apex_tier="Solid" not in our tier set; floor_gates_passed missing
    possible_bust_system (12) — apex_tier="Archetype Miss" not in our tier set
    riser_tier_jump (13)      — apex_tier_change requires historical snapshot comparison
    faller_tier_drop (14)     — apex_tier_change requires historical snapshot comparison
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from draftos.db.connect import connect

SEASON_ID = 1
MODEL_VER  = "apex_v2.2"

# ---------------------------------------------------------------------------
# Premium positions — only actionable divergence signals
# Non-premium (ILB, OLB, OG, C, TE, RB, LB, OL) are structural PVC discounts.
# Divergence Alert rules (rule_id=5,6) only fire for these positions.
# Session 20: added to prevent non-premium noise from polluting the board weekly.
# ---------------------------------------------------------------------------
PREMIUM_POSITIONS: frozenset[str] = frozenset({"QB", "CB", "EDGE", "OT", "S"})

# ---------------------------------------------------------------------------
# translation_confidence: gap_label → numeric tier for rule 10
# SOLID → 3, TWEENER → 2, NO_FIT → None (ambiguous — skip development_bet rule)
# ---------------------------------------------------------------------------
_GAP_LABEL_TO_TRANS_CONF: dict[str, int | None] = {
    "SOLID":   3,
    "TWEENER": 2,
    "NO_FIT":  None,
}


def _translation_confidence(gap_label: str | None) -> int | None:
    if not gap_label:
        return None
    return _GAP_LABEL_TO_TRANS_CONF.get(gap_label.upper())


# ---------------------------------------------------------------------------
# Rule condition evaluator
# ---------------------------------------------------------------------------

def eval_condition(data: dict[str, Any], condition: dict) -> bool:
    """
    Recursively evaluate a rule_expression condition dict against a data dict.

    Handles simple and compound "and"-nested conditions.
    Returns False if any required field is None (no false positives on missing data).

    Operators: >=, <=, >, <, =, ==, !=
    """
    field    = condition.get("field")
    operator = condition.get("operator")
    value    = condition.get("value")

    actual = data.get(field)

    # Field not available → condition cannot be evaluated → no false positives
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
            return False  # Unknown operator — never fire
    except (TypeError, ValueError):
        return False

    if not result:
        return False

    # Recurse into compound "and" clause
    and_cond = condition.get("and")
    if and_cond:
        return eval_condition(data, and_cond)

    return True


# ---------------------------------------------------------------------------
# Triggered value formatter
# ---------------------------------------------------------------------------

def _format_triggered_value(rule_name: str, data: dict[str, Any]) -> str:
    """Return a human-readable description of what fired the rule."""
    n = rule_name.lower()
    if n == "elite_ras":
        v = data.get("ras_total")
        return f"RAS: {v:.2f}" if v is not None else "RAS: (unknown)"
    if n == "great_ras":
        v = data.get("ras_total")
        return f"RAS: {v:.2f}" if v is not None else "RAS: (unknown)"
    if n == "poor_ras":
        v = data.get("ras_total")
        return f"RAS: {v:.2f}" if v is not None else "RAS: (unknown)"
    if n == "compression_flag":
        gap = data.get("apex_archetype_gap")
        label = data.get("gap_label", "")
        return (f"Archetype Gap: {gap:.1f} ({label})" if gap is not None
                else "Archetype Gap: (unknown)")
    if n == "divergence_alert_positive":
        div = data.get("apex_consensus_divergence")
        return f"Divergence: +{div}" if div is not None else "Divergence: (unknown)"
    if n == "divergence_alert_negative":
        div = data.get("apex_consensus_divergence")
        return f"Divergence: {div}" if div is not None else "Divergence: (unknown)"
    if n == "injury_flag":
        v = data.get("trait_injury_durability")
        return f"Injury: {v:.1f}/10" if v is not None else "Injury: (unknown)"
    if n == "character_watch":
        v = data.get("trait_character_composite")
        return f"Character: {v:.1f}/10" if v is not None else "Character: (unknown)"
    if n == "scheme_dependent":
        v = data.get("trait_scheme_versatility")
        return f"Scheme Vers: {v:.1f}/10" if v is not None else "Scheme Vers: (unknown)"
    if n == "development_bet":
        dt  = data.get("trait_dev_trajectory", "?")
        tc  = data.get("translation_confidence", "?")
        gl  = data.get("gap_label", "")
        return f"Dev Traj: {dt}, TransConf: {tc} ({gl})"
    if n in ("floor_play", "possible_bust_system"):
        tier = data.get("apex_tier", "?")
        cr   = data.get("consensus_rank", "?")
        return f"Tier: {tier}, ConsensusRank: {cr}"
    if n in ("riser_tier_jump", "faller_tier_drop"):
        return f"Tier change: {data.get('apex_tier_change', '(unavailable)')}"
    return rule_name


# ---------------------------------------------------------------------------
# Prospect data loader
# ---------------------------------------------------------------------------

def _load_prospect_data(conn, season_id: int, model_ver: str,
                        prospect_id_filter: int | None = None) -> list[dict]:
    """
    Load all active scored prospects with trait data assembled for rule evaluation.

    Joins apex_scores with prospects, ras (IS NOT NULL), divergence_flags,
    and prospect_consensus_rankings.

    Returns list of data dicts keyed by rule_expression field names.
    """
    filter_clause = ""
    filter_args: list[Any] = [season_id, model_ver]
    if prospect_id_filter is not None:
        filter_clause = "AND a.prospect_id = ?"
        filter_args.append(prospect_id_filter)

    rows = conn.execute(
        f"""
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
            r.ras_total,
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
        WHERE a.season_id               = ?
          AND a.model_version           = ?
          AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
          {filter_clause}
        ORDER BY a.apex_composite DESC
        """,
        filter_args,
    ).fetchall()

    result = []
    for row in rows:
        gap_label  = (row["gap_label"] or "").upper()
        trans_conf = _translation_confidence(gap_label)

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
            # Fields not in current schema — eval_condition returns False on None
            "floor_gates_passed":        None,
            "apex_tier_change":          None,
            # Display metadata (prefixed _ to avoid collision with rule fields)
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
    """Load all active trigger rules from tag_trigger_rules."""
    rows = conn.execute(
        """
        SELECT rule_id, tag_def_id, rule_name, rule_expression
        FROM tag_trigger_rules
        WHERE is_active = 1
        ORDER BY rule_id
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
            "expression": expr,
        })
    return rules


# ---------------------------------------------------------------------------
# Rules that cannot fire on current data (documented, not errors)
# ---------------------------------------------------------------------------
_UNFIREABLE_RULES: frozenset[str] = frozenset({
    "floor_play",            # apex_tier="Solid" not in our tier set; floor_gates_passed=None
    "possible_bust_system",  # apex_tier="Archetype Miss" not in our tier set
    "riser_tier_jump",       # apex_tier_change not available (requires historical comparison)
    "faller_tier_drop",      # apex_tier_change not available (requires historical comparison)
})

# Divergence Alert rule IDs — only fire for PREMIUM_POSITIONS
_DIVERGENCE_RULE_IDS: frozenset[int] = frozenset({5, 6})


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate(conn, season_id: int, model_ver: str, apply: bool,
             prospect_id_filter: int | None = None) -> None:
    """Core evaluation loop — loads rules + prospects, fires rules, writes recs."""
    now       = datetime.now(timezone.utc).isoformat()
    rules     = _load_rules(conn)
    prospects = _load_prospect_data(conn, season_id, model_ver, prospect_id_filter)

    scope_msg = f"pid={prospect_id_filter}" if prospect_id_filter else "all active scored"
    print(f"\n  Loaded {len(rules)} active rules.")
    print(f"  Loaded {len(prospects)} prospects ({scope_msg}, is_calibration_artifact=0).")

    # --- First pass: determine which rules fire for which prospects ---
    fired:    list[tuple[dict, dict, str]] = []  # (rule, data, triggered_value)
    skipped:  set[str] = set()
    filtered: int = 0  # non-premium divergence skips

    for data in prospects:
        pos = data.get("_position_group") or ""
        for rule in rules:
            rule_name = rule["rule_name"]
            rule_id   = rule["rule_id"]

            if rule_name in _UNFIREABLE_RULES:
                skipped.add(rule_name)
                continue

            # Divergence Alert rules only fire for premium positions.
            # Non-premium APEX divergence is structural PVC discount — not actionable.
            if rule_id in _DIVERGENCE_RULE_IDS and pos not in PREMIUM_POSITIONS:
                filtered += 1
                continue

            if eval_condition(data, rule["expression"]):
                tv = _format_triggered_value(rule_name, data)
                fired.append((rule, data, tv))

    # --- Dry run output ---
    if not apply:
        by_prospect: dict[int, list[tuple[dict, str]]] = defaultdict(list)
        for rule, data, tv in fired:
            by_prospect[data["_prospect_id"]].append((rule, tv))

        print(f"\n[DRY RUN] Would fire {len(fired)} recommendations "
              f"across {len(by_prospect)} prospects.")
        print(f"  Skipped unfireable rules: {sorted(skipped)}")
        print(f"  Skipped non-premium divergence checks: {filtered} "
              f"(position not in PREMIUM_POSITIONS)")

        by_rule = Counter(r["rule_name"] for r, _, _ in fired)
        print("\n  Breakdown by rule:")
        for rname, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
            print(f"    {rname}: {cnt}")

        print()
        for pid in sorted(by_prospect.keys()):
            entries = by_prospect[pid]
            pdata   = next(d for _, d, _ in fired if d["_prospect_id"] == pid)
            pname   = pdata["_display_name"]
            ppos    = pdata["_position_group"] or "?"
            ptags   = ", ".join(f"{r['rule_name']} ({tv})" for r, tv in entries)
            print(f"  {pname} ({ppos}) pid={pid}: {ptags}")

        print(f"\n[DRY RUN COMPLETE] Run with --apply 1 to write recommendations.")
        return

    # --- Apply: INSERT OR IGNORE ---
    new_count      = 0
    existing_count = 0

    for rule, data, tv in fired:
        pid        = data["_prospect_id"]
        tag_def_id = rule["tag_def_id"]
        rule_id    = rule["rule_id"]

        exists = conn.execute(
            """
            SELECT 1 FROM prospect_tag_recommendations
            WHERE prospect_id = ? AND tag_def_id = ? AND rule_id = ?
            """,
            (pid, tag_def_id, rule_id),
        ).fetchone()

        if exists:
            existing_count += 1
            continue

        conn.execute(
            """
            INSERT OR IGNORE INTO prospect_tag_recommendations
              (prospect_id, tag_def_id, rule_id, status, triggered_value, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (pid, tag_def_id, rule_id, tv, now),
        )
        new_count += 1

    conn.commit()

    total = new_count + existing_count
    print(f"\n[OK] {total} recommendations evaluated ({new_count} new, {existing_count} already existed).")
    print(f"  Skipped unfireable rules: {sorted(skipped)}")
    print(f"  Skipped non-premium divergence checks: {filtered} "
          f"(position not in PREMIUM_POSITIONS)")

    by_rule = Counter(r["rule_name"] for r, _, _ in fired)
    print("\n  Breakdown by rule:")
    for rname, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"    {rname}: {cnt}")

    print("\n  Pending recommendations by tag name:")
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DraftOS Tag Trigger Evaluation Engine — 2026"
    )
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        required=True,
        help="0=dry run (no writes), 1=write recommendations to DB",
    )
    parser.add_argument(
        "--prospect-id",
        type=int,
        default=None,
        dest="prospect_id",
        help="Evaluate a single prospect (default: all scored prospects)",
    )
    args   = parser.parse_args()
    apply  = bool(args.apply)

    print("=" * 60)
    print("DraftOS Tag Trigger Evaluation Engine  |  Season 2026")
    print(f"Apply:  {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    if args.prospect_id:
        print(f"Filter: prospect_id={args.prospect_id}")
    print("=" * 60)

    with connect() as conn:
        evaluate(
            conn,
            season_id          = SEASON_ID,
            model_ver          = MODEL_VER,
            apply              = apply,
            prospect_id_filter = args.prospect_id,
        )


if __name__ == "__main__":
    main()
