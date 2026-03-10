"""
APEX v2.2 Scoring Engine — 2026 NFL Draft

Calls the Claude API to evaluate prospects across 8 trait vectors, assigns archetypes,
computes APEX composite scores, and writes results to apex_scores + divergence_flags.

Usage:
    python -m scripts.run_apex_scoring_2026 --batch calibration --apply 0|1 [--season 2026]
    python -m scripts.run_apex_scoring_2026 --batch top50      --apply 0|1 [--force]
    python -m scripts.run_apex_scoring_2026 --batch all        --apply 0|1

--batch calibration  Score 12 calibration prospects (hardcoded overrides)
--batch top50        Score top 50 by consensus rank (skips already-scored unless --force)
--batch all          (Session 5+) Score all prospects with consensus_score > 0
--apply 0            Dry run — shows what would be scored, no API calls, no DB writes
--apply 1            Full run — calls Claude API and writes to DB
--force              Re-score already-scored prospects (overrides skip logic)

CALIBRATION_OVERRIDES:
  Maps display name -> best prospect_id + correct position for PVC.
  Required because DB has duplicate bootstrap entries (position normalization artifacts).
  Each entry selects the prospect_id with the highest consensus score for that name.

TOP50_POSITION_OVERRIDES:
  Maps prospect_id -> correct APEX position for PVC lookup.
  DB position_group is unreliable (LB/OL are catch-all fallbacks).
  position_raw is used where clean; overrides applied for known LB->ILB cases and DT->IDL.

# TODO Session 5: --batch all mode — score all prospects with consensus_score > 0
# TODO Session 5: Add position-specific archetype libraries (QB, EDGE, CB, OT, S, IDL)
#   as separate prompt modules — currently using v2.2 base weights for all non-QB/ILB
# TODO Session 5: Tune system prompt based on top50 tier distribution results
# TODO Session 5: Add apex_pos_rank computation (rank within position group)
# TODO Session 5: Integrate live web search via anthropic beta web_search_20250305 tool
#   pattern: client.beta.messages.create(
#     model=..., tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
#     betas=["web-search-2025-03-05"], messages=[...]
#   )
#   Query per prospect: f"{display_name} {school} NFL draft 2026 combine stats scouting"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

# Load .env if present (for ANTHROPIC_API_KEY)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic

from draftos.db.connect import connect
from draftos.apex.engine import (
    get_pvc,
    compute_apex_composite,
    compute_apex_tier,
    compute_divergence,
)
from draftos.apex.prompts import build_system_prompt, build_user_prompt
from draftos.apex.writer import backup_once, upsert_apex_score, upsert_divergence_flag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL_VERSION  = "apex_v2.2"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"
MAX_TOKENS     = 1000
SEASON_ID      = 1
API_SLEEP_SEC  = 2   # seconds between API calls (rate limit buffer)

# ---------------------------------------------------------------------------
# Position normalization
# ---------------------------------------------------------------------------
# Raw positions that map cleanly to APEX PVC table keys (pass through as-is)
_CLEAN_POSITIONS: set[str] = {
    "QB", "CB", "EDGE", "WR", "RB", "S", "TE",
    "OT", "OG", "C", "OL",
    "ILB", "OLB", "LB",
    "IDL", "DT",
}

# Normalize raw position strings to APEX PVC table keys
_POSITION_NORM: dict[str, str] = {
    "DT":  "IDL",    # interior DL → IDL
    "DE":  "EDGE",   # legacy DE → EDGE
    "MLB": "ILB",    # middle LB → ILB
    "SLB": "OLB",    # strong-side LB → OLB
    "WLB": "OLB",    # weak-side LB → OLB
    "SS":  "S",      # strong safety
    "FS":  "S",      # free safety
    "NT":  "IDL",    # nose tackle
}


def _normalize_position(pos: str | None) -> str:
    """Apply standard position normalization. Returns 'LB' for unknown."""
    if not pos:
        return "LB"
    up = pos.upper().strip()
    return _POSITION_NORM.get(up, up)


# ---------------------------------------------------------------------------
# Top50 position overrides
# ---------------------------------------------------------------------------
# Maps prospect_id -> correct APEX position for prospects where DB data is wrong.
# Derived from position_raw column + domain knowledge of the 2026 draft class.
#
# OL entries: position_raw tells us OT / OG / C specifically.
# LB entries: known ILB prospects misclassified as generic LB.
# DT entries: normalised to IDL (already handled by _normalize_position, but
#   listed here explicitly for documentation clarity).
# ---------------------------------------------------------------------------
TOP50_POSITION_OVERRIDES: dict[int, str] = {
    # OL -> specific sub-position (from position_raw)
    18:   "OT",    # Spencer Fano      (Utah, raw=OT)
    450:  "OT",    # Francis Mauigoa   (Miami, raw=OT)
    4659: "OT",    # Francis Mauigoa   (Miami FL, dup, raw=OT)
    22:   "OG",    # Olaivavega Ioane  (Penn State, raw=OG)
    25:   "OT",    # Kadyn Proctor     (Alabama, raw=OT)
    31:   "OT",    # Monroe Freeling   (Georgia, raw=OT)
    65:   "C",     # Connor Lew        (Auburn, raw=C)
    54:   "OG",    # Chase Bisontis    (Texas A&M, raw=OG)
    29:   "OT",    # Caleb Lomu        (Utah, raw=OT)
    # DT -> IDL
    641:  "IDL",   # Peter Woods       (Clemson)
    456:  "IDL",   # Caleb Banks       (Florida)
    452:  "IDL",   # Kayden Mcdonald   (Ohio State)
    4660: "IDL",   # Kayden McDonald   (Ohio State, dup)
    # LB -> ILB for known linebacker prospects
    3:    "ILB",   # Arvell Reese      (Ohio State)
    8:    "ILB",   # Sonny Styles      (Ohio State)
    27:   "ILB",   # CJ Allen          (Georgia)
    40:   "ILB",   # Anthony Hill      (Texas)
    # LB stays LB where position is genuinely ambiguous
    26:   "LB",    # Lee Hunter        (Texas Tech)
    803:  "LB",    # R Mason Thomas    (Colorado)
}


def _resolve_position(prospect_id: int, position_group: str, position_raw: str | None) -> str:
    """
    Resolve the correct APEX position for a prospect.

    Priority:
    1. TOP50_POSITION_OVERRIDES (explicit per-prospect correction)
    2. position_raw if it's a clean, recognised position string
    3. position_group after normalization
    4. Fallback: "LB" (0.85 PVC)
    """
    if prospect_id in TOP50_POSITION_OVERRIDES:
        return TOP50_POSITION_OVERRIDES[prospect_id]

    # Try position_raw first — it's from the source CSV and usually more specific
    if position_raw:
        norm = _normalize_position(position_raw)
        if norm in _CLEAN_POSITIONS or norm in _POSITION_NORM.values():
            return norm

    return _normalize_position(position_group)


# ---------------------------------------------------------------------------
# Calibration batch — hardcoded overrides
# ---------------------------------------------------------------------------
# Maps display_name -> {prospect_id, position, school, display_name}
#
# prospect_id: best DB entry (highest consensus score) for that player name.
#   Multiple bootstrap duplicates exist per prospect due to source normalization.
#
# position: correct NFL position for PVC. Overrides DB position_group.
# school: used in prompt context for Claude's training knowledge lookup.
#
# NOTE on prospect_id selection: all 12 pids are confirmed as the best-ranked
# DB entry for each player (pre-flight verified 2026-03-10). DB consensus ranks
# are inflated (190–680) due to source coverage gaps and name normalization
# artifacts. Use CALIBRATION_KNOWN_RANKS below for correct divergence computation.
# ---------------------------------------------------------------------------
CALIBRATION_OVERRIDES: dict[str, dict] = {
    "Carson Schwesinger": {
        "prospect_id":  1464,
        "position":     "ILB",
        "school":       "UCLA",
        "display_name": "Carson Schwesinger",
    },
    "Travis Hunter": {
        "prospect_id":  885,
        "position":     "CB",
        "school":       "Colorado",
        "display_name": "Travis Hunter",
    },
    "Shedeur Sanders": {
        "prospect_id":  813,
        "position":     "QB",
        "school":       "Colorado",
        "display_name": "Shedeur Sanders",
    },
    "Armand Membou": {
        "prospect_id":  1717,
        "position":     "OT",
        "school":       "Missouri",
        "display_name": "Armand Membou",
    },
    "Tate Ratledge": {
        "prospect_id":  1254,
        "position":     "OG",
        "school":       "Georgia",
        "display_name": "Tate Ratledge",
    },
    "Gunnar Helm": {
        "prospect_id":  842,
        "position":     "TE",
        "school":       "Texas",
        "display_name": "Gunnar Helm",
    },
    "Trevor Etienne": {
        "prospect_id":  838,
        "position":     "RB",
        "school":       "Georgia",
        "display_name": "Trevor Etienne",
    },
    "Nick Emmanwori": {
        "prospect_id":  1591,
        "position":     "S",
        "school":       "South Carolina",
        "display_name": "Nick Emmanwori",
    },
    "Donovan Ezeiruaku": {
        "prospect_id":  1420,
        "position":     "EDGE",
        "school":       "Boston College",
        "display_name": "Donovan Ezeiruaku",
    },
    "Tyleik Williams": {
        "prospect_id":  1405,
        "position":     "IDL",
        "school":       "Ohio State",
        "display_name": "Tyleik Williams",
    },
    "Chris Paul": {
        "prospect_id":  916,
        "position":     "C",
        "school":       "Pittsburgh",
        "display_name": "Chris Paul Jr.",
    },
    "Jared Wilson": {
        "prospect_id":  1736,
        "position":     "C",
        "school":       "Georgia",
        "display_name": "Jared Wilson",
    },
}

CALIBRATION_PROSPECTS = list(CALIBRATION_OVERRIDES.keys())

# ---------------------------------------------------------------------------
# Known correct consensus ranks for calibration prospects.
#
# DB consensus ranks for these players are inflated (190–680) because they are
# under-covered by our 11 canonical sources and have name normalization artifacts.
# These ranks reflect real-world 2026 draft consensus boards (PFF, TDN, ESPN
# composite) as of 2026-03-10, and are used for divergence computation in
# --batch calibration runs.
#
# Format: display_name -> (known_consensus_rank, consensus_tier_approx)
# display_name must match the key in CALIBRATION_OVERRIDES.
# ---------------------------------------------------------------------------
CALIBRATION_KNOWN_RANKS: dict[str, tuple[int, str]] = {
    "Travis Hunter":      (  2,  "Elite"),
    "Shedeur Sanders":    (  5,  "Elite"),
    "Armand Membou":      ( 18,  "Strong"),
    "Donovan Ezeiruaku":  ( 19,  "Strong"),
    "Nick Emmanwori":     ( 24,  "Strong"),
    "Carson Schwesinger": ( 33,  "Strong"),
    "Tate Ratledge":      ( 48,  "Strong"),
    "Gunnar Helm":        ( 62,  "Standard"),
    "Tyleik Williams":    ( 65,  "Standard"),
    "Jared Wilson":       ( 80,  "Standard"),
    "Chris Paul":         ( 88,  "Standard"),  # display_name "Chris Paul Jr."
    "Trevor Etienne":     ( 95,  "Standard"),
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_consensus_data(conn, prospect_id: int, season_id: int) -> dict:
    """Pull consensus rank, score, and tier from prospect_consensus_rankings."""
    row = conn.execute(
        """
        SELECT consensus_rank, score, tier
        FROM prospect_consensus_rankings
        WHERE prospect_id = ? AND season_id = ?
        """,
        (prospect_id, season_id),
    ).fetchone()

    if row:
        return {
            "consensus_rank":  int(row["consensus_rank"]),
            "consensus_score": round(float(row["score"]), 2),
            "consensus_tier":  row["tier"] or "Unknown",
        }

    return {
        "consensus_rank":  9999,
        "consensus_score": 0.0,
        "consensus_tier":  "Unknown",
    }


def _get_ras_data(conn, prospect_id: int, season_id: int) -> float | None:
    """Pull RAS total from ras table. Returns None if not found."""
    row = conn.execute(
        "SELECT ras_total FROM ras WHERE prospect_id = ? AND season_id = ?",
        (prospect_id, season_id),
    ).fetchone()

    if row and row["ras_total"] is not None:
        return float(row["ras_total"])
    return None


def _is_already_scored(conn, prospect_id: int, season_id: int) -> bool:
    """Return True if this prospect already has an apex_scores row for this model."""
    n = conn.execute(
        """
        SELECT COUNT(*) FROM apex_scores
        WHERE prospect_id = ? AND season_id = ? AND model_version = ?
        """,
        (prospect_id, season_id, MODEL_VERSION),
    ).fetchone()[0]
    return n > 0


def _build_web_context(
    name:            str,
    position:        str,
    school:          str,
    consensus_rank:  int,
    consensus_score: float,
    ras_score:       float | None,
) -> str:
    """
    Build structured context string for the prospect prompt.
    Provides DB-derived data; instructs Claude to use training knowledge.

    # TODO Session 5: Integrate live web search via anthropic beta web_search tool:
    #   client.beta.messages.create(
    #       model=CLAUDE_MODEL, max_tokens=MAX_TOKENS,
    #       tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
    #       betas=["web-search-2025-03-05"],
    #       system=system_prompt,
    #       messages=[{"role": "user", "content": user_prompt}]
    #   )
    #   Search query: f"{name} {school} NFL draft 2026 combine stats scouting"
    """
    lines = [
        f"  Prospect: {name} ({position}, {school})",
        f"  DraftOS consensus rank: #{consensus_rank}  score={consensus_score:.1f}/100",
    ]

    if ras_score is not None:
        lines.append(f"  RAS (Relative Athletic Score): {ras_score:.2f}/10.00")
    else:
        lines.append("  RAS: Not yet available (pre-combine or pro day pending)")

    lines.append(
        "  Evaluate using your training knowledge: production stats, combine/pro day "
        "measurables, injury history, coaching context, and character profile."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude_api(
    client:        anthropic.Anthropic,
    system_prompt: str,
    user_prompt:   str,
) -> str:
    """Call Claude API and return raw text response. Raises on API error."""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# JSON parsing + validation
# ---------------------------------------------------------------------------

def _parse_json_response(raw: str, prospect_name: str) -> dict | None:
    """
    Parse JSON from Claude response.
    Strips accidental markdown code fences before parsing.
    Returns None on failure.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse failed for {prospect_name}: {e}")
        print(f"  [RAW response first 600 chars]:\n{raw[:600]}")
        return None


