from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone

from draftos.config import PATHS
from draftos.db.connect import connect


PILOT_TEAMS = [
    {
        "team_id": "BAL",
        "team_name": "Baltimore Ravens",
        "development_timeline": "win_now",
        "risk_tolerance": "medium",
        "primary_offense_family": "multiple_play_action",
        "primary_defense_family": "multiple_zone_match",
        "coverage_bias": "quarters_robber",
        "man_rate_tolerance": "medium",
        "premium_needs_json": ["S", "EDGE", "OT"],
        "depth_chart_pressure_json": {"S": "high", "EDGE": "medium", "OT": "low"},
        "draft_capital_json": {"pick_1": 27, "pick_2": 59},
        "notes": "Versatility and deployable intelligence favored over pure testing outliers."
    },
    {
        "team_id": "TEN",
        "team_name": "Tennessee Titans",
        "development_timeline": "balanced",
        "risk_tolerance": "medium",
        "primary_offense_family": "play_action_vertical",
        "primary_defense_family": "multiple_front_attack",
        "coverage_bias": "single_high_mix",
        "man_rate_tolerance": "medium_high",
        "premium_needs_json": ["EDGE", "OT", "QB"],
        "depth_chart_pressure_json": {"EDGE": "high", "OT": "medium", "QB": "medium"},
        "draft_capital_json": {"pick_1": 1, "pick_2": 35},
        "notes": "Front-facing value on premium positions; role clarity matters."
    },
    {
        "team_id": "NYG",
        "team_name": "New York Giants",
        "development_timeline": "balanced",
        "risk_tolerance": "medium_high",
        "primary_offense_family": "spread_multiple",
        "primary_defense_family": "multiple_pressure",
        "coverage_bias": "man_zone_mix",
        "man_rate_tolerance": "high",
        "premium_needs_json": ["QB", "CB", "OT"],
        "depth_chart_pressure_json": {"QB": "high", "CB": "high", "OT": "medium"},
        "draft_capital_json": {"pick_1": 3, "pick_2": 34},
        "notes": "Can force aggressive usage; role mismatch risk matters."
    },
    {
        "team_id": "GB",
        "team_name": "Green Bay Packers",
        "development_timeline": "balanced",
        "risk_tolerance": "medium",
        "primary_offense_family": "wide_zone_play_action",
        "primary_defense_family": "four_man_zone",
        "coverage_bias": "quarters_zone",
        "man_rate_tolerance": "low_medium",
        "premium_needs_json": ["CB", "EDGE", "OT"],
        "depth_chart_pressure_json": {"CB": "high", "EDGE": "medium", "OT": "medium"},
        "draft_capital_json": {"pick_1": 23, "pick_2": 55},
        "notes": "Prefers athletic thresholds but fit is best when role is defined."
    },
    {
        "team_id": "PIT",
        "team_name": "Pittsburgh Steelers",
        "development_timeline": "win_now",
        "risk_tolerance": "medium_low",
        "primary_offense_family": "balanced_pro",
        "primary_defense_family": "pressure_multiple",
        "coverage_bias": "single_high_fire_zone",
        "man_rate_tolerance": "medium_high",
        "premium_needs_json": ["QB", "CB", "DT"],
        "depth_chart_pressure_json": {"QB": "high", "CB": "medium", "DT": "medium"},
        "draft_capital_json": {"pick_1": 21, "pick_2": 52},
        "notes": "Urgency can push pick-fit mistakes if value band is ignored."
    },
    {
        "team_id": "MIN",
        "team_name": "Minnesota Vikings",
        "development_timeline": "win_now",
        "risk_tolerance": "medium_high",
        "primary_offense_family": "multiple_shot",
        "primary_defense_family": "pressure_multiple",
        "coverage_bias": "disguise_pressure_zone",
        "man_rate_tolerance": "medium",
        "premium_needs_json": ["CB", "S", "IDL"],
        "depth_chart_pressure_json": {"CB": "high", "S": "medium", "IDL": "medium"},
        "draft_capital_json": {"pick_1": 24, "pick_2": 56},
        "notes": "High disguise load can expose processing and assignment-risk profiles."
    },
    {
        "team_id": "DET",
        "team_name": "Detroit Lions",
        "development_timeline": "win_now",
        "risk_tolerance": "medium",
        "primary_offense_family": "gap_play_action",
        "primary_defense_family": "attack_front_zone_mix",
        "coverage_bias": "split_safety_mix",
        "man_rate_tolerance": "medium",
        "premium_needs_json": ["EDGE", "CB", "G"],
        "depth_chart_pressure_json": {"EDGE": "high", "CB": "medium", "G": "medium"},
        "draft_capital_json": {"pick_1": 28, "pick_2": 60},
        "notes": "Values competitiveness and role-defined toughness; cleaner role paths score better."
    },
    {
        "team_id": "PHI",
        "team_name": "Philadelphia Eagles",
        "development_timeline": "win_now",
        "risk_tolerance": "medium",
        "primary_offense_family": "shotgun_rpo_multiple",
        "primary_defense_family": "front_four_coverage",
        "coverage_bias": "quarters_match",
        "man_rate_tolerance": "medium",
        "premium_needs_json": ["EDGE", "OT", "CB"],
        "depth_chart_pressure_json": {"EDGE": "medium", "OT": "medium", "CB": "high"},
        "draft_capital_json": {"pick_1": 32, "pick_2": 64},
        "notes": "Strong environment for trench and coverage archetypes with clean usage."
    },
]


