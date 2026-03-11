"""
log_draft_pick_2026.py -- Draft Night Pick Logger (Session 22)

Fast, single-command script for logging picks live on draft night.
Two actions fire atomically per pick:
  1. INSERT into draft_results (frozen snapshot fields + pick metadata)
  2. UPDATE prospects.board_status -> 'drafted'

MODES:
  log      -- log a single pick
  tracker  -- print live pick board with APEX signal

Usage:
    python -m scripts.log_draft_pick_2026 log \\
        --pick 1 --round 1 --pick-in-round 1 \\
        --team "Jacksonville Jaguars" --abbrev JAX \\
        --name "Travis Hunter" [--trade-up] [--notes "TEXT"] [--yes]

    python -m scripts.log_draft_pick_2026 tracker

Constraints:
  - season_id = 1, model_version = 'apex_v2.2'
  - No writes to apex_scores, consensus_rankings, divergence_flags, or tag tables
  - DB backup on first pick of each script run (not every call)
  - UNIQUE constraint on (season_id, pick_overall) and (prospect_id, season_id)
  - career_outcome is never written here -- post-draft audit only
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from draftos.config import PATHS

SEASON_ID     = 1
MODEL_VERSION = "apex_v2.2"

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(PATHS.db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _backup_db() -> None:
    db_path = PATHS.db
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak     = db_path.parent / f"{db_path.stem}.backup.draftnight_{ts}{db_path.suffix}"
    shutil.copy2(str(db_path), str(bak))
    print(f"  [backup] DB backed up -> {bak.name}")


# ---------------------------------------------------------------------------
# Prospect resolution (6-step fuzzy match)
# ---------------------------------------------------------------------------

def resolve_prospect(conn: sqlite3.Connection, name: str, pid: int | None) -> dict:
    """
    6-step name matching against active, available prospects.
    Returns a prospect dict on unambiguous match.
    Raises SystemExit with an actionable message on any failure.
    """
    base_q = """
        SELECT prospect_id, display_name, position_group, school_canonical
        FROM   prospects
        WHERE  season_id        = ?
          AND  is_active        = 1
          AND  board_status     = 'available'
          AND  school_canonical NOT LIKE '__dedup_%'
    """

    # If caller supplied --pid, go straight to lookup
    if pid is not None:
        row = conn.execute(
            base_q + " AND prospect_id = ?", (SEASON_ID, pid)
        ).fetchone()
        if row is None:
            # Check if already drafted
            drafted = conn.execute(
                "SELECT display_name FROM prospects WHERE prospect_id=? AND season_id=?",
                (pid, SEASON_ID)
            ).fetchone()
            if drafted:
                _check_already_drafted(conn, pid, drafted["display_name"])
            sys.exit(f"[ERROR] No active available prospect with prospect_id={pid}.")
        return dict(row)

    name_clean = name.strip()

    # STEP 1 — Exact match (case-insensitive)
    rows = conn.execute(
        base_q + " AND LOWER(display_name) = LOWER(?)", (SEASON_ID, name_clean)
    ).fetchall()

    # STEP 2 — Partial: input contained in display_name
    if not rows:
        rows = conn.execute(
            base_q + " AND LOWER(display_name) LIKE LOWER(?)",
            (SEASON_ID, f"%{name_clean}%")
        ).fetchall()

    # STEP 3 — Last token of input used as last-name search
    if not rows:
        tokens = name_clean.split()
        last   = tokens[-1] if tokens else name_clean
        rows   = conn.execute(
            base_q + " AND LOWER(display_name) LIKE LOWER(?)",
            (SEASON_ID, f"%{last}%")
        ).fetchall()

    # STEP 4 — No matches
    if not rows:
        # Check if name matches a drafted prospect
        already = conn.execute(
            """SELECT display_name, position_group
               FROM prospects
               WHERE season_id=? AND is_active=1
                 AND board_status='drafted'
                 AND LOWER(display_name) LIKE LOWER(?)""",
            (SEASON_ID, f"%{name_clean}%")
        ).fetchall()
        if already:
            p = already[0]
            sys.exit(
                f"[ERROR] '{name}' matches '{p['display_name']}' ({p['position_group']}) "
                f"who is already marked as drafted. Use tracker to verify."
            )
        # Suggest nearby names by position group if possible
        tokens = name_clean.split()
        last   = tokens[-1] if tokens else name_clean
        suggestions = conn.execute(
            base_q + " AND LOWER(display_name) LIKE LOWER(?) LIMIT 5",
            (SEASON_ID, f"%{last[0]}%")
        ).fetchall()
        msg = f"[ERROR] No active available prospect matched '{name}'."
        if suggestions:
            msg += "\nClosest partial matches:\n"
            for s in suggestions:
                msg += f"  pid={s['prospect_id']:>5}  {s['display_name']:<30}  {s['position_group']}  {s['school_canonical']}\n"
        sys.exit(msg)

    # STEP 5 — Multiple matches
    if len(rows) > 1:
        msg = f"[AMBIGUOUS] '{name}' matched {len(rows)} prospects. Add --pid to disambiguate:\n"
        for r in rows:
            msg += (
                f"  pid={r['prospect_id']:>5}  {r['display_name']:<30}  "
                f"{r['position_group']:<6}  {r['school_canonical']}\n"
            )
        sys.exit(msg)

    # STEP 6 — Exactly one match
    return dict(rows[0])


def _check_already_drafted(conn: sqlite3.Connection, pid: int, name: str) -> None:
    """Exits with error if prospect is already in draft_results."""
    dr = conn.execute(
        "SELECT pick_overall FROM draft_results WHERE prospect_id=? AND season_id=?",
        (pid, SEASON_ID)
    ).fetchone()
    if dr:
        sys.exit(
            f"[ERROR] {name} already logged as pick #{dr['pick_overall']}. "
            "No duplicate entries. Use tracker to verify."
        )


# ---------------------------------------------------------------------------
# APEX context fetch
# ---------------------------------------------------------------------------

def fetch_apex_context(conn: sqlite3.Connection, prospect_id: int) -> dict:
    """
    Pulls apex_composite, apex_tier, capital_adjusted, consensus_rank,
    divergence_flag, divergence_rank_delta, and active tag names.
    Returns dict with None values if rows absent.
    """
    apex_row = conn.execute(
        """SELECT apex_composite, apex_tier, capital_adjusted
           FROM   apex_scores
           WHERE  prospect_id   = ?
             AND  season_id     = ?
             AND  model_version = ?""",
        (prospect_id, SEASON_ID, MODEL_VERSION)
    ).fetchone()

    cons_row = conn.execute(
        """SELECT consensus_rank
           FROM   prospect_consensus_rankings
           WHERE  prospect_id = ?
             AND  season_id   = ?""",
        (prospect_id, SEASON_ID)
    ).fetchone()

    div_row = conn.execute(
        """SELECT divergence_flag, divergence_rank_delta
           FROM   divergence_flags
           WHERE  prospect_id   = ?
             AND  season_id     = ?
             AND  model_version = ?""",
        (prospect_id, SEASON_ID, MODEL_VERSION)
    ).fetchone()

    tags = conn.execute(
        """SELECT td.tag_name
           FROM   prospect_tags pt
           JOIN   tag_definitions td ON td.tag_def_id = pt.tag_def_id
           WHERE  pt.prospect_id = ?
             AND  pt.is_active   = 1""",
        (prospect_id,)
    ).fetchall()

    return {
        "apex_composite":      apex_row["apex_composite"]    if apex_row else None,
        "apex_tier":           apex_row["apex_tier"]         if apex_row else None,
        "capital_adjusted":    apex_row["capital_adjusted"]  if apex_row else None,
        "consensus_rank":      cons_row["consensus_rank"]    if cons_row else None,
        "divergence_flag":     div_row["divergence_flag"]    if div_row  else None,
        "divergence_rank_delta": div_row["divergence_rank_delta"] if div_row else None,
        "tags":                [t["tag_name"] for t in tags],
    }


# ---------------------------------------------------------------------------
# Confirmation display
# ---------------------------------------------------------------------------

def _fmt_div(flag: str | None, delta: int | None) -> str:
    if flag is None:
        return "-"
    # normalise space-style legacy values
    flag_norm = flag.replace(" ", "_")
    delta_str = f"  rank_delta: {delta:+d}" if delta is not None else ""
    return f"{flag_norm}{delta_str}"


def _show_confirmation(prospect: dict, args, apex_ctx: dict) -> None:
    trade_str = "Yes" if args.trade_up else "No"
    abbrev    = args.abbrev or args.team[:3].upper()

    apex_score = f"{apex_ctx['apex_composite']:.1f}" if apex_ctx["apex_composite"] is not None else "---"
    apex_tier  = apex_ctx["apex_tier"] or "-"
    capital    = apex_ctx["capital_adjusted"] or "-"
    cons_rank  = str(apex_ctx["consensus_rank"]) if apex_ctx["consensus_rank"] is not None else "-"
    div_str    = _fmt_div(apex_ctx["divergence_flag"], apex_ctx["divergence_rank_delta"])
    tags_str   = ", ".join(apex_ctx["tags"]) if apex_ctx["tags"] else "-"

    print()
    print("=== DRAFT NIGHT LOG — CONFIRM PICK ===")
    print()
    print(f"  Pick #{args.pick:<4} Round {args.round}  Pick {args.pick_in_round} in round")
    print(f"  Team:     {args.team} ({abbrev})")
    print(f"  Player:   {prospect['display_name']}")
    print(f"  Position: {prospect['position_group']} | {prospect['school_canonical']}")
    print(f"  Trade-up: {trade_str}")
    print()
    print(f"  APEX at draft:  {apex_score}  Tier: {apex_tier}  Capital: {capital}")
    print(f"  Consensus rank: {cons_rank}")
    print(f"  Divergence:     {div_str}")
    print()
    print(f"  Tags at draft:  {tags_str}")
    print()


# ---------------------------------------------------------------------------
# Write: atomic INSERT + UPDATE
# ---------------------------------------------------------------------------

def log_pick(
    conn: sqlite3.Connection,
    prospect: dict,
    args,
    apex_ctx: dict,
    backed_up: bool,
) -> bool:
    """
    Atomic transaction: INSERT draft_results + UPDATE board_status.
    Returns True on success, False on UNIQUE conflict (caller handles messaging).
    """
    abbrev = args.abbrev or args.team[:3].upper()

    # Check UNIQUE constraints before attempting write
    existing_pick = conn.execute(
        "SELECT p.display_name FROM draft_results dr JOIN prospects p ON p.prospect_id=dr.prospect_id "
        "WHERE dr.season_id=? AND dr.pick_overall=?",
        (SEASON_ID, args.pick)
    ).fetchone()
    if existing_pick:
        print(
            f"[ERROR] Pick #{args.pick} already logged for {existing_pick['display_name']}. "
            "Use tracker to verify."
        )
        return False

    existing_player = conn.execute(
        "SELECT pick_overall FROM draft_results WHERE season_id=? AND prospect_id=?",
        (SEASON_ID, prospect["prospect_id"])
    ).fetchone()
    if existing_player:
        print(
            f"[ERROR] {prospect['display_name']} already logged as pick #{existing_player['pick_overall']}. "
            "No duplicate entries."
        )
        return False

    try:
        with conn:
            conn.execute(
                """INSERT INTO draft_results (
                       prospect_id, season_id, pick_overall, pick_round, pick_in_round,
                       team_name, team_abbrev, was_trade_up, trade_details,
                       apex_score_at_draft, apex_tier_at_draft,
                       consensus_rank_at_draft, divergence_at_draft,
                       notes, career_outcome
                   ) VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,NULL)""",
                (
                    prospect["prospect_id"],
                    SEASON_ID,
                    args.pick,
                    args.round,
                    args.pick_in_round,
                    args.team,
                    abbrev,
                    1 if args.trade_up else 0,
                    apex_ctx["apex_composite"],
                    apex_ctx["apex_tier"],
                    apex_ctx["consensus_rank"],
                    apex_ctx["divergence_rank_delta"],
                    getattr(args, "notes", None),
                )
            )
            conn.execute(
                """UPDATE prospects
                   SET    board_status = 'drafted',
                          updated_at   = datetime('now')
                   WHERE  prospect_id  = ?
                     AND  season_id    = ?""",
                (prospect["prospect_id"], SEASON_ID)
            )
    except sqlite3.IntegrityError as exc:
        print(f"[ERROR] Write failed (integrity constraint): {exc}")
        return False

    return True


# ---------------------------------------------------------------------------
# Tracker mode
# ---------------------------------------------------------------------------

def _div_marker(flag: str | None) -> str:
    if flag is None:
        return ""
    f = flag.replace(" ", "_")
    if "APEX_HIGH" in f:
        return " \u2191"   # ↑
    if "APEX_LOW" in f:
        return " \u2193"   # ↓
    return ""


def show_tracker(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """SELECT
               dr.pick_overall,
               dr.pick_round,
               dr.pick_in_round,
               dr.team_abbrev,
               p.display_name,
               p.position_group,
               dr.apex_tier_at_draft,
               dr.apex_score_at_draft,
               dr.divergence_at_draft,
               df.divergence_flag
           FROM draft_results dr
           JOIN prospects p ON p.prospect_id = dr.prospect_id
           LEFT JOIN divergence_flags df
                  ON df.prospect_id   = dr.prospect_id
                 AND df.season_id     = dr.season_id
                 AND df.model_version = ?
           WHERE dr.season_id = ?
           ORDER BY dr.pick_overall""",
        (MODEL_VERSION, SEASON_ID)
    ).fetchall()

    print()
    print("=== 2026 NFL DRAFT — LIVE TRACKER ===")
    if not rows:
        print("  No picks logged yet.")
        print()
        return

    print(f"  Picks logged: {len(rows)}")
    print()
    print(f"  {'#':>4}  {'Rd.Pk':>5}  {'Team':>4}  {'Name':<28}  {'Pos':<6}  {'Tier':<5}  {'Score':>5}  Divergence")
    print("  " + "-" * 80)

    for r in rows:
        apex_tier  = r["apex_tier_at_draft"] or "-"
        apex_score = f"{r['apex_score_at_draft']:.1f}" if r["apex_score_at_draft"] is not None else "---"
        div_flag   = r["divergence_flag"] or "-"
        div_norm   = div_flag.replace(" ", "_") if div_flag != "-" else "-"
        marker     = _div_marker(r["divergence_flag"])

        print(
            f"  #{r['pick_overall']:>3}  "
            f"R{r['pick_round']}.{r['pick_in_round']:>02}  "
            f"{r['team_abbrev']:>4}  "
            f"{r['display_name']:<28}  "
            f"{r['position_group']:<6}  "
            f"{apex_tier:<5}  "
            f"{apex_score:>5}  "
            f"{div_norm}{marker}"
        )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log_draft_pick_2026",
        description="DraftOS 2026 — Draft Night Pick Logger",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # -- log subcommand
    log_p = sub.add_parser("log", help="Log a single draft pick")
    log_p.add_argument("--pick",          type=int,   required=True, help="Overall pick number")
    log_p.add_argument("--round",         type=int,   required=True, help="Round number")
    log_p.add_argument("--pick-in-round", type=int,   required=True, dest="pick_in_round",
                       help="Pick number within round")
    log_p.add_argument("--team",          type=str,   required=True, help="Full team name")
    log_p.add_argument("--name",          type=str,   required=True, help="Player name (fuzzy matched)")
    log_p.add_argument("--abbrev",        type=str,   default=None,  help="Team abbreviation (e.g. PHI)")
    log_p.add_argument("--pid",           type=int,   default=None,  help="Prospect ID (disambiguate multi-match)")
    log_p.add_argument("--trade-up",      action="store_true", dest="trade_up",
                       help="Flag: team traded up for this pick")
    log_p.add_argument("--notes",         type=str,   default=None,  help="Draft night observation text")
    log_p.add_argument("--yes",           action="store_true",       help="Skip confirmation prompt")
    log_p.add_argument("--apply",         type=int,   default=1,     choices=[0, 1],
                       help="0=dry run (default shows confirmation only), 1=write (default)")

    # -- tracker subcommand
    sub.add_parser("tracker", help="Show live draft pick tracker")

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    conn = _get_conn()

    if args.mode == "tracker":
        show_tracker(conn)
        conn.close()
        return

    # ---- LOG mode ----
    if args.apply == 0:
        print("[DRY RUN] No writes will be made.")

    # Resolve prospect
    prospect = resolve_prospect(conn, args.name, args.pid)

    # Guard: already drafted but somehow still hit (edge case for --pid path)
    if prospect.get("board_status") == "drafted":
        _check_already_drafted(conn, prospect["prospect_id"], prospect["display_name"])

    # Fetch APEX context
    apex_ctx = fetch_apex_context(conn, prospect["prospect_id"])

    # Show confirmation
    _show_confirmation(prospect, args, apex_ctx)

    if args.apply == 0:
        print("[DRY RUN] Would write the above pick. Re-run with --apply 1 to log.")
        conn.close()
        return

    # Prompt unless --yes
    if not args.yes:
        try:
            answer = input("Confirm? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            conn.close()
            sys.exit(0)
        if answer != "y":
            print("Aborted.")
            conn.close()
            sys.exit(0)

    # Backup DB (once per script invocation — check sentinel file in temp dir)
    import tempfile
    sentinel = Path(tempfile.gettempdir()) / "draftos_draftnight_backed_up"
    if not sentinel.exists():
        _backup_db()
        sentinel.touch()

    success = log_pick(conn, prospect, args, apex_ctx, backed_up=True)

    if success:
        abbrev = args.abbrev or args.team[:3].upper()
        apex_score = f"{apex_ctx['apex_composite']:.1f}" if apex_ctx["apex_composite"] is not None else "---"
        print(
            f"\n[OK] Pick #{args.pick} logged: "
            f"{abbrev} selects {prospect['display_name']} "
            f"({prospect['position_group']}) — APEX {apex_score} {apex_ctx['apex_tier'] or '-'}"
        )
    else:
        conn.close()
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
