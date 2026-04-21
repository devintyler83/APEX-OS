"""
scripts/rebuild_team_fit_2026.py

Idempotent recompute of the team-fit layer for the 300-prospect APEX v2.3
universe (season_id=1, 2026 draft).

What this script does
---------------------
1. Reads 300 active, non-calibration APEX v2.3 prospects from apex_scores.
2. Reads all 32 active team contexts from team_draft_context.
3. Computes a deterministic fit score for every prospect × team pair (9 600 rows)
   using the existing evaluate_team_fit() engine.
4. Creates team_prospect_fit if it does not exist (additive migration).
5. Upserts all rows via INSERT OR REPLACE on (prospect_id, team_id, season_id).
6. Backs up the DB before any write.

Constraints
-----------
- season_id=1 only. Script refuses any other season value.
- Does NOT touch apex_scores, prospect_consensus_rankings, or tags.
- Idempotent: re-running produces identical rows (deterministic engine).

Usage
-----
    python -m scripts.rebuild_team_fit_2026 --apply 0   # dry run
    python -m scripts.rebuild_team_fit_2026 --apply 1   # write
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
from draftos.team_fitevaluator import evaluate_team_fit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEASON_ID      = 1
MODEL_VERSION  = "apex_v2.3"

# Mirrors the role-outcome strings emitted by team_fitevaluator._verdict branches.
_ROLE_SCORE: dict[str, int] = {
    "Day 1 starter":                                   85,
    "Sub-package role early, full-time by Year 2":     74,
    "Needs redshirt runway":                           58,
}

# ---------------------------------------------------------------------------
# DDL (additive — CREATE TABLE IF NOT EXISTS)
# ---------------------------------------------------------------------------

_CREATE_FIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS team_prospect_fit (
    prospect_id     INTEGER NOT NULL,
    team_id         TEXT    NOT NULL,
    season_id       INTEGER NOT NULL DEFAULT 1,
    fit_score       REAL,
    fit_tier        TEXT,
    deployment_fit  INTEGER,
    pick_fit        INTEGER,
    fm_risk_score   INTEGER,
    verdict         TEXT,
    why_for         TEXT,
    why_against     TEXT,
    confidence      REAL,
    fit_explanation TEXT,
    last_updated    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (prospect_id, team_id, season_id)
);
"""

_CREATE_FIT_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_team_prospect_fit_team_season "
    "ON team_prospect_fit (team_id, season_id);",
    "CREATE INDEX IF NOT EXISTS idx_team_prospect_fit_prospect_season "
    "ON team_prospect_fit (prospect_id, season_id);",
]

