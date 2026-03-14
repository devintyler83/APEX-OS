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
    3:    "ILB",   # Kc Concepcion     (Texas A&M)
    4:    "ILB",   # Lee Hunter        (Texas Tech)
    5:    "ILB",   # Max Iheanachor    (Arizona State)
    6:    "TE",    # Max Klare         (Ohio State — projects as TE, not LB)
    7:    "ILB",   # R Mason Thomas    (Oklahoma)
    8:    "ILB",   # Sonny Styles      (Ohio State)
    9:    "ILB",   # Ty Simpson        (Alabama)
    10:   "ILB",   # Zion Young        (Missouri)
    11:   "ILB",   # Cj Allen          (Georgia)
    12:   "ILB",   # Omar Cooper       (Indiana)
    16:   "OLB",   # Arvell Reese      (Ohio State — pass-rush LB, OLB library)
    18:   "ILB",   # Gabe Jacas        (Illinois)
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
        "archetype_label": "CB-3 Athletic Freak — CB-1 Development Pathway Confirmed",
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
        "archetype_label": "CB-3 Athletic Freak — CB-1 Development Pathway NOT Confirmed",
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
        "archetype_label": "CB-1 Press-Man Shutdown — FM-4 Medical Flag Active",
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
        "archetype_label": "CB-2 Zone Coverage Technician — Confirmed Correct",
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
        "forced_archetype":  "CB-3 Athletic Freak",
        "archetype_direction": (
            "Assigned archetype: CB-3 Athletic Freak — CB-1 Development Pathway Confirmed\n\n"
            "Rationale: Ponds wins through physical superiority at the line — length, "
            "burst, and press dominance. His primary winning mechanism is athleticism, "
            "not spatial intelligence or zone reading. "
            "CB-1 development pathway is confirmed: technique is trending upward year-over-year, "
            "and processing is developing, but not yet Tier A confirmed against top-25 competition. "
            "The CB-1 pathway flag is a ceiling expander, not a reclassification — it signals "
            "his technique is trending toward CB-1 mechanism. "
            "Do NOT score as CB-2 Zone Technician — he is not a spatial processor reading "
            "the quarterback. CB-2 overweights scheme dependency he does not yet possess. "
            "Score against CB-3 archetype weights (Athleticism bumped to 28%). "
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

    # Jalon Kilgore — S entry (pid=309). Canonical Safety entry. No prior APEX score.
    # Documented here for completeness; lower consensus score reflects coverage gap not quality gap.
    309: {
        "forced_archetype":   "S-3",
        "archetype_label":    "S-3 Multiplier Safety",
        "archetype_rationale": (
            "Same evaluation as pid=449 (CB entry). Canonical Safety entry for Jalon Kilgore. "
            "Lower consensus score reflects coverage gap not quality gap — fewer sources ranked "
            "the S row vs the CB row due to source normalization. S-3 Multiplier Safety archetype "
            "and Tier B confidence carry forward from full PAA evaluation."
        ),
        "eval_confidence":     "Tier B",
        "capital_range":       "R3 base; R2 late if combine confirms man coverage floor",
        "fm_flags":            ["FM-6", "FM-2"],
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
            p.position_group     AS position,
            a.apex_composite,
            a.apex_tier,
            a.capital_adjusted,
            c.consensus_rank,
            c.tier               AS consensus_tier
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
            pos_tier,
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
               position_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    print(f"APEX v2.2 Scoring Engine  |  Season {args.season}")
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

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
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

        elif args.batch == "single":
            _run_single(
                client, conn, system_prompt,
                args.prospect_id, args.position, season_id, apply, args.force,
            )

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