_REQUIRED_FIELDS: set[str] = {
    "prospect_name", "position", "archetype", "archetype_gap", "gap_label",
    "eval_confidence",
    "v_processing", "v_athleticism", "v_scheme_vers", "v_comp_tough",
    "v_character", "c1_public_record", "c2_motivation", "c3_psych_profile",
    "v_dev_traj", "v_production", "v_injury",
    "raw_score", "schwesinger_full", "schwesinger_half", "smith_rule",
    "tags", "strengths", "red_flags",
    "capital_base", "capital_adjusted", "two_way_premium",
}


def _validate_response(data: dict, prospect_name: str) -> bool:
    """Validate all required fields are present in parsed response."""
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        print(f"  [ERROR] Missing required fields for {prospect_name}: {sorted(missing)}")
        return False
    return True


# ---------------------------------------------------------------------------
# Per-prospect scoring pipeline
# ---------------------------------------------------------------------------

def _score_prospect(
    client:                  anthropic.Anthropic,
    conn,
    system_prompt:           str,
    name:                    str,
    override:                dict,
    season_id:               int,
    apply:                   bool,
    backed_up:               bool,
    consensus_rank_override: int | None = None,
    consensus_tier_override: str | None = None,
) -> tuple[bool, bool]:
    """
    Score a single prospect end-to-end.
    Returns (success: bool, backed_up: bool).

    consensus_rank_override: if provided, overrides the DB consensus_rank for
      both the prompt context and divergence computation. Used for calibration
      prospects whose DB ranks are inflated due to coverage/normalization issues.
    """
    prospect_id  = override["prospect_id"]
    position     = override["position"]
    school       = override["school"]
    display_name = override["display_name"]

    print(f"\n{'='*60}")
    print(f"  {display_name}  |  {position}  |  {school}")
    print(f"  prospect_id={prospect_id}  model={MODEL_VERSION}")

    consensus  = _get_consensus_data(conn, prospect_id, season_id)
    ras_score  = _get_ras_data(conn, prospect_id, season_id)

    # Apply known-correct rank override for calibration prospects.
    # DB ranks are inflated (coverage gaps + name normalization artifacts).
    if consensus_rank_override is not None:
        consensus["consensus_rank"] = consensus_rank_override
    if consensus_tier_override is not None:
        consensus["consensus_tier"] = consensus_tier_override

    print(
        f"  Consensus: rank=#{consensus['consensus_rank']}  "
        f"score={consensus['consensus_score']}  tier={consensus['consensus_tier']}"
        + (" [known override]" if consensus_rank_override is not None else "")
    )
    print(f"  RAS: {ras_score}")

    web_context = _build_web_context(
        display_name, position, school,
        consensus["consensus_rank"], consensus["consensus_score"], ras_score,
    )

    prospect_data = {
        "name":            display_name,
        "position":        position,
        "school":          school,
        "consensus_rank":  consensus["consensus_rank"],
        "consensus_tier":  consensus["consensus_tier"],
        "consensus_score": consensus["consensus_score"],
        "ras_total":       ras_score,
        "web_context":     web_context,
    }
    user_prompt = build_user_prompt(prospect_data)

    if not apply:
        print(f"  [DRY RUN] Would call Claude API for {display_name}")
        print(f"  User prompt preview:\n{user_prompt[:300]}...")
        return True, backed_up

    print(f"  Calling Claude API ({CLAUDE_MODEL}, max_tokens={MAX_TOKENS})...")
    try:
        raw = _call_claude_api(client, system_prompt, user_prompt)
    except Exception as e:
        print(f"  [ERROR] API call failed: {e}")
        return False, backed_up

    apex_data = _parse_json_response(raw, display_name)
    if apex_data is None:
        return False, backed_up

    if not _validate_response(apex_data, display_name):
        print(f"  [RAW response]:\n{raw[:400]}")
        return False, backed_up

    pvc            = get_pvc(position)
    raw_score      = float(apex_data["raw_score"])
    apex_composite = compute_apex_composite(raw_score, position)
    apex_tier      = compute_apex_tier(apex_composite)
    divergence     = compute_divergence(
        apex_composite,
        consensus["consensus_rank"],
        apex_tier,
        consensus["consensus_tier"],
    )

    print(f"  Archetype:   {apex_data.get('archetype')}")
    print(
        f"  Score:       raw={raw_score:.1f}  PVC={pvc}  "
        f"composite={apex_composite}  tier={apex_tier}"
    )
    print(
        f"  Gap:         {apex_data.get('gap_label')} "
        f"(gap={apex_data.get('archetype_gap', 0):.1f})"
    )
    print(f"  Confidence:  {apex_data.get('eval_confidence')}")
    print(f"  Tags:        {apex_data.get('tags', '') or '(none)'}")
    print(
        f"  Divergence:  {divergence['divergence_flag']} "
        f"({divergence['divergence_mag']})  score={divergence['divergence_score']}"
    )
    print(f"  Capital:     {apex_data.get('capital_adjusted')}")

    backed_up = backup_once(backed_up)

    upsert_apex_score(
        conn,
        prospect_id=prospect_id,
        season_id=season_id,
        model_version=MODEL_VERSION,
        apex_data=apex_data,
        apex_composite=apex_composite,
        apex_tier=apex_tier,
        pvc=pvc,
        ras_score=ras_score,
    )

    upsert_divergence_flag(
        conn,
        prospect_id=prospect_id,
        season_id=season_id,
        model_version=MODEL_VERSION,
        apex_composite=apex_composite,
        apex_tier=apex_tier,
        apex_capital=apex_data.get("capital_adjusted"),
        consensus_rank=consensus["consensus_rank"],
        consensus_tier=consensus["consensus_tier"],
        divergence=divergence,
    )

    print(f"  [OK] Written to DB")
    return True, backed_up