_INSERT_SQL = """
INSERT OR REPLACE INTO team_prospect_fit (
    prospect_id, team_id, season_id,
    fit_score, fit_tier,
    deployment_fit, pick_fit, fm_risk_score,
    verdict, why_for, why_against, confidence,
    fit_explanation, last_updated
) VALUES (
    ?, ?, ?,
    ?, ?,
    ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?
)
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _loads(v: str | None, fallback):
    if not v:
        return fallback
    try:
        return json.loads(v)
    except Exception:
        return fallback


def backup_db() -> Path:
    src     = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst     = out_dir / f"draftos_{ts}_rebuild_team_fit.sqlite"
    shutil.copy2(src, dst)
    return dst


def _recompute_composite(result: dict) -> float:
    """
    Re-derive the composite score from the returned TeamFitResult fields.
    Mirrors the formula in team_fitevaluator.evaluate_team_fit() exactly:
        composite = 0.35*deployment + 0.25*pick_fit + 0.20*(100-fm_risk)
                    + 0.15*role_score + 0.05*65
    role_score is mapped from role_outcome because the evaluator does not
    expose it directly as a return field.
    """
    role_score = _ROLE_SCORE.get(result["role_outcome"], 58)
    raw = (
        0.35 * result["deployment_fit"] +
        0.25 * result["pick_fit"] +
        0.20 * (100 - result["fm_risk_score"]) +
        0.15 * role_score +
        0.05 * 65
    )
    return round(max(0.0, min(100.0, raw)), 1)


def _fit_tier(score: float) -> str:
    if score >= 80:
        return "IDEAL"
    if score >= 70:
        return "STRONG"
    if score >= 60:
        return "VIABLE"
    if score >= 50:
        return "FRINGE"
    return "POOR"


def _fit_explanation(prospect: dict, team_ctx: dict, result: dict) -> str:
    archetype = prospect["matched_archetype"] or prospect["position_group"]
    # scheme_family is set for the 24 default teams; pilot teams retain None
    # so fall back to primary_defense_family
    scheme = (
        team_ctx.get("scheme_family")
        or team_ctx.get("primary_defense_family")
        or "balanced-prototype"
    )
    verdict = result["verdict"]
    why = result["why_for"][0] if result["why_for"] else ""
    explanation = f"{archetype} | {scheme} | {verdict}"
    if why:
        explanation += f". {why}"
    return explanation


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_prospects(conn) -> list[dict]:
    """
    Load all 300 active, non-calibration APEX v2.3 prospects.
    Uses correct apex_scores column names (failure_mode_primary / capital_adjusted).
    NOTE: draftosqueriesteamfit.get_player_team_fit_context() uses stale column
    names (failuremodeprimary, capitalrange) — do NOT call that function here.
    """
    rows = conn.execute(
        """
        SELECT
            p.prospect_id,
            p.display_name,
            p.position_group,
            a.matched_archetype,
            a.failure_mode_primary,
            a.failure_mode_secondary,
            a.capital_adjusted,
            a.apex_composite,
            a.apex_tier,
            a.eval_confidence,
            d.divergence_rank_delta
        FROM apex_scores a
        JOIN prospects p
            ON p.prospect_id = a.prospect_id
           AND p.season_id   = a.season_id
        LEFT JOIN divergence_flags d
            ON d.prospect_id   = a.prospect_id
           AND d.season_id     = a.season_id
           AND d.model_version = a.model_version
        WHERE a.season_id  = ?
          AND a.model_version = ?
          AND p.is_active = 1
          AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
        ORDER BY a.apex_composite DESC
        """,
        (SEASON_ID, MODEL_VERSION),
    ).fetchall()

    prospects = []
    for r in rows:
        # Extract FM codes (e.g. "FM-4 Body Breakdown" → "FM-4")
        fms = [
            x.split()[0]
            for x in [r["failure_mode_primary"], r["failure_mode_secondary"]]
            if x
        ]
        prospects.append({
            "prospect_id":        r["prospect_id"],
            "display_name":       r["display_name"],
            "position_group":     r["position_group"],
            "matched_archetype":  r["matched_archetype"] or r["position_group"],
            "active_fm_codes":    fms,
            "capital_range":      r["capital_adjusted"],  # use adjusted
            "apex_tier":          r["apex_tier"],
            "eval_confidence":    r["eval_confidence"],
            "divergence_rank_delta": r["divergence_rank_delta"],
        })
    return prospects


def _load_teams(conn) -> dict[str, dict]:
    """
    Load all 32 active team contexts from team_draft_context, including
    the scheme_family column added in the expand-to-32 seed pass.
    Returns a dict keyed by team_id.
    """
    rows = conn.execute(
        """
        SELECT
            team_id, team_name,
            development_timeline, risk_tolerance,
            primary_offense_family, primary_defense_family,
            coverage_bias, man_rate_tolerance,
            premium_needs_json, depth_chart_pressure_json,
            draft_capital_json, scheme_family, notes
        FROM team_draft_context
        WHERE season_id = ? AND is_active = 1
        ORDER BY team_id
        """,
        (SEASON_ID,),
    ).fetchall()

    teams = {}
    for r in rows:
        teams[r["team_id"]] = {
            "team_id":                r["team_id"],
            "team_name":              r["team_name"],
            "development_timeline":   r["development_timeline"],
            "risk_tolerance":         r["risk_tolerance"],
            "primary_offense_family": r["primary_offense_family"],
            "primary_defense_family": r["primary_defense_family"],
            "coverage_bias":          r["coverage_bias"],
            "man_rate_tolerance":     r["man_rate_tolerance"],
            "premium_needs":          _loads(r["premium_needs_json"], []),
            "depth_chart_pressure":   _loads(r["depth_chart_pressure_json"], {}),
            "draft_capital":          _loads(r["draft_capital_json"], {}),
            "scheme_family":          r["scheme_family"],
            "notes":                  r["notes"],
        }
    return teams


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _ensure_fit_table(conn) -> bool:
    """Create team_prospect_fit + indexes if they don't exist. Returns True if created."""
    existed = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
        "AND name='team_prospect_fit'"
    ).fetchone()[0]
    conn.execute(_CREATE_FIT_TABLE_SQL)
    for idx_sql in _CREATE_FIT_INDEX_SQL:
        conn.execute(idx_sql)
    return not existed


def _build_records(prospects: list[dict], teams: dict[str, dict], ts: str) -> list[tuple]:
    """
    Compute evaluate_team_fit() for every prospect × team and return a list of
    INSERT tuples.  Pure computation — no DB access.
    """
    records: list[tuple] = []
    for prospect in prospects:
        for team_id, team_ctx in teams.items():
            result     = evaluate_team_fit(prospect, team_ctx)
            fit_score  = _recompute_composite(result)
            fit_tier   = _fit_tier(fit_score)
            explanation = _fit_explanation(prospect, team_ctx, result)
            records.append((
                prospect["prospect_id"],
                team_id,
                SEASON_ID,
                fit_score,
                fit_tier,
                result["deployment_fit"],
                result["pick_fit"],
                result["fm_risk_score"],
                result["verdict"],
                json.dumps(result["why_for"]),
                json.dumps(result["why_against"]),
                result["confidence"],
                explanation,
                ts,
            ))
    return records


def _run(apply: bool) -> None:
    with connect() as conn:
        # ------------------------------------------------------------------
        # Load universe
        # ------------------------------------------------------------------
        prospects = _load_prospects(conn)
        teams     = _load_teams(conn)

        print(f"Prospects loaded : {len(prospects)}")
        print(f"Teams loaded     : {len(teams)}")
        print(f"Rows to compute  : {len(prospects) * len(teams)}")
        print(f"Mode             : {'APPLY' if apply else 'DRY RUN'}")
        print()

        if len(prospects) == 0:
            print("ERROR: No prospects found. Check apex_v2.3 model_version in apex_scores.")
            sys.exit(1)
        if len(teams) == 0:
            print("ERROR: No teams found. Run seed_team_draft_context_2026 first.")
            sys.exit(1)

        # ------------------------------------------------------------------
        # Compute all records (no DB writes yet)
        # ------------------------------------------------------------------
        ts      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        records = _build_records(prospects, teams, ts)
        print(f"Records computed : {len(records)}")

        # Tier distribution summary
        tier_counts: dict[str, int] = {}
        for r in records:
            tier_counts[r[4]] = tier_counts.get(r[4], 0) + 1
        for tier in ("IDEAL", "STRONG", "VIABLE", "FRINGE", "POOR"):
            print(f"  {tier:<7} : {tier_counts.get(tier, 0)}")
        print()

        if not apply:
            # Sample: top-5 fit scores across all pairs
            sorted_recs = sorted(records, key=lambda r: r[3], reverse=True)
            print("Top-5 fit pairs (dry run preview):")
            for rec in sorted_recs[:5]:
                print(f"  pid={rec[0]:>5d}  team={rec[1]:<5s}  score={rec[3]:>5.1f}  tier={rec[4]}  {rec[12][:60]}")
            print()
            print("Dry run complete. No changes written.")
            return

        # ------------------------------------------------------------------
        # Apply
        # ------------------------------------------------------------------
        backup_path = backup_db()
        print(f"Backup : {backup_path}")

        table_created = _ensure_fit_table(conn)
        if table_created:
            print("team_prospect_fit table created (new).")
        else:
            print("team_prospect_fit table already exists.")

        conn.executemany(_INSERT_SQL, records)
        conn.commit()

        # Verify
        count = conn.execute(
            "SELECT COUNT(*) FROM team_prospect_fit WHERE season_id = ?",
            (SEASON_ID,),
        ).fetchone()[0]
        print(f"Verified : {count} rows in team_prospect_fit (season_id={SEASON_ID})")

        tier_dist = conn.execute(
            """
            SELECT fit_tier, COUNT(*) cnt
            FROM team_prospect_fit
            WHERE season_id = ?
            GROUP BY fit_tier
            ORDER BY cnt DESC
            """,
            (SEASON_ID,),
        ).fetchall()
        print("Tier distribution (DB):")
        for r in tier_dist:
            print(f"  {r['fit_tier']:<7} : {r['cnt']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild team-fit layer for all 300 APEX v2.3 prospects × 32 teams."
    )
    parser.add_argument(
        "--apply",
        type=int,
        default=0,
        choices=[0, 1],
        help="0 = dry run (default), 1 = write to DB",
    )
    args = parser.parse_args()
    _run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
