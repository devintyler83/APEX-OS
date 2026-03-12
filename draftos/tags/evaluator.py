"""
draftos/tags/evaluator.py — Tag Rule Evaluator

Pure function library. No DB access. No side effects.

Takes a rule_expression (JSON string) and a prospect_context (dict)
and returns (passed: bool, triggered_value: str).

Never raises — all errors are caught and returned as (False, "ERROR: ...").

Usage:
    from draftos.tags.evaluator import evaluate_rule

    passed, value = evaluate_rule(rule_expression_json, ctx_dict)

Rule expression format (JSON string):
    Simple:   {"field": "ras_total", "operator": ">=", "value": 9.0}
    Compound: {"field": "ras_total", "operator": ">=", "value": 7.0,
               "and": {"field": "ras_total", "operator": "<", "value": 9.0}}

Supported operators: >=, <=, >, <, =, ==, !=
Compound logic: "and" only (recursively evaluated). "or" not yet implemented.

Field map (ctx key → DB source, populated by engine before calling this):
    ras_total                  → MAX(ras.ras_total) WHERE ras_total IS NOT NULL
    apex_archetype_gap         → apex_scores.archetype_gap
    apex_consensus_divergence  → divergence_flags.divergence_rank_delta
    trait_injury_durability    → apex_scores.v_injury
    trait_character_composite  → apex_scores.v_character
    trait_scheme_versatility   → apex_scores.v_scheme_vers
    trait_dev_trajectory       → apex_scores.v_dev_traj
    apex_composite             → apex_scores.apex_composite
    apex_tier                  → apex_scores.apex_tier
    eval_confidence            → apex_scores.eval_confidence
    consensus_rank             → prospect_consensus_rankings.consensus_rank
    translation_confidence     → derived: gap_label SOLID→3, TWEENER→2, NO_FIT→None
    floor_gates_passed         → None (schema gap — rules using this never fire)
    apex_tier_change           → None (requires historical comparison — rules never fire)
    gap_label                  → apex_scores.gap_label (display metadata for triggered_value)
"""
from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Internal: single-condition evaluation
# ---------------------------------------------------------------------------

def _eval_condition(ctx: dict[str, Any], condition: dict) -> bool:
    """
    Recursively evaluate one condition node against a context dict.

    Returns False if:
    - The required field is missing or None (no false positives on missing data)
    - The operator is unknown
    - A numeric comparison fails due to type error

    Recursively evaluates "and" sub-condition after primary passes.
    "or" is not implemented — any "or" key is ignored (reserved for future use).
    """
    field    = condition.get("field")
    operator = condition.get("operator")
    value    = condition.get("value")

    actual = ctx.get(field)

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
        return _eval_condition(ctx, and_cond)

    return True


# ---------------------------------------------------------------------------
# Internal: triggered value formatter
# ---------------------------------------------------------------------------

def _format_triggered_value(rule_name: str, ctx: dict[str, Any]) -> str:
    """Return a human-readable description of what value triggered the rule."""
    n = rule_name.lower()

    if n in ("elite_ras", "great_ras", "poor_ras"):
        v = ctx.get("ras_total")
        return f"RAS: {v:.2f}" if v is not None else "RAS: (unknown)"

    if n == "compression_flag":
        gap   = ctx.get("apex_archetype_gap")
        label = ctx.get("gap_label", "")
        return (f"Archetype Gap: {gap:.1f} ({label})" if gap is not None
                else "Archetype Gap: (unknown)")

    if n == "divergence_alert_positive":
        div = ctx.get("apex_consensus_divergence")
        return f"Divergence: +{div}" if div is not None else "Divergence: (unknown)"

    if n == "divergence_alert_negative":
        div = ctx.get("apex_consensus_divergence")
        return f"Divergence: {div}" if div is not None else "Divergence: (unknown)"

    if n == "injury_flag":
        v = ctx.get("trait_injury_durability")
        return f"Injury: {v:.1f}/10" if v is not None else "Injury: (unknown)"

    if n == "character_watch":
        v = ctx.get("trait_character_composite")
        return f"Character: {v:.1f}/10" if v is not None else "Character: (unknown)"

    if n == "scheme_dependent":
        v = ctx.get("trait_scheme_versatility")
        return f"Scheme Vers: {v:.1f}/10" if v is not None else "Scheme Vers: (unknown)"

    if n == "development_bet":
        dt  = ctx.get("trait_dev_trajectory", "?")
        tc  = ctx.get("translation_confidence", "?")
        gl  = ctx.get("gap_label", "")
        return f"Dev Traj: {dt}, TransConf: {tc} ({gl})"

    if n in ("floor_play", "possible_bust_system"):
        tier = ctx.get("apex_tier", "?")
        cr   = ctx.get("consensus_rank", "?")
        return f"Tier: {tier}, ConsensusRank: {cr}"

    if n in ("riser_tier_jump", "faller_tier_drop"):
        return f"Tier change: {ctx.get('apex_tier_change', '(unavailable)')}"

    # Fallback: return rule name as the value
    return rule_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_rule(rule_expression: str, ctx: dict[str, Any]) -> tuple[bool, str]:
    """
    Evaluate a single trigger rule against a prospect context dict.

    Args:
        rule_expression: JSON string from tag_trigger_rules.rule_expression
        ctx: Prospect context dict with rule-expression field names as keys.
             Must also contain '_rule_name' key for triggered_value formatting.
             All field values that are None or missing cause the rule to return False.

    Returns:
        (True, triggered_value_str)  if condition passes
        (False, "")                  if condition fails or field is missing
        (False, "ERROR: ...")        if rule_expression is malformed or any exception occurs

    Never raises.
    """
    try:
        condition = json.loads(rule_expression)
    except (json.JSONDecodeError, TypeError) as e:
        return False, f"ERROR: malformed rule_expression — {e}"

    try:
        passed = _eval_condition(ctx, condition)
    except Exception as e:
        return False, f"ERROR: evaluation exception — {e}"

    if not passed:
        return False, ""

    rule_name = ctx.get("_rule_name", "")
    try:
        triggered_value = _format_triggered_value(rule_name, ctx)
    except Exception as e:
        triggered_value = f"(triggered — format error: {e})"

    return True, triggered_value
