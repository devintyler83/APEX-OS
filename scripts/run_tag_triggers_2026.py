"""
run_tag_triggers_2026.py — Tag Trigger Evaluation Engine (Session 24)

Evaluates all active tag_trigger_rules against scored prospects and writes
recommendations to prospect_tag_recommendations.

Reads from:  apex_scores, ras, divergence_flags, prospects, prospect_consensus_rankings,
             tag_trigger_rules, seasons
Writes to:   prospect_tag_recommendations
Scope:       is_active=1 prospects + is_calibration_artifact=0 apex_scores only
Idempotent:  INSERT OR IGNORE on UNIQUE(prospect_id, tag_def_id, rule_id)
             Re-running never duplicates or modifies existing rows.
             Dismissed recommendations are never re-opened.

Usage:
    python -m scripts.run_tag_triggers_2026 --apply 0                      # dry run
    python -m scripts.run_tag_triggers_2026 --apply 1                      # write recs
    python -m scripts.run_tag_triggers_2026 --apply 1 --prospect_id 449    # single prospect

Flags:
    --apply        0 = dry run (print what would fire, no writes)
                   1 = write to prospect_tag_recommendations
    --prospect_id  N  (optional) run against a single prospect_id only
    --season       draft_year, default 2026

Architecture:
    - Imports pure evaluation logic from draftos.tags.evaluator
    - This script owns DB access; evaluator.py has zero DB access
    - No scoring logic — reads derived data only (apex_scores, divergence_flags)
    - No UI logic — writes to DB only, prints to stdout
    - ENGINE FIRST: data layer only

Field mapping (rule_expression field → DB column):
    ras_total                 → MAX(ras.ras_total) WHERE ras_total IS NOT NULL
    apex_archetype_gap        → apex_scores.archetype_gap
    apex_consensus_divergence → divergence_flags.divergence_rank_delta
    trait_injury_durability   → apex_scores.v_injury
    trait_character_composite → apex_scores.v_character
    trait_scheme_versatility  → apex_scores.v_scheme_vers
    trait_dev_trajectory      → apex_scores.v_dev_traj
    apex_composite            → apex_scores.apex_composite
    apex_tier                 → apex_scores.apex_tier
    eval_confidence           → apex_scores.eval_confidence
    translation_confidence    → derived: gap_label SOLID→3, TWEENER→2, NO_FIT→None (skip)
    consensus_rank            → prospect_consensus_rankings.consensus_rank
    floor_gates_passed        → None — schema gap; rules using this field will not fire
    apex_tier_change          → None — requires historical comparison; rules will not fire

Unfireable rules on current data (documented gaps, not errors):
    floor_play (rule 11)      — apex_tier="Solid" not in tier set; floor_gates_passed missing
    possible_bust_system (12) — apex_tier="Archetype Miss" not in tier set
    riser_tier_jump (13)      — apex_tier_change requires historical snapshot comparison
    faller_tier_drop (14)     — apex_tier_change requires historical snapshot comparison
"""
from __future__ import annotations

import argparse
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.tags.evaluator import evaluate_rule

MODEL_VER = "apex_v2.2"

# ---------------------------------------------------------------------------
# Premium positions — only actionable divergence signals.
# Non-premium (ILB, OLB, OG, C, TE, RB, LB, OL) divergence is structural PVC.
# Divergence Alert rules (rule_id=5,6) only fire for these positions.
# ---------------------------------------------------------------------------
PREMIUM_POSITIONS: frozenset[str] = frozenset({"QB", "CB", "EDGE", "OT", "S"})

# Divergence Alert rule IDs — only fire for PREMIUM_POSITIONS
_DIVERGENCE_RULE_IDS: frozenset[int] = frozenset({5, 6})

# Rules that cannot fire on current data (documented, not errors)
_UNFIREABLE_RULES: frozenset[str] = frozenset({
    "floor_play",            # apex_tier="Solid" not in our tier set; floor_gates_passed=None
    "possible_bust_system",  # apex_tier="Archetype Miss" not in our tier set
    "riser_tier_jump",       # apex_tier_change not available (requires historical comparison)
    "faller_tier_drop",      # apex_tier_change not available (requires historical comparison)
})

