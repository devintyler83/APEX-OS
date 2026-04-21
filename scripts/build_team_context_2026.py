"""
scripts/build_team_context_2026.py

Build / refresh full team context for all 32 NFL teams for season_id=1 (2026 draft).

Purpose
-------
Populate team_draft_context with evidence-backed, sourced 2026 team data so that
rebuild_team_fit_2026.py can compute meaningful (non-baseline) fit scores for all
300 APEX v2.3 prospects × all 32 teams.

Prior state
-----------
Only 8 pilot teams (BAL, CLE, DET, GB, KC, MIA, NYJ, PHI) had real premium_needs /
depth_chart_pressure / draft_capital populated. All 24 remaining teams had empty JSON
defaults, collapsing rebuild_team_fit_2026 output into a FRINGE-heavy distribution.

What this script does
---------------------
1. Applies Migration 0050 (additive: adds secondary_needs_json, failure_mode_sensitivity_json,
   source_provenance, context_version, snapshot_date to team_draft_context).
2. Registers migration in meta_migrations.
3. UPSERTs all 32 teams with:
   - 2026 draft pick capital (NFL.com full picks article, Apr 2026)
   - 2026 positional needs in priority order (NFL.com + ESPN + SharpFootball, Apr 2026)
   - Depth chart pressure by position group
   - Correct scheme / coverage context (defense_family, coverage_bias, man_rate_tolerance)
   - Secondary needs, FM sensitivity notes, source provenance
4. Preserves created_at for rows that already exist.
5. Does NOT touch apex_scores, consensus, tags, or team_prospect_fit.

Evaluator field contracts
-------------------------
The following fields are read by draftos.team_fitevaluator.evaluate_team_fit():
  premium_needs         → list via premium_needs_json
  depth_chart_pressure  → dict via depth_chart_pressure_json
  primary_defense_family → string: "pressure" substring → EDGE bonus + FM-3 path
                                   "multiple" substring  → FM-3 activated
  coverage_bias         → string: "man" → CB-3 bonus
                                   "zone" → CB-2 bonus + FM-2 suppression for CB-2
                                   "disguise" → FM-3 activated
                                   "quarters"|"robber" → S bonus
  man_rate_tolerance    → "high"|"medium"|"low"
  draft_capital         → dict, key "pick_1" used for pick_fit computation

Sources
-------
- 2026 draft order (R1+R2): nfl.com/news/2026-nfl-draft-every-teams-full-set-of-picks
- Team needs (primary): nfl.com/news/2026-nfl-draft-order-round-1-needs-for-all-32-teams
- Team needs (cross-ref): sharpfootballanalysis.com, espn.com/nfl/draft2026
- Scheme context: team HC/DC history; SharpFootball scheme analytics

Derivation rules for fields without direct source
--------------------------------------------------
- depth_chart_pressure: "high" = position is in premium_needs list AND represents
  a starter vacancy (free agent departure or year-end depth chart gap).
  "medium" = need exists but some depth remains.
- failure_mode_sensitivity_json: deterministic from scheme context:
  FM-3 activated if "disguise" in coverage_bias OR "multiple" in primary_defense_family.
  FM-2 suppressed for CB-2 if "zone" in coverage_bias.
  FM-6 noted as activated for teams with no early capital (pick_1 > 64).
- positional_emphasis: set to APEX PVC default for all teams (field not yet consumed
  by evaluator; team-specific overrides deferred to future session).

Usage
-----
    python -m scripts.build_team_context_2026 --apply 0   # dry run
    python -m scripts.build_team_context_2026 --apply 1   # write
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from draftos.config import PATHS
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEASON_ID       = 1
CONTEXT_VERSION = "v2.0"   # bump from v1.0 (default seed) to v2.0 (full 2026 build)
SNAPSHOT_DATE   = "2026-04-21"  # date of research; update if re-running with newer data

_SOURCE_DEFAULT = (
    "NFL.com 2026 draft order + team needs (Apr 2026); "
    "SharpFootball Analysis 2026 team needs; "
    "ESPN 2026 draft needs; "
    "picks: nfl.com/news/2026-nfl-draft-every-teams-full-set-of-picks"
)

_DEFAULT_POSITIONAL_EMPHASIS = json.dumps({
    "QB": 1.00, "CB": 1.00, "EDGE": 1.00, "OT": 0.95,
    "S": 0.90,  "IDL": 0.90, "WR": 0.90,
    "ILB": 0.85, "OLB": 0.85,
    "OG": 0.80, "C": 0.80, "TE": 0.80, "RB": 0.70,
})

# New columns to add additively (Migration 0050).
_NEW_COLUMNS: list[tuple[str, str]] = [
    ("secondary_needs_json",         "TEXT NOT NULL DEFAULT '[]'"),
    ("failure_mode_sensitivity_json","TEXT NOT NULL DEFAULT '{}'"),
    ("source_provenance",            "TEXT"),
    ("context_version",              "TEXT NOT NULL DEFAULT 'v1.0'"),
    ("snapshot_date",                "TEXT"),
]

# ---------------------------------------------------------------------------
# 32-team data (all sourced — see module docstring for derivation rules)
# ---------------------------------------------------------------------------
# Keys used by evaluate_team_fit():
#   premium_needs, depth_chart_pressure, draft_capital,
#   primary_defense_family, coverage_bias, man_rate_tolerance
# Keys stored for provenance / future evaluator use:
#   secondary_needs, failure_mode_sensitivity, scheme_family, offense_style,
#   defense_structure, notes, source_provenance

_TEAM_DATA: dict[str, dict] = {

    # -----------------------------------------------------------------------
    # AFC EAST
    # -----------------------------------------------------------------------
    "BUF": {
        "team_name":               "Buffalo Bills",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "4-3_Tampa2_zone",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "OT", "ILB"],
        "secondary_needs":         ["S", "WR"],
        "depth_chart_pressure":    {"EDGE": "high", "OT": "medium", "ILB": "medium"},
        "draft_capital":           {"pick_1": 26, "r3_1": 91},
        "failure_mode_sensitivity": {"FM-3": "suppressed", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "McDermott Tampa-2 / Cover-2 zone defense. Zone-scheme CB preferred; "
            "CB-1 and CB-2 archetypes have clear role path. No R2 own pick; best "
            "back-end capital is R3:91. EDGE is primary day-1 need opposite Chubb. "
            "ILB depth gap emerged post-FA. Bradley Chubb supplemental."
        ),
    },
    "MIA": {
        "team_name":               "Miami Dolphins",
        "development_timeline":    "win_now",
        "risk_tolerance":          "high",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "scheme_family":           "4-3_pressure_man",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["WR", "CB", "EDGE"],
        "secondary_needs":         ["OT", "S"],
        "depth_chart_pressure":    {"WR": "high", "CB": "medium", "EDGE": "medium"},
        "draft_capital":           {"pick_1": 11, "pick_1b": 30, "pick_2": 43},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "activated_zone_CB_in_man"},
        "notes": (
            "Waddle trade elevates WR to top need. Two R1 picks (#11, #30 from DEN). "
            "High man-coverage rate — CB-3 press-man archetypes have premium role path; "
            "zone-only CBs face FM-2 activation. Speed-first roster construction. "
            "OT right side succession ongoing."
        ),
    },
    "NE": {
        "team_name":               "New England Patriots",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style",
        "primary_defense_family":  "4-3_multiple",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_multiple_zone",
        "offense_style":           "pro_style",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "OT", "IDL"],
        "secondary_needs":         ["TE", "WR"],
        "depth_chart_pressure":    {"EDGE": "high", "OT": "medium", "IDL": "medium"},
        "draft_capital":           {"pick_1": 31, "pick_2": 63},
        "failure_mode_sensitivity": {"FM-3": "activated_multiple", "FM-6": "neutral"},
        "notes": (
            "Vrabel-led rebuild. Belichick-legacy 4-3 multiple — FM-3 activated for "
            "processing-sensitive QBs. Morgan Moses OT succession near (age 35). "
            "EDGE rotation is day-1 starter need. Zone coverage — CB-1/CB-2 preferred."
        ),
    },
    "NYJ": {
        "team_name":               "New York Jets",
        "development_timeline":    "win_now",
        "risk_tolerance":          "high",
        "primary_offense_family":  "pro_style",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "scheme_family":           "4-3_pressure_man",
        "offense_style":           "pro_style",
        "defense_structure":       "4-3",
        "premium_needs":           ["QB", "OT", "CB", "EDGE"],
        "secondary_needs":         ["WR", "S"],
        "depth_chart_pressure":    {"QB": "high", "OT": "high", "CB": "medium", "EDGE": "medium"},
        "draft_capital":           {"pick_1": 2, "pick_1b": 16, "pick_2": 33, "pick_2b": 44},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "activated_zone_CB_in_man"},
        "notes": (
            "Four R1-R2 equivalent picks (#2, #16, #33, #44). QB franchise reset — "
            "Geno Smith bridge. Two OT and CB starter needs. High man-coverage — "
            "CB-3 press-man archetypes have day-1 role path. EDGE opposite McDonald IV. "
            "Heavy capital load enables tier flexibility."
        ),
    },

    # -----------------------------------------------------------------------
    # AFC NORTH
    # -----------------------------------------------------------------------
    "BAL": {
        "team_name":               "Baltimore Ravens",
        "development_timeline":    "win_now",
        "risk_tolerance":          "low",
        "primary_offense_family":  "run_RPO",
        "primary_defense_family":  "4-3_multiple",
        "coverage_bias":           "quarters",
        "man_rate_tolerance":      "low",
        "scheme_family":           "4-3_multiple",
        "offense_style":           "run_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["OT", "EDGE", "WR"],
        "secondary_needs":         ["IDL", "TE"],
        "depth_chart_pressure":    {"OT": "high", "EDGE": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 14, "pick_2": 45},
        "failure_mode_sensitivity": {
            "FM-3": "activated_multiple",
            "FM-2": "suppressed_CB2_zone_quarters",
            "FM-6": "neutral",
        },
        "notes": (
            "OL need elevated post-Linderbaum departure. WR depth thin behind top-2. "
            "4-3 multiple with quarters/Cover-4 — low man rate limits CB-3 press-man "
            "value; FM-3 activated for processing-sensitive QBs. EDGE rotation depth "
            "secondary. Safeties in quarters system get deployment bonus (S-1/2/3)."
        ),
    },
    "CIN": {
        "team_name":               "Cincinnati Bengals",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_air_raid",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "spread_air_raid",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "IDL", "S"],
        "secondary_needs":         ["OT", "WR"],
        "depth_chart_pressure":    {"EDGE": "high", "IDL": "medium", "S": "medium"},
        "draft_capital":           {"pick_1": 41},
        "failure_mode_sensitivity": {"FM-3": "suppressed", "FM-6": "activated_late_capital"},
        "notes": (
            "No R1 pick (traded to NYG). Top capital is R2:#41. Zac Taylor spread offense. "
            "4-3 zone defense — zone-trained CB valued. EDGE is day-1 starter need. "
            "DT upgrade critical (3-technique). FM-6 risk elevated with no early capital; "
            "developmental prospects carry higher bust risk in this draft slot range."
        ),
    },
    "CLE": {
        "team_name":               "Cleveland Browns",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "pro_style_power",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "4-3_zone",
        "offense_style":           "pro_style_power",
        "defense_structure":       "4-3",
        "premium_needs":           ["QB", "OT", "WR"],
        "secondary_needs":         ["CB", "EDGE"],
        "depth_chart_pressure":    {"QB": "high", "OT": "high", "WR": "medium"},
        "draft_capital":           {"pick_1": 6, "pick_1b": 24, "pick_2": 39},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-6": "suppressed_early_capital"},
        "notes": (
            "Franchise reset. Two R1 picks (#6 own, #24 from JAX). QB is primary target; "
            "OT is simultaneous day-1 need (both 'high' depth pressure). Zone coverage, "
            "low man rate. High risk tolerance — developmental QB acceptable at #6."
        ),
    },
    "PIT": {
        "team_name":               "Pittsburgh Steelers",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_power",
        "primary_defense_family":  "3-4_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "3-4_Cover2_zone",
        "offense_style":           "pro_style_power",
        "defense_structure":       "3-4",
        "premium_needs":           ["QB", "OT", "WR"],
        "secondary_needs":         ["TE", "ILB"],
        "depth_chart_pressure":    {"QB": "high", "OT": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 21, "pick_2": 53},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Tomlin Cover-2 / zone defense. Arthur Smith pro-style power offense. "
            "QB succession is pressing — franchise transition post-Wilson. 3-4 zone: "
            "CB-1 and CB-2 archetypes preferred; low man rate suppresses CB-3 press-man. "
            "OT succession and WR target addition secondary."
        ),
    },

    # -----------------------------------------------------------------------
    # AFC SOUTH
    # -----------------------------------------------------------------------
    "HOU": {
        "team_name":               "Houston Texans",
        "development_timeline":    "win_now",
        "risk_tolerance":          "low",
        "primary_offense_family":  "zone_run_RPO",
        "primary_defense_family":  "3-4_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "3-4_Tampa2_zone",
        "offense_style":           "zone_run_RPO",
        "defense_structure":       "3-4",
        "premium_needs":           ["OT", "IDL", "ILB"],
        "secondary_needs":         ["S", "EDGE"],
        "depth_chart_pressure":    {"OT": "high", "IDL": "medium", "ILB": "medium"},
        "draft_capital":           {"pick_1": 28, "pick_2": 38, "pick_2b": 59},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "DeMeco Ryans zone-run system (Shanahan roots). 3-4 Tampa-2 defense — "
            "low man rate. OT is day-1 starter need. Best early capital is R2:#38 "
            "(acquired from WAS). IDL penetrator needed for 3-technique. "
            "Zone defense: CB-1/CB-2 archetypes preferred."
        ),
    },
    "IND": {
        "team_name":               "Indianapolis Colts",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "S", "ILB"],
        "secondary_needs":         ["CB", "OT"],
        "depth_chart_pressure":    {"EDGE": "high", "S": "medium", "ILB": "medium"},
        "draft_capital":           {"pick_1": 47},
        "failure_mode_sensitivity": {"FM-6": "activated_late_capital", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Steichen spread-RPO system. No R1 (traded to NYJ); top capital R2:#47. "
            "EDGE is day-1 starter need. 4-3 zone — zone-trained CB preferred. "
            "FM-6 risk elevated with no early capital — developmental bets less suitable "
            "without immediate role path."
        ),
    },
    "JAX": {
        "team_name":               "Jacksonville Jaguars",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "mixed",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_pressure",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["IDL", "EDGE", "OT"],
        "secondary_needs":         ["CB", "WR"],
        "depth_chart_pressure":    {"IDL": "high", "EDGE": "medium", "OT": "medium"},
        "draft_capital":           {"pick_1": 56},
        "failure_mode_sensitivity": {"FM-6": "activated_late_capital", "FM-3": "neutral"},
        "notes": (
            "Rebuild mode; traded R1 to CLE. Top capital R2:#56. 4-3 pressure system. "
            "IDL depth and EDGE rotation both critical starter-level needs. "
            "Late capital only — FM-6 (bust risk) elevated for all picks in this context. "
            "Mixed coverage — no strong CB scheme premium."
        ),
    },
    "TEN": {
        "team_name":               "Tennessee Titans",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["OT", "EDGE", "WR"],
        "secondary_needs":         ["RB", "ILB"],
        "depth_chart_pressure":    {"OT": "high", "EDGE": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 4, "pick_2": 35},
        "failure_mode_sensitivity": {"FM-6": "neutral", "FM-3": "neutral"},
        "notes": (
            "Callahan spread-RPO system (Bengals roots). 4-3 zone defense. "
            "OT is primary day-1 need (#4 overall capital justifies premium OT). "
            "EDGE and WR complete early pick targets. High risk tolerance supports "
            "developmental prospects. Zone scheme — CB-1/CB-2 preferred."
        ),
    },

    # -----------------------------------------------------------------------
    # AFC WEST
    # -----------------------------------------------------------------------
    "DEN": {
        "team_name":               "Denver Broncos",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_shotgun",
        "primary_defense_family":  "3-4_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_zone",
        "offense_style":           "pro_style_shotgun",
        "defense_structure":       "3-4",
        "premium_needs":           ["TE", "S", "IDL"],
        "secondary_needs":         ["CB", "OT"],
        "depth_chart_pressure":    {"TE": "high", "S": "medium", "IDL": "medium"},
        "draft_capital":           {"pick_1": 62},
        "failure_mode_sensitivity": {"FM-6": "activated_late_capital", "FM-3": "neutral"},
        "notes": (
            "Payton pro-style system with Bo Nix. No R1 (traded to MIA); top capital R2:#62. "
            "TE receiving weapon is scheme-critical for Payton's New Orleans-style play-action. "
            "3-4 zone defense. FM-6 risk elevated with no early capital — "
            "this team values polished, translatable prospects over high-ceiling bets."
        ),
    },
    "KC": {
        "team_name":               "Kansas City Chiefs",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure_disguise",
        "coverage_bias":           "man_disguise",
        "man_rate_tolerance":      "high",
        "scheme_family":           "4-3_pressure_disguise",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["CB", "EDGE", "WR"],
        "secondary_needs":         ["IDL", "OT"],
        "depth_chart_pressure":    {"CB": "high", "EDGE": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 9, "pick_1b": 29, "pick_2": 40},
        "failure_mode_sensitivity": {
            "FM-3": "activated_disguise",
            "FM-2": "activated_zone_CB_in_man",
        },
        "notes": (
            "Win-now. Two R1 picks (#9 own, #29 from LAR). High man-coverage rate — "
            "CB-3 press-man archetypes have day-1 role path; zone-only CBs face FM-2. "
            "Disguise/pre-snap complexity activates FM-3 for processing-sensitive QBs. "
            "EDGE rotation opposite existing starters. WR and IDL secondary."
        ),
    },
    "LAC": {
        "team_name":               "Los Angeles Chargers",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_power",
        "primary_defense_family":  "3-4_multiple",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_multiple_zone",
        "offense_style":           "pro_style_power",
        "defense_structure":       "3-4",
        "premium_needs":           ["OT", "EDGE", "IDL"],
        "secondary_needs":         ["S", "WR"],
        "depth_chart_pressure":    {"OT": "high", "EDGE": "medium", "IDL": "medium"},
        "draft_capital":           {"pick_1": 22, "pick_2": 55},
        "failure_mode_sensitivity": {"FM-3": "activated_multiple", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Harbaugh pro-style power system (Michigan roots). 3-4 multiple defense — "
            "FM-3 activated for processing-sensitive QBs. OT is day-1 starter need. "
            "Minter DC: zone-leaning, multiple fronts. EDGE rotation and IDL depth secondary."
        ),
    },
    "LV": {
        "team_name":               "Las Vegas Raiders",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "pro_style_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "mixed",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "pro_style_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["QB", "EDGE", "CB"],
        "secondary_needs":         ["WR", "OT"],
        "depth_chart_pressure":    {"QB": "high", "EDGE": "medium", "CB": "medium"},
        "draft_capital":           {"pick_1": 1, "pick_2": 36},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-6": "suppressed_early_capital"},
        "notes": (
            "Franchise reset with pick #1. New regime post-Carroll. QB is primary target; "
            "EDGE and CB are complementary needs. 4-3 zone defense in transition. "
            "High risk tolerance and early capital suppress FM-6 — role path exists "
            "even for players with developmental timelines."
        ),
    },

    # -----------------------------------------------------------------------
    # NFC EAST
    # -----------------------------------------------------------------------
    "DAL": {
        "team_name":               "Dallas Cowboys",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "man_disguise",
        "man_rate_tolerance":      "high",
        "scheme_family":           "4-3_pressure_man",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "ILB", "CB"],
        "secondary_needs":         ["IDL", "OT"],
        "depth_chart_pressure":    {"EDGE": "high", "ILB": "medium", "CB": "medium"},
        "draft_capital":           {"pick_1": 12, "pick_1b": 20},
        "failure_mode_sensitivity": {
            "FM-3": "activated_disguise",
            "FM-2": "activated_zone_CB_in_man",
        },
        "notes": (
            "Two R1 picks (#12, #20 from GB). No R2 own pick. Pass rush is primary need. "
            "Man/disguise defense — CB-3 press-man archetypes have day-1 role path; "
            "zone-only CBs face FM-2. FM-3 elevated for processing-sensitive QBs "
            "via pre-snap disguise. Micah Parsons-anchored defense needs rotation help."
        ),
    },
    "NYG": {
        "team_name":               "New York Giants",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "pro_style_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "pro_style_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["IDL", "OT", "CB"],
        "secondary_needs":         ["ILB", "WR"],
        "depth_chart_pressure":    {"IDL": "high", "OT": "high", "CB": "medium"},
        "draft_capital":           {"pick_1": 5, "pick_1b": 10, "pick_2": 37},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-6": "neutral"},
        "notes": (
            "Daboll rebuild. Two R1 picks (#5, #10 from CIN). IDL and OT are both "
            "day-1 starter needs (double high depth pressure). Zone coverage system — "
            "CB-1 and CB-2 archetypes preferred. High risk tolerance with two top-10 "
            "picks enables swing on premium developmental prospects."
        ),
    },
    "PHI": {
        "team_name":               "Philadelphia Eagles",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_RPO",
        "primary_defense_family":  "3-4_zone_pressure",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_zone_pressure",
        "offense_style":           "pro_style_RPO",
        "defense_structure":       "3-4",
        "premium_needs":           ["EDGE", "OT", "S"],
        "secondary_needs":         ["WR", "TE"],
        "depth_chart_pressure":    {"EDGE": "high", "OT": "medium", "S": "medium"},
        "draft_capital":           {"pick_1": 23, "pick_2": 54},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Fangio-influenced 3-4 zone pressure. EDGE pass-rush rotation depth is "
            "day-1 need. OT right-side succession ongoing. Zone defense — CB-2 zone "
            "architect archetypes preferred; FM-2 suppressed in this system. "
            "S versatility valued for deep coverage role."
        ),
    },
    "WAS": {
        "team_name":               "Washington Commanders",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_air_raid",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone_Cover3",
        "offense_style":           "spread_air_raid",
        "defense_structure":       "4-3",
        "premium_needs":           ["WR", "EDGE", "OT"],
        "secondary_needs":         ["S", "RB"],
        "depth_chart_pressure":    {"WR": "high", "EDGE": "medium", "OT": "medium"},
        "draft_capital":           {"pick_1": 7},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Quinn Cover-3 / zone system. Kingsbury air-raid offense demands WR target "
            "for Daniels. WR is day-1 premium need. No R2 own pick — pick 7 is the "
            "only first-day capital. Zone defense: CB-1/CB-2 preferred. EDGE and OT "
            "rotation secondary needs."
        ),
    },

    # -----------------------------------------------------------------------
    # NFC NORTH
    # -----------------------------------------------------------------------
    "CHI": {
        "team_name":               "Chicago Bears",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "4-3_zone",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["S", "OT", "IDL"],
        "secondary_needs":         ["EDGE", "WR"],
        "depth_chart_pressure":    {"S": "high", "OT": "medium", "IDL": "medium"},
        "draft_capital":           {"pick_1": 25, "pick_2": 57, "pick_2b": 60},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Ben Johnson spread-RPO system (Detroit roots). Safety is premium need — "
            "zone-safety hybrid (S-2, S-3 archetypes) valued. IDL disruptor role open "
            "for 3-technique. Double R2 picks (#57, #60 from BUF) provide depth-round "
            "flexibility. Zone defense: CB-1/CB-2 preferred."
        ),
    },
    "DET": {
        "team_name":               "Detroit Lions",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_power",
        "primary_defense_family":  "3-4_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_zone",
        "offense_style":           "pro_style_power",
        "defense_structure":       "3-4",
        "premium_needs":           ["OT", "EDGE", "S"],
        "secondary_needs":         ["CB", "ILB"],
        "depth_chart_pressure":    {"OT": "high", "EDGE": "high", "S": "medium"},
        "draft_capital":           {"pick_1": 17, "pick_2": 50},
        "failure_mode_sensitivity": {"FM-2": "suppressed_CB2_zone", "FM-3": "neutral"},
        "notes": (
            "Campbell power run / zone system. OT right side is day-1 need (#17 capital). "
            "EDGE rotation is simultaneous high-pressure need (both OT and EDGE at 'high'). "
            "3-4 zone: CB-1 and CB-2 archetypes preferred over press-man types. "
            "S versatility needed for deep coverage alignment."
        ),
    },
    "GB": {
        "team_name":               "Green Bay Packers",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "3-4_disguise_multiple",
        "coverage_bias":           "mixed_disguise",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_multiple",
        "offense_style":           "spread_RPO",
        "defense_structure":       "3-4",
        "premium_needs":           ["EDGE", "CB", "OT"],
        "secondary_needs":         ["WR", "IDL"],
        "depth_chart_pressure":    {"EDGE": "high", "CB": "medium", "OT": "medium"},
        "draft_capital":           {"pick_1": 52},
        "failure_mode_sensitivity": {
            "FM-3": "activated_disguise_multiple",
            "FM-2": "suppressed_CB2_mixed",
        },
        "notes": (
            "LaFleur spread system. No R1 (traded to DAL); top capital R2:#52. "
            "3-4 multiple/disguise — FM-3 elevated for processing-sensitive QBs. "
            "EDGE is primary need without top-5 capital to address it. "
            "Mixed coverage: CB-1/CB-2 archetypes have broader fit than CB-3 alone."
        ),
    },
    "MIN": {
        "team_name":               "Minnesota Vikings",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "air_raid",
        "primary_defense_family":  "3-4_pressure",
        "coverage_bias":           "zone_blitz_disguise",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_disguise_blitz",
        "offense_style":           "air_raid",
        "defense_structure":       "3-4",
        "premium_needs":           ["IDL", "OT", "S"],
        "secondary_needs":         ["WR", "CB"],
        "depth_chart_pressure":    {"IDL": "high", "OT": "medium", "S": "medium"},
        "draft_capital":           {"pick_1": 18, "pick_2": 49},
        "failure_mode_sensitivity": {
            "FM-3": "activated_disguise",
            "FM-6": "neutral",
        },
        "notes": (
            "O'Connell air-raid offense. Flores 3-4 blitz/disguise — heaviest blitz "
            "rate in NFL; FM-3 elevated for all QBs. IDL penetrator needed for 3-tech role. "
            "S versatility valued in disguise system. Zone-leaning coverage — "
            "CB-2 archetypes preferred."
        ),
    },

    # -----------------------------------------------------------------------
    # NFC SOUTH
    # -----------------------------------------------------------------------
    "ATL": {
        "team_name":               "Atlanta Falcons",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "pro_style",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "OT", "WR"],
        "secondary_needs":         ["CB", "IDL"],
        "depth_chart_pressure":    {"EDGE": "high", "OT": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 48},
        "failure_mode_sensitivity": {"FM-6": "activated_late_capital", "FM-3": "neutral"},
        "notes": (
            "Raheem Morris system. No R1 (traded to LAR for pick #13). Top capital R2:#48. "
            "EDGE is day-1 starter need. 4-3 zone — CB-1/CB-2 archetypes preferred. "
            "FM-6 elevated with no early capital; developmental bets less viable."
        ),
    },
    "CAR": {
        "team_name":               "Carolina Panthers",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["CB", "OT", "WR"],
        "secondary_needs":         ["S", "IDL"],
        "depth_chart_pressure":    {"CB": "high", "OT": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 19, "pick_2": 51},
        "failure_mode_sensitivity": {"FM-2": "suppressed_CB2_zone", "FM-3": "neutral"},
        "notes": (
            "Canales spread-RPO system. CB depth is day-1 critical (#19 supports premium CB). "
            "4-3 zone — zone-trained CB preferred; FM-2 suppressed for CB-2 archetype. "
            "OT and WR add to early-pick targets. High risk tolerance supports developmental."
        ),
    },
    "NO": {
        "team_name":               "New Orleans Saints",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_RPO",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "4-3_zone_pressure",
        "offense_style":           "pro_style_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["WR", "EDGE", "CB"],
        "secondary_needs":         ["IDL", "OT"],
        "depth_chart_pressure":    {"WR": "high", "EDGE": "medium", "CB": "medium"},
        "draft_capital":           {"pick_1": 8, "pick_2": 42},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "New regime inheriting Payton-legacy pro-style offense. WR is day-1 premium need "
            "(#8 capital justifies elite WR). 4-3 zone pressure defense — CB-1/CB-2 preferred. "
            "EDGE depth secondary. Zone coverage suppresses FM-2 for CB-2 archetypes."
        ),
    },
    "TB": {
        "team_name":               "Tampa Bay Buccaneers",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "scheme_family":           "4-3_pressure_man",
        "offense_style":           "spread",
        "defense_structure":       "4-3",
        "premium_needs":           ["EDGE", "CB", "ILB"],
        "secondary_needs":         ["OT", "IDL"],
        "depth_chart_pressure":    {"EDGE": "high", "CB": "high", "ILB": "medium"},
        "draft_capital":           {"pick_1": 15, "pick_2": 46},
        "failure_mode_sensitivity": {
            "FM-3": "neutral",
            "FM-2": "activated_zone_CB_in_man",
        },
        "notes": (
            "Bowles high man-rate defense (Tampa-2 origins evolved to press-man). "
            "EDGE and CB are both day-1 starter needs (both 'high' depth pressure). "
            "Zone-only CBs face FM-2 activation in this system — CB-3 press-man archetype "
            "has premium value. ILB depth secondary. 4-3 pressure: EDGE-3/EDGE-4 archetypes "
            "benefit from pressure-scheme bonus."
        ),
    },

    # -----------------------------------------------------------------------
    # NFC WEST
    # -----------------------------------------------------------------------
    "ARI": {
        "team_name":               "Arizona Cardinals",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "4-3_zone",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["QB", "OT", "EDGE"],
        "secondary_needs":         ["IDL", "ILB"],
        "depth_chart_pressure":    {"QB": "high", "OT": "medium", "EDGE": "medium"},
        "draft_capital":           {"pick_1": 3, "pick_2": 34},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Gannon-led rebuild (Eagles defensive roots — zone-heavy). QB is franchise "
            "reset after Murray departure (#3 capital). OT is co-primary need to protect "
            "incoming QB. 4-3 zone: low man rate suppresses CB-3; CB-1/CB-2 preferred. "
            "High risk tolerance supports developmental bets at premium positions."
        ),
    },
    "LAR": {
        "team_name":               "Los Angeles Rams",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "3-4_zone_blitz",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "scheme_family":           "3-4_zone_blitz",
        "offense_style":           "spread_RPO",
        "defense_structure":       "3-4",
        "premium_needs":           ["WR", "OT", "ILB"],
        "secondary_needs":         ["EDGE", "CB"],
        "depth_chart_pressure":    {"WR": "high", "OT": "medium", "ILB": "medium"},
        "draft_capital":           {"pick_1": 13, "pick_2": 61},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "McVay spread-RPO system. Pick #13 acquired from ATL. WR3 depth is "
            "day-1 priority — McVay offense is route-running intensive. OT right-side "
            "succession (Havenstein replacement). 3-4 zone blitz — CB-2 zone architect "
            "archetypes preferred. ILB deployment fits 3-4 system."
        ),
    },
    "SEA": {
        "team_name":               "Seattle Seahawks",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure_man",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "scheme_family":           "4-3_press_man",
        "offense_style":           "spread_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["RB", "OT", "S"],
        "secondary_needs":         ["EDGE", "WR"],
        "depth_chart_pressure":    {"RB": "medium", "OT": "medium", "S": "medium"},
        "draft_capital":           {"pick_1": 32, "pick_2": 64},
        "failure_mode_sensitivity": {
            "FM-3": "neutral",
            "FM-2": "activated_zone_CB_in_man",
        },
        "notes": (
            "Macdonald press-man defense (Michigan-style) — very high man rate. "
            "CB-3 and CB-1 archetypes have clear day-1 role path; zone-only CBs face FM-2. "
            "RB need is depth-chart driven (unusual for pick #32 range). "
            "S versatility valued in disguise/press system. Late capital both picks."
        ),
    },
    "SF": {
        "team_name":               "San Francisco 49ers",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "zone_run_RPO",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "scheme_family":           "4-3_zone",
        "offense_style":           "zone_run_RPO",
        "defense_structure":       "4-3",
        "premium_needs":           ["OT", "EDGE", "WR"],
        "secondary_needs":         ["IDL", "S"],
        "depth_chart_pressure":    {"OT": "high", "EDGE": "medium", "WR": "medium"},
        "draft_capital":           {"pick_1": 27, "pick_2": 58},
        "failure_mode_sensitivity": {"FM-3": "neutral", "FM-2": "suppressed_CB2_zone"},
        "notes": (
            "Shanahan zone-run play-action system. OT succession is critical need "
            "(day-1 starter). 4-3 zone defense — zone-trained CB preferred; "
            "low man rate suppresses CB-3 press-man. WR3 depth needed for "
            "route-running scheme demands. EDGE rotation secondary."
        ),
    },
}

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO team_draft_context (
    team_id, season_id, team_name,
    development_timeline, risk_tolerance,
    primary_offense_family, primary_defense_family,
    coverage_bias, man_rate_tolerance,
    premium_needs_json, depth_chart_pressure_json, draft_capital_json,
    notes, is_active,
    scheme_family, offense_style, defense_structure, positional_emphasis,
    secondary_needs_json, failure_mode_sensitivity_json,
    source_provenance, context_version, snapshot_date,
    updated_at
) VALUES (
    ?, 1, ?,
    ?, ?,
    ?, ?,
    ?, ?,
    ?, ?, ?,
    ?, 1,
    ?, ?, ?, ?,
    ?, ?,
    ?, ?, ?,
    CURRENT_TIMESTAMP
)
ON CONFLICT (team_id, season_id) DO UPDATE SET
    team_name                     = excluded.team_name,
    development_timeline          = excluded.development_timeline,
    risk_tolerance                = excluded.risk_tolerance,
    primary_offense_family        = excluded.primary_offense_family,
    primary_defense_family        = excluded.primary_defense_family,
    coverage_bias                 = excluded.coverage_bias,
    man_rate_tolerance            = excluded.man_rate_tolerance,
    premium_needs_json            = excluded.premium_needs_json,
    depth_chart_pressure_json     = excluded.depth_chart_pressure_json,
    draft_capital_json            = excluded.draft_capital_json,
    notes                         = excluded.notes,
    scheme_family                 = excluded.scheme_family,
    offense_style                 = excluded.offense_style,
    defense_structure             = excluded.defense_structure,
    positional_emphasis           = excluded.positional_emphasis,
    secondary_needs_json          = excluded.secondary_needs_json,
    failure_mode_sensitivity_json = excluded.failure_mode_sensitivity_json,
    source_provenance             = excluded.source_provenance,
    context_version               = excluded.context_version,
    snapshot_date                 = excluded.snapshot_date,
    updated_at                    = CURRENT_TIMESTAMP
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def backup_db() -> Path:
    src     = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst     = out_dir / f"draftos_{ts}_build_team_context.sqlite"
    shutil.copy2(src, dst)
    return dst


def _column_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("PRAGMA table_info(team_draft_context)").fetchall()}


def _ensure_columns(conn) -> list[str]:
    """Add missing Migration-0050 columns. Idempotent."""
    existing = _column_names(conn)
    added: list[str] = []
    for col_name, col_def in _NEW_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE team_draft_context ADD COLUMN {col_name} {col_def}")
            added.append(col_name)
    return added


def _register_migration(conn) -> bool:
    """Insert migration 0050 into meta_migrations if not already present."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM meta_migrations WHERE name LIKE '%0050%'"
    ).fetchone()[0]
    if existing:
        return False
    conn.execute(
        "INSERT INTO meta_migrations (name, applied_at) VALUES (?, ?)",
        ("0050_team_context_enrichment", datetime.now(timezone.utc).isoformat()),
    )
    return True


