"""
scripts/seed_team_draft_context_2026.py

Seed pilot team rows into team_draft_context for season_id=1.
Pilot set: 8 teams chosen for scheme diversity across offense/defense/coverage families.

Usage:
    python scripts/seed_team_draft_context_2026.py --apply 0   # dry run
    python scripts/seed_team_draft_context_2026.py --apply 1   # write

Idempotent: INSERT OR IGNORE — safe to re-run. No updates on conflict.
Backup: Script will not write without --apply 1. No destructive operations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Pilot team seed data
# 8 teams — maximum scheme diversity for MVP coverage
# ---------------------------------------------------------------------------

PILOT_TEAMS: list[dict] = [
    {
        "team_id":                 "KC",
        "team_name":               "Kansas City Chiefs",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure_disguise",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "premium_needs_json":      json.dumps(["CB", "EDGE", "OT"]),
        "depth_chart_pressure_json": json.dumps({"CB": "high", "EDGE": "medium", "OT": "medium"}),
        "draft_capital_json":      json.dumps({"pick_1": 32, "pick_2": 63}),
        "notes":                   "Win-now. High man-coverage rate. Offensive line depth concern ongoing.",
    },
    {
        "team_id":                 "PHI",
        "team_name":               "Philadelphia Eagles",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_RPO",
        "primary_defense_family":  "3-4_zone_pressure",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "premium_needs_json":      json.dumps(["CB", "S", "OT"]),
        "depth_chart_pressure_json": json.dumps({"CB": "high", "S": "medium", "OT": "medium"}),
        "draft_capital_json":      json.dumps({"pick_1": 22, "pick_2": 54}),
        "notes":                   "Zone-heavy defense. CB premium need. Robust OL culture.",
    },
    {
        "team_id":                 "BAL",
        "team_name":               "Baltimore Ravens",
        "development_timeline":    "win_now",
        "risk_tolerance":          "low",
        "primary_offense_family":  "run_RPO",
        "primary_defense_family":  "4-3_multiple",
        "coverage_bias":           "quarters",
        "man_rate_tolerance":      "low",
        "premium_needs_json":      json.dumps(["EDGE", "CB", "OT"]),
        "depth_chart_pressure_json": json.dumps({"EDGE": "high", "CB": "medium", "OT": "low"}),
        "draft_capital_json":      json.dumps({"pick_1": 27, "pick_2": 59}),
        "notes":                   "Quarters/Cover-4 dominant. Low man tolerance — CB-3 risk amplified here.",
    },
    {
        "team_id":                 "MIA",
        "team_name":               "Miami Dolphins",
        "development_timeline":    "win_now",
        "risk_tolerance":          "high",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "premium_needs_json":      json.dumps(["OT", "EDGE", "CB"]),
        "depth_chart_pressure_json": json.dumps({"OT": "high", "EDGE": "medium", "CB": "low"}),
        "draft_capital_json":      json.dumps({"pick_1": 21, "pick_2": 52}),
        "notes":                   "High man-coverage rate. OT is the most urgent premium need. Speed-first roster construction.",
    },
    {
        "team_id":                 "DET",
        "team_name":               "Detroit Lions",
        "development_timeline":    "win_now",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "pro_style_power",
        "primary_defense_family":  "3-4_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "medium",
        "premium_needs_json":      json.dumps(["EDGE", "CB", "S"]),
        "depth_chart_pressure_json": json.dumps({"EDGE": "high", "CB": "high", "S": "medium"}),
        "draft_capital_json":      json.dumps({"pick_1": 28, "pick_2": 60}),
        "notes":                   "Zone coverage family. EDGE and CB both premium needs. Strong offensive identity.",
    },
    {
        "team_id":                 "GB",
        "team_name":               "Green Bay Packers",
        "development_timeline":    "balanced",
        "risk_tolerance":          "medium",
        "primary_offense_family":  "spread_RPO",
        "primary_defense_family":  "3-4_disguise_multiple",
        "coverage_bias":           "mixed",
        "man_rate_tolerance":      "medium",
        "premium_needs_json":      json.dumps(["CB", "OT", "EDGE"]),
        "depth_chart_pressure_json": json.dumps({"CB": "medium", "OT": "medium", "EDGE": "medium"}),
        "draft_capital_json":      json.dumps({"pick_1": 23, "pick_2": 55}),
        "notes":                   "Multiple coverage fronts. Balanced risk profile. Development-friendly org culture.",
    },
    {
        "team_id":                 "NYJ",
        "team_name":               "New York Jets",
        "development_timeline":    "win_now",
        "risk_tolerance":          "high",
        "primary_offense_family":  "pro_style",
        "primary_defense_family":  "4-3_pressure",
        "coverage_bias":           "man",
        "man_rate_tolerance":      "high",
        "premium_needs_json":      json.dumps(["OT", "CB", "EDGE"]),
        "depth_chart_pressure_json": json.dumps({"OT": "high", "CB": "high", "EDGE": "medium"}),
        "draft_capital_json":      json.dumps({"pick_1": 7, "pick_2": 39}),
        "notes":                   "High man rate. Top-10 pick — premium position capital exposure. OT and CB both Day 1 needs.",
    },
    {
        "team_id":                 "CLE",
        "team_name":               "Cleveland Browns",
        "development_timeline":    "rebuild",
        "risk_tolerance":          "high",
        "primary_offense_family":  "pro_style_power",
        "primary_defense_family":  "4-3_zone",
        "coverage_bias":           "zone",
        "man_rate_tolerance":      "low",
        "premium_needs_json":      json.dumps(["QB", "EDGE", "CB"]),
        "depth_chart_pressure_json": json.dumps({"QB": "high", "EDGE": "medium", "CB": "medium"}),
        "draft_capital_json":      json.dumps({"pick_1": 2, "pick_2": 33}),
        "notes":                   "Rebuild mode. Top-5 pick. QB is primary need — franchise-level capital decision.",
    },
]


def _run(apply: bool) -> None:
    with connect() as conn:
        # Gate: verify table exists
        exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='team_draft_context'"
        ).fetchone()[0]
        if not exists:
            print("ERROR: team_draft_context table does not exist. Apply migration 0049 first.")
            sys.exit(1)

        print(f"Pilot teams to seed: {len(PILOT_TEAMS)}")
        print(f"Mode: {'APPLY' if apply else 'DRY RUN'}")
        print()

        inserted = 0
        skipped  = 0

        for t in PILOT_TEAMS:
            existing = conn.execute(
                "SELECT team_id FROM team_draft_context WHERE season_id=1 AND team_id=?",
                (t["team_id"],),
            ).fetchone()

            if existing:
                print(f"  SKIP  {t['team_id']:5s}  {t['team_name']}  (already exists)")
                skipped += 1
                continue

            if apply:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO team_draft_context (
                        season_id, team_id, team_name,
                        development_timeline, risk_tolerance,
                        primary_offense_family, primary_defense_family,
                        coverage_bias, man_rate_tolerance,
                        premium_needs_json, depth_chart_pressure_json,
                        draft_capital_json, notes, is_active
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        t["team_id"], t["team_name"],
                        t["development_timeline"], t["risk_tolerance"],
                        t["primary_offense_family"], t["primary_defense_family"],
                        t["coverage_bias"], t["man_rate_tolerance"],
                        t["premium_needs_json"], t["depth_chart_pressure_json"],
                        t["draft_capital_json"], t["notes"],
                    ),
                )
                print(f"  INSERT {t['team_id']:5s}  {t['team_name']}")
                inserted += 1
            else:
                print(f"  DRY    {t['team_id']:5s}  {t['team_name']}  (would insert)")
                inserted += 1

        if apply:
            conn.commit()

        print()
        print(f"Summary: {inserted} inserted, {skipped} skipped")

        if apply:
            # Verify
            count = conn.execute(
                "SELECT COUNT(*) FROM team_draft_context WHERE season_id=1 AND is_active=1"
            ).fetchone()[0]
            print(f"Verification: {count} active rows in team_draft_context (season_id=1)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed pilot teams into team_draft_context")
    parser.add_argument("--apply", type=int, default=0, choices=[0, 1],
                        help="0=dry run (default), 1=write to DB")
    args = parser.parse_args()
    _run(apply=bool(args.apply))