def _backup_db(reason: str) -> None:
    db_path = PATHS.db
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_dir = db_path.parent / ".." / ".." / "exports" / "backups"
    bak_dir = bak_dir.resolve()
    bak_dir.mkdir(parents=True, exist_ok=True)
    dst = bak_dir / f"draftos_{ts}_{reason}.sqlite"
    shutil.copy2(str(db_path), str(dst))
    print(f"[backup] {dst.name}")


def _resolve_season_id(conn, draft_year: int) -> int:
    row = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?",
        (draft_year,),
    ).fetchone()
    if not row:
        raise SystemExit(f"ERROR: No season found for draft_year={draft_year}")
    return row["season_id"]


def seed(conn, season_id: int, apply: bool) -> None:
    inserted = 0
    existing = 0

    for t in PILOT_TEAMS:
        exists = conn.execute(
            """
            SELECT 1
            FROM team_draft_context
            WHERE team_id = ? AND season_id = ?
            """,
            (t["team_id"], season_id),
        ).fetchone()

        if exists:
            existing += 1
            print(f"[skip] {t['team_id']} already exists")
            continue

        if not apply:
            print(f"[dry] would insert {t['team_id']} {t['team_name']}")
            inserted += 1
            continue

        conn.execute(
            """
            INSERT INTO team_draft_context (
                team_id, season_id, team_name,
                development_timeline, risk_tolerance,
                primary_offense_family, primary_defense_family,
                coverage_bias, man_rate_tolerance,
                premium_needs_json, depth_chart_pressure_json,
                draft_capital_json, notes, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                t["team_id"],
                season_id,
                t["team_name"],
                t["development_timeline"],
                t["risk_tolerance"],
                t["primary_offense_family"],
                t["primary_defense_family"],
                t["coverage_bias"],
                t["man_rate_tolerance"],
                json.dumps(t["premium_needs_json"]),
                json.dumps(t["depth_chart_pressure_json"]),
                json.dumps(t["draft_capital_json"]),
                t["notes"],
            ),
        )
        inserted += 1
        print(f"[ok] inserted {t['team_id']} {t['team_name']}")

    if apply:
        conn.commit()

    print(f"\nInserted: {inserted}")
    print(f"Existing: {existing}")
    print(f"Apply: {apply}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed pilot 2026 team draft context rows")
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    apply = bool(args.apply)

    with connect() as conn:
        season_id = _resolve_season_id(conn, args.season)
        if apply:
            _backup_db("team_draft_context_seed")
        seed(conn, season_id, apply)


if __name__ == "__main__":
    main()