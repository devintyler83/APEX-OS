"""
scripts/seed_team_draft_context_2026.py

Seed all 32 NFL teams into team_draft_context for season_id=1 (2026 draft).

Behavior
--------
- 8 pilot teams (BAL, CLE, DET, GB, KC, MIA, NYJ, PHI) already have
  detailed scheme profiles seeded in the prior pass.  Their rows are
  untouched — INSERT OR IGNORE on the (team_id, season_id) composite PK
  guarantees idempotency.
- 24 remaining teams receive a deterministic default "balanced-prototype"
  row.  Downstream editors update these per-team as scheme intel arrives.
- Additive column migration: adds scheme_family / offense_style /
  defense_structure / positional_emphasis to team_draft_context if those
  columns are not already present.  Safe to re-run on any DB state.

Constraints
-----------
- season_id=1 only.  Script refuses to touch any other season.
- Backup is created before every write operation (--apply 1).
- Dry-run (--apply 0) prints what would be inserted; no DB mutation.

Usage
-----
    python -m scripts.seed_team_draft_context_2026 --apply 0   # dry run
    python -m scripts.seed_team_draft_context_2026 --apply 1   # write
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
from draftos.queries.team_fit import _NFL_32_TEAMS  # canonical 32-team registry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEASON_ID = 1

# Default positional emphasis weights for un-profiled teams.
# Keys mirror APEX position_group labels.  Values scale the fit score
# the same way PVC weights scale APEX composite — multiply, not add.
_DEFAULT_POSITIONAL_EMPHASIS: dict[str, float] = {
    "QB":  1.00,
    "CB":  1.00,
    "EDGE": 1.00,
    "OT":  0.95,
    "S":   0.90,
    "IDL": 0.90,
    "WR":  0.90,
    "ILB": 0.85,
    "OLB": 0.85,
    "OG":  0.80,
    "C":   0.80,
    "TE":  0.80,
    "RB":  0.70,
}

_DEFAULT_POSITIONAL_EMPHASIS_JSON = json.dumps(_DEFAULT_POSITIONAL_EMPHASIS)

# New columns to add additively if not already present.
# Each tuple: (column_name, sql_type, default_literal)
_NEW_COLUMNS: list[tuple[str, str, str]] = [
    ("scheme_family",      "TEXT", "NULL"),
    ("offense_style",      "TEXT", "NULL"),
    ("defense_structure",  "TEXT", "NULL"),
    ("positional_emphasis","TEXT", "NULL"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def backup_db() -> Path:
    """Copy the canonical DB to data/exports/backups/ with a UTC timestamp."""
    src     = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst     = out_dir / f"draftos_{ts}_seed_team_draft_context.sqlite"
    shutil.copy2(src, dst)
    return dst


def _column_names(conn) -> set[str]:
    """Return the set of column names currently on team_draft_context."""
    rows = conn.execute("PRAGMA table_info(team_draft_context)").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(conn) -> list[str]:
    """
    Add any missing columns from _NEW_COLUMNS via ALTER TABLE.
    Returns list of column names that were added (empty if all existed).
    Idempotent — safe to call on every run.
    """
    existing = _column_names(conn)
    added: list[str] = []
    for col_name, col_type, _default in _NEW_COLUMNS:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE team_draft_context ADD COLUMN {col_name} {col_type}"
            )
            added.append(col_name)
    return added


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _run(apply: bool) -> None:
    with connect() as conn:
        # -- Gate: table must exist ----------------------------------------
        tbl_exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='team_draft_context'"
        ).fetchone()[0]
        if not tbl_exists:
            print("ERROR: team_draft_context table not found. Apply migration 0049 first.")
            sys.exit(1)

        # -- Backup before any write ----------------------------------------
        if apply:
            backup_path = backup_db()
            print(f"Backup: {backup_path}\n")

        # -- Additive column migration (dry-run prints intent, apply executes)
        if apply:
            added_cols = _ensure_columns(conn)
            if added_cols:
                print(f"Columns added: {added_cols}")
            else:
                print("Schema: all expected columns already present.")
        else:
            existing_cols = _column_names(conn)
            missing_cols  = [c for c, _, _ in _NEW_COLUMNS if c not in existing_cols]
            if missing_cols:
                print(f"DRY RUN — would add columns: {missing_cols}")
            else:
                print("Schema: all expected columns already present.")

        print()
        print(f"Mode:      {'APPLY' if apply else 'DRY RUN'}")
        print(f"Season:    {SEASON_ID}")
        print(f"Teams:     {len(_NFL_32_TEAMS)}")
        print()

        inserted = 0
        skipped  = 0

        for team in _NFL_32_TEAMS:
            team_id   = team["team_id"]
            team_name = team["team_name"]

            existing = conn.execute(
                "SELECT team_id FROM team_draft_context "
                "WHERE season_id = ? AND team_id = ?",
                (SEASON_ID, team_id),
            ).fetchone()

            if existing:
                print(f"  SKIP   {team_id:<5s}  {team_name}")
                skipped += 1
                continue

            if apply:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO team_draft_context (
                        season_id,
                        team_id,
                        team_name,
                        development_timeline,
                        risk_tolerance,
                        primary_offense_family,
                        primary_defense_family,
                        coverage_bias,
                        man_rate_tolerance,
                        premium_needs_json,
                        depth_chart_pressure_json,
                        draft_capital_json,
                        scheme_family,
                        offense_style,
                        defense_structure,
                        positional_emphasis,
                        notes,
                        is_active
                    ) VALUES (
                        1, ?, ?,
                        'balanced', 'medium',
                        'balanced', 'multiple-front',
                        'mixed', 'medium',
                        '[]', '{}', '{}',
                        'balanced-prototype', 'balanced', 'multiple-front',
                        ?, ?, 1
                    )
                    """,
                    (
                        team_id,
                        team_name,
                        _DEFAULT_POSITIONAL_EMPHASIS_JSON,
                        "2026 default seeded context v1.0; update per-team manually as needed.",
                    ),
                )
                print(f"  INSERT {team_id:<5s}  {team_name}")
                inserted += 1
            else:
                print(f"  DRY    {team_id:<5s}  {team_name}  (would insert)")
                inserted += 1

        if apply:
            conn.commit()

        # -- Summary --------------------------------------------------------
        print()
        print(f"Result: {inserted} inserted, {skipped} skipped (of {len(_NFL_32_TEAMS)} teams)")

        if apply:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM team_draft_context "
                "WHERE season_id = ? AND is_active = 1",
                (SEASON_ID,),
            ).fetchone()[0]
            print(f"Verify: {active_count} active rows in team_draft_context (season_id={SEASON_ID})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed all 32 NFL teams into team_draft_context (season_id=1)."
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
