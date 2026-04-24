"""
S76: Triage divergence_flags for Gabe Jacas (CONFIRMED_LEGITIMATE) and
     R. Mason Thomas (DISMISSED_INFLATION).
Run: python -m scripts.divergence_triage_jacas_thomas_s76 --apply 0|1
"""
import argparse
import datetime
import shutil
import sqlite3

DB_PATH = "data/edge/draftos.sqlite"
SEASON_ID = 1
MODEL_VERSION = "apex_v2.3"

JACAS_STATUS = "CONFIRMED_LEGITIMATE"
JACAS_RATIONALE = (
    "EDGE-3 Power-Counter Technician archetype confirmed. Mechanism: stab-chop combination, "
    "bull/long-arm primary, Ghost as counter feel move (70 wins, 38.6% win rate, Ghost 1.4% "
    "per-move but Ghost usage confirms processing-based winning). Power Technique 87, Hand "
    "Usage/Counters 74. Divergence is real: APEX weights power technique and counter sequencing "
    "quality as primary Production vector for EDGE-3; consensus weights Bend and Arc Speed as "
    "athleticism ceiling for all EDGE archetypes equally. FM-2 is the legitimate risk — run "
    "defense (Play Recognition 25, Block Avoidance 45) limits every-down deployment. Signal "
    "is valid APEX_HIGH. Do not suppress."
)

THOMAS_STATUS = "DISMISSED_INFLATION"
THOMAS_RATIONALE = (
    "EDGE-2 Speed-Bend Specialist archetype confirmed on bend profile (Bend 95, Arc Speed 83, "
    "Explosiveness 94) but FM-6 + FM-2 compound fires. Physical profile disqualifies every-down "
    "deployment: 6022, 241 lbs, ARM 31.63 (red), HND 8.88 (red), Anchor 28, Block Shedding 29, "
    "Run Defense 24.6. Pass rush mechanism is real but single-dimensional — Counters 31, Hand "
    "Usage 46, success collapses in prolonged hand-fighting (FM-2). APEX_HIGH signal is "
    "inflation: APEX scores the pass rush ceiling correctly but does not sufficiently penalize "
    "deployment ceiling (specialist-only at 241 lbs). Capital floor Round 3, not Round 2. "
    "Dismissed."
)

TRIAGED_BY = "session_s76_mode2_handoff"


def _lookup_pid(conn, name_pattern: str, position_group: str | None = None,
                school: str | None = None) -> tuple[int | None, str]:
    """Return (pid, display_name) or (None, error_message)."""
    sql = (
        "SELECT prospect_id, display_name, position_group, school_canonical "
        "FROM prospects WHERE display_name LIKE ? AND is_active=1 AND season_id=?"
    )
    params: list = [f"%{name_pattern}%", SEASON_ID]
    if position_group:
        sql += " AND position_group=?"
        params.append(position_group)
    rows = conn.execute(sql, params).fetchall()

    if school:
        rows = [r for r in rows if (r["school_canonical"] or "").lower() == school.lower()]

    if len(rows) == 0:
        return None, f"No active prospect found matching '{name_pattern}'"
    if len(rows) > 1:
        return None, f"Multiple matches for '{name_pattern}': {[(r['prospect_id'], r['display_name']) for r in rows]}"
    return rows[0]["prospect_id"], rows[0]["display_name"]


def _get_div_row(conn, pid: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM divergence_flags WHERE prospect_id=? AND season_id=? AND model_version=?",
        (pid, SEASON_ID, MODEL_VERSION),
    ).fetchone()
    return dict(row) if row else None