# translation_confidence: gap_label → numeric tier for development_bet rule (rule 10)
_GAP_LABEL_TO_TRANS_CONF: dict[str, int | None] = {
    "SOLID":   3,
    "TWEENER": 2,
    "NO_FIT":  None,  # ambiguous — development_bet will not fire
}


# ---------------------------------------------------------------------------
# DB backup
# ---------------------------------------------------------------------------

def _backup_db(reason: str) -> None:
    db_path  = PATHS.db
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_dir  = db_path.parent / ".." / ".." / "exports" / "backups"
    bak_dir  = bak_dir.resolve()
    bak_dir.mkdir(parents=True, exist_ok=True)
    dst = bak_dir / f"draftos_{ts}_{reason}.sqlite"
    shutil.copy2(str(db_path), str(dst))
    print(f"  [backup] DB backed up -> {dst.name}")


# ---------------------------------------------------------------------------
# Season ID resolver
# ---------------------------------------------------------------------------

def _resolve_season_id(conn, draft_year: int) -> int:
    row = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?", (draft_year,)
    ).fetchone()
    if not row:
        raise SystemExit(f"ERROR: No season found for draft_year={draft_year}")
    return row["season_id"]


# ---------------------------------------------------------------------------
# translation_confidence helper
# ---------------------------------------------------------------------------

def _translation_confidence(gap_label: str | None) -> int | None:
    if not gap_label:
        return None
    return _GAP_LABEL_TO_TRANS_CONF.get(gap_label.upper())


# ---------------------------------------------------------------------------
# Data loaders
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
        if not row["rule_expression"]:
            print(f"  [WARN] Empty rule_expression for rule_id={row['rule_id']} "
                  f"({row['rule_name']}). Skipping.")
            continue
        rules.append({
            "rule_id":        row["rule_id"],
            "tag_def_id":     row["tag_def_id"],
            "rule_name":      row["rule_name"],
            "rule_expression": row["rule_expression"],
        })
    return rules