def _build_row(team_id: str, d: dict) -> tuple:
    return (
        team_id,
        d["team_name"],
        d["development_timeline"],
        d["risk_tolerance"],
        d["primary_offense_family"],
        d["primary_defense_family"],
        d["coverage_bias"],
        d["man_rate_tolerance"],
        json.dumps(d["premium_needs"]),
        json.dumps(d["depth_chart_pressure"]),
        json.dumps(d["draft_capital"]),
        d["notes"],
        d.get("scheme_family", ""),
        d.get("offense_style", ""),
        d.get("defense_structure", ""),
        _DEFAULT_POSITIONAL_EMPHASIS,
        json.dumps(d.get("secondary_needs", [])),
        json.dumps(d.get("failure_mode_sensitivity", {})),
        _SOURCE_DEFAULT,
        CONTEXT_VERSION,
        SNAPSHOT_DATE,
    )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _run(apply: bool) -> None:
    with connect() as conn:
        # -- Gate: table must exist -----------------------------------------
        if not conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='team_draft_context'"
        ).fetchone()[0]:
            print("ERROR: team_draft_context does not exist. Apply migration 0049 first.")
            sys.exit(1)

        if apply:
            backup_path = backup_db()
            print(f"Backup : {backup_path}\n")

        # -- Migration 0050 columns -----------------------------------------
        if apply:
            added = _ensure_columns(conn)
            print(f"Columns added (0050): {added if added else 'none (already present)'}")
            if _register_migration(conn):
                print("Migration 0050 registered in meta_migrations.")
            else:
                print("Migration 0050 already registered.")
        else:
            existing = _column_names(conn)
            missing  = [c for c, _ in _NEW_COLUMNS if c not in existing]
            print(f"DRY RUN — columns to add (0050): {missing if missing else 'none'}")

        print()
        print(f"Teams in data dict : {len(_TEAM_DATA)}")
        print(f"Mode               : {'APPLY' if apply else 'DRY RUN'}")
        print()

        # -- Preview / execute upsert ---------------------------------------
        for team_id in sorted(_TEAM_DATA):
            d = _TEAM_DATA[team_id]
            needs_str  = ", ".join(d["premium_needs"])
            depth_keys = list(d["depth_chart_pressure"].keys())
            pick1      = d["draft_capital"].get("pick_1", "—")
            tag        = "APPLY" if apply else "DRY"
            print(
                f"  {tag}  {team_id:<5s} "
                f"needs={needs_str:<22s} "
                f"depth={depth_keys} "
                f"pick1={pick1}"
            )
            if apply:
                conn.execute(_UPSERT_SQL, _build_row(team_id, d))

        if apply:
            conn.commit()

        print()

        # -- Summary --------------------------------------------------------
        if apply:
            rich = conn.execute(
                """
                SELECT COUNT(*) FROM team_draft_context
                WHERE season_id = 1 AND is_active = 1
                  AND premium_needs_json != '[]'
                  AND depth_chart_pressure_json != '{}'
                """
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM team_draft_context WHERE season_id=1 AND is_active=1"
            ).fetchone()[0]
            print(f"Result: {total} total active teams, {rich} with rich context (target: 32/32)")

            # Context version distribution
            cv = conn.execute(
                """
                SELECT context_version, COUNT(*) cnt
                FROM team_draft_context WHERE season_id=1 AND is_active=1
                GROUP BY context_version
                """
            ).fetchall()
            print("Context versions:")
            for r in cv:
                print(f"  {r['context_version']}: {r['cnt']} teams")
        else:
            print("Dry run complete. No DB changes written.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build 2026 team context for all 32 NFL teams (season_id=1)."
    )
    parser.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="0 = dry run (default), 1 = write to DB",
    )
    args = parser.parse_args()
    _run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