def _upsert_triage(conn, pid: int, status: str, rationale: str, triaged_at: str,
                   div_row: dict | None) -> None:
    if div_row:
        conn.execute(
            "UPDATE divergence_flags SET status=?, triage_rationale=?, triaged_by=?, triaged_at=? "
            "WHERE prospect_id=? AND season_id=? AND model_version=?",
            (status, rationale, TRIAGED_BY, triaged_at, pid, SEASON_ID, MODEL_VERSION),
        )
    else:
        conn.execute(
            "INSERT INTO divergence_flags "
            "(prospect_id, season_id, model_version, apex_composite, apex_tier, "
            "consensus_ovr_rank, divergence_flag, divergence_mag, divergence_rank_delta, "
            "computed_at, status, triage_rationale, triaged_by, triaged_at) "
            "VALUES (?, ?, ?, 0, 'UNKNOWN', NULL, 'UNKNOWN', NULL, NULL, ?, ?, ?, ?, ?)",
            (pid, SEASON_ID, MODEL_VERSION, triaged_at,
             status, rationale, TRIAGED_BY, triaged_at),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── JACAS lookup ──────────────────────────────────────────────────────────
    jacas_pid, jacas_name = _lookup_pid(conn, "Jacas", position_group="EDGE")
    if jacas_pid is None:
        print(f"ERROR (Jacas): {jacas_name}")
        conn.close()
        return
    jacas_div = _get_div_row(conn, jacas_pid)
    print(f"\nJacas: {jacas_name} | pid={jacas_pid}")
    if jacas_div:
        print(f"  Current divergence_flags: flag={jacas_div['divergence_flag']} "
              f"status={jacas_div.get('status')} triaged_by={jacas_div.get('triaged_by')}")
    else:
        print("  No divergence_flags row — will INSERT.")

    # ── THOMAS lookup ─────────────────────────────────────────────────────────
    thomas_pid, thomas_name = _lookup_pid(conn, "Thomas", position_group="EDGE", school="Oklahoma")
    if thomas_pid is None:
        # Retry without school filter, show matches
        thomas_pid, thomas_name = _lookup_pid(conn, "Thomas", position_group="EDGE")
    if thomas_pid is None:
        print(f"ERROR (Thomas): {thomas_name}")
        conn.close()
        return
    thomas_div = _get_div_row(conn, thomas_pid)
    print(f"\nThomas: {thomas_name} | pid={thomas_pid}")
    if thomas_div:
        print(f"  Current divergence_flags: flag={thomas_div['divergence_flag']} "
              f"status={thomas_div.get('status')} triaged_by={thomas_div.get('triaged_by')}")
    else:
        print("  No divergence_flags row — will INSERT.")

    # ── Dry run summary ───────────────────────────────────────────────────────
    print(f"\n{'DRY RUN' if not args.apply else 'WRITING'}")
    print(f"\n  Jacas  (pid={jacas_pid}): status = {JACAS_STATUS!r}")
    print(f"  Thomas (pid={thomas_pid}): status = {THOMAS_STATUS!r}")

    if not args.apply:
        print("\n[DRY RUN] No writes. Pass --apply 1 to commit.")
        conn.close()
        return

    # ── Apply ─────────────────────────────────────────────────────────────────
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = f"data/edge/draftos.sqlite.bak_divergence_triage_s76_{ts}"
    shutil.copy2(DB_PATH, backup)
    print(f"\nBackup: {backup}")

    triaged_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _upsert_triage(conn, jacas_pid, JACAS_STATUS, JACAS_RATIONALE, triaged_at, jacas_div)
    print(f"Jacas  (pid={jacas_pid}): written {JACAS_STATUS}")
    _upsert_triage(conn, thomas_pid, THOMAS_STATUS, THOMAS_RATIONALE, triaged_at, thomas_div)
    print(f"Thomas (pid={thomas_pid}): written {THOMAS_STATUS}")
    conn.commit()

    # ── Verification ──────────────────────────────────────────────────────────
    print("\nVerification:")
    rows = conn.execute(
        """
        SELECT p.display_name, df.status, df.triaged_by, df.triaged_at
        FROM divergence_flags df
        JOIN prospects p ON p.prospect_id = df.prospect_id
        WHERE (p.display_name LIKE '%Jacas%'
            OR (p.display_name LIKE '%Thomas%' AND p.position_group='EDGE'))
          AND df.season_id = ?
          AND df.model_version = ?
        """,
        (SEASON_ID, MODEL_VERSION),
    ).fetchall()
    for r in rows:
        print(f"  {r['display_name']}: status={r['status']} | triaged_by={r['triaged_by']} | at={r['triaged_at']}")

    conn.close()


if __name__ == "__main__":
    main()