# ---------------------------------------------------------------------------
# Batch runners
# ---------------------------------------------------------------------------

def _run_calibration(
    client:        anthropic.Anthropic,
    conn,
    system_prompt: str,
    season_id:     int,
    apply:         bool,
) -> None:
    """Score all 12 calibration prospects."""
    backed_up     = False
    success_count = 0
    fail_count    = 0

    print(f"\nCalibration batch: {len(CALIBRATION_PROSPECTS)} prospects")

    for i, name in enumerate(CALIBRATION_PROSPECTS):
        override = CALIBRATION_OVERRIDES[name]

        # Use known correct consensus rank if available (DB ranks are inflated).
        known = CALIBRATION_KNOWN_RANKS.get(name)
        known_rank = known[0] if known else None
        known_tier = known[1] if known else None

        if i > 0 and apply:
            print(f"  [sleeping {API_SLEEP_SEC}s for rate limit]")
            time.sleep(API_SLEEP_SEC)

        ok, backed_up = _score_prospect(
            client, conn, system_prompt,
            name, override, season_id, apply, backed_up,
            consensus_rank_override=known_rank,
            consensus_tier_override=known_tier,
        )

        if ok:
            success_count += 1
        else:
            fail_count += 1

    print(f"\n{'='*60}")
    print(
        f"Calibration complete: {success_count} scored, {fail_count} failed"
        f"  (total={len(CALIBRATION_PROSPECTS)})"
    )


