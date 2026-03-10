"""
APEX v2.2 Scoring Engine — 2026 NFL Draft

Calls the Claude API to evaluate prospects across 8 trait vectors, assigns archetypes,
computes APEX composite scores, and writes results to apex_scores + divergence_flags.

Usage:
    python -m scripts.run_apex_scoring_2026 --batch calibration --apply 0|1 [--season 2026]

--batch calibration  Score 12 calibration prospects (hardcoded overrides)
--batch top50        (Session 4) Score top 50 by consensus rank
--batch all          (Session 4) Score all prospects with consensus_score > 0
--apply 0            Dry run — shows what would be scored, no API calls, no DB writes
--apply 1            Full run — calls Claude API and writes to DB

CALIBRATION_OVERRIDES:
  Maps display name → best prospect_id + correct position for PVC.
  Required because the DB has duplicate bootstrap entries (position normalization artifacts).
  Each entry selects the prospect_id with the highest consensus score for that name.

# TODO Session 4: --batch top50 mode — score top 50 by consensus rank
# TODO Session 4: Add position-specific archetype libraries (QB, EDGE, CB, OT, S, IDL)
#   as separate prompt modules — currently using v2.2 base weights for all non-QB/ILB
# TODO Session 4: Tune system prompt based on calibration results (tier accuracy review)
# TODO Session 4: Add apex_pos_rank computation (rank within position group)
# TODO Session 4: Integrate live web search via anthropic beta web_search_20250305 tool
#   to pull combine results, pro day data, and recent scouting reports per prospect
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
# Calibration batch — hardcoded overrides
# ---------------------------------------------------------------------------
# Maps display_name → {prospect_id, position, school, display_name}
#
# prospect_id: best DB entry for this name (highest consensus score).
#   Multiple bootstrap duplicates exist per prospect due to source CSV normalization.
#   We select the entry with the most coverage data (highest consensus score).
#
# position: correct NFL position for PVC. Overrides DB position_group, which is
#   wrong for many entries due to the known position normalization fallback issue.
#
# school: used in prompt context for Claude's training knowledge lookup.
# ---------------------------------------------------------------------------
CALIBRATION_OVERRIDES: dict[str, dict] = {
    "Carson Schwesinger": {
        "prospect_id":  1464,    # LB, rank=621, score=19.09 (best coverage entry)
        "position":     "ILB",   # DB shows LB — correct to ILB for PVC
        "school":       "UCLA",
        "display_name": "Carson Schwesinger",
    },
    "Travis Hunter": {
        "prospect_id":  885,     # CB, rank=190, score=28.72 (primary defensive side)
        "position":     "CB",    # Two-way player; CB is primary defensive position
        "school":       "Colorado",
        "display_name": "Travis Hunter",
    },
    "Shedeur Sanders": {
        "prospect_id":  813,     # QB, rank=400, score=22.84
        "position":     "QB",
        "school":       "Colorado",
        "display_name": "Shedeur Sanders",
    },
    "Armand Membou": {
        "prospect_id":  1717,    # OL, rank=210, score=28.14 (best coverage entry)
        "position":     "OT",    # DB shows OL — correct to OT for PVC
        "school":       "Missouri",
        "display_name": "Armand Membou",
    },
    "Tate Ratledge": {
        "prospect_id":  1254,    # TE(wrong pos in DB), rank=537, score=20.60 (best coverage)
        "position":     "OG",    # DB shows TE artifact — correct to OG for PVC
        "school":       "Georgia",
        "display_name": "Tate Ratledge",
    },
    "Gunnar Helm": {
        "prospect_id":  842,     # TE, rank=294, score=25.99
        "position":     "TE",
        "school":       "Texas",
        "display_name": "Gunnar Helm",
    },
    "Trevor Etienne": {
        "prospect_id":  838,     # RB, rank=680, score=18.01
        "position":     "RB",
        "school":       "Georgia",
        "display_name": "Trevor Etienne",
    },
    "Nick Emmanwori": {
        "prospect_id":  1591,    # LB, rank=441, score=22.30 (best coverage entry)
        "position":     "S",     # DB shows LB artifact — correct to S for PVC
        "school":       "South Carolina",
        "display_name": "Nick Emmanwori",
    },
    "Donovan Ezeiruaku": {
        "prospect_id":  1420,    # EDGE, rank=477, score=21.68 (best coverage entry)
        "position":     "EDGE",
        "school":       "Boston College",
        "display_name": "Donovan Ezeiruaku",
    },
    "Tyleik Williams": {
        "prospect_id":  1405,    # DT, rank=364, score=23.76
        "position":     "IDL",   # DB shows DT — normalize to IDL for PVC table
        "school":       "Ohio State",
        "display_name": "Tyleik Williams",
    },
    "Chris Paul": {
        "prospect_id":  916,     # LB, rank=425, score=22.42 (best coverage entry)
        "position":     "C",     # DB shows LB artifact — Chris Paul Jr. plays C (Pittsburgh)
        "school":       "Pittsburgh",
        "display_name": "Chris Paul Jr.",
    },
    "Jared Wilson": {
        "prospect_id":  1736,    # OL, rank=437, score=22.31
        "position":     "C",     # DB shows OL — correct to C for PVC
        "school":       "Georgia",
        "display_name": "Jared Wilson",
    },
}

CALIBRATION_PROSPECTS = list(CALIBRATION_OVERRIDES.keys())


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
    Provides DB-derived data and instructs Claude to use training knowledge.

    # TODO Session 4: Integrate live web search via anthropic beta web_search tool
    #   pattern: client.beta.messages.create(
    #       ..., tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
    #       betas=["web-search-2025-03-05"]
    #   )
    #   Query: f"{name} {school} NFL draft 2026 combine stats scouting"
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
    # Strip ```json ... ``` or ``` ... ``` fences
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
    client:        anthropic.Anthropic,
    conn,
    system_prompt: str,
    name:          str,
    override:      dict,
    season_id:     int,
    apply:         bool,
    backed_up:     bool,
) -> tuple[bool, bool]:
    """
    Score a single prospect end-to-end.
    Returns (success: bool, backed_up: bool).
    """
    prospect_id  = override["prospect_id"]
    position     = override["position"]
    school       = override["school"]
    display_name = override["display_name"]

    print(f"\n{'='*60}")
    print(f"  {display_name}  |  {position}  |  {school}")
    print(f"  prospect_id={prospect_id}  model={MODEL_VERSION}")

    # Pull DB data
    consensus  = _get_consensus_data(conn, prospect_id, season_id)
    ras_score  = _get_ras_data(conn, prospect_id, season_id)

    print(
        f"  Consensus: rank=#{consensus['consensus_rank']}  "
        f"score={consensus['consensus_score']}  tier={consensus['consensus_tier']}"
    )
    print(f"  RAS: {ras_score}")

    # Build context
    web_context = _build_web_context(
        display_name, position, school,
        consensus["consensus_rank"], consensus["consensus_score"], ras_score,
    )

    prospect_data = {
        "name":           display_name,
        "position":       position,
        "school":         school,
        "consensus_rank": consensus["consensus_rank"],
        "consensus_tier": consensus["consensus_tier"],
        "consensus_score": consensus["consensus_score"],
        "ras_total":      ras_score,
        "web_context":    web_context,
    }
    user_prompt = build_user_prompt(prospect_data)

    # Dry run — skip API call
    if not apply:
        print(f"  [DRY RUN] Would call Claude API for {display_name}")
        print(f"  User prompt preview:\n{user_prompt[:300]}...")
        return True, backed_up

    # Call Claude API
    print(f"  Calling Claude API ({CLAUDE_MODEL}, max_tokens={MAX_TOKENS})...")
    try:
        raw = _call_claude_api(client, system_prompt, user_prompt)
    except Exception as e:
        print(f"  [ERROR] API call failed: {e}")
        return False, backed_up

    # Parse JSON
    apex_data = _parse_json_response(raw, display_name)
    if apex_data is None:
        return False, backed_up

    # Validate required fields
    if not _validate_response(apex_data, display_name):
        print(f"  [RAW response]:\n{raw[:400]}")
        return False, backed_up

    # Deterministic math
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

    # Log result
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

    # Backup before first write
    backed_up = backup_once(backed_up)

    # Write to DB
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

        # Rate limit buffer between calls
        if i > 0 and apply:
            print(f"  [sleeping {API_SLEEP_SEC}s for rate limit]")
            time.sleep(API_SLEEP_SEC)

        ok, backed_up = _score_prospect(
            client, conn, system_prompt,
            name, override, season_id, apply, backed_up,
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
    args = parser.parse_args()

    season_id = 1 if args.season == 2026 else args.season
    apply     = bool(args.apply)

    print("=" * 60)
    print(f"APEX v2.2 Scoring Engine  |  Season {args.season}")
    print(f"Batch:   {args.batch}")
    print(f"Apply:   {'YES — DB writes enabled' if apply else 'DRY RUN — no writes'}")
    print(f"Model:   {CLAUDE_MODEL}")
    print(f"Version: {MODEL_VERSION}")
    print("=" * 60)

    # Verify API key before any work
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if apply and not api_key:
        print("\n[ERROR] ANTHROPIC_API_KEY not set in environment.")
        print("  Set it:   export ANTHROPIC_API_KEY=sk-ant-...")
        print("  Or add to .env file in project root.")
        sys.exit(1)

    # Use a placeholder key for dry runs (no API calls made)
    client        = anthropic.Anthropic(api_key=api_key if api_key else "dry-run-no-key")
    system_prompt = build_system_prompt()

    with connect() as conn:
        if args.batch == "calibration":
            _run_calibration(client, conn, system_prompt, season_id, apply)

        elif args.batch == "top50":
            # TODO Session 4: implement top50 batch
            #   Query: SELECT prospect_id FROM prospect_consensus_rankings
            #          WHERE season_id=? ORDER BY consensus_rank ASC LIMIT 50
            #   Resolve position from prospects table + apply position override map
            print("[TODO] --batch top50 not yet implemented. Use --batch calibration.")
            sys.exit(1)

        elif args.batch == "all":
            # TODO Session 4: implement all batch
            #   Query: SELECT prospect_id FROM prospect_consensus_rankings
            #          WHERE season_id=? AND score > 0 ORDER BY consensus_rank ASC
            print("[TODO] --batch all not yet implemented. Use --batch calibration.")
            sys.exit(1)

    if not apply:
        print(
            "\n[DRY RUN COMPLETE] "
            "Run with --apply 1 to execute API calls and DB writes."
        )


if __name__ == "__main__":
    main()
