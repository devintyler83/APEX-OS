"""
scripts/mark_drafted_2026.py — Draft Mode pick recorder (2026)

Records a single drafted player into drafted_picks_2026 for the 2026 season.

Validation before any write:
  - prospect must exist in v_draft_targets_2026 (season_id=1, any team)
  - prospect must not already appear in drafted_picks_2026 for season_id=1
  - pick_number must not already be used in drafted_picks_2026 for season_id=1

Dry run (--apply 0, default): prints the row that would be written, makes no changes.
Apply     (--apply 1)        : backs up DB, then writes one row to drafted_picks_2026.

Usage:
    # Dry run (safe to run anytime)
    python -m scripts.mark_drafted_2026 \\
        --pick-number 1 --round-number 1 --team PHI --prospect-id 5

    # Apply
    python -m scripts.mark_drafted_2026 \\
        --pick-number 1 --round-number 1 --team PHI --prospect-id 5 --apply 1

    # With optional note and source
    python -m scripts.mark_drafted_2026 \\
        --pick-number 32 --team KC --prospect-id 42 \\
        --note "Traded up from pick 38" --source manual --apply 1
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.config import PATHS
from draftos.db.connect import connect


def _backup_db(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_mark_drafted.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record a drafted player into drafted_picks_2026 (season_id=1)."
    )
    parser.add_argument("--pick-number",  type=int, required=True,
                        help="Overall pick number (e.g. 1, 32, 257).")
    parser.add_argument("--round-number", type=int, default=None,
                        help="Round number (optional; 1–7).")
    parser.add_argument("--team",         type=str, required=True,
                        help="Drafting team abbreviation (e.g. PHI, KC).")
    parser.add_argument("--prospect-id",  type=int, required=True,
                        help="Prospect ID (prospect_id in prospects table).")
    parser.add_argument("--note",         type=str, default=None,
                        help="Optional free-text note (e.g. 'Traded up').")
    parser.add_argument("--source",       type=str, default="manual",
                        help="Source label (default: manual).")
    parser.add_argument("--draft-session-label", type=str, default=None,
                        dest="draft_session_label",
                        help="Optional session label (e.g. 'S93_draftnight').")
    parser.add_argument("--apply",        type=int, choices=[0, 1], default=0,
                        help="0 = dry run (default), 1 = write to DB.")
    args = parser.parse_args()

    season_id   = 1
    pick_number = args.pick_number
    prospect_id = args.prospect_id
    team        = args.team.strip().upper()

    with connect() as conn:
        # ── Validation 1: prospect exists in v_draft_targets_2026 ─────────────
        target_row = conn.execute(
            """
            SELECT prospect_id, consensus_rank, fit_tier
            FROM v_draft_targets_2026
            WHERE prospect_id = ? AND season_id = ?
            LIMIT 1
            """,
            (prospect_id, season_id),
        ).fetchone()

        if target_row is None:
            print(
                f"REJECT: prospect_id={prospect_id} not found in v_draft_targets_2026 "
                f"for season_id={season_id}.\n"
                f"Ensure the prospect has an active consensus and divergence row."
            )
            sys.exit(1)

        # ── Validation 2: prospect not already drafted ────────────────────────
        existing_pid = conn.execute(
            "SELECT pick_number FROM drafted_picks_2026 WHERE season_id=? AND prospect_id=?",
            (season_id, prospect_id),
        ).fetchone()
        if existing_pid is not None:
            print(
                f"REJECT: prospect_id={prospect_id} already drafted at "
                f"pick #{existing_pid['pick_number']} this season."
            )
            sys.exit(1)

        # ── Validation 3: pick number not already used ────────────────────────
        existing_pick = conn.execute(
            "SELECT prospect_id FROM drafted_picks_2026 WHERE season_id=? AND pick_number=?",
            (season_id, pick_number),
        ).fetchone()
        if existing_pick is not None:
            print(
                f"REJECT: pick_number={pick_number} already used (prospect_id="
                f"{existing_pick['prospect_id']}) this season."
            )
            sys.exit(1)

        # ── Resolve display name for confirmation output ──────────────────────
        name_row = conn.execute(
            "SELECT display_name, position_group FROM prospects WHERE prospect_id=?",
            (prospect_id,),
        ).fetchone()
        display_name   = name_row["display_name"]   if name_row else f"pid={prospect_id}"
        position_group = name_row["position_group"] if name_row else "?"

        drafted_at = _utc_now_iso()

    row_preview = {
        "season_id":           season_id,
        "pick_number":         pick_number,
        "round_number":        args.round_number,
        "drafting_team":       team,
        "prospect_id":         prospect_id,
        "drafted_at":          drafted_at,
        "draft_session_label": args.draft_session_label,
        "source":              args.source,
        "note":                args.note,
    }

    print("=" * 60)
    print("MARK DRAFTED — 2026 (season_id=1)")
    print("=" * 60)
    print(f"  Prospect   : {display_name} ({position_group}) — pid={prospect_id}")
    print(f"  Pick       : #{pick_number}" + (f" (Round {args.round_number})" if args.round_number else ""))
    print(f"  Team       : {team}")
    print(f"  Source     : {args.source}")
    if args.note:
        print(f"  Note       : {args.note}")
    if args.draft_session_label:
        print(f"  Session    : {args.draft_session_label}")
    print(f"  drafted_at : {drafted_at}")
    print(f"  fit_tier   : {dict(target_row)['fit_tier']}")
    print(f"  consensus# : {dict(target_row)['consensus_rank']}")
    print()

    if args.apply == 0:
        print("DRY RUN: no DB writes. Re-run with --apply 1 to record.")
        return

    # ── Apply: backup then write ──────────────────────────────────────────────
    backup_path = _backup_db(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO drafted_picks_2026
                (season_id, pick_number, round_number, drafting_team, prospect_id,
                 drafted_at, draft_session_label, source, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                season_id,
                pick_number,
                args.round_number,
                team,
                prospect_id,
                drafted_at,
                args.draft_session_label,
                args.source,
                args.note,
            ),
        )
        conn.commit()

    print(f"OK: pick #{pick_number} — {display_name} ({team}) written to drafted_picks_2026.")


if __name__ == "__main__":
    main()