def _load_prospect_data(conn, season_id: int,
                        prospect_id_filter: int | None = None) -> list[dict]:
    """
    Load all active, scored, non-calibration prospects with trait data assembled
    for rule evaluation.

    Joins apex_scores with prospects, ras (ras_total IS NOT NULL), divergence_flags,
    and prospect_consensus_rankings.

    Returns list of context dicts keyed by rule_expression field names.
    Display metadata prefixed with '_' to avoid collision with rule fields.
    """
    filter_clause = ""
    filter_args: list[Any] = [season_id, MODEL_VER]
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

        ctx: dict[str, Any] = {
            # Rule-expression field names (evaluator reads these)
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
            # Schema gaps — eval returns False on None, rules never fire
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
        result.append(ctx)

    return result


# ---------------------------------------------------------------------------
# Core evaluation loop
# ---------------------------------------------------------------------------

def evaluate(conn, season_id: int, apply: bool,
             prospect_id_filter: int | None = None) -> None:
    """Load rules + prospects, fire rules, write recs (or dry-run print)."""
    now       = datetime.now(timezone.utc).isoformat()
    rules     = _load_rules(conn)
    prospects = _load_prospect_data(conn, season_id, prospect_id_filter)

    scope_msg = f"pid={prospect_id_filter}" if prospect_id_filter else "all active scored"
    print(f"\n  Loaded {len(rules)} active rules.")
    print(f"  Loaded {len(prospects)} prospects ({scope_msg}, is_calibration_artifact=0).")

    # --- Evaluation pass ---
    fired:    list[tuple[dict, dict, str]] = []  # (rule, ctx, triggered_value)
    skipped:  set[str] = set()
    filtered: int = 0   # non-premium divergence skips

    for ctx in prospects:
        pos = ctx.get("_position_group") or ""

        for rule in rules:
            rule_name = rule["rule_name"]
            rule_id   = rule["rule_id"]

            if rule_name in _UNFIREABLE_RULES:
                skipped.add(rule_name)
                continue

            # Divergence Alert rules only fire for premium positions.
            if rule_id in _DIVERGENCE_RULE_IDS and pos not in PREMIUM_POSITIONS:
                filtered += 1
                continue

            # Inject rule_name into ctx so evaluator can format triggered_value
            ctx["_rule_name"] = rule_name
            passed, triggered_value = evaluate_rule(rule["rule_expression"], ctx)

            if triggered_value.startswith("ERROR:"):
                print(f"  [WARN] rule_id={rule_id} ({rule_name}) pid={ctx['_prospect_id']}: "
                      f"{triggered_value}")
                continue

            if passed:
                fired.append((rule, ctx, triggered_value))

    # --- Dry run output ---
    if not apply:
        by_prospect: dict[int, list] = defaultdict(list)
        for rule, ctx, tv in fired:
            by_prospect[ctx["_prospect_id"]].append((rule, tv))

        print(f"\n[DRY RUN] Would fire {len(fired)} recommendations "
              f"across {len(by_prospect)} prospects.")
        print(f"  Skipped unfireable rules: {sorted(skipped)}")
        print(f"  Skipped non-premium divergence checks: {filtered}")

        by_rule = Counter(r["rule_name"] for r, _, _ in fired)
        print("\n  Breakdown by rule:")
        for rname, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
            print(f"    {rname}: {cnt}")

        print()
        pid_to_ctx = {}
        for _, ctx, _ in fired:
            pid_to_ctx.setdefault(ctx["_prospect_id"], ctx)
        for pid in sorted(by_prospect.keys()):
            entries = by_prospect[pid]
            pctx    = pid_to_ctx[pid]
            pname   = pctx["_display_name"]
            ppos    = pctx["_position_group"] or "?"
            ptags   = ", ".join(f"{r['rule_name']} ({tv})" for r, tv in entries)
            print(f"  {pname} ({ppos}) pid={pid}: {ptags}")

        print(f"\n[DRY RUN COMPLETE] Run with --apply 1 to write recommendations.")
        return

    # --- Apply: INSERT OR IGNORE ---
    new_count      = 0
    existing_count = 0

    for rule, ctx, tv in fired:
        pid        = ctx["_prospect_id"]
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

    print(f"\nProspects evaluated: {len(prospects)}")
    print(f"Rules checked: {len(rules)}")
    print(f"New recommendations written: {new_count}")
    print(f"Skipped (already existed): {existing_count}")
    print(f"  Skipped unfireable rules: {sorted(skipped)}")
    print(f"  Skipped non-premium divergence checks: {filtered}")

    by_rule = Counter(r["rule_name"] for r, _, _ in fired)
    print("\n  Breakdown by rule:")
    for rname, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"    {rname}: {cnt}")

    print("\n  Pending recommendations by tag name:")
    tag_recs = conn.execute(
        """
        SELECT td.tag_name, COUNT(*) AS cnt
        FROM prospect_tag_recommendations ptr
        JOIN tag_definitions td ON td.tag_def_id = ptr.tag_def_id
        WHERE ptr.status = 'pending'
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
        "--prospect_id",
        type=int,
        default=None,
        help="Evaluate a single prospect (default: all scored prospects)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=2026,
        help="Draft year (default: 2026)",
    )
    args  = parser.parse_args()
    apply = bool(args.apply)

    print("=" * 60)
    print("DraftOS Tag Trigger Evaluation Engine  |  Season", args.season)
    print(f"Apply:  {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    if args.prospect_id:
        print(f"Filter: prospect_id={args.prospect_id}")
    print("=" * 60)

    with connect() as conn:
        season_id = _resolve_season_id(conn, args.season)

        if apply:
            _backup_db("tag_triggers")

        evaluate(
            conn,
            season_id          = season_id,
            apply              = apply,
            prospect_id_filter = args.prospect_id,
        )


if __name__ == "__main__":
    main()
