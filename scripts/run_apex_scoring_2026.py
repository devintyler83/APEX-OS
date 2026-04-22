"""
APEX v2.3 Scoring Engine — 2026 NFL Draft

Calls the Claude API to evaluate prospects across 8 trait vectors, assigns archetypes,
computes APEX composite scores, and writes results to apex_scores + divergence_flags.

Usage:
    python -m scripts.run_apex_scoring_2026 --batch calibration --apply 0|1 [--season 2026]
    python -m scripts.run_apex_scoring_2026 --batch top50      --apply 0|1 [--force]
    python -m scripts.run_apex_scoring_2026 --batch single     --prospect_id N --apply 0|1 [--position POS] [--force]
    python -m scripts.run_apex_scoring_2026 --batch divergence --apply 0|1
    python -m scripts.run_apex_scoring_2026 --batch all        --apply 0|1

--batch calibration  Score 12 calibration prospects (hardcoded overrides)
--batch top50        Score top 50 by consensus rank (skips already-scored unless --force)
--batch single       Score one prospect by prospect_id (requires --prospect_id)
--batch divergence   Recompute divergence flags for all scored prospects (no API calls)
--batch all          (Session 5+) Score all prospects with consensus_score > 0
--apply 0            Dry run — shows what would be scored, no API calls, no DB writes
--apply 1            Full run — calls Claude API and writes to DB
--force              Re-score already-scored prospects; for single: deletes existing rows first
--prospect_id N      Prospect ID for --batch single mode
--position POS       Position override for --batch single mode (e.g. TE, ILB, QB)

CALIBRATION_OVERRIDES:
  Maps display name -> best prospect_id + correct position for PVC.
  Required because DB has duplicate bootstrap entries (position normalization artifacts).
  Each entry selects the prospect_id with the highest consensus score for that name.

TOP50_POSITION_OVERRIDES:
  Maps prospect_id -> correct APEX position for PVC lookup.
  DB position_group is unreliable (LB/OL are catch-all fallbacks).
  position_raw is used where clean; overrides applied for known LB->ILB cases and DT->IDL.

# SESSION 7 TODO: Re-score calibration + top-50 with --force after API credits restored.
# Helm (pid=842) removed from calibration — 2025 draftee, cross-season contamination.
# Run: python -m scripts.run_apex_scoring_2026 --batch calibration --force --apply 1
# Run: python -m scripts.run_apex_scoring_2026 --batch top50 --force --apply 1

# TODO Session 5: --batch all mode — score all prospects with consensus_score > 0
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
from datetime import datetime, timezone

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
MODEL_VERSION  = "apex_v2.3"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"
MAX_TOKENS     = 1000
SEASON_ID      = 1
API_SLEEP_SEC  = 2   # seconds between API calls (rate limit buffer)


def _resolve_api_key() -> str:
    """Return the Anthropic API key from env, checking canonical names in priority order."""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_APIKEY", "ANTHROPICAPIKEY"):
        val = os.environ.get(var, "")
        if val:
            return val
    return ""


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
# Position tier — premium vs. non-premium for divergence classification
# ---------------------------------------------------------------------------

PREMIUM_POSITIONS: set[str] = {"QB", "CB", "EDGE", "OT", "S"}
NON_PREMIUM_POSITIONS: set[str] = {"ILB", "OLB", "OG", "C", "TE", "RB", "IDL", "WR", "FB"}


def get_position_tier(position: str) -> str:
    """
    Return 'premium' or 'non_premium' based on PVC tier.

    Premium (QB, CB, EDGE, OT, S): divergence is actionable.
    Non-premium: APEX LOW is structural PVC behavior, not actionable.
    """
    pos = (position or "").upper().strip()
    if pos in PREMIUM_POSITIONS:
        return "premium"
    return "non_premium"


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
    # OL -> specific sub-position
    # Rebuilt Session 15: all IDs verified against current DB (post-Session 12 rebuild).
    # Previous overrides used stale pre-rebuild IDs; corrected here.
    21:   "OT",    # Chase Bisontis    (Texas A&M)
    22:   "OG",    # Francis Mauigoa   (Miami)
    23:   "OT",    # Kadyn Proctor     (Alabama)
    25:   "OT",    # Monroe Freeling   (Georgia)
    26:   "OT",    # Spencer Fano      (Utah)
    54:   "OT",    # Caleb Lomu        (Utah)
    55:   "OT",    # Emmanuel Pregnon  (Oregon)
    96:   "OT",    # Blake Miller      (Clemson)
    98:   "OG",    # Olaivavega Ioane  (Penn State)
    136:  "OG",    # Keylan Rutledge   (Georgia) — position_raw='G' not in _CLEAN_POSITIONS; added Session 37
    225:  "C",     # Connor Lew        (Auburn)
    # DT -> IDL
    75:   "IDL",   # Caleb Banks       (Florida)
    78:   "IDL",   # Kayden Mcdonald   (Ohio State)
    79:   "IDL",   # Peter Woods       (Clemson)
    # LB -> ILB for known interior/hybrid linebacker prospects
    1:    "ILB",   # Anthony Hill      (Texas)
    # 3: removed — KC Concepcion (Texas A&M) is WR, not ILB. Remediated 2026-03-15.
    4:    "ILB",   # Lee Hunter        (Texas Tech)
    5:    "ILB",   # Max Iheanachor    (Arizona State)
    6:    "TE",    # Max Klare         (Ohio State — projects as TE, not LB)
    # 7: removed S62 — R Mason Thomas PID consolidated; position_group=EDGE in DB
    8:    "ILB",   # Sonny Styles      (Ohio State)
    # 9: removed S62 — Ty Simpson PID consolidated; position_group=QB in DB
    10:   "ILB",   # Zion Young        (Missouri)
    11:   "ILB",   # Cj Allen          (Georgia)
    12:   "ILB",   # Omar Cooper       (Indiana)
    16:   "ILB",   # Arvell Reese — S71: ILB-3 mechanism confirmed; DB=EDGE is S62 consolidation artifact
    # 18: removed S62 — Gabe Jacas PID consolidated; position_group=EDGE in DB
    20:   "ILB",   # Josiah Trotter    (Missouri)
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
        "prospect_id":  1925,   # corrected Session 26 (was 1464=Jalen Catalon)
        "position":     "ILB",
        "school":       "UCLA",
        "display_name": "Carson Schwesinger",
    },
    "Travis Hunter": {
        "prospect_id":  455,    # corrected Session 26 (was 885=Travis Kelce)
        "position":     "CB",
        "school":       "Colorado",
        "display_name": "Travis Hunter",
    },
    "Shedeur Sanders": {
        "prospect_id":  230,    # corrected Session 26 (was 813=Tyler Allgeier)
        "position":     "QB",
        "school":       "Colorado",
        "display_name": "Shedeur Sanders",
    },
    "Armand Membou": {
        "prospect_id":  1371,   # corrected Session 26 (was 1717=Danny Striggow)
        "position":     "OT",
        "school":       "Missouri",
        "display_name": "Armand Membou",
    },
    "Tate Ratledge": {
        "prospect_id":  880,    # corrected Session 26 (was 1254=Logan Webb)
        "position":     "OG",
        "school":       "Georgia",
        "display_name": "Tate Ratledge",
    },
    # Gunnar Helm (pid=313) removed — 2025 draftee, cross-season contamination.
    # Ghost row introduced via spamml (TEN NFL rows) + stale PFF list. Do NOT re-score.
    "Trevor Etienne": {
        "prospect_id":  304,    # corrected Session 26 (was 838=Kaimi Fairbairn)
        "position":     "RB",
        "school":       "Georgia",
        "display_name": "Trevor Etienne",
    },
    "Nick Emmanwori": {
        "prospect_id":  1278,   # corrected Session 26 (was 1591=Jordan Clark)
        "position":     "S",
        "school":       "South Carolina",
        "display_name": "Nick Emmanwori",
    },
    "Donovan Ezeiruaku": {
        "prospect_id":  1729,   # corrected Session 26 (was 1420=Kyron Drones)
        "position":     "EDGE",
        "school":       "Boston College",
        "display_name": "Donovan Ezeiruaku",
    },
    "Tyleik Williams": {
        "prospect_id":  1050,   # corrected Session 26 (was 1405=Tj Sanders)
        "position":     "IDL",
        "school":       "Ohio State",
        "display_name": "Tyleik Williams",
    },
    "Chris Paul": {
        "prospect_id":  504,    # corrected Session 26 (was 916=Demario Douglas)
        "position":     "C",
        "school":       "Pittsburgh",
        "display_name": "Chris Paul Jr.",
    },
    "Jared Wilson": {
        "prospect_id":  1391,   # corrected Session 26 (was 1736=Ethan Downs)
        "position":     "C",
        "school":       "Georgia",
        "display_name": "Jared Wilson",
    },
}

CALIBRATION_PROSPECTS = list(CALIBRATION_OVERRIDES.keys())

# ---------------------------------------------------------------------------
# Archetype correction overrides
# ---------------------------------------------------------------------------
# Maps prospect_id -> forced archetype assignment for prospects where the batch
# API run assigned the wrong archetype. Injected into the user prompt as an
# ANALYST OVERRIDE block so the API scores against the correct weight table.
#
# Use when: post-score review identifies archetype mismatch vs. evaluation record.
# Do NOT use to nudge scores up/down — only for clear archetype family mismatches.
# ---------------------------------------------------------------------------
ARCHETYPE_OVERRIDES: dict[int, dict] = {
    # Keys rebuilt Session 15: all IDs verified against current DB (post-Session 12 rebuild).
    # Previous keys used stale pre-rebuild IDs; all 8 entries corrected here.
    16: {
        # Arvell Reese — Session 71: ILB-3 Run-First Enforcer.
        # Pipeline correction: DB=EDGE (S62 consolidation artifact). Mechanism analysis confirms ILB-3.
        # S70 scored as EDGE-4/FM-1 (wrong library). S71 gate scored as EDGE-1/FM-3 (still wrong library).
        # Correct classification: ILB-3. Run defense Blk Shed=99, Anchor=98, HitPow=97. Coverage=39.4 (structural).
        # TOP50_POSITION_OVERRIDES[16]="ILB" reinstated to route scoring against ILB library.
        "archetype_label":    "ILB-3 Run-First Enforcer",
        "archetype_rationale": (
            "Reese's primary win mechanism is run-gap enforcement via elite hand technique and anchor "
            "(Block Shedding 99, Anchor 98, Hit Power 97). YaTA 2.0, 2nd among P4 LBs — run-stopping "
            "mechanism is Tier A confirmed. 4.46 forty at 241 lbs is elite ILB athleticism "
            "(95th+ percentile at position) and scores as a competitive toughness asset, NOT a speed-arc ceiling. "
            "Coverage grade 39.4 (Zone 31, Man 53) is a structural scheme constraint — route to SchemeVers, "
            "not Processing. This is not a coverage LB with developmental upside in coverage; "
            "this is a run defender who has been correctly not deployed in coverage. "
            "Pass-rush production (22/27 pressures, 8 sacks in first 8 games) is context-dependent "
            "(QB spy, package deployment) — do not price as every-down EDGE mechanism. "
            "Primary bust risk: FM-6 (Role Mismatch) — organizations deploying him as a coverage-first "
            "ILB in a coverage-demanding scheme generate the bust from their own misread of the profile. "
            "Secondary risk: FM-3 limited (PA bite 100%, late route ID) — coverage-specific processing "
            "floor, not a positional Processing Wall. "
            "Landing spot is a mandatory capital modifier: run-first schemes (gap-sound, two-high) "
            "unlock full value; coverage-demanding schemes (Tampa 2, pattern-match heavy) structurally "
            "limit him to a rotational role regardless of run-stopping ability."
        ),
        "fm_flags": ["FM-6", "FM-3-limited"],
    },
    80: {
        "forced_archetype":  "EDGE-4 Athletic Dominator",
        "archetype_direction": (
            "Assigned archetype: EDGE-4 Athletic Dominator\n\n"
            "Rationale: Mesidor wins through superior physical tools vs. college competition. "
            "Pass rush wins are athletically generated — first-step speed and length, "
            "not hand technique or sequenced counters. Pre-snap diagnosis is reactive. "
            "Counter development is incomplete at this stage of his career. "
            "FM-1 (first-move primary) is his primary risk — counters are not yet reliable "
            "at NFL speed. Do NOT score as EDGE-3 (Power-Counter Technician) — "
            "he does not win through hand technique or leverage sequencing. "
            "Bust risk: Moderate-High (technique dependence on athleticism)."
        ),
    },
    29: {
        "forced_archetype":  "S-3 Multiplier Safety",
        "archetype_direction": (
            "Assigned archetype: S-3 Multiplier Safety\n\n"
            "Rationale: Thieneman's primary value is deployment versatility and "
            "post-snap adjustment — S-3 Multiplier Safety. S-1 Centerfielder is a "
            "secondary mechanism only. His ceiling is captured by S-3, not S-1. "
            "Score against S-3 Multiplier Safety archetype weights. "
            "Eval Confidence: Tier B — Q4 competition flag (top-25 processing confirmed "
            "in 2-3 games, not 4+ games against elite opposition; not fully cleared). "
            "Do NOT assign S-1 Centerfielder. The S-3 archetype correctly captures "
            "his hybrid deployment profile and three-level playmaking."
        ),
    },
    42: {
        "forced_archetype":  "EDGE-3 Power-Counter Technician",
        "archetype_direction": (
            "Assigned archetype: EDGE-3 Power-Counter Technician\n\n"
            "Rationale: Faulk wins through hand technique, leverage, and a three-counter "
            "sequence off his initial punch — not through converting arc speed into corner pressure. "
            "His counter package is confirmed and sequenced. Processing-led mechanism. "
            "Do NOT score as EDGE-2 — he does not win through bend or speed-to-corner. "
            "Score against EDGE-3 weights: DevTraj 12%, Processing 20% leads the table."
        ),
    },
    72: {
        "name": "Colton Hood",
        "position": "CB",
        "forced_archetype": "CB-3",
        "archetype_label": "CB-3 Press Man Corner — CB-1 Development Pathway Confirmed",
        "paa_findings": {
            "Q1": "CLEAR — 83.3 PFF coverage grade, targeted at starter volume and held up under pressure",
            "Q2": "CLEAR — man coverage confirmed at starter level, PFF 70+ in both man and zone contexts",
            "Q3": "CLEAR — held McMillan (Pick 8, 2025) to 5 catches / 38 yards in direct matchup",
            "Q4": (
                "PARTIAL CB-3 — anticipatory tendencies present and trending, but primary winning "
                "mechanism is physical press dominance, not pre-break route anticipation. CB-3 primary "
                "archetype. CB-1 development pathway confirmed as realistic ceiling trajectory."
            ),
        },
        "eval_confidence": "Tier A",
        "capital_range": "R1 Picks 16-25",
        "fm_flags": [],
        "archetype_rationale": (
            "Physical press dominance is the primary mechanism. Hood wins at the line of scrimmage "
            "through length and contact timing, not anticipatory processing. CB-1 pathway is real and "
            "trending — Q4 anticipatory signals are present — but the confirmed mechanism at this stage "
            "is CB-3. Scoring against CB-1 criteria before the pathway is confirmed produces inflated "
            "capital. CB-3 at R1 Picks 16-25 is the correct capital expression with CB-1 upside "
            "embedded in the trajectory."
        ),
    },
    71: {
        "name": "Brandon Cisse",
        "position": "CB",
        "forced_archetype": "CB-3",
        "archetype_label": "CB-3 Press Man Corner — CB-1 Development Pathway NOT Confirmed",
        "paa_findings": {
            "Q1": "CLEAR — athleticism and coverage presence confirmed at starter level",
            "Q2": "CLEAR — physical tools and press ability confirmed",
            "Q3": (
                "PARTIAL FLAG — production decline vs. elite competition. Wins against NFL-caliber "
                "WRs not confirmed at the rate required for full Q3 clear."
            ),
            "Q4": (
                "FLAG — reactive processing dominant. Pre-break route anticipation not confirmed. "
                "CB-1 pathway requires anticipatory processing — this gate does not clear. CB-3 "
                "ceiling confirmed; CB-1 pathway is speculative, not trending."
            ),
        },
        "eval_confidence": "Tier B",
        "capital_range": "R1 Picks 25-32 / Top R2",
        "fm_flags": [],
        "bust_warning": (
            "Gareon Conley pattern active. CB-3 prospects who show Q3 production decline vs. elite "
            "competition AND Q4 reactive processing flag carry elevated FM-1 (Athleticism Mirage) bust "
            "risk. Physical dominance that doesn't translate against NFL-caliber athletes is the exact "
            "FM-1 expression. Capital ceiling is hard at Picks 25-32 / Top R2 until competition "
            "performance resolves."
        ),
        "archetype_rationale": (
            "Cisse is a legitimate CB-3. The physical tools are real. The ceiling question is whether "
            "reactive processing will hold at the NFL level against route runners who can manufacture "
            "separation without needing to beat him physically. Q3 partial and Q4 flag say that question "
            "is open, not trending positive. CB-1 pathway is not confirmed and should not be priced into "
            "capital. Conley Warning is active."
        ),
    },
    38: {
        "name": "Jermod McCoy",
        "position": "CB",
        "forced_archetype": "CB-1",
        "archetype_label": "CB-1 Anticipatory Lockdown — FM-4 Medical Flag Active",
        "paa_findings": {
            "Q1": "CLEAR — production grade and assignment execution confirm CB-1 mechanism",
            "Q2": "CLEAR — man coverage dominant mechanism confirmed, anticipatory processing validated",
            "Q3": "CLEAR — competitive toughness and assignment execution vs. NFL-caliber competition confirmed",
            "Q4": "CLEAR — processing and anticipation confirmed as primary mechanism, not reactionary",
        },
        "eval_confidence": "Tier B-Conditional",
        "eval_confidence_note": (
            "Tier A mechanism. Tier B capital. Tier A only if combine medicals confirm pre-injury "
            "movement quality is intact. ACL tear January 2025, missed entire 2025 season. "
            "Injury vector HARD CAP at 6/10 — framework rule: no prospect who has missed a full "
            "season to soft tissue injury may exceed 6/10 on injury vector until two full "
            "post-injury seasons confirmed."
        ),
        "capital_range": "R1 Picks 12-22",
        "fm_flags": ["FM-4"],
        "fm_4_note": (
            "ACL tear January 2025. Full 2025 season missed. Injury vector capped at 6/10. Capital "
            "ceiling suppressed one tier from mechanism-implied range. Tier B capital is not a "
            "mechanism discount — it is an injury risk discount. If combine medicals are clean and "
            "movement quality is confirmed pre-injury level, capital range upgrades to Picks 11-20."
        ),
        "archetype_rationale": (
            "CB-1 mechanism is fully confirmed. The archetype is correct. The capital suppression is "
            "entirely FM-4 driven. Do not conflate the mechanism grade (CB-1, would otherwise be "
            "Picks 8-15 range) with the capital recommendation (suppressed to Picks 12-22 by injury "
            "floor). These are separate outputs."
        ),
    },
    35: {
        "name": "Chris Johnson",
        "position": "CB",
        "forced_archetype": "CB-2",
        "archetype_label": "CB-2 Zone Architect — Confirmed Correct",
        "paa_findings": {
            "Q1": "CLEAR — zone coverage production grade confirmed at starter level",
            "Q2": (
                "PARTIAL FLAG — man coverage real and present, but NFL-level man coverage confirmation "
                "incomplete. PAA Q2 partial means CB-1 cannot be assigned. CB-2 is the correct "
                "classification at this evidence level."
            ),
            "Q3": "CLEAR — production vs. competition confirms CB-2 mechanism",
            "Q4": "CLEAR — zone processing and pattern recognition confirmed as primary mechanism",
        },
        "eval_confidence": "Tier B",
        "capital_range": "R1 Picks 22-32 / Top R2",
        "fm_flags": [],
        "divergence_note": (
            "APEX_HIGH direction correct. +15 magnitude is slightly aggressive — +5 to +8 is the "
            "defensible range given PAA Q2 partial. The market undervaluation is real; the magnitude "
            "of the signal overstates confirmation level. Score against CB-2 criteria only."
        ),
        "archetype_rationale": (
            "CB-2 is confirmed. The API overcorrected to CB-1 when the PAA gate pushed it to confirm "
            "man coverage — PAA Q2 partial means man coverage is present and real, not that it's "
            "NFL-confirmed starter-level. CB-2 with clean Q2 would justify Picks 16-22. Q2 partial "
            "suppresses to Picks 22-32 / Top R2. APEX_HIGH is the right directional call."
        ),
    },
    3236: {
        "forced_archetype":  "CB-3 Press Man Corner",
        "archetype_direction": (
            "Assigned archetype: CB-3 Press Man Corner — CB-1 Development Pathway Confirmed\n\n"
            "Rationale: Ponds wins through physical superiority at the line — length, "
            "burst, and press dominance. His primary winning mechanism is athleticism, "
            "not spatial intelligence or zone reading. "
            "CB-1 development pathway is confirmed: technique is trending upward year-over-year, "
            "and processing is developing, but not yet Tier A confirmed against top-25 competition. "
            "The CB-1 pathway flag is a ceiling expander, not a reclassification — it signals "
            "his technique is trending toward CB-1 mechanism. "
            "Do NOT score as CB-2 Zone Architect — he is not a spatial processor reading "
            "the quarterback. CB-2 overweights scheme dependency he does not yet possess. "
            "Score against CB-3 archetype weights (Athleticism bumped to 26%). "
            "Eval Confidence: Tier B. Capital range: R1 Picks 16-32 / Early R2. "
            "Tier A (Picks 1-15) accessible if PAA Q4 processing confirmation clears. "
            "The CB-1 development pathway flag MUST appear in the archetype field or tags."
        ),
    },

    # ---------------------------------------------------------------------------
    # Session 18 overrides
    # ---------------------------------------------------------------------------

    # Jalon Kilgore — CB entry (pid=449). Re-scored as S-3 Multiplier Safety.
    # CB-3 ELITE 90.0 was a position-library error: DB position_group=CB but canonical
    # position is Safety. CB PVC=1.00 inflated the composite; S weight table is correct.
    # --position S passed at CLI to force S library. Archetype direction injected below.
    449: {
        "forced_archetype":   "S-3",
        "archetype_label":    "S-3 Multiplier Safety",
        "archetype_rationale": (
            "RAS 9.66 elite for position. CB/S dual experience creates genuine scheme versatility "
            "but S-3 post-snap adjustment is developmentally pending. Man coverage DEVELOPING — "
            "Tier B floor, not unconfirmed. Zone production is primary confirmed mechanism. "
            "Score reflects S weight table with S-3 archetype direction. "
            "Capital locked R3 until combine confirms man coverage floor."
        ),
        "eval_confidence_note": "Tier B — position ambiguity resolved to S. Post-snap: DEVELOPING.",
        "fm_flags":            ["FM-6", "FM-2"],
        "bust_warning":        (
            "FM-6 Role Mismatch primary: CB/S hybrid value requires scheme that actively deploys "
            "multiplier. Heavy man-coverage teams destroy value."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R3 base; R2 late if combine confirms man coverage floor",
        "paa_findings": {
            "Man coverage":        "DEVELOPING (not unconfirmed — Tier B floor)",
            "Post-snap adjustment": "PARTIAL — crossfield range confirmed, scripted vs genuine ambiguous",
            "SOS Gate":            "PASSES (SEC Power 4)",
            "Zone production":     "PRIMARY confirmed mechanism",
            "RAS":                 "9.66 ELITE",
        },
    },

    # Jalon Kilgore — S entry (pid=309). Sports Almanac Mode 1 S75.
    # S-3 Multiplier Safety REJECTED: processing-dominant, scheme-dependent zone centerfielder.
    # Lateral agility drag (4.32 shuttle, 45.2 agility composite) prevents man-coverage recovery.
    # FM-6 primary (scheme-dependent), FM-3 secondary. Correct archetype: S-2 Coverage Centerfielder.
    309: {
        "forced_archetype":    "S-2",
        "archetype_label":     "S-2 Coverage Centerfielder",
        "archetype_rationale": (
            "Sports Almanac Mode 1 complete S75. S-3 Multiplier Safety REJECTED. "
            "S-3 prices full-responsibility multiplier deployment — post-snap movement versatility, "
            "man-coverage floor, and blitz package participation. Kilgore does not clear S-3 on "
            "lateral agility: 4.32 shuttle (S-tier floor) and 45.2 agility composite structurally "
            "prevent man-coverage recovery against separating routes. "
            "S-2 Coverage Centerfielder is the correct archetype: processing-dominant, zone-deployed, "
            "scheme-dependent deep coverage. Zone production is the primary confirmed mechanism. "
            "FM-6 Role Mismatch is primary: scheme-dependent value requires zone-heavy/two-high "
            "deployment architecture. Commanders landing is optimal scheme fit. "
            "FM-3 Processing Wall is secondary: scheme-complexity escalation beyond confirmed "
            "zone-centerfielder responsibilities exposes processing floor. "
            "Capital: R2 Late base. Source coverage gap (consensus #89) reflects CB/S normalization "
            "artifact from S62 consolidation — not a quality discount."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R2 Late (Commanders optimal) — R3 base all other fits",
        "fm_flags":            ["FM-6 Role Mismatch (primary)", "FM-3 Processing Wall (secondary)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-6 Role Mismatch primary: S-2 value is scheme-dependent. Zone-heavy/two-high "
            "deployment unlocks value; man-heavy or press-dominant schemes structurally limit "
            "to backup role. Lateral agility drag (4.32 shuttle) prevents man-coverage recovery. "
            "FM-3 secondary: complexity escalation beyond confirmed zone responsibilities exposes floor."
        ),
        "paa_findings": {
            "Zone_production":       "PRIMARY confirmed mechanism — deep coverage dominant",
            "Man_coverage_gate":     "PARTIAL — 4.32 shuttle is S-tier floor; man recovery structurally limited",
            "Lateral_agility":       "DRAG — 4.32 shuttle + 45.2 agility composite prevent man-coverage ceiling",
            "Speed_gate":            "CLEAR — forty 4.40 sub-4.50 threshold",
            "Explosiveness":         "ELITE — 37in vertical, 10ft-10in broad",
            "S3_rejected":           "Multiplier deployment (man-coverage + blitz package) requires agility Kilgore does not have",
            "FM_primary":            "FM-6 Role Mismatch — zone-heavy/two-high deployment required",
            "FM_secondary":          "FM-3 Processing Wall — scheme-complexity-conditional",
            "Archetype_lock":        "S-2 Coverage Centerfielder confirmed S75",
        },
    },

    # Kyron Drones — QB (pid=1420). Documentation override only — no API re-score warranted.
    # Already re-scored Session 15 to QB-5 49.1 DAY3 after contaminated vector corrected.
    # This entry documents the eval rationale and freeze conditions for future reference.
    # Do NOT re-score until combine RAS confirms elite athleticism threshold.
    1420: {
        "forced_archetype":   "QB-5",
        "archetype_label":    "QB-5 Raw Projection",
        "archetype_rationale": (
            "Athletic-first QB whose mobility exceeds current processing and scheme familiarity. "
            "SAA Gate: probable trigger — VT offense was run-first, short-area design. "
            "Processing unconfirmed at NFL complexity. Transfer history (WVU→VT) noted, not flagged. "
            "Wide consensus variance (25% coverage) reflects genuine scout disagreement on processing. "
            "No APEX re-score warranted until combine RAS confirms elite athleticism threshold."
        ),
        "eval_confidence":     "Tier C",
        "capital_range":       "R6-R7 / UDFA",
        "fm_flags":            ["FM-3", "FM-2"],
        "bust_warning":        (
            "FM-3 Processing Wall primary: athletic-first QBs who cannot develop NFL pre-snap "
            "diagnosis stall at practice squad. Combine threshold: sub-4.45 + 130+ Burst Score "
            "required before any capital investment."
        ),
        "eval_confidence_note": (
            "Tier C — SAA probable, processing unconfirmed, wide variance consensus. "
            "Do not re-score until combine data available."
        ),
    },

    # ---------------------------------------------------------------------------
    # Session 20 overrides
    # ---------------------------------------------------------------------------

    # Jeremiyah Love — RB (pid=61). GEN score 59.8 DAY2 — API re-score pending.
    # Local weight-table matched RB-1 correctly. API re-score needed to replace GEN
    # trait vectors with real evaluated scores. RB-3 secondary layer documented here.
    # FM-6 elevated to co-primary with FM-4. SOS-ELITE confirmed.
    # Carry Accumulation Clock volume audit must be run before finalizing FM-4 tier.
    61: {
        "name":          "Jeremiyah Love",
        "position":      "RB",
        "forced_archetype": "RB-1",
        "archetype_label":  "RB-1 Elite Workhorse — RB-3 Secondary Layer Active",
        "paa_findings": {
            "SOS Gate": (
                "CLEAR — ELITE tier. Michigan, Georgia, playoff field. Production held "
                "against top-15 defense quality. SOS-ELITE is the highest confirmation "
                "tier. Do NOT apply SOS discount."
            ),
            "Three-Down Mechanism": (
                "CLEAR — pass protection confirmed vs. Power 4 edge rushers at starter "
                "volume. Receiving is genuine (route tree, not schemed flare routes). "
                "Power/speed balance places him in top tier of 2026 RB class. "
                "RB-1 three-down mechanism is the confirmed primary archetype."
            ),
            "RB-3 Secondary Layer": (
                "ACTIVE — elite burst and acceleration are present as a secondary mechanism. "
                "Home-run threat ability is real and above-average for RB-1 profiles. "
                "Do NOT reclassify to RB-3 primary — the workhorse mechanism leads. "
                "RB-3 traits expand ceiling and inform v_athleticism scoring upward. "
                "Score v_athleticism toward upper range; both RB-1 and RB-3 share the "
                "25% Athleticism bump — apply it."
            ),
            "Carry Accumulation Clock": (
                "CLEAR — ~479 college carries (2022-2024). "
                "Below 500-carry FM-4 threshold. v_injury hard cap lifted. "
                "Score v_injury at 9.0."
            ),
        },
        "eval_confidence": "Tier A",
        "capital_range":   "R2 top | Floor: R2 late | Ceiling: R1 late (thin-class market)",
        "fm_flags":        ["FM-6", "FM-4"],
        "fm_6_note": (
            "FM-6 Role Mismatch is CO-PRIMARY with FM-4 — not secondary. "
            "FM-6 is the higher-probability bad outcome at R2 capital for a PVC=0.70 player: "
            "landing in a pass-heavy committee system destroys the three-down deployment that "
            "makes RB-1 value actionable at this capital. "
            "Best fits: KC, PHI, DET, BAL — organizations with volume deployment and design "
            "touches that multiply RB-1 value. "
            "Worst fits: pass-heavy committee systems (NE historical, LAR historical pattern). "
            "The FM-6 bust scenario produces underperformance at high draft capital — which "
            "for a PVC=0.70 position is the more likely bad outcome than FM-4 career end."
        ),
        "fm_4_note": (
            "FM-4 Body Breakdown is CO-PRIMARY with FM-6. Position-structural risk for any "
            "3-down RB drafted at R2 capital. Injury vector score is contingent on the "
            "Carry Accumulation Clock audit (see paa_findings). If 2022+2023+2024 Notre Dame "
            "carries exceed high-risk threshold, v_injury is hard-capped and FM-4 risk "
            "tier elevates to primary. Score v_injury no higher than 8.0 pending audit. "
            "FM-4 ends careers; FM-6 produces underperformance — both are relevant here."
        ),
        "bust_warning": (
            "Dual primary failure mode: FM-6 (role mismatch — wrong system destroys value "
            "at draft capital) + FM-4 (body breakdown — position-structural, carry volume "
            "audit pending). Either alone at R2 capital produces a bust outcome. "
            "FM-6 is the higher-probability event — market will price the athlete, not the "
            "deployment fit. FM-4 becomes dominant if carry volume audit flags. "
            "Resolve carry audit before finalizing capital recommendation."
        ),
        "archetype_rationale": (
            "RB-1 Elite Workhorse is the confirmed primary archetype. Three-down mechanism "
            "is real: pass protection, genuine receiving (route tree), power/speed balance "
            "at top-of-class level. SOS-ELITE (Michigan, Georgia, playoff field) confirms "
            "the mechanism is not a product-of-competition artifact. "
            "RB-3 Explosive Playmaker traits are present as a secondary layer — elite burst, "
            "home-run threat — but the primary winning mechanism is the workhorse profile, "
            "not the explosive play profile. Score against RB-1 weight table with 25% "
            "Athleticism bump applied (shared by RB-1 and RB-3). PVC=0.70 is structural "
            "and correct. Do not suppress the composite below what the mechanism earns."
        ),
    },

    # ---------------------------------------------------------------------------
    # Session 29 overrides
    # ---------------------------------------------------------------------------

    # Kamari Ramsey — S (pid=148). PAA confirmed S-3 Multiplier Safety (Developing).
    # Session 26 scored S-1 Centerfielder 61.2 DAY2. S-1 is incorrect — processing
    # profile (7.0) does not support Centerfielder mechanism. Zone-dominant production
    # is the confirmed primary mechanism. S-3 is the correct archetype.
    148: {
        "forced_archetype":    "S-3 Multiplier Safety",
        "archetype_direction": (
            "S-3 Multiplier Safety (Developing). PAA complete. "
            "Zone-dominant production confirmed. Man coverage floor PARTIAL — "
            "functional but not tested at volume vs. elite competition. "
            "Post-snap assignment adjustment DEVELOPING — not confirmed. "
            "SOS gate PASSED. Do NOT assign S-1 Centerfielder — processing "
            "profile (7.0) does not support that mechanism. "
            "S-3 is the correct archetype. Capital: R3. Eval confidence: Tier B."
        ),
        "archetype_rationale": "PAA-confirmed S-3. Zone-first mechanism. Processing developing.",
        "eval_confidence":     "Tier B",
        "capital_range":       "R3",
        "fm_flags":            ["FM-2 Scheme Ghost (primary)", "FM-3 Processing Wall (secondary)"],
    },

    # ---------------------------------------------------------------------------
    # Session 5 (scoring expansion) overrides
    # ---------------------------------------------------------------------------

    # Davison Igbinosun — CB (pid=36). Sports Almanac Mode 1 S75.
    # CB-3 Press Man Corner REJECTED (supersedes prior PAA override): zone-processing elite but
    # athleticism is a structural floor (4.7/10), not a ceiling variable. Elite size does not
    # substitute for functional athleticism. FM-2 Scheme Ghost primary (Ohio State zone
    # architecture amplifying production). Correct archetype: CB-2 Zone Coverage Technician.
    36: {
        "forced_archetype":    "CB-2",
        "archetype_label":     "CB-2 Zone Coverage Technician",
        "archetype_rationale": (
            "Sports Almanac Mode 1 complete S75. CB-3 Press Man Corner REJECTED — "
            "supersedes prior PAA override. Zone-processing is elite (8.6/10) and is the "
            "confirmed primary win mechanism. Athleticism is a structural floor: 4.7/10 composite, "
            "vertical jump 22.1 (bottom-5 pct at CB), broad jump 20.8 (bottom-3 pct at CB). "
            "Elite size (height 92.2 pct, arm 89.9 pct, wingspan 88.3 pct) does not substitute "
            "for functional athleticism — size provides contest radius, not recovery speed. "
            "CB-3 press dominance requires functional explosion and recovery, which Igbinosun does "
            "not demonstrate in jump metrics. CB-2 Zone Coverage Technician correctly captures the "
            "confirmed mechanism: elite zone processing, structural athleticism floor. "
            "FM-2 Scheme Ghost is primary: Ohio State zone architecture amplified production — "
            "zone-heavy deployment required at NFL level to replicate college output. "
            "FM-3 Processing Wall is secondary: athleticism floor creates scheme-dependency "
            "that cascades if zone processing encounters NFL route complexity. "
            "FM-6 Role Mismatch tertiary: misdeployment in press-man or off-man schemes "
            "exposes athleticism floor directly. "
            "Capital: R4 Early base. Steelers zone deployment is the R3 Early context ceiling — "
            "scheme fit is the single capital lever."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R4 Early (base) — R3 Early ceiling (Steelers zone fit only)",
        "fm_flags":            ["FM-2 Scheme Ghost (primary)", "FM-3 Processing Wall (secondary)", "FM-6 Role Mismatch (tertiary)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-2 Scheme Ghost primary: zone processing is elite but Ohio State zone architecture "
            "may be amplifying production. NFL zone-heavy deployment required — press-man or "
            "off-man schemes expose athleticism floor immediately. "
            "Athleticism floor (VJ 22.1 bottom-5 pct, BJ 20.8 bottom-3 pct) is structural, "
            "not developmental. Size does not cover for explosion deficiency against NFL athletes."
        ),
        "paa_findings": {
            "Zone_processing":       "ELITE — 8.6/10 confirmed primary mechanism",
            "Athleticism":           "STRUCTURAL FLOOR — 4.7/10; VJ 22.1 (bottom-5 pct), BJ 20.8 (bottom-3 pct)",
            "Size":                  "ELITE — height 92.2 pct, arm 89.9 pct, wing 88.3 pct; does NOT substitute for athleticism",
            "CB3_rejected":          "Press dominance requires functional explosion; jump metrics disqualify",
            "FM_primary":            "FM-2 Scheme Ghost — Ohio State zone architecture; zone-heavy deployment required",
            "FM_secondary":          "FM-3 Processing Wall — athleticism floor creates scheme-dependency cascade",
            "FM_tertiary":           "FM-6 Role Mismatch — press-man/off-man misdeployment exposes floor",
            "Capital_ceiling":       "R3 Early (Steelers zone fit) — R4 Early base all other fits",
            "Archetype_lock":        "CB-2 Zone Coverage Technician confirmed S75",
        },
    },

    # Julian Neal — CB (pid=109). S64 3-cone gate injection.
    # Gate doctrine (S39): sub-6.9s = R2 ceiling clear; above 6.9s = R3 cap fires.
    # 3-cone = 7.13s confirmed. Gate FIRES. R3 capital cap applies.
    109: {
        "gate_three_cone":           7.13,
        "gate_three_cone_threshold": 6.90,
        "gate_three_cone_result":    "FAIL",
        "gate_capital_cap":          "R3",
        "archetype_rationale": (
            "S64 3-cone gate injection. 3-cone = 7.13s (ABOVE 6.90 threshold). "
            "Gate FIRES per S39 doctrine. R3 capital cap applies. "
            "Neal wins as CB-2 Zone Architect through anticipatory read-and-react zone coverage "
            "and spatial awareness — the 3-cone result is mechanically consistent: "
            "he is a zone-first processor, not an elite man-coverage hip-flipper. "
            "7.13s 3-cone narrows his ceiling — he cannot credibly play press-man at the "
            "next level without elite COD recovery. Capital ceiling: R3 top, not R2. "
            "Score against CB-2 Zone Architect weights. Reduce capital expectation from "
            "pre-gate R2 base to post-gate R3 ceiling. "
            "Consensus #66 (13 sources) — APEX_HIGH signal should reflect gate-adjusted capital."
        ),
        "eval_confidence":    "Tier B",
        "paa_findings": {
            "Three_cone_gate":       "FAIL — 7.13s > 6.90 threshold; R3 cap fires (S39 doctrine)",
            "Man_coverage_floor":    "CONCERN — 7.13s 3-cone inconsistent with elite press-man alignment",
            "Zone_mechanism":        "CONFIRMED — CB-2 Zone Architect; spatial anticipation primary",
            "Capital_gate":          "R3 ceiling confirmed — R2 upgrade path closed by 3-cone gate",
            "Archetype_consistency": "CB-2 Zone Architect is gate-consistent (zone-first, not man-first)",
        },
        "capital_range":      "R3 top (3-cone gate fired S64 — R2 ceiling closed)",
        "fm_flags":           ["FM-2"],
        "bust_warning": (
            "FM-2 Scheme Ghost primary: CB-2 value requires zone-heavy deployment. "
            "3-cone 7.13s removes man-coverage utility — heavy man scheme = floor player. "
            "Capital ceiling R3 hard gate."
        ),
    },

    # ---------------------------------------------------------------------------
    # Session 75 overrides
    # ---------------------------------------------------------------------------

    # Malik Muhammad — CB (pid=13). Sports Almanac Mode 1 + Mode 2 S75.
    # CB-3 Press Man Corner REJECTED: processing-primary, scheme-versatile outside corner.
    # Elite size (arm 80.0, wing 77.4), 8.4/10 processing, 8.1/10 scheme versatility.
    # Production (49.5) confirmed schedule-suppressed via Gardner 2022 comp — adjusted 56-62 Y1.
    # No FM at archetype level. FM-6 contingent (slot misdeployment). Capital R2 Early.
    13: {
        "forced_archetype":    "CB-1",
        "archetype_label":     "CB-1 Outside Press Cornerback",
        "archetype_rationale": (
            "Sports Almanac Mode 1 + Mode 2 complete S75. CB-3 Press Man Corner REJECTED. "
            "Muhammad wins through processing-primary mechanism: elite anticipatory processing "
            "(8.4/10) and scheme versatility (8.1/10) confirm CB-1 Outside Press Cornerback. "
            "Elite size package (arm 80.0 pct, wingspan 77.4 pct) provides physical confirmation "
            "of CB-1 press mechanism at the line. "
            "Production (49.5) is confirmed schedule-suppressed — Gardner 2022 comp analysis "
            "indicates adjusted Year 1 production of 56-62, resolving the production gap. "
            "No failure mode at archetype level. FM-6 Role Mismatch is contingent: slot "
            "misdeployment destroys value but is not a structural risk at all landing spots. "
            "Capital: R2 Early. R1 Late ceiling if Texas opponent film confirms CB-1 mechanism "
            "against elite competition."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R2 Early — R1 Late ceiling (Texas opponent film gate)",
        "fm_flags":            ["FM-6 Role Mismatch (contingent — slot misdeployment only)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-6 contingent: slot misdeployment destroys CB-1 value — outside corner mechanism "
            "does not translate to slot. Production schedule-suppression discount confirmed resolved "
            "via Gardner 2022 comp. R1 Late ceiling requires opponent film confirmation."
        ),
        "paa_findings": {
            "Processing":            "ELITE — 8.4/10 anticipatory processing confirmed",
            "Scheme_versatility":    "ELITE — 8.1/10 confirmed",
            "Size":                  "ELITE — arm 80.0 pct, wing 77.4 pct; CB-1 press confirmation",
            "Production_adjustment": "CONFIRMED schedule-suppressed — Gardner 2022 comp; adjusted 56-62 Y1",
            "CB3_rejected":          "Processing-primary mechanism confirms CB-1, not athletic-primary CB-3",
            "FM_contingent":         "FM-6 Role Mismatch — slot misdeployment only; not structural",
            "Capital_ceiling":       "R1 Late (opponent film gate) — R2 Early base",
            "Archetype_lock":        "CB-1 Outside Press Cornerback confirmed S75",
        },
    },

    # Daylen Everette — CB (pid=107). Sports Almanac Mode 1 S75.
    # CB-3 Press Man Corner REJECTED: athlete-first, man-coverage dominant.
    # Athleticism 9.1/10 (elite) but processing 6.8/10 and scheme versatility 4.2/10 are dual
    # constraints. Production (40.7) accurate — not schedule-suppressed, reflects real ceiling.
    # FM-3 Processing Wall primary, FM-6 secondary. Capital R2 Mid.
    107: {
        "forced_archetype":    "CB-2",
        "archetype_label":     "CB-2 Outside Man-Coverage Corner",
        "archetype_rationale": (
            "Sports Almanac Mode 1 complete S75. CB-3 Press Man Corner REJECTED. "
            "Everette wins through athlete-first man-coverage mechanism — athleticism 9.1/10 "
            "is elite and is the confirmed primary win driver. "
            "Processing 6.8/10 and scheme versatility 4.2/10 are dual confirmed constraints: "
            "CB-3 requires scheme-reading and press technique as primary mechanisms, not "
            "athleticism as the primary driver. CB-2 Outside Man-Coverage Corner correctly "
            "captures the athlete-led man-coverage profile. "
            "Production (40.7) is accurate — not schedule-suppressed, reflects real ceiling. "
            "FM-3 Processing Wall is primary: processing 6.8/10 creates scheme-complexity "
            "ceiling at NFL pace — route combinations that require pre-break anticipation "
            "will create exploitable windows. "
            "FM-6 Role Mismatch is secondary: zone-heavy deployments expose the processing "
            "constraint structurally. "
            "Capital: R2 Mid. Miami landing suppresses FM-3 (man-coverage system); "
            "Chiefs/Jets landing elevates both FM-3 and FM-6 risk."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R2 Mid — Miami suppresses FM-3; Chiefs/Jets elevate risk",
        "fm_flags":            ["FM-3 Processing Wall (primary)", "FM-6 Role Mismatch (secondary)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-3 Processing Wall primary: processing 6.8/10 creates exploitable windows against "
            "route combinations requiring pre-break anticipation at NFL pace. "
            "FM-6 secondary: zone deployments structurally expose the processing constraint. "
            "Production (40.7) is the real ceiling — not suppressed, not expandable via scheme fix."
        ),
        "paa_findings": {
            "Athleticism":           "ELITE — 9.1/10; confirmed primary win mechanism",
            "Processing":            "CONSTRAINT — 6.8/10; pre-break anticipation limited",
            "Scheme_versatility":    "CONSTRAINT — 4.2/10; man-coverage specialist only",
            "Production":            "ACCURATE — 40.7; not schedule-suppressed, reflects real ceiling",
            "CB3_rejected":          "CB-3 requires scheme-reading primary; Everette is athleticism-primary",
            "FM_primary":            "FM-3 Processing Wall — scheme-complexity ceiling at NFL pace",
            "FM_secondary":          "FM-6 Role Mismatch — zone deployments expose processing constraint",
            "Capital_modifier":      "Miami (man-heavy) suppresses FM-3; Chiefs/Jets compound both",
            "Archetype_lock":        "CB-2 Outside Man-Coverage Corner confirmed S75",
        },
    },

    # Genesis Smith — S (pid=147). Sports Almanac Mode 1 S75.
    # S-3 archetype confirmed correct but multiplier weights inflating composite.
    # Coverage elite (deep zone 93, catch point 85, VJ 98.0 pct) but run defense catastrophic
    # (tackling 14, run defense 25.4, motor 17, 20.1% missed tackle rate).
    # FM-5 Motivation Cliff primary (effort-dependent run support). Capital R4 Late pending triage.
    147: {
        "forced_archetype":    "S-3",
        "archetype_label":     "S-3 Multiplier Safety — FM-5 Active",
        "archetype_rationale": (
            "Sports Almanac Mode 1 complete S75. S-3 Multiplier Safety archetype is confirmed "
            "correct but multiplier weights are inflating composite by pricing full-responsibility "
            "contribution that tape does not support. "
            "Coverage is elite: deep zone 93, catch point 85, vertical jump 98.0 pct (ELITE burst). "
            "Run defense is catastrophic: tackling 14, run defense 25.4, motor/effort 17, "
            "20.1% missed tackle rate. These are not developmental gaps — they are effort-dependent "
            "metrics. The variance between coverage elite and run defense catastrophic is the "
            "FM-5 Motivation Cliff signature: situation-selective effort. "
            "FM-5 Motivation Cliff is primary: run support effort collapses in non-coverage snaps. "
            "FM-6 Role Mismatch is secondary: multiplier deployment requires willingness to engage "
            "run force, which tape does not confirm. "
            "FM-3 Processing Wall is tertiary: ball-tracking in reactive situations. "
            "Capital: R4 Late pending character triage. R4 Mid if triage confirms "
            "situation-dependent effort (coachable) rather than structural disengagement. "
            "Cardinals/Texans landing suppresses FM-5 and FM-6 (coverage-specialist deployment). "
            "Seahawks compounds both failure modes."
        ),
        "eval_confidence":     "Tier C",
        "capital_range":       "R4 Late (FM-5 triage pending) — R4 Mid if triage confirms situation-dependent",
        "fm_flags":            ["FM-5 Motivation Cliff (primary)", "FM-6 Role Mismatch (secondary)", "FM-3 Processing Wall (tertiary)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-5 Motivation Cliff primary: 20.1% missed tackle rate + tackling 14 + motor 17 "
            "is the effort-variance signature, not a technique gap. Situation-selective effort "
            "at NFL level produces inconsistent run-support performance that defeats multiplier "
            "deployment value. FM-6 secondary: multiplier requires run-force willingness tape "
            "does not confirm. Cardinals/Texans coverage-specialist deployment is the only "
            "landing spot that does not activate FM-5 directly."
        ),
        "paa_findings": {
            "Coverage":              "ELITE — deep zone 93, catch point 85, VJ 98.0 pct",
            "Run_defense":           "CATASTROPHIC — tackling 14, run defense 25.4, 20.1% missed tackle rate",
            "Motor_effort":          "FLAG — motor/effort 17; effort-variance signature (FM-5)",
            "FM5_signal":            "ACTIVE — coverage-elite vs run-catastrophic variance = Motivation Cliff",
            "FM_primary":            "FM-5 Motivation Cliff — situation-selective effort confirmed via tape variance",
            "FM_secondary":          "FM-6 Role Mismatch — multiplier deployment requires run-force willingness",
            "FM_tertiary":           "FM-3 Processing Wall — ball-tracking reactive situations",
            "Capital_gate":          "TRIAGE PENDING — R4 Late base; R4 Mid if effort is situation-dependent",
            "Archetype_lock":        "S-3 archetype correct; multiplier weights must not price full-responsibility",
        },
    },

    # Garrett Nussmeier — QB (pid=58). Sports Almanac Mode 1 S75.
    # QB-4 Game Manager REJECTED: processing elite (8.8/10) but athleticism catastrophic
    # (2.7/10 — 4.92 40-dash 24.2 pct, VJ 28.0 9.3 pct). Athleticism is an existence
    # condition — eliminates 60-70% of NFL offensive systems from deployment consideration.
    # Scheme versatility 2.1/10. FM-6 primary. Capital R5.
    58: {
        "forced_archetype":    "QB-3",
        "archetype_label":     "QB-3 Pocket Technician",
        "archetype_rationale": (
            "Sports Almanac Mode 1 complete S75. QB-4 Game Manager Elevated REJECTED. "
            "Nussmeier's processing is elite: 8.8/10 anticipatory processing, anticipation 93, "
            "which correctly places him above QB-4. QB-3 Pocket Technician captures the confirmed "
            "mechanism: processing-led quarterback in structure-dependent deployments. "
            "Athleticism is catastrophic and is an existence condition, not a ceiling modifier: "
            "2.7/10 composite, 40-yard dash 4.92s (24.2 pct), vertical jump 28.0 (9.3 pct). "
            "Catastrophic athleticism eliminates 60-70% of NFL offensive systems from deployment "
            "consideration — not as a ceiling suppressor but as a deployment prerequisite. "
            "Scheme versatility 2.1/10 confirms the structure-dependency. "
            "Deep accuracy 33 and decision-making 30 are the critical in-structure execution gaps. "
            "FM-6 Role Mismatch is primary: structure-heavy deployment required — any system "
            "that requires scramble extension, platform mobility, or designed quarterback movement "
            "immediately activates FM-6. "
            "FM-3 Processing Wall is secondary: scheme-complexity escalation beyond confirmed "
            "comfort zone generates processing failures at NFL pace. "
            "FM-2 Scheme Ghost is tertiary: LSU offense may be amplifying processing output. "
            "Capital: R5. Saints landing is optimal scheme architecture fit. Vikings creates "
            "immediate FM-6 and FM-3 compound risk. Webb at R3 is the cautionary capital comp."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R5 — Saints optimal; Vikings compound risk; Webb R3 cautionary comp",
        "fm_flags":            ["FM-6 Role Mismatch (primary)", "FM-3 Processing Wall (secondary)", "FM-2 Scheme Ghost (tertiary)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-6 Role Mismatch primary: structure-heavy deployment is a prerequisite, not a "
            "preference. Athleticism 2.7/10 (forty 4.92s 24.2 pct, VJ 28.0 9.3 pct) is an "
            "existence condition that eliminates the majority of NFL offensive systems. "
            "Athleticism is not a ceiling modifier here — it is a system-compatibility gate. "
            "FM-3 secondary: processing elite but scheme-complexity ceiling unconfirmed at "
            "NFL complexity level. Webb at R3 is the comp — capital overpayment risk is real."
        ),
        "paa_findings": {
            "Processing":              "ELITE — 8.8/10 anticipatory processing; anticipation 93",
            "Athleticism":             "CATASTROPHIC EXISTENCE CONDITION — 2.7/10; forty 4.92s (24.2 pct); VJ 28.0 (9.3 pct)",
            "Scheme_versatility":      "CATASTROPHIC — 2.1/10; structure-dependency confirmed",
            "Deep_accuracy":           "CONCERN — 33; in-structure execution gap",
            "Decision_making":         "CONCERN — 30; in-structure execution gap",
            "QB4_rejected":            "QB-3 correct — processing elite supersedes QB-4 label; athleticism is existence condition",
            "FM_primary":              "FM-6 Role Mismatch — structure-heavy deployment required; mobility systems activate FM-6",
            "FM_secondary":            "FM-3 Processing Wall — scheme-complexity ceiling unconfirmed",
            "FM_tertiary":             "FM-2 Scheme Ghost — LSU offense may amplify output",
            "Capital_comp":            "Webb R3 = cautionary comp; Saints optimal; Vikings compound risk",
            "Archetype_lock":          "QB-3 Pocket Technician confirmed S75",
        },
    },

    # Ty Simpson — QB (pid=9). Sports Almanac Mode 1 S75.
    # QB-5 Raw Projection REJECTED: Processing efficiency and scheme mastery are confirmed.
    # Accuracy at 55th-60th percentile means defenses will not honor the arm as primary threat,
    # inverting the QB-2 mechanism. Simpson wins through processing efficiency and mistake
    # elimination in scheme-controlled contexts. FM-6 Role Mismatch primary.
    # Landing-spot-conditional capital: Steelers R1 late justified; Jets/Cardinals R2;
    # Browns R2 mid-late ceiling. Correct archetype: QB-4 Game Manager Elevated.
    9: {
        "forced_archetype":    "QB-4",
        "archetype_label":     "QB-4 Game Manager Elevated",
        "archetype_rationale": (
            "Sports Almanac Mode 1 complete S75. QB-5 Raw Projection REJECTED — QB-5 assigns "
            "processing as underdeveloped/unconfirmed, which is incorrect for Simpson. "
            "QB-2 Dual-Threat Field General is also REJECTED: accuracy at 55th-60th percentile "
            "means defenses will not honor the arm as a primary threat, structurally inverting "
            "the QB-2 mechanism. Simpson wins through processing efficiency, scheme mastery, "
            "and mistake elimination in controlled-context playcalling. "
            "QB-4 Game Manager Elevated correctly captures the profile: confirmed processor, "
            "limited arm-talent ceiling, scheme-dependent value. "
            "FM-6 Role Mismatch is primary: QB-4 value requires a scheme architect who designs "
            "around the manager profile — Steelers under Canada/offense-by-committee, "
            "structure-heavy offensive systems. Expansion-franchise or high-volume arm-talent "
            "systems destroy value. "
            "Capital is landing-spot-conditional: Steelers scheme fit → R1 late (Pick 18-25 range) "
            "justified. Jets / Cardinals → R2 Early ceiling. Browns → R2 Mid-Late ceiling. "
            "No landing spot justifies R1 top-15 capital."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R1 late (Picks 18-25) Steelers confirmed; R2 Early all other fits",
        "fm_flags":            ["FM-6 Role Mismatch (primary)", "FM-3 Processing Wall (secondary — scheme-conditional)"],
        "placed_session":      75,
        "bust_warning": (
            "FM-6 Role Mismatch primary: QB-4 value is entirely scheme-dependent. "
            "High-volume arm-talent systems (air raid, spread-pass) expose accuracy ceiling "
            "and generate bust outcome at any R1 capital. "
            "Landing spot confirmation is mandatory before R1 capital is allocated. "
            "FM-3 secondary: QB-4 Game Managers face processing wall risk when scheme complexity "
            "escalates beyond their confirmed comfort zone."
        ),
        "paa_findings": {
            "Processing_efficiency":  "CONFIRMED — scheme mastery and mistake elimination confirmed",
            "Arm_talent":             "CONCERN — accuracy 55th-60th percentile; not a primary threat arm",
            "QB2_mechanism":          "REJECTED — defenses do not honor arm → QB-2 inversion active",
            "QB5_mechanism":          "REJECTED — processing is confirmed, not raw/underdeveloped",
            "FM_primary":             "FM-6 Role Mismatch — scheme-architect required",
            "FM_secondary":           "FM-3 Processing Wall — scheme-complexity-conditional",
            "Capital_gate":           "LANDING_SPOT_CONDITIONAL — Steelers R1 late; all others R2",
            "Archetype_lock":         "QB-4 Game Manager Elevated confirmed S75",
        },
    },

    # Treydan Stukes — CB (pid=160). Sports Almanac Mode 3 S76.
    # API returned CB-3 Press Man Corner on fresh re-score — mechanism wrong.
    # CB-4 Slot Specialist confirmed: zone processing complete (Play Rec=73, Deep Zone=72),
    # condensed-space technique, FM-6 Role Mismatch organizational primary.
    # CB-5 Zone-Instinct Nickel (prior Mode 3 output) rejected: processing is complete,
    # not developmental. CB-5 requires athleticism-complete/processing-incomplete architecture.
    # CB-3 Press Man Corner rejected: not a press/man mechanism.
    # CB-4 Chris Harris Jr. mechanism match. Override placed S76.
    # Capital: R2 Mid–R3 Early, scheme-dependent. Hold wide until landing spot confirmed.
    160: {
        "forced_archetype": "CB-4",
        "archetype_label":  "CB-4 Slot Specialist",
        "archetype_rationale": (
            "Sports Almanac Mode 3 complete S76. CB-3 Press Man Corner REJECTED — API selected "
            "on source-priority logic, not mechanism. CB-4 Slot Specialist confirmed. "
            "Zone processing is complete, not developmental: Play Rec=73, Deep Zone=72 both clear. "
            "Condensed-space technique is the primary win mechanism — AGI and ACC primary, "
            "SIZE not a gate. FM-6 Role Mismatch is organizational primary: organizations "
            "deploying him outside at boundary as a press corner generate the bust from "
            "scheme misread. CB-5 rejected — processing-complete/athleticism-incomplete "
            "architecture disqualifies Raw Projection label. "
            "Capital: R2 Mid–R3 Early, scheme-dependent. Cardinals/Colts/Steelers confirm "
            "Day 2 Mid; all other landing spots cap at R3 ceiling until scheme is known."
        ),
        "eval_confidence": "Tier B",
        "fm_flags": ["FM-6 Role Mismatch (primary)", "FM-2 Scheme Dependency (secondary)"],
        "placed_session": 76,
        "paa_findings": {
            "Play_recognition":  "73 — zone processing complete, not developmental",
            "Deep_zone":         "72 — zone coverage mechanism confirmed",
            "Condensed_space":   "CONFIRMED — slot technique primary win mechanism",
            "CB3_rejected":      "API error — press/man mechanism does not match film",
            "CB5_rejected":      "Processing complete disqualifies Raw Projection label",
            "FM_primary":        "FM-6 Role Mismatch — boundary corner deployment destroys value",
            "FM_secondary":      "FM-2 Scheme Dependency — slot/zone deployment required",
            "Capital_gate":      "LANDING_SPOT_CONDITIONAL — scheme confirmation required",
            "Archetype_lock":    "CB-4 Slot Specialist confirmed S76",
        },
    },

    # Caleb Downs — S (pid=28). ARCHETYPE CORRECTED S82: S-4 -> S-1 Centerfielder (Zone-Processor variant).
    # ZONE_COVERAGE_FLAG ACTIVE: Zone 91.5 vs Man 56.9 gap. Man/Press constraints are real but
    # do not disqualify S-1 when primary mechanism is zone-processing/robber, not man rep.
    # DIVERGENCE_VALID: market pricing scheme-proof S-3/S-4 hybrid; data shows zone processor.
    # LANDING_SPOT_MANDATORY: FM-2 primary, FM-6 secondary. Tier-A only in zone-dominant structures.
    28: {
        "forced_archetype":    "S-1",
        "archetype_label":     "S-1 Centerfielder",
        "archetype_rationale": (
            "ARCHETYPE CORRECTED S82: S-4 -> S-1 Centerfielder (Zone-Processor variant). "
            "Mechanism: anticipatory zone processor at intermediate depths; elite robber/poach; "
            "box-adjacent run fits genuine; deep zone adequate only. "
            "ZONE_COVERAGE_FLAG ACTIVE -- Zone 91.5 vs Man 56.9 gap (delta=34.6). "
            "Man 56.9 and Press 35 are real constraints: not a coverage safety, not a slot man solution. "
            "S-1 assignment reflects zone-processing as primary win mechanism, not scheme-proof versatility. "
            "DIVERGENCE_VALID -- consensus #3 is pricing scheme-proof S-3/S-4 hybrid; ratings show "
            "zone processor with real man-coverage limitation. Market assumption error, not model miss. "
            "FM-2 Scheme Ghost primary: value unlocked only in zone-dominant/two-high/robber structures. "
            "FM-6 secondary: landing spot mismatch destroys value at top-5 capital in man-heavy systems. "
            "LANDING_SPOT_MANDATORY -- Tier-A only in confirmed zone-dominant deployment."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R1 Late / R2 Early -- scheme-confirmed landing spot required",
        "fm_flags":            ["FM-2 Scheme Ghost (primary)", "FM-6 Role Mismatch (secondary)"],
        "placed_session":      82,
        "bust_warning": (
            "ZONE_COVERAGE_FLAG ACTIVE: Zone 91.5 / Man 56.9 / Press 35. "
            "Not a scheme-proof safety -- man-heavy or press-dominant landing spot structurally limits value. "
            "Top-5 consensus capital only justified in confirmed zone-dominant, robber/quarters deployment. "
            "FM-6 risk is real: role mismatch in Cover-1/man-heavy systems destroys capital return."
        ),
        "paa_findings": {
            "Zone_coverage":      "ELITE -- 91.5 confirms zone processing as primary win mechanism",
            "Man_coverage":       "CONSTRAINT -- 56.9; not a coverage safety or slot man solution",
            "Press":              "CONSTRAINT -- 35; disqualifies press-man deployment",
            "Zone_coverage_flag": "ACTIVE -- Zone 91.5 vs Man 56.9 gap; zone-processor variant only",
            "FM_primary":         "FM-2 Scheme Ghost -- zone-heavy/two-high/robber deployment required",
            "FM_secondary":       "FM-6 Role Mismatch -- landing spot is critical capital modifier",
            "Divergence_status":  "DIVERGENCE_VALID -- market pricing man-coverage versatility not in ratings",
            "Capital_gate":       "LANDING_SPOT_MANDATORY -- Tier-A only in zone-dominant structures",
            "Archetype_lock":     "S-1 Centerfielder (Zone-Processor variant) confirmed S82",
        },
        "draft_day_take": (
            "S-1 zone processor with elite robber instincts and real man-coverage limits; "
            "we'll pay late-1/early-2 in confirmed zone-dominant structures, but top-5 "
            "'scheme-proof' pricing ignores FM-2/FM-6 risk."
        ),
    },

    # ---------------------------------------------------------------------------
    # Session 76 overrides (continued)
    # ---------------------------------------------------------------------------

    # Joshua Josephs — EDGE (pid=114). Sports Almanac Mode 3 S76.
    # EDGE-3 Power-Counter Technician REJECTED: single-move hook dependency,
    # scheme-manufactured production. FM-1 Athleticism Mirage primary (wins generated
    # by Tennessee gap-blitz architecture, not independent hand sequences).
    # FM-2 Scheme Ghost secondary. Correct archetype: EDGE-4 Athletic Dominator.
    # Capital ceiling R3 Early–R3 Mid. Landing Spot Note mandatory.
    114: {
        "forced_archetype":    "EDGE-4",
        "archetype_label":     "EDGE-4 Athletic Dominator",
        "archetype_rationale": (
            "Sports Almanac Mode 3 correction S76. EDGE-3 Power-Counter Technician REJECTED — "
            "prior label was Sports Almanac error. Single-move hook dependency confirmed: "
            "primary pass-rush mechanism is athletically generated via line games and stunts, "
            "not independent hand sequences. Scheme-manufactured production: "
            "Tennessee gap-blitz architecture amplified win totals. "
            "FM-1 Athleticism Mirage is primary: wins manufactured by scheme rather than "
            "confirmed independent hand technique — counters are not reliable at NFL speed. "
            "FM-2 Scheme Ghost is secondary: gap-blitz-dependent production does not transfer "
            "to base-front deployments. "
            "Capital ceiling R3 Early–R3 Mid. Landing Spot Note mandatory: "
            "Cowboys/Packers/Dolphins gap-blitz-heavy schemes only."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R3 Early–R3 Mid",
        "fm_flags":            ["FM-1 Athleticism Mirage (primary)", "FM-2 Scheme Ghost (secondary)"],
        "placed_session":      76,
        "bust_warning": (
            "FM-1 Athleticism Mirage primary: scheme-manufactured production masks absence of "
            "independent hand technique. NFL base-front defenders not running gap-blitz "
            "architectures expose the single-move dependency immediately. "
            "FM-2 Scheme Ghost secondary: gap-blitz-dependent win totals do not transfer — "
            "NFL base defenses require hand-sequence counters Josephs has not confirmed."
        ),
        "paa_findings": {
            "Pass_rush_mechanism":  "SCHEME-MANUFACTURED — line games/stunts primary; independent hand sequences unconfirmed",
            "Counter_package":      "NOT CONFIRMED at NFL speed — single-move hook dependency",
            "FM_primary":           "FM-1 Athleticism Mirage — athletically generated wins via scheme, not technique",
            "FM_secondary":         "FM-2 Scheme Ghost — Tennessee gap-blitz architecture amplifying production",
            "EDGE3_rejected":       "Power-Counter Technician requires confirmed hand-sequence counters; gate fails",
            "Landing_spot_note":    "MANDATORY — Cowboys/Packers/Dolphins gap-blitz architectures only",
            "Capital_ceiling":      "R3 Early–R3 Mid",
            "Archetype_lock":       "EDGE-4 Athletic Dominator confirmed S76 Mode 3",
        },
    },

    # ---------------------------------------------------------------------------
    # Session 89 overrides
    # ---------------------------------------------------------------------------

    # Jacob Rodriguez — ILB (pid=19). Archetype corrected S89: ILB-2 Coverage Eraser -> ILB-1 Green Dot Anchor.
    # DB writes applied S89 via seed_rodriguez_s89.py --apply 1. Do NOT re-run seed script.
    # This ARCHETYPE_OVERRIDES entry protects the correction on all future --batch all re-scores.
    # PAA status: PARTIAL (Q1 CLEAR, Q2 CLEAR w/ caveat, Q3 FAILED, Q4 FM-6 elevated).
    # v_scheme_vers hard-capped at 5.0 — PAA Q3 FAILED; scheme versatility gate does not clear.
    # Capital: R3 Early base / R2 Late upside (landing-spot conditional: green-dot/command-structure schemes).
    19: {
        "forced_archetype":    "ILB-1",
        "archetype_label":     "ILB-1 Green Dot Anchor",
        "archetype_rationale": (
            "Archetype corrected S89 (ILB-2 Coverage Eraser REJECTED). "
            "Rodriguez's primary win mechanism is pre-snap command and gap-sound run defense — "
            "the Green Dot Anchor profile. ILB-2 Coverage Eraser was incorrect: it prices "
            "man-coverage floor and post-snap disguise as primary mechanisms, which Rodriguez "
            "does not confirm. ILB-1 Green Dot Anchor correctly captures the profile: "
            "pre-snap identification, play-call execution, and gap discipline are the "
            "confirmed primary mechanisms. "
            "PAA Q3 FAILED: scheme versatility gate does not clear — v_scheme_vers hard-capped "
            "at 5.0. Rodriguez reads base-formation run fits at a high level but does not "
            "demonstrate confirmed adaptability across scheme families at the NFL complexity level. "
            "PAA Q4 FM-6 elevated: Green Dot deployment requires organizational commitment to "
            "a command structure — wrong scheme family activates FM-6 Role Mismatch immediately. "
            "FM-6 is primary: scheme-dependent value requires gap-sound, two-level run-defense "
            "architecture with explicit green-dot responsibility. "
            "FM-2 is secondary: scheme-ghost risk if deployed in zone-heavy coverage schemes "
            "where pre-snap command responsibility is reduced or transferred. "
            "Capital: R3 Early base. R2 Late upside is landing-spot-conditional — requires "
            "confirmed green-dot/command-structure deployment (Ravens, Steelers, Commanders "
            "run-first architecture as optimal fits). "
            "Demario Davis (hit/primary), Bobby Wagner (hit/ceiling), Deion Jones (miss/bust) "
            "are the prospect comps seeded S89."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R3 Early base — R2 Late upside (green-dot/command-structure landing only)",
        "fm_flags":            ["FM-6 Role Mismatch (primary)", "FM-2 Scheme Ghost (secondary)"],
        "v_scheme_vers_cap":   5.0,
        "placed_session":      89,
        "bust_warning": (
            "FM-6 Role Mismatch primary: Green Dot Anchor value is entirely deployment-dependent. "
            "Organizations that do not allocate green-dot/command responsibility reduce Rodriguez "
            "to a volume tackler — FM-6 activates regardless of physical performance. "
            "FM-2 Scheme Ghost secondary: zone-heavy deployments that remove pre-snap command "
            "responsibility expose the scheme-versatility gap (PAA Q3 FAILED). "
            "v_scheme_vers hard-capped at 5.0 — do NOT allow API to score above this value."
        ),
        "paa_findings": {
            "Q1":                  "CLEAR — pre-snap identification and gap discipline confirmed at starter level",
            "Q2":                  "CLEAR w/ caveat — run-defense mechanism confirmed; man-coverage floor present but not dominant",
            "Q3":                  "FAILED — scheme versatility gate does not clear; v_scheme_vers hard-capped 5.0",
            "Q4":                  "FM-6 ELEVATED — Green Dot deployment requires organizational command structure commitment",
            "FM_primary":          "FM-6 Role Mismatch — scheme-dependent value; green-dot/command deployment mandatory",
            "FM_secondary":        "FM-2 Scheme Ghost — zone-heavy deployment exposes scheme-versatility gap",
            "Comps_seeded_S89":    "Demario Davis (hit/primary), Bobby Wagner (hit/ceiling), Deion Jones (miss/bust)",
            "Capital_gate":        "LANDING_SPOT_CONDITIONAL — R2 Late only in confirmed green-dot architecture",
            "Archetype_lock":      "ILB-1 Green Dot Anchor confirmed S89 (ILB-2 Coverage Eraser REJECTED)",
        },
    },
}

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


MEASURABLES_ARCHETYPE_CONTEXT: dict[str, str] = {

    "EDGE-1": (
        "ARCHETYPE CONTEXT — EDGE-1 Every-Down Disruptor: "
        "Primary mechanism metrics: hand size, arm length, wingspan, 10-yard split, "
        "weight-adjusted power metrics. "
        "Evaluation standard: This archetype wins on technique, hand fighting, and motor "
        "— not speed arc. A 40-time in the 4.40–4.55 range is functionally adequate; "
        "do not read it as a ceiling signal. Forty time is a secondary metric for EDGE-1. "
        "Primary athleticism signals are first-step quickness (10-yard split) and "
        "size-power combination (weight + arm length). "
        "Counter sequencing and pre-snap processing score against Processing. A player "
        "with one dominant rush move and no confirmed counter is an FM-3 risk — "
        "but absence of elite forty time is not FM-3 evidence. "
        "FM-1 (Athleticism Mirage) does not apply to technique-primary archetypes. "
        "Do not penalize functional-not-elite speed metrics on EDGE-1 profiles."
    ),

    "EDGE-2": (
        "ARCHETYPE CONTEXT — EDGE-2 Speed-Bend Specialist: "
        "Primary mechanism metrics: 40-time, 10-yard split, bend angle on film, "
        "wingspan, agility scores. "
        "Evaluation standard: Speed is the primary mechanism — a 40-time ≥4.55 is a "
        "genuine ceiling signal for this archetype. Forty time scores directly against "
        "Athleticism as a mechanism-primary metric, not a secondary one. "
        "FM-1 (Athleticism Mirage) is the highest-frequency bust mode — confirm that "
        "combine speed translates to bend and arc on film before pricing athleticism "
        "at ceiling value. A fast forty with stiff hips is FM-1, not EDGE-2."
    ),

    "EDGE-3": (
        "EVALUATION NOTE — EDGE-3 Power-Counter Technician: "
        "Primary mechanism metrics are arm length, wingspan, and SIZE score "
        "(base strength and anchor). "
        "ACC score (acceleration) is a secondary positive signal. "
        "Forty-yard dash is NOT a primary ceiling gate for this archetype — "
        "EDGE-3 wins through counter sequencing and hand technique, not burst. "
        "Apply forty time as a floor check only (flag if >4.75), not as a ceiling limiter."
    ),

    "EDGE-4": (
        "EVALUATION NOTE — EDGE-4 Athletic Dominator: "
        "Primary mechanism metrics are forty-yard dash, ATH composite, "
        "SPEED composite, and ten-yard split. "
        "Unlike EDGE-1 and EDGE-3, athleticism IS the mechanism for "
        "this archetype — speed and explosion metrics are genuine "
        "ceiling indicators, not floor checks. "
        "Apply forty time at full weight as a ceiling indicator: "
        "sub-4.45 with elite ATH composite (≥85) reinforces the "
        "archetype and supports DAY1+ capital. "
        "Forty 4.46–4.55 with ATH composite 75–84: functional tools, "
        "FM-1 risk moderate — apply one-tier capital discount. "
        "Forty >4.55 OR ATH composite <75: FM-1 risk is high — "
        "production is likely athleticism-generated against college "
        "competition and may not transfer. Flag explicitly. "
        "ARM LENGTH and WINGSPAN are secondary signals — adequate "
        "length (≥32\") matters for point-of-attack control but does "
        "not override a speed concern the way it does for EDGE-1/EDGE-3. "
        "PROD composite is a positive secondary signal only when "
        "speed metrics clear the threshold above — do not use "
        "production to override an FM-1 athletic flag."
    ),

    "CB-1": (
        "EVALUATION NOTE — CB-1 Anticipatory Lockdown: "
        "Primary mechanism metrics are AGI score (hip fluidity and transition), "
        "shuttle time, and hand size (press disruption). "
        "Forty-yard dash is secondary — CB-1 wins through anticipation and "
        "processing, not chase speed. "
        "A forty in the 4.45-4.52 range is acceptable for CB-1 if AGI and "
        "shuttle are elite. Flag forty >4.55 as a potential recovery-speed concern."
    ),

    "CB-3": (
        "EVALUATION NOTE — CB-3 Press Man Corner: "
        "Primary mechanism metrics are forty-yard dash, SPEED score, shuttle, "
        "and wingspan (press leverage). "
        "This archetype wins through physical press and recovery speed — "
        "forty and shuttle are genuine ceiling indicators here, not just floor checks. "
        "SIZE score matters for press leverage at the line. "
        "Apply all speed metrics at full weight for this archetype."
    ),

    "CB-2": (
        "EVALUATION NOTE — CB-2 Zone Coverage Technician: "
        "Primary mechanism metrics are AGI score (lateral quickness "
        "for zone drops and redirects) and SPEED score (zone range). "
        "Processing is the mechanism — this archetype wins by reading "
        "the quarterback, not by matching the receiver athletically. "
        "Forty-yard dash is NOT a primary ceiling gate for CB-2 — "
        "zone technicians do not need elite straight-line speed if "
        "AGI and pattern recognition are confirmed. "
        "A forty in the 4.45-4.58 range is acceptable for CB-2. "
        "SIZE score is secondary — CB-2 does not require CB-3-level "
        "length to function. "
        "FLAG: if SIZE score is very high but AGI is average, the "
        "prospect may be CB-3 press-man misclassified as CB-2 — "
        "scheme dependency (FM-2) risk elevated."
    ),

    "CB-4": (
        "EVALUATION NOTE — CB-4 Slot Specialist: "
        "Primary mechanism metrics are AGI score (condensed-space "
        "change of direction) and ACC score (acceleration into breaks). "
        "This archetype wins in condensed space — lateral quickness "
        "and short-area burst matter more than straight-line speed. "
        "Forty-yard dash is secondary — a 4.55 forty with elite AGI "
        "and ACC is a better CB-4 profile than a 4.40 forty with "
        "average AGI. "
        "SIZE score should NOT be applied as a ceiling gate — "
        "slot specialists do not require boundary corner length. "
        "Apply SIZE only as a floor check: flag if SIZE score "
        "suggests a frame that cannot survive physical releases "
        "in condensed space. "
        "SPEED composite is tertiary — relevant for recovery range "
        "in off-coverage but not the primary value mechanism."
    ),

    "CB-5": (
        "EVALUATION NOTE — CB-5 Raw Projection: "
        "Primary mechanism metrics are SIZE score (physical tools "
        "that underpin the projection) and ATH composite (raw "
        "athletic ceiling being purchased). "
        "This archetype's draft value IS the physical profile — "
        "apply SIZE, ATH, and SPEED at full weight as they represent "
        "the tools the investment thesis depends on. "
        "However: FLAG if forty and ATH composite do not clear "
        "elite thresholds (forty >4.52 or ATH <78) — the projection "
        "thesis weakens materially when the tools are merely good "
        "rather than elite. FM-1 risk elevates. "
        "Do NOT use measurables to confirm processing — there is "
        "no measurable proxy for the anticipatory processing "
        "development that determines whether this archetype succeeds. "
        "Measurables confirm the tool floor; they cannot confirm "
        "the development ceiling."
    ),

    "OT-2": (
        "EVALUATION NOTE — OT-2 Athletic Pass Protector: "
        "Primary mechanism metrics are AGI score, shuttle, and arm length "
        "(kick-slide fluidity and reach). "
        "Forty-yard dash is NOT a meaningful ceiling gate for offensive tackles — "
        "lateral agility and anchor, not straight-line speed, determine pass "
        "protection ceiling. "
        "Apply forty time as a curiosity only. Weight AGI, shuttle, and arm "
        "length as the primary athletic ceiling indicators."
    ),

    "OT-3": (
        "EVALUATION NOTE — OT-3 Power Run Blocker: "
        "Primary mechanism metrics are SIZE score, weight, and arm length "
        "(mass, anchor, and reach at the point of attack). "
        "AGI and shuttle are secondary — sufficient mobility matters but "
        "this archetype wins through base and drive, not athleticism. "
        "Forty-yard dash is NOT a ceiling gate. "
        "Flag SIZE score <70 or arm length <32\" as legitimate concerns "
        "for the power mechanism."
    ),

    "OT-1": (
        "EVALUATION NOTE — OT-1 Elite Athletic Anchor: "
        "Both athleticism AND technique must clear — this archetype "
        "is defined by the combination, not either alone. "
        "Primary mechanism metrics: forty-yard dash (functional "
        "speed for mirror and lateral redirect — sub-5.0 required), "
        "AGI score (kick-slide fluidity and change-of-direction "
        "under pass rush), and ARM LENGTH (reach and leverage "
        "at the point of attack — ≥33.0\" preferred). "
        "Apply forty and AGI at full weight as genuine ceiling "
        "indicators: a tackle who does not clear sub-5.0 "
        "functional speed AND sub-7.6 3-cone equivalent cannot "
        "be OT-1 regardless of technique. "
        "SIZE score: apply as a secondary positive signal — "
        "confirms the frame can absorb NFL edge rusher power. "
        "WINGSPAN: positive signal for pass set reach and "
        "the ability to redirect outside the tackle box. "
        "FM-4 watch: elite long-lean frames (high ATH, high "
        "SPEED, lower SIZE) carry higher soft tissue risk — "
        "flag when ATH and SPEED are elite but SIZE is below "
        "average for the position."
    ),

    "OT-4": (
        "EVALUATION NOTE — OT-4 Versatile Chess Piece: "
        "Primary mechanism metrics are AGI score (multi-position "
        "movement fluidity) and ACC score (quickness into "
        "assignment execution across multiple alignments). "
        "The mechanism is processing-enabled versatility — "
        "athletic profile must support LT, RT, and guard "
        "execution with equal soundness. "
        "Forty-yard dash is a secondary positive signal: "
        "sub-4.90 confirms adequate movement range for tackle "
        "alignment; above 5.10 at tackle depth creates a "
        "legitimate LT speed concern. "
        "ARM LENGTH: apply as a binary gate — below 32.5\" "
        "flags a probable position move to interior guard "
        "(see The Zabel Rule: interior move is a translation "
        "confidence upgrade, not a downgrade, when processing "
        "is confirmed elite). "
        "SIZE score: secondary — versatility value does not "
        "require power-mauler size. Functional anchor adequate. "
        "Do NOT use ATH composite as a ceiling gate — "
        "OT-4 ceiling is processing-dependent, not athleticism-dependent."
    ),

    "S-1": (
        "EVALUATION NOTE — S-1 Range Enforcer: "
        "Primary mechanism metrics are forty-yard dash, SPEED score, and "
        "ten-yard split (range and closing speed). "
        "AGI score matters for zone-to-man transitions. "
        "Apply speed metrics at full weight — range is the core mechanism. "
        "SIZE score is secondary; S-1 does not require CB-caliber size."
    ),

    "QB-1": (
        "EVALUATION NOTE — QB-1 Field General: "
        "Measurables are LOW-WEIGHT for this archetype. "
        "Processing is the mechanism — physical tools are "
        "modifiers, not primary drivers. "
        "ARM LENGTH and HAND SIZE are the only measurables that "
        "carry meaningful weight: adequate hand size (≥9.0\") "
        "for ball security in adverse weather; functional arm "
        "length for release point. Flag hand size <8.75\" only. "
        "Forty-yard dash: apply as a floor check only — flag if "
        ">5.00 as a pure pocket mobility concern. Do NOT use "
        "forty as a ceiling limiter for a confirmed processor. "
        "ATH, SPEED, ACC, AGI composites: do not apply as "
        "ceiling gates. A QB-1 with a 4.9 forty and elite "
        "processing is a better prospect than a QB-2 with a "
        "4.5 forty and reactive processing. "
        "The SAA (Structural Authenticity Audit) governs this "
        "archetype — processing confirmation outweighs all "
        "measurables combined."
    ),

    "QB-2": (
        "EVALUATION NOTE — QB-2 Dual-Threat Architect: "
        "Both dimensions must clear thresholds: passing AND rushing. "
        "Primary mechanism metrics are forty-yard dash (rushing "
        "credibility — sub-4.65 required for genuine run threat "
        "at NFL level), AGI score (evasion and scramble fluidity), "
        "and SPEED composite (open-field burst). "
        "Apply forty and SPEED at full weight — the run threat "
        "must be genuine or the mechanism collapses. A QB-2 "
        "whose forty does not clear the threshold is actually "
        "a QB-1 or QB-4 with mobility as a secondary trait. "
        "FM-4 watch: higher forty-based athleticism = higher "
        "contact frequency = higher Body Breakdown risk. "
        "Note this explicitly when SPEED and ATH composites are "
        "elite — the same tools that confirm the ceiling also "
        "compress the durability timeline. "
        "ARM LENGTH and HAND SIZE: apply standard floor checks "
        "(hand size ≥9.0\", arm length functional for release)."
    ),

    "QB-3": (
        "EVALUATION NOTE — QB-3 Gunslinger: "
        "Primary mechanism metrics are ARM LENGTH (delivery angle "
        "and throw into tight windows) and HAND SIZE (ball "
        "control on velocity throws). "
        "The mechanism is arm talent — physical tools that enable "
        "throws other archetypes cannot make. "
        "Forty-yard dash is secondary — Gunslingers can function "
        "with functional mobility (sub-4.85). Apply as a floor "
        "check only; do not use as a ceiling limiter. "
        "ATH and SPEED composites are low-weight — the archetype "
        "does not depend on athleticism as the primary mechanism. "
        "HAND SIZE below 9.0\": flag as a ball-security concern "
        "specifically on velocity throws in adverse conditions — "
        "this is the one measurable that directly affects the "
        "Gunslinger mechanism. "
        "ARM LENGTH below 31.5\": flag as a release-point concern "
        "that affects the archetype's primary weapon — the ability "
        "to throw into tight windows from platform."
    ),

    "QB-4": (
        "EVALUATION NOTE — QB-4 Game Manager Elevated: "
        "Measurables are LOW-WEIGHT for this archetype. "
        "The mechanism is efficiency and mistake elimination — "
        "physical tools are functional minimums, not value drivers. "
        "Apply all measurables only as floor checks: "
        "forty >5.10 flags pocket mobility concern; "
        "hand size <8.75\" flags adverse-weather ball security; "
        "arm length <30.5\" flags throwing lane limitation. "
        "Do NOT use ATH, SPEED, or AGI composites as ceiling "
        "gates — this archetype is not an athlete-first profile "
        "and composite scores will systematically understate "
        "its NFL value. "
        "The two populations inside QB-4 (true ceiling vs. "
        "suppressed QB-1) cannot be distinguished by measurables. "
        "Processing confirmation via SAA governs that distinction, "
        "not physical profile."
    ),

    "QB-5": (
        "EVALUATION NOTE — QB-5 Raw Projection: "
        "Measurables ARE the primary confirmable variable at "
        "draft time — the tools are what the investment purchases. "
        "Apply ATH, SPEED, ARM LENGTH, and HAND SIZE at full "
        "weight: these confirm whether the physical ceiling being "
        "projected is real. "
        "Forty-yard dash: sub-4.65 is a significant positive "
        "signal (dual-threat optionality during development); "
        "above 4.80 flags limited mobility floor during the "
        "development window. "
        "HAND SIZE below 9.0\": elevated flag for this archetype — "
        "ball security during the inconsistent processing phase "
        "is a compounding risk. "
        "ARM LENGTH and SPEED: apply at full weight as ceiling "
        "indicators. Elite arm length + elite ATH composite = "
        "the tools are real. Functional-only tools with a "
        "projection thesis = FM-1 risk elevated for the archetype. "
        "CRITICAL: measurables confirm the tool floor only. "
        "Character (C2) is the ceiling determinant — no measurable "
        "substitutes for it. Do not let elite measurables override "
        "a C2 concern at this archetype."
    ),

    "ILB-3": (
        "ARCHETYPE CONTEXT — ILB-3 Run-First Enforcer: "
        "Primary mechanism metrics: size-adjusted speed (40-time at playing weight), "
        "hand size, arm length, acceleration (10-yard split). "
        "Evaluation standard: A 40-time ≤4.50 at 235+ lbs is an elite ILB athleticism "
        "signal — price it as a competitive toughness and pursuit-angle asset, not a "
        "speed-arc ceiling. Lateral agility and short-area quickness are secondary "
        "metrics for this archetype; absence of elite agility scores does not cap the "
        "ceiling of a run-first mechanism player. "
        "Coverage metrics (zone/man ratings) score against SchemeVers, not Processing. "
        "A coverage floor at ILB-3 is a scheme deployment constraint — evaluate against "
        "landing spot fit, not as a Processing Wall indicator. "
        "FM-6 (Role Mismatch) is the primary bust mode for this archetype. Flag it when "
        "coverage demands exceed confirmed coverage capability."
    ),

    "ILB-4": (
        "EVALUATION NOTE — ILB-4 Hybrid Chess Piece: "
        "Primary mechanism metrics are AGI score (multi-alignment "
        "movement fluidity) and ATH composite (the athletic base "
        "that enables multiple deployment roles). "
        "This archetype wins through positional versatility — "
        "the athletic profile must support ILB, WILL, SAM, and "
        "box safety alignment with equal effectiveness. "
        "AGI and ACC scores are the most mechanism-relevant metrics: "
        "multi-directional burst and lateral quickness determine "
        "whether the hybrid role is real or aspirational. "
        "Forty-yard dash is a secondary positive signal — confirms "
        "range for coverage assignments. Sub-4.55 reinforces the "
        "archetype; above 4.65 creates a legitimate coverage "
        "ceiling concern for the hybrid role. "
        "SIZE score is secondary — ILB-4 does not require "
        "traditional ILB size if athleticism supports the "
        "multi-alignment concept. "
        "FM-3 watch: if ATH composite is elite but ACC and AGI "
        "are only average, the athleticism may be straight-line "
        "rather than functional — flag for processing review."
    ),

    "OG-1": (
        "EVALUATION NOTE — OG-1 Complete Interior Anchor: "
        "Measurables serve as secondary CONFIRMATION signals "
        "only — this archetype is defined by technique and "
        "processing, not by physical profile. "
        "The combine overvalues guard athleticism; this "
        "archetype does not. "
        "ARM LENGTH is the one measurable that directly "
        "affects the OG-1 mechanism: adequate length (≥32.0\") "
        "enables hand placement at the leverage point; "
        "below 31.0\" is a flag for punch effectiveness at "
        "the interior engagement distance. "
        "SIZE score: apply as a positive anchor signal only — "
        "confirms the frame can sustain 70 snaps of interior "
        "contact. Do NOT apply as a ceiling indicator. "
        "ATH composite: WARNING — do NOT use elite ATH as a "
        "positive ceiling signal for OG-1. An OG-1 with "
        "elite ATH but unconfirmed technique is OG-3 "
        "(Athletic Zone Mauler) or OG-2 (Mauler) — the "
        "SIZE inflation risk identified at OG-1 is precisely "
        "this: physically large, athletically impressive players "
        "misclassified as Complete Interior Anchors before "
        "PAA Q2 and Q4 have confirmed the technique. "
        "Apply ATH at neutral weight. Technique confirmation "
        "via PAA governs OG-1 ceiling, not measurables."
    ),

    "OG-3": (
        "EVALUATION NOTE — OG-3 Athletic Zone Mauler: "
        "Primary mechanism metrics are AGI score (lateral "
        "quickness for zone reach and seal blocks) and ACC "
        "score (pull burst on counter and trap runs). "
        "This archetype wins through functional athleticism "
        "inside a zone-blocking framework — AGI and ACC are "
        "genuine mechanism metrics, not secondary signals. "
        "Apply AGI and ACC at full weight: elite AGI (≥75) "
        "reinforces zone-scheme value; below-average AGI (<60) "
        "for this archetype is a legitimate ceiling concern. "
        "Forty-yard dash: secondary positive signal for pull "
        "burst confirmation — sub-5.0 at guard weight is "
        "elite; 5.1-5.2 is functional. "
        "SIZE score: apply as an anchor check only — confirms "
        "adequate base for interior power exchanges. Do NOT "
        "use SIZE as a ceiling indicator; this archetype wins "
        "through movement, not mass. "
        "ATH composite: positive signal when combined with "
        "elite AGI; flag if ATH is elite but AGI is average "
        "(straight-line athlete misread as zone-agile mauler — "
        "FM-2 Scheme Ghost risk elevated). "
        "FM-2 watch: zone athleticism that looks elite against "
        "inferior interior competition may not hold against "
        "NFL 3-tech power — apply PAA Q2 premium-DL check "
        "before finalizing any OG-3 ceiling assessment."
    ),
}


def _get_measurables_context(conn, prospect_id: int, archetype_code: str | None = None) -> str:
    """
    Returns a structured measurables string for the APEX prompt,
    or empty string if no data exists for this prospect.
    Session 69 — jfosterfilm expanded measurables pipeline.
    Session 71 — archetype_code parameter for mechanism-aware prefix injection.
    """
    row = conn.execute(
        """
        SELECT age, height_in, weight_lbs, arm_length, wingspan,
               hand_size, ten_yard_split, forty_yard_dash, shuttle,
               three_cone, vertical_jump, broad_jump,
               prod_score, ath_score, size_score,
               speed_score, acc_score, agi_score,
               consensus_rank
        FROM prospect_measurables
        WHERE prospect_id = ? AND season_id = 1
        """,
        (prospect_id,),
    ).fetchone()

    if not row:
        return ""

    def fmt(val, suffix=""):
        return f"{val}{suffix}" if val is not None else "\u2014"

    height_str = ""
    if row["height_in"]:
        ft = row["height_in"] // 12
        inch = row["height_in"] % 12
        height_str = f"{ft}'{inch}\""

    lines = ["MEASURABLES (jfosterfilm 2026):"]
    lines.append(
        f"  Build: {height_str or chr(8212)} | {fmt(row['weight_lbs'], 'lbs')} "
        f"| Arm: {fmt(row['arm_length'], chr(34))} "
        f"| Wing: {fmt(row['wingspan'], chr(34))} "
        f"| Hand: {fmt(row['hand_size'], chr(34))}"
    )
    lines.append(
        f"  Speed: 40yd={fmt(row['forty_yard_dash'])} "
        f"| 10yd={fmt(row['ten_yard_split'])} "
        f"| Shuttle={fmt(row['shuttle'])} "
        f"| 3-Cone={fmt(row['three_cone'])}"
    )
    lines.append(
        f"  Explosiveness: Vert={fmt(row['vertical_jump'], chr(34))} "
        f"| Broad={fmt(row['broad_jump'], chr(34))}"
    )
    lines.append(
        f"  Composite scores: ATH={fmt(row['ath_score'])} "
        f"| SPEED={fmt(row['speed_score'])} "
        f"| ACC={fmt(row['acc_score'])} "
        f"| AGI={fmt(row['agi_score'])} "
        f"| SIZE={fmt(row['size_score'])} "
        f"| PROD={fmt(row['prod_score'])}"
    )
    if row["consensus_rank"]:
        lines.append(f"  Consensus rank: #{row['consensus_rank']}")

    # Archetype-aware priority prefix (Session 71)
    prefix = ""
    if archetype_code:
        base_code = archetype_code.split()[0] if archetype_code else ""
        prefix = MEASURABLES_ARCHETYPE_CONTEXT.get(base_code, "")

    if prefix:
        return prefix + "\n\n" + "\n".join(lines)
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
    "failure_mode_primary",
    "failure_mode_secondary",
    "signature_play",
    "translation_risk",
}


def _validate_response(data: dict, prospect_name: str) -> bool:
    """Validate all required fields are present in parsed response."""
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        print(f"  [ERROR] Missing required fields for {prospect_name}: {sorted(missing)}")
        return False
    return True


# ---------------------------------------------------------------------------
# Capital range derivation — PVC-adjusted APEX composite
# ---------------------------------------------------------------------------

def _derive_capital_range(apex_composite: float) -> str:
    """
    Derive draft capital range from PVC-adjusted APEX composite score.
    Capital must reflect what the system values the player at after PVC discount,
    not the raw positional grade (RPG) before discount.
    """
    if apex_composite >= 85.0:
        return "R1 Picks 1-10"
    elif apex_composite >= 80.0:
        return "R1 Picks 11-32"
    elif apex_composite >= 74.0:
        return "R2 Top"
    elif apex_composite >= 68.0:
        return "R2 Mid–R3 Top"
    elif apex_composite >= 62.0:
        return "R3"
    elif apex_composite >= 56.0:
        return "R4"
    elif apex_composite >= 50.0:
        return "R5–R6"
    else:
        return "R7–UDFA"


# ---------------------------------------------------------------------------
# Historical comp context injection
# ---------------------------------------------------------------------------

# Normalise archetype prefix for DB lookup.
# apex_scores.matched_archetype uses "DT-N"; historical_comps stores "IDL-N".
_COMP_ARCH_REMAP: dict[str, str] = {"DT": "IDL"}


def _norm_comp_arch(code: str | None) -> str | None:
    """'DT-3 Two-Gap Anchor' → 'IDL-3';  'EDGE-1 ...' → 'EDGE-1';  None → None."""
    if not code:
        return code
    parts = code.strip().split()
    if not parts or "-" not in parts[0]:
        return code
    prefix, rest = parts[0].split("-", 1)
    canon = _COMP_ARCH_REMAP.get(prefix.upper(), prefix.upper())
    return f"{canon}-{rest}"


def _get_comp_context(
    conn,
    archetype_code: str | None,
    fm_code: str | None,
) -> str:
    """
    Query historical_comps and build a compact comp context block for injection
    into the APEX scoring prompt.

    Returns formatted string or "" if no comps found.
    Selection priority:
      Slot 1: HIT, same archetype (is_fm_reference=0)
      Slot 2: MISS/PARTIAL, same archetype + same fm_code (or any MISS/PARTIAL
              same archetype if no fm_code)
      Slot 3: FM cross-position reference (is_fm_reference=1), only if fm_code
              set and slot 2 is empty

    archetype_code is normalised through _norm_comp_arch() before querying so
    that DT-* codes from apex_scores correctly resolve to IDL-* rows in
    historical_comps.
    """
    if not archetype_code:
        return ""

    # Normalise DT-* → IDL-* before any query
    archetype_code = _norm_comp_arch(archetype_code)

    def _trunc(s: str | None, n: int) -> str:
        if not s:
            return ""
        s = s.strip()
        return s[:n] + "..." if len(s) > n else s

    # SLOT 1: Archetype ceiling HIT
    slot1 = conn.execute(
        """
        SELECT player_name, archetype_code, translation_outcome,
               mechanism, outcome_summary, fm_code, fm_mechanism,
               pre_draft_signal, is_fm_reference
        FROM historical_comps
        WHERE archetype_code = ?
          AND translation_outcome = 'HIT'
          AND is_fm_reference = 0
        ORDER BY comp_confidence ASC, player_name ASC
        LIMIT 1
        """,
        (archetype_code,),
    ).fetchone()

    # SLOT 2: Risk comp — same archetype, preferring matching fm_code
    slot2 = None
    if fm_code:
        slot2 = conn.execute(
            """
            SELECT player_name, archetype_code, translation_outcome,
                   mechanism, outcome_summary, fm_code, fm_mechanism,
                   pre_draft_signal, is_fm_reference
            FROM historical_comps
            WHERE archetype_code = ?
              AND translation_outcome IN ('MISS','PARTIAL')
              AND fm_code = ?
            LIMIT 1
            """,
            (archetype_code, fm_code),
        ).fetchone()
    if slot2 is None:
        slot2 = conn.execute(
            """
            SELECT player_name, archetype_code, translation_outcome,
                   mechanism, outcome_summary, fm_code, fm_mechanism,
                   pre_draft_signal, is_fm_reference
            FROM historical_comps
            WHERE archetype_code = ?
              AND translation_outcome IN ('MISS','PARTIAL')
            ORDER BY
              CASE WHEN fm_code = ? THEN 0 ELSE 1 END,
              comp_confidence ASC
            LIMIT 1
            """,
            (archetype_code, fm_code or ""),
        ).fetchone()

    # SLOT 3: FM cross-position reference fallback (only if slot 2 empty)
    slot3 = None
    if fm_code and slot2 is None:
        slot3 = conn.execute(
            """
            SELECT player_name, archetype_code, translation_outcome,
                   mechanism, outcome_summary, fm_code, fm_mechanism,
                   pre_draft_signal, is_fm_reference
            FROM historical_comps
            WHERE fm_code = ?
              AND is_fm_reference = 1
              AND translation_outcome IN ('MISS','PARTIAL')
            LIMIT 1
            """,
            (fm_code,),
        ).fetchone()

    risk_comp = slot2 or slot3
    if slot1 is None and risk_comp is None:
        return ""

    lines = [
        "=== HISTORICAL COMPS (mechanism anchors — use when writing "
        "strengths, red_flags, and outcome_summary) ==="
    ]

    if slot1:
        fm_tag = f" / {slot1['fm_code']}" if slot1['fm_code'] else ""
        lines.append(
            f"\nARCHETYPE CEILING ({slot1['archetype_code']}"
            f"{fm_tag}): {slot1['player_name']} — {slot1['translation_outcome']}"
        )
        mech = _trunc(slot1["mechanism"], 200)
        if mech:
            lines.append(f"  Mechanism: {mech}")
        summ = _trunc(slot1["outcome_summary"], 150)
        if summ:
            lines.append(f"  Outcome: {summ}")

    if risk_comp:
        fm_tag = f" / {risk_comp['fm_code']}" if risk_comp['fm_code'] else ""
        lines.append(
            f"\nARCHETYPE FM RISK ({risk_comp['archetype_code']}"
            f"{fm_tag}): {risk_comp['player_name']} — {risk_comp['translation_outcome']}"
        )
        fm_mech = _trunc(risk_comp["fm_mechanism"], 200)
        if fm_mech:
            lines.append(f"  Mechanism: {fm_mech}")
        if risk_comp["is_fm_reference"] and risk_comp["pre_draft_signal"]:
            sig = _trunc(risk_comp["pre_draft_signal"], 180)
            lines.append(f"  Pre-Draft Signal: {sig}")
        else:
            summ = _trunc(risk_comp["outcome_summary"], 150)
            if summ:
                lines.append(f"  Outcome: {summ}")

    lines.append(
        "\nINSTRUCTION: Reference these comps by name in your evaluation "
        "text when mechanism parallels exist. Do not invent comps. If the "
        "prospect's mechanism diverges from both comps, note the divergence explicitly."
    )
    lines.append("=== END HISTORICAL COMPS ===")

    return "\n".join(lines)


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

    # Inject archetype direction / gate enforcement if this prospect has an override
    arch_override      = ARCHETYPE_OVERRIDES.get(prospect_id)
    arch_direction     = None
    arch_is_forced     = False
    paa_findings       = None
    override_eval_conf = None
    override_capital   = None
    override_fm_flags  = None
    if arch_override:
        arch_direction = arch_override.get("archetype_direction")
        forced         = arch_override.get("forced_archetype")
        arch_is_forced = bool(forced)
        paa_findings       = arch_override.get("paa_findings")
        override_eval_conf = arch_override.get("eval_confidence")
        override_capital   = arch_override.get("capital_range")
        override_fm_flags  = arch_override.get("fm_flags")

        # Build arch_direction from structured fields when archetype_direction is absent.
        # New-style entries use archetype_rationale + optional extra note fields.
        if arch_direction is None and arch_override.get("archetype_rationale"):
            label     = arch_override.get("archetype_label") or forced or ""
            rationale = arch_override["archetype_rationale"]
            parts     = [f"Assigned archetype: {label}\n\nRationale: {rationale}"]
            for extra_key in ("eval_confidence_note", "fm_4_note", "fm_6_note", "bust_warning", "divergence_note"):
                val = arch_override.get(extra_key)
                if val:
                    parts.append(val)
            arch_direction = "\n\n".join(parts)

        if forced:
            print(f"  Archetype override: {forced} [ANALYST FORCED]")
        elif arch_direction:
            print(f"  Archetype gate enforced for pid={prospect_id} [Q2 GATE]")
        if paa_findings:
            print(f"  PAA findings injected: {len(paa_findings)} confirmed gate results")
        if override_fm_flags:
            print(f"  FM flags active: {', '.join(override_fm_flags)}")

    # Pull current matched_archetype + failure_mode_primary for comp injection.
    # If never scored before, defaults to None → empty comp block (graceful).
    existing_score = conn.execute(
        """
        SELECT matched_archetype, failure_mode_primary
        FROM apex_scores
        WHERE prospect_id = ? AND season_id = ? AND model_version = ?
        ORDER BY scored_at DESC
        LIMIT 1
        """,
        (prospect_id, season_id, MODEL_VERSION),
    ).fetchone()

    # Extract archetype_code: "EDGE-1 Every-Down Disruptor" → "EDGE-1"
    existing_archetype_code = None
    if existing_score and existing_score["matched_archetype"]:
        raw_arch = existing_score["matched_archetype"].strip()
        parts = raw_arch.split()
        if parts and "-" in parts[0]:
            existing_archetype_code = parts[0]

    # Extract FM code for comp selection:
    # Priority: override_fm_flags (analyst set) > failure_mode_primary from DB
    comp_fm_code = None
    if override_fm_flags:
        comp_fm_code = override_fm_flags[0]  # primary FM flag
    elif existing_score and existing_score["failure_mode_primary"]:
        raw_fm = existing_score["failure_mode_primary"].strip()
        fm_parts = raw_fm.split()
        if fm_parts and fm_parts[0].startswith("FM-"):
            comp_fm_code = fm_parts[0]

    comp_context = _get_comp_context(conn, existing_archetype_code, comp_fm_code)
    if comp_context:
        print(f"  Comp context: {existing_archetype_code} / {comp_fm_code or 'no FM'} -> injecting")
    else:
        print(f"  Comp context: {existing_archetype_code or 'no prior score'} -> no comps (first score or gap)")

    # --- Measurables block (Session 71: archetype-aware prefix) ---
    # Priority: forced_archetype from ARCHETYPE_OVERRIDES > prior DB score's matched_archetype
    _archetype_for_measurables = None
    if arch_override:
        _archetype_for_measurables = (
            arch_override.get("forced_archetype") or arch_override.get("archetype_label")
        )
    if not _archetype_for_measurables and existing_score and existing_score["matched_archetype"]:
        _archetype_for_measurables = existing_score["matched_archetype"]
    measurables_block = _get_measurables_context(
        conn, prospect_id, archetype_code=_archetype_for_measurables
    )
    if measurables_block:
        web_context = web_context + "\n\n" + measurables_block

    prospect_data = {
        "name":                display_name,
        "position":            position,
        "school":              school,
        "consensus_rank":      consensus["consensus_rank"],
        "consensus_tier":      consensus["consensus_tier"],
        "consensus_score":     consensus["consensus_score"],
        "ras_total":           ras_score,
        "web_context":         web_context,
        "archetype_direction": arch_direction,
        "forced_archetype":    arch_is_forced,
        "paa_findings":        paa_findings,
        "override_eval_conf":  override_eval_conf,
        "override_capital":    override_capital,
        "override_fm_flags":   override_fm_flags,
        "comp_context":        comp_context,
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

    # Capital range must derive from PVC-adjusted apex_composite, not raw_score (RPG).
    # Analyst gate (override_capital from ARCHETYPE_OVERRIDES) takes priority.
    if override_capital:
        apex_data["capital_base"]     = override_capital
        apex_data["capital_adjusted"] = override_capital
    else:
        _derived_cap = _derive_capital_range(apex_composite)
        apex_data["capital_base"]     = _derived_cap
        apex_data["capital_adjusted"] = _derived_cap

    divergence     = compute_divergence(
        apex_composite,
        consensus["consensus_rank"],
        apex_tier,
        consensus["consensus_tier"],
    )
    pos_tier = get_position_tier(position)

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
    print(f"  Pos tier:    {pos_tier}")

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
        position_tier=pos_tier,
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


def _run_all(
    client:        anthropic.Anthropic,
    conn,
    system_prompt: str,
    season_id:     int,
    apply:         bool,
    force:         bool,
) -> None:
    """
    Score all active, non-calibration prospects that have consensus data.
    Skip already-scored unless --force. Calibration artifacts always excluded.
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
        FROM apex_scores a
        JOIN prospects p ON p.prospect_id = a.prospect_id
        LEFT JOIN prospect_consensus_rankings r
          ON r.prospect_id = p.prospect_id AND r.season_id = ?
        WHERE a.season_id = ?
          AND a.model_version = ?
          AND a.is_calibration_artifact = 0
          AND p.is_active = 1
        GROUP BY p.prospect_id
        ORDER BY COALESCE(r.consensus_rank, 9999) ASC
        """,
        (season_id, season_id, MODEL_VERSION),
    ).fetchall()

    prospects = [dict(r) for r in rows]
    total = len(prospects)
    print(f"\nAll-prospects batch: {total} scored prospects loaded from DB (calibration excluded)")

    already_scored = []
    to_score       = []
    for p in prospects:
        if not force and _is_already_scored(conn, p["prospect_id"], season_id):
            already_scored.append(p["display_name"])
        else:
            to_score.append(p)

    if already_scored:
        print(f"  Skipping {len(already_scored)} already-scored (pass --force to re-score)")
    print(f"  Will score: {len(to_score)}")

    if not to_score:
        print("\n[COMPLETE] All prospects already scored.")
        return

    backed_up     = False
    success_count = 0
    fail_count    = 0
    skip_count    = len(already_scored)

    for i, p in enumerate(to_score):
        pid          = p["prospect_id"]
        display_name = p["display_name"]
        position     = _resolve_position(pid, p["position_group"], p["position_raw"])
        school       = p["school_canonical"] or "Unknown"

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
        f"All-prospects complete: {success_count} scored, {fail_count} failed, "
        f"{skip_count} skipped (total={total})"
    )


def _run_single(
    client:            anthropic.Anthropic,
    conn,
    system_prompt:     str,
    prospect_id:       int,
    position_override: str | None,
    season_id:         int,
    apply:             bool,
    force:             bool,
) -> None:
    """
    Score a single prospect by prospect_id.

    Looks up the prospect from DB. Uses --position override if provided,
    otherwise resolves from DB position_group / position_raw.

    If --force and --apply 1: deletes existing apex_scores + divergence_flags
    rows for this prospect_id + model_version before writing new ones.
    """
    row = conn.execute(
        """
        SELECT prospect_id, display_name, position_group, position_raw, school_canonical
        FROM prospects
        WHERE prospect_id = ? AND season_id = ?
        """,
        (prospect_id, season_id),
    ).fetchone()

    if not row:
        print(f"[ERROR] prospect_id={prospect_id} not found in DB (season_id={season_id})")
        sys.exit(1)

    display_name = row["display_name"]
    position = (
        _normalize_position(position_override)
        if position_override
        else _resolve_position(prospect_id, row["position_group"], row["position_raw"])
    )
    school = row["school_canonical"] or "Unknown"

    print(f"\nSingle prospect batch")
    print(f"  prospect_id={prospect_id}  display_name={display_name}")
    print(f"  position={position}  school={school}  force={force}")

    if force and apply:
        conn.execute(
            "DELETE FROM apex_scores WHERE prospect_id=? AND season_id=? AND model_version=?",
            (prospect_id, season_id, MODEL_VERSION),
        )
        conn.execute(
            "DELETE FROM divergence_flags WHERE prospect_id=? AND season_id=? AND model_version=?",
            (prospect_id, season_id, MODEL_VERSION),
        )
        conn.commit()
        print(
            f"  [FORCE] Deleted existing apex_scores + divergence_flags "
            f"rows for pid={prospect_id} model={MODEL_VERSION}"
        )
    elif force and not apply:
        print(
            f"  [DRY RUN + FORCE] Would delete existing rows for "
            f"pid={prospect_id} model={MODEL_VERSION}"
        )

    override = {
        "prospect_id":  prospect_id,
        "position":     position,
        "school":       school,
        "display_name": display_name,
    }

    ok, _ = _score_prospect(
        client, conn, system_prompt,
        display_name, override, season_id, apply, False,
    )

    print(f"\n{'='*60}")
    if ok:
        print(f"[COMPLETE] {display_name} scored successfully.")
    else:
        print(f"[FAILED] {display_name} scoring failed.")
        sys.exit(1)


def _run_prospect_ids(
    client:        anthropic.Anthropic,
    conn,
    system_prompt: str,
    prospect_ids:  list[int],
    season_id:     int,
    apply:         bool,
) -> None:
    """
    Score specific prospects by prospect_id, always with force-delete semantics.

    Used for targeted re-scores (e.g. archetype corrections) without touching
    the rest of the top-50. Deletes existing apex_scores + divergence_flags rows
    before writing new ones (equivalent to --force --batch single for each pid).

    Looks up position, school, and display_name from DB. Applies ARCHETYPE_OVERRIDES
    if present for the given prospect_id.
    """
    backed_up     = False
    success_count = 0
    fail_count    = 0

    print(f"\nProspect-IDs batch: {prospect_ids}")

    for i, pid in enumerate(prospect_ids):
        row = conn.execute(
            """
            SELECT prospect_id, display_name, position_group, position_raw, school_canonical
            FROM prospects
            WHERE prospect_id = ? AND season_id = ?
            """,
            (pid, season_id),
        ).fetchone()

        if not row:
            print(f"\n[ERROR] prospect_id={pid} not found in DB (season_id={season_id})")
            fail_count += 1
            continue

        display_name = row["display_name"]
        position     = _resolve_position(pid, row["position_group"], row["position_raw"])
        school       = row["school_canonical"] or "Unknown"

        print(f"\n{'='*60}")
        print(f"  [FORCE] Deleting existing rows for pid={pid} ({display_name})")

        if apply:
            conn.execute(
                "DELETE FROM apex_scores WHERE prospect_id=? AND season_id=? AND model_version=?",
                (pid, season_id, MODEL_VERSION),
            )
            conn.execute(
                "DELETE FROM divergence_flags WHERE prospect_id=? AND season_id=? AND model_version=?",
                (pid, season_id, MODEL_VERSION),
            )
            conn.commit()
        else:
            print(f"  [DRY RUN] Would delete apex_scores + divergence_flags for pid={pid}")

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
        f"Prospect-IDs complete: {success_count} scored, {fail_count} failed "
        f"(total={len(prospect_ids)})"
    )


def _make_apex_favors_text(
    flag: str,
    matched_archetype: str | None,
    failure_mode_primary: str | None,
) -> str | None:
    """
    Build a short human-readable phrase describing what APEX weights differently:
      APEX_HIGH + APEX_LOW_PVC_STRUCTURAL → archetype mechanism name + " profile"
        e.g. "EDGE-1 Elite Pass Rusher" → "Elite Pass Rusher profile"
      APEX_LOW → failure mode risk phrase
        e.g. "FM-2 CONDITIONAL" → "FM-2 Conditional risk"
      ALIGNED  → None
    """
    if flag in ("APEX_HIGH", "APEX_LOW_PVC_STRUCTURAL"):
        if matched_archetype:
            # Strip leading "POS-N " to isolate the mechanism name
            name = re.sub(r"^[A-Z]+-\d+\s+", "", matched_archetype).strip()
            return f"{name} profile" if name else None
        return None
    if flag == "APEX_LOW":
        if failure_mode_primary:
            parts = failure_mode_primary.strip().split(None, 1)
            code  = parts[0]                              # "FM-2"
            label = parts[1].title() if len(parts) > 1 else ""
            return f"{code} {label} risk".strip() if label else f"{code} risk"
        return None
    return None  # ALIGNED


def _run_divergence_batch(conn, season_id: int, model_version: str, apply: bool) -> None:
    """
    Recompute divergence flags for all scored prospects using rank-relative method.

    Primary signal: divergence_rank_delta = consensus_ovr_rank - apex_ovr_rank
      Positive = APEX ranks prospect higher than consensus (APEX HIGH)
      Negative = consensus ranks prospect higher (APEX LOW)

    Diagnostic: divergence_raw_delta = apex_composite - consensus_implied_score
      Retained from old method for historical comparison.

    Flag logic:
      Non-premium + rank_delta < -5  → APEX_LOW_PVC_STRUCTURAL (not actionable)
      abs(rank_delta) <= 5           → ALIGNED
      rank_delta > 0                 → APEX_HIGH
      rank_delta < 0                 → APEX_LOW (premium only, actionable)

    Magnitude (rank positions):
      0-15:  MINOR
      16-30: MODERATE
      >30:   MAJOR (premium positions only for MAJOR override)

    No API calls. Reads apex_scores + prospect_consensus_rankings, writes divergence_flags.
    Idempotent — INSERT OR REPLACE on UNIQUE(prospect_id, season_id, model_version).
    """
    print(f"\n  Computing divergence flags (rank-relative method)...")
    print(f"  model_version={model_version}  season_id={season_id}  apply={apply}")

    def _rank_to_implied_score(rank: int | None) -> float | None:
        """Legacy: convert consensus rank to implied 0-100 score. Diagnostic only."""
        if rank is None:
            return None
        return max(0.0, round(100.0 - (rank - 1) * (100.0 / 250.0), 1))

    # Pull all scored prospects with consensus rank
    scored = conn.execute(
        """
        SELECT
            a.prospect_id,
            p.position_group         AS position,
            a.apex_composite,
            a.apex_tier,
            a.capital_adjusted,
            c.consensus_rank,
            c.tier                   AS consensus_tier,
            a.matched_archetype,
            a.failure_mode_primary
        FROM apex_scores a
        JOIN prospects p
          ON p.prospect_id = a.prospect_id
         AND p.season_id   = a.season_id
        JOIN prospect_consensus_rankings c
          ON c.prospect_id = a.prospect_id
         AND c.season_id   = a.season_id
        WHERE a.model_version = ?
          AND a.season_id     = ?
        ORDER BY a.apex_composite DESC
        """,
        (model_version, season_id),
    ).fetchall()

    if not scored:
        print(f"  [WARN] No scored prospects found for model={model_version} season={season_id}")
        return

    # Assign APEX overall rank by apex_composite ordering (DESC = rank 1 = best)
    apex_ovr_rank_map: dict[int, int] = {
        row["prospect_id"]: (i + 1)
        for i, row in enumerate(scored)
    }

    print(f"  Loaded {len(scored)} scored prospects")

    now     = datetime.now(timezone.utc).isoformat()
    updated = 0

    rows_to_write = []
    for row in scored:
        pid       = row["prospect_id"]
        position  = row["position"] or ""
        apex_comp = row["apex_composite"]
        cons_rank = row["consensus_rank"]
        apex_ovr  = apex_ovr_rank_map.get(pid)

        if apex_comp is None or cons_rank is None or apex_ovr is None:
            print(f"  [SKIP] pid={pid} — missing apex_comp/cons_rank/apex_ovr")
            continue

        # PRIMARY SIGNAL: rank delta
        # consensus_rank - apex_ovr_rank
        # Positive = APEX ranks prospect higher (APEX HIGH)
        # Negative = consensus ranks prospect higher (APEX LOW)
        rank_delta = int(round(cons_rank - apex_ovr))

        # DIAGNOSTIC: raw score delta (old method, retained)
        cons_implied  = _rank_to_implied_score(int(cons_rank))
        raw_delta     = round(apex_comp - cons_implied, 1) if cons_implied is not None else None

        # Position tier
        pos_tier  = get_position_tier(position)
        abs_delta = abs(rank_delta)

        # Divergence magnitude
        if abs_delta <= 15:
            mag = "MINOR"
        elif abs_delta <= 30:
            mag = "MODERATE"
        else:
            mag = "MAJOR"

        # Flag logic
        if pos_tier == "non_premium" and rank_delta < -5:
            # Non-premium APEX LOW = structural PVC discount, not actionable
            flag = "APEX_LOW_PVC_STRUCTURAL"
        elif abs_delta <= 5:
            flag = "ALIGNED"
        elif rank_delta > 0:
            flag = "APEX_HIGH"
        else:
            flag = "APEX_LOW"

        favors = 1 if rank_delta > 0 else (-1 if rank_delta < 0 else 0)
        favors_text = _make_apex_favors_text(
            flag,
            row["matched_archetype"],
            row["failure_mode_primary"],
        )

        rows_to_write.append((
            pid, season_id, now, model_version,
            apex_comp, row["apex_tier"], row["capital_adjusted"],
            float(cons_rank), row["consensus_tier"],
            None,          # consensus_round — not in current schema, keep NULL
            rank_delta,    # divergence_score — updated to rank delta as primary signal
            rank_delta,    # divergence_rank_delta — new explicit column
            raw_delta,     # divergence_raw_delta — diagnostic
            None,          # rounds_diff — deprecated, keep NULL
            flag, mag, favors,
            pos_tier, favors_text,
        ))

    # Print dry-run summary before any writes
    from collections import Counter
    flag_counts = Counter(r[14] for r in rows_to_write)
    tier_counts = Counter(r[17] for r in rows_to_write)
    print(f"\n  Divergence summary ({len(rows_to_write)} prospects):")
    for label in ["ALIGNED", "APEX_HIGH", "APEX_LOW", "APEX_LOW_PVC_STRUCTURAL"]:
        print(f"    {label}: {flag_counts.get(label, 0)}")
    print(f"  Position tiers: {dict(tier_counts)}")

    if not apply:
        print(f"\n  [DRY RUN] No writes. Run with --apply 1 to commit.")

        # Preview actionable divergence (premium APEX_LOW and APEX_HIGH)
        print("\n  Premium APEX_LOW (actionable — consensus ranks higher than APEX):")
        actionable_low = [r for r in rows_to_write if r[14] == "APEX_LOW" and r[17] == "premium"]
        actionable_low.sort(key=lambda r: r[10])  # sort by rank_delta (most negative first)
        for r in actionable_low:
            pid_r   = r[0]
            rd      = r[10]
            mag_r   = r[15]
            # Look up name from scored list
            name_row = next((s for s in scored if s["prospect_id"] == pid_r), None)
            pos_r = name_row["position"] if name_row else "?"
            print(f"    pid={pid_r} ({pos_r})  rank_delta={rd}  [{mag_r}]")

        print("\n  Premium APEX_HIGH (actionable — APEX ranks higher than consensus):")
        actionable_high = [r for r in rows_to_write if r[14] == "APEX_HIGH" and r[17] == "premium"]
        actionable_high.sort(key=lambda r: r[10], reverse=True)
        for r in actionable_high:
            pid_r    = r[0]
            rd       = r[10]
            mag_r    = r[15]
            name_row = next((s for s in scored if s["prospect_id"] == pid_r), None)
            pos_r    = name_row["position"] if name_row else "?"
            print(f"    pid={pid_r} ({pos_r})  rank_delta={rd}  [{mag_r}]")
        return

    # Apply writes
    for row_vals in rows_to_write:
        conn.execute(
            """
            INSERT OR REPLACE INTO divergence_flags
              (prospect_id, season_id, computed_at, model_version,
               apex_composite, apex_tier, apex_capital,
               consensus_ovr_rank, consensus_tier, consensus_round,
               divergence_score, divergence_rank_delta, divergence_raw_delta,
               rounds_diff, divergence_flag, divergence_mag, apex_favors,
               position_tier, apex_favors_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row_vals,
        )
        updated += 1

    conn.commit()
    print(f"\n  [OK] Divergence recomputed for {updated} prospects.")

    # Detailed actionable list (post-write)
    print("\n  Premium APEX_LOW (actionable — consensus ranks higher than APEX):")
    actionable = conn.execute(
        """
        SELECT df.prospect_id, p.full_name, p.position_group,
               df.divergence_rank_delta, df.divergence_flag, df.divergence_mag
        FROM divergence_flags df
        JOIN prospects p ON p.prospect_id = df.prospect_id
        WHERE df.divergence_flag = 'APEX_LOW'
          AND df.position_tier   = 'premium'
          AND df.season_id       = ?
          AND df.model_version   = ?
        ORDER BY df.divergence_rank_delta ASC
        """,
        (season_id, model_version),
    ).fetchall()
    for r in actionable:
        print(
            f"    {r['full_name']} ({r['position_group']})  "
            f"rank_delta={r['divergence_rank_delta']}  [{r['divergence_mag']}]"
        )

    print("\n  Premium APEX_HIGH (actionable — APEX ranks higher than consensus):")
    actionable_high = conn.execute(
        """
        SELECT df.prospect_id, p.full_name, p.position_group,
               df.divergence_rank_delta, df.divergence_flag, df.divergence_mag
        FROM divergence_flags df
        JOIN prospects p ON p.prospect_id = df.prospect_id
        WHERE df.divergence_flag = 'APEX_HIGH'
          AND df.position_tier   = 'premium'
          AND df.season_id       = ?
          AND df.model_version   = ?
        ORDER BY df.divergence_rank_delta DESC
        """,
        (season_id, model_version),
    ).fetchall()
    for r in actionable_high:
        print(
            f"    {r['full_name']} ({r['position_group']})  "
            f"rank_delta={r['divergence_rank_delta']}  [{r['divergence_mag']}]"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="APEX v2.3 Scoring Engine — 2026 NFL Draft"
    )
    parser.add_argument(
        "--batch",
        choices=["calibration", "top50", "all", "single", "divergence"],
        default="calibration",
        help="Which prospect set to score (or 'divergence' to recompute flags only)",
    )
    parser.add_argument(
        "--prospect-ids",
        type=str,
        default=None,
        dest="prospect_ids",
        help="Comma-separated prospect_ids for targeted re-score (e.g. '457,39'). "
             "Always force-deletes existing rows. No --batch needed.",
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
        help="Re-score already-scored prospects; for --batch single: deletes existing rows first",
    )
    parser.add_argument(
        "--prospect_id",
        type=int,
        default=None,
        help="Prospect ID for --batch single mode",
    )
    parser.add_argument(
        "--position",
        type=str,
        default=None,
        help="Position override for --batch single mode (e.g. TE, ILB, QB)",
    )
    args = parser.parse_args()

    # Validate single-mode requirements
    if args.batch == "single" and args.prospect_id is None:
        parser.error("--batch single requires --prospect_id")

    season_id = 1 if args.season == 2026 else args.season
    apply     = bool(args.apply)

    print("=" * 60)
    print(f"APEX v2.3 Scoring Engine  |  Season {args.season}")
    print(f"Batch:   {args.batch}")
    print(f"Apply:   {'YES -- DB writes enabled' if apply else 'DRY RUN -- no writes'}")
    print(f"Force:   {args.force}")
    print(f"Model:   {CLAUDE_MODEL}")
    print(f"Version: {MODEL_VERSION}")
    if args.batch == "single":
        print(f"ProspectID: {args.prospect_id}  Position override: {args.position or '(none)'}")
    print("=" * 60)

    # --prospect-ids: targeted re-score, always force, requires API key
    if args.prospect_ids is not None:
        try:
            pid_list = [int(x.strip()) for x in args.prospect_ids.split(",") if x.strip()]
        except ValueError:
            print(f"[ERROR] --prospect-ids must be comma-separated integers: {args.prospect_ids}")
            sys.exit(1)

        if not pid_list:
            print("[ERROR] --prospect-ids is empty.")
            sys.exit(1)

        print(f"Prospect IDs: {pid_list}")

        api_key = _resolve_api_key()
        if apply and not api_key:
            print("\n[ERROR] ANTHROPIC_API_KEY not set. Required for --prospect-ids.")
            sys.exit(1)

        client        = anthropic.Anthropic(api_key=api_key if api_key else "dry-run-no-key")
        system_prompt = build_system_prompt()

        with connect() as conn:
            _run_prospect_ids(client, conn, system_prompt, pid_list, season_id, apply)

        if apply:
            print("\n  Recomputing divergence for all scored prospects...")
            with connect() as conn:
                _run_divergence_batch(conn, season_id, MODEL_VERSION, apply=True)

        if not apply:
            print("\n[DRY RUN COMPLETE] Run with --apply 1 to execute API calls and DB writes.")
        return

    # --batch divergence: no API calls needed
    if args.batch == "divergence":
        with connect() as conn:
            _run_divergence_batch(conn, season_id, MODEL_VERSION, apply)
        if not apply:
            print(
                "\n[DRY RUN COMPLETE] "
                "Run with --apply 1 to execute DB writes."
            )
        return

    # All other batches require API key for actual runs
    api_key = _resolve_api_key()
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

        elif args.batch == "single":
            _run_single(
                client, conn, system_prompt,
                args.prospect_id, args.position, season_id, apply, args.force,
            )

        elif args.batch == "all":
            _run_all(client, conn, system_prompt, season_id, apply, args.force)

    if not apply:
        print(
            "\n[DRY RUN COMPLETE] "
            "Run with --apply 1 to execute API calls and DB writes."
        )


if __name__ == "__main__":
    main()
