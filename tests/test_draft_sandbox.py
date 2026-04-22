"""
tests/test_draft_sandbox.py — Sandbox draft overlay tests (Migration 0057)

Uses an isolated in-memory SQLite DB built from the minimal schema needed
to exercise draft_mode.py sandbox helpers without touching the real DB.

Canonical behavior is verified unchanged when sandbox_id is absent.
Sandbox behavior is verified for isolation, precedence, and reset.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────
# Helpers: build a minimal in-memory DB that satisfies sandbox helpers
# ─────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS prospects (
    prospect_id   INTEGER PRIMARY KEY,
    display_name  TEXT,
    position_group TEXT,
    is_active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS drafted_picks_2026 (
    id             INTEGER PRIMARY KEY,
    season_id      INTEGER NOT NULL,
    pick_number    INTEGER NOT NULL,
    round_number   INTEGER,
    drafting_team  TEXT NOT NULL,
    prospect_id    INTEGER NOT NULL,
    drafted_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    draft_session_label TEXT,
    source         TEXT NOT NULL DEFAULT 'test',
    note           TEXT,
    UNIQUE (season_id, pick_number),
    UNIQUE (season_id, prospect_id)
);

CREATE TABLE IF NOT EXISTS draft_sandbox_picks (
    sandbox_id   TEXT    NOT NULL,
    season_id    INTEGER NOT NULL,
    prospect_id  INTEGER NOT NULL,
    sandboxed_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    note         TEXT,
    PRIMARY KEY (sandbox_id, season_id, prospect_id)
);

-- Minimal views the sandbox overlay helpers need
CREATE VIEW IF NOT EXISTS v_draft_targets_2026 AS
SELECT
    p.prospect_id,
    'TEST' AS team_id,
    1      AS season_id,
    NULL   AS fit_score,
    NULL   AS fit_tier,
    NULL   AS fit_band,
    NULL   AS deployment_fit,
    NULL   AS pick_fit,
    NULL   AS fm_risk_score,
    NULL   AS verdict,
    NULL   AS why_for,
    NULL   AS why_against,
    NULL   AS confidence,
    NULL   AS fit_explanation,
    NULL   AS capital_adjusted,
    NULL   AS failure_mode_primary,
    NULL   AS failure_mode_secondary,
    NULL   AS team_primary_needs,
    NULL   AS team_secondary_needs,
    NULL   AS coverage_bias,
    NULL   AS primary_defense_family,
    NULL   AS consensus_rank,
    NULL   AS apex_rank,
    NULL   AS divergence_delta,
    NULL   AS divergence_flag,
    NULL   AS divergence_magnitude,
    NULL   AS jfoster_con_rank,
    NULL   AS recon_bucket
FROM prospects p
WHERE p.is_active = 1;

CREATE VIEW IF NOT EXISTS v_draft_targets_remaining_2026 AS
SELECT *
FROM v_draft_targets_2026 t
WHERE NOT EXISTS (
    SELECT 1 FROM drafted_picks_2026 dp
    WHERE dp.prospect_id = t.prospect_id AND dp.season_id = 1
);

CREATE VIEW IF NOT EXISTS v_draft_remaining_2026 AS
SELECT * FROM v_draft_targets_remaining_2026;
"""

_SEED_PROSPECTS = [
    (1, "Alpha Prospect", "QB"),
    (2, "Beta Prospect",  "CB"),
    (3, "Gamma Prospect", "EDGE"),
    (4, "Delta Prospect", "OT"),
    (5, "Epsilon Prospect", "S"),
]


def _make_in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    conn.executemany(
        "INSERT INTO prospects (prospect_id, display_name, position_group) VALUES (?,?,?)",
        _SEED_PROSPECTS,
    )
    conn.commit()
    return conn


def _patch_connect(conn: sqlite3.Connection):
    """Context manager that patches draftos.db.connect.connect to use the in-memory conn."""
    from contextlib import contextmanager

    @contextmanager
    def _fake_connect():
        yield conn

    return patch("draftos.queries.draft_mode.connect", side_effect=_fake_connect)


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────