def _run_top50(
    client:        anthropic.Anthropic,
    conn,
    system_prompt: str,
    season_id:     int,
    apply:         bool,
    force:         bool,
) -> None:
    """
    Score the top 50 prospects by consensus rank.

    Skip logic: prospects already in apex_scores (same model_version) are skipped
    unless --force is passed. This makes the run resumable — safe to re-run after
    a partial failure without re-scoring already-completed prospects.
    """
    rows = conn.execute(
        """
        SELECT
            p.prospect_id,
            p.display_name,
            p.position_group,
            p.position_raw,
            p.school_canonical,
            r.consensus_rank,
            r.score     AS consensus_score,
            r.tier      AS consensus_tier
        FROM prospect_consensus_rankings r
        JOIN prospects p
          ON p.prospect_id = r.prospect_id
         AND p.season_id   = r.season_id
        WHERE r.season_id = ?
        ORDER BY r.consensus_rank ASC
        LIMIT 50
        """,
        (season_id,),
    ).fetchall()

    prospects = [dict(r) for r in rows]
    print(f"\nTop-50 batch: {len(prospects)} prospects loaded from DB")

    # Identify which are already scored
    already_scored = []
    to_score       = []
    for p in prospects:
        if not force and _is_already_scored(conn, p["prospect_id"], season_id):
            already_scored.append(p["display_name"])
        else:
            to_score.append(p)

    if already_scored:
        print(f"  Skipping {len(already_scored)} already-scored: {already_scored}")
        print("  (pass --force to re-score)")
    print(f"  Will score: {len(to_score)}")

    if not to_score:
        print("\n[COMPLETE] All top-50 prospects already scored.")
        return

    backed_up     = False
    success_count = 0
    fail_count    = 0
    skip_count    = len(already_scored)

    for i, p in enumerate(to_score):
        pid           = p["prospect_id"]
        display_name  = p["display_name"]
        position      = _resolve_position(pid, p["position_group"], p["position_raw"])
        school        = p["school_canonical"] or "Unknown"

        override = {
            "prospect_id":  pid,
            "position":     position,
            "school":       school,
            "display_name": display_name,
        }

        if i > 0 and apply:
            print(f"  [sleeping {API_SLEEP_SEC}s for rate limit]")
            time.sleep(API_SLEEP_SEC)

        ok, backed_up = _score_prospect(
            client, conn, system_prompt,
            display_name, override, season_id, apply, backed_up,
        )

        if ok:
            success_count += 1
        else:
            fail_count += 1

    print(f"\n{'='*60}")
    print(
        f"Top-50 complete: {success_count} scored, {fail_count} failed, "
        f"{skip_count} skipped (total=50)"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="APEX v2.2 Scoring Engine — 2026 NFL Draft"
    )
    parser.add_argument(
        "--batch",
        choices=["calibration", "top50", "all"],
        default="calibration",
        help="Which prospect set to score",
    )
    parser.add_argument(
        "--apply",
        type=int,
        choices=[0, 1],
        required=True,
        help="0=dry run (no API calls, no writes), 1=full run",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=2026,
        help="Draft year (default 2026)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-score already-scored prospects (top50/all batches only)",
    )
    args = parser.parse_args()

    season_id = 1 if args.season == 2026 else args.season
    apply     = bool(args.apply)

    print("=" * 60)
    print(f"APEX v2.2 Scoring Engine  |  Season {args.season}")
    print(f"Batch:   {args.batch}")
    print(f"Apply:   {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    print(f"Force:   {args.force}")
    print(f"Model:   {CLAUDE_MODEL}")
    print(f"Version: {MODEL_VERSION}")
    print("=" * 60)

    # Verify API key before any work (only required for actual runs)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if apply and not api_key:
        print("\n[ERROR] ANTHROPIC_API_KEY not set in environment.")
        print("  Windows PowerShell: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        print("  Windows permanent:  setx ANTHROPIC_API_KEY 'sk-ant-...'")
        print("  Or add to .env file in project root.")
        print()
        print("  Alternative (no API key needed):")
        print("  1. Evaluate prospects and save to a JSON file")
        print("  2. python -m scripts.import_apex_batch_json --file <path> --apply 1")
        sys.exit(1)

    client        = anthropic.Anthropic(api_key=api_key if api_key else "dry-run-no-key")
    system_prompt = build_system_prompt()

    with connect() as conn:
        if args.batch == "calibration":
            _run_calibration(client, conn, system_prompt, season_id, apply)

        elif args.batch == "top50":
            _run_top50(client, conn, system_prompt, season_id, apply, args.force)

        elif args.batch == "all":
            # TODO Session 5: implement all batch
            #   Query: SELECT from prospect_consensus_rankings
            #          WHERE season_id=? AND score > 0 ORDER BY consensus_rank ASC
            print("[TODO] --batch all not yet implemented. Use --batch top50.")
            sys.exit(1)

    if not apply:
        print(
            "\n[DRY RUN COMPLETE] "
            "Run with --apply 1 to execute API calls and DB writes."
        )


if __name__ == "__main__":
    main()