class TestSandboxIsolation:
    """Two sandbox IDs see completely independent drafted state."""

    def test_two_sessions_independent(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            r1 = dm.mark_prospect_sandboxed("session-A", prospect_id=1, season_id=1)
            r2 = dm.mark_prospect_sandboxed("session-B", prospect_id=2, season_id=1)

            assert r1.startswith("OK")
            assert r2.startswith("OK")

            pids_a = dm.get_sandbox_drafted_pids("session-A", season_id=1)
            pids_b = dm.get_sandbox_drafted_pids("session-B", season_id=1)

            assert pids_a == {1}, "Session A should only see its own mark"
            assert pids_b == {2}, "Session B should only see its own mark"
            assert pids_a.isdisjoint(pids_b), "Sessions must not share state"

    def test_sandbox_mark_does_not_appear_in_canonical(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            dm.mark_prospect_sandboxed("session-X", prospect_id=3, season_id=1)

            # drafted_picks_2026 must be untouched
            canonical_n = conn.execute(
                "SELECT COUNT(*) AS n FROM drafted_picks_2026"
            ).fetchone()["n"]
            assert canonical_n == 0, "Sandbox write must never touch drafted_picks_2026"

    def test_idempotent_sandbox_mark(self):
        """Calling mark_prospect_sandboxed twice on same pid is safe (INSERT OR REPLACE)."""
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            dm.mark_prospect_sandboxed("session-A", prospect_id=1, season_id=1)
            r = dm.mark_prospect_sandboxed("session-A", prospect_id=1, season_id=1)
            assert r.startswith("OK")

            pids = dm.get_sandbox_drafted_pids("session-A", season_id=1)
            assert pids == {1}  # still exactly one entry


class TestSandboxPrecedence:
    """Canonical picks take priority; sandbox can only add to the hidden set."""

    def test_canonical_pick_not_sandboxable(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm
            from datetime import datetime, timezone

            # Insert a canonical pick for prospect 1
            conn.execute(
                """
                INSERT INTO drafted_picks_2026
                    (season_id, pick_number, round_number, drafting_team, prospect_id,
                     drafted_at, source)
                VALUES (1, 1, 1, 'PHI', 1, ?, 'test')
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),),
            )
            conn.commit()

            # Attempting to sandbox an already-canonically-drafted prospect is rejected
            result = dm.mark_prospect_sandboxed("session-A", prospect_id=1, season_id=1)
            assert result.startswith("REJECT"), (
                "Should not sandbox an already-canonical pick: " + result
            )

    def test_remaining_board_sandbox_excludes_both(self):
        """get_remaining_board_sandbox() hides canonical AND sandbox picks."""
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm
            from datetime import datetime, timezone

            # Canonical: prospect 1 picked
            conn.execute(
                """
                INSERT INTO drafted_picks_2026
                    (season_id, pick_number, round_number, drafting_team, prospect_id,
                     drafted_at, source)
                VALUES (1, 1, 1, 'PHI', 1, ?, 'test')
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),),
            )
            conn.commit()

            # Sandbox: mark prospect 2 for session-A
            dm.mark_prospect_sandboxed("session-A", prospect_id=2, season_id=1)

            # Session A board should exclude both 1 (canonical) and 2 (sandbox)
            board = dm.get_remaining_board_sandbox("session-A", season_id=1)
            pids_on_board = {r["prospect_id"] for r in board}

            assert 1 not in pids_on_board, "Canonical pick must not appear on sandbox board"
            assert 2 not in pids_on_board, "Sandbox-marked pick must not appear on sandbox board"
            assert 3 in pids_on_board,     "Unmarked prospect must still appear"

            # Session B board should exclude only 1 (canonical), but keep 2
            board_b = dm.get_remaining_board_sandbox("session-B", season_id=1)
            pids_b = {r["prospect_id"] for r in board_b}

            assert 1 not in pids_b, "Canonical pick must be hidden from all sessions"
            assert 2 in pids_b,     "Session B never sandboxed prospect 2"


class TestSandboxMutations:
    """Delete and reset operations for sandbox marks."""

    def test_delete_sandbox_pick(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            dm.mark_prospect_sandboxed("session-A", prospect_id=1, season_id=1)
            dm.mark_prospect_sandboxed("session-A", prospect_id=2, season_id=1)

            ok = dm.delete_sandbox_pick("session-A", prospect_id=1, season_id=1)
            assert ok is True

            pids = dm.get_sandbox_drafted_pids("session-A", season_id=1)
            assert pids == {2}, "Only the non-deleted pick should remain"

    def test_delete_nonexistent_sandbox_pick_returns_false(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            ok = dm.delete_sandbox_pick("session-A", prospect_id=99, season_id=1)
            assert ok is False

    def test_reset_sandbox(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            dm.mark_prospect_sandboxed("session-A", prospect_id=1, season_id=1)
            dm.mark_prospect_sandboxed("session-A", prospect_id=2, season_id=1)
            dm.mark_prospect_sandboxed("session-B", prospect_id=3, season_id=1)

            n = dm.reset_sandbox("session-A", season_id=1)
            assert n == 2

            pids_a = dm.get_sandbox_drafted_pids("session-A", season_id=1)
            pids_b = dm.get_sandbox_drafted_pids("session-B", season_id=1)

            assert pids_a == set(),  "Session A should be fully cleared"
            assert pids_b == {3},    "Session B must be unaffected by session A reset"

    def test_reset_empty_sandbox_is_safe(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm

            n = dm.reset_sandbox("no-picks-session", season_id=1)
            assert n == 0


class TestCanonicalUnchanged:
    """Canonical draft functions are unaffected by sandbox operations."""

    def test_get_drafted_count_canonical_unaffected(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm
            from datetime import datetime, timezone

            # Add one canonical pick
            conn.execute(
                """
                INSERT INTO drafted_picks_2026
                    (season_id, pick_number, round_number, drafting_team, prospect_id,
                     drafted_at, source)
                VALUES (1, 1, 1, 'PHI', 1, ?, 'test')
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),),
            )
            conn.commit()

            # Add sandbox marks — must not affect canonical count
            dm.mark_prospect_sandboxed("session-A", prospect_id=2, season_id=1)
            dm.mark_prospect_sandboxed("session-A", prospect_id=3, season_id=1)

            canonical_n = dm.get_drafted_count(season_id=1)
            assert canonical_n == 1, "Canonical count must not include sandbox marks"

    def test_get_drafted_count_sandbox_adds_to_canonical(self):
        conn = _make_in_memory_conn()
        with _patch_connect(conn):
            from draftos.queries import draft_mode as dm
            from datetime import datetime, timezone

            # One canonical pick
            conn.execute(
                """
                INSERT INTO drafted_picks_2026
                    (season_id, pick_number, round_number, drafting_team, prospect_id,
                     drafted_at, source)
                VALUES (1, 1, 1, 'PHI', 1, ?, 'test')
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),),
            )
            conn.commit()

            # Two sandbox-only picks
            dm.mark_prospect_sandboxed("session-A", prospect_id=2, season_id=1)
            dm.mark_prospect_sandboxed("session-A", prospect_id=3, season_id=1)

            sandbox_total = dm.get_drafted_count_sandbox("session-A", season_id=1)
            assert sandbox_total == 3, "Sandbox total = canonical(1) + session sandbox(2)"
