from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from draftos.config import PATHS

# First 16 bytes of every valid SQLite 3 file.
_SQLITE_MAGIC = b"SQLite format 3\x00"

# Tables that must exist for the app to be usable.  A missing entry here means
# either the DB is an LFS pointer file or a required migration never ran.
_REQUIRED_TABLES = frozenset({
    "prospect_board_snapshots",
    "prospects",
    "apex_scores",
    "sources",
    "seasons",
    "models",
})


def _validate_db(path: Path) -> None:
    """
    Raise a precise RuntimeError if *path* is not a populated DraftOS database.

    Two failure modes are detected:
    1. The file is an LFS pointer (Git LFS object not fetched — common on
       Streamlit Cloud).  Detected by reading the first 16 bytes and comparing
       against the SQLite magic header.
    2. The file is a valid SQLite database but required tables are absent
       (migrations never ran, or a stale/empty DB was committed).
    """
    header = path.read_bytes()[:16]
    if header != _SQLITE_MAGIC:
        raise RuntimeError(
            f"Database file is not a valid SQLite database: {path}\n\n"
            "Most likely cause: the file is a Git LFS pointer.  Streamlit Cloud "
            "does not fetch LFS objects automatically.\n\n"
            "Fix options:\n"
            "  1. Remove data/edge/draftos.sqlite from LFS tracking:\n"
            "       git lfs untrack 'data/edge/draftos.sqlite'\n"
            "       git rm --cached data/edge/draftos.sqlite\n"
            "       git add data/edge/draftos.sqlite   # re-add as regular file\n"
            "       git commit -m 'chore: move DB out of LFS for Streamlit Cloud'\n"
            "  2. Or enable Git LFS on the Streamlit Cloud repo (requires a paid plan)."
        )

    probe = sqlite3.connect(str(path))
    try:
        present = {
            row[0]
            for row in probe.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )
        }
    finally:
        probe.close()

    missing = _REQUIRED_TABLES - present
    if missing:
        raise RuntimeError(
            f"Database at {path} is missing required tables: {sorted(missing)}\n\n"
            "The database file exists but has not been fully bootstrapped.\n"
            "Run the DraftOS pipeline locally (doctor.py, then run_weekly_update.py), "
            "then commit and push data/edge/draftos.sqlite."
        )


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row

    # Enforce FK constraints consistently.
    conn.execute("PRAGMA foreign_keys = ON;")

    # Practical local-first defaults.
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")


@contextmanager
def connect(*, create_ok: bool = False):
    """
    Open the DraftOS SQLite database.

    create_ok=False (default): raises FileNotFoundError if the DB does not exist,
      and RuntimeError if the file is an LFS pointer or missing required tables.
      Use this in the Streamlit app and any read-only context.
    create_ok=True: creates the DB file if absent (used by migration / pipeline scripts).
    """
    PATHS.db.parent.mkdir(parents=True, exist_ok=True)
    if not create_ok and not PATHS.db.exists():
        raise FileNotFoundError(
            f"Database not found: {PATHS.db}\n"
            "Run the DraftOS pipeline locally to build the database, "
            "then commit data/edge/draftos.sqlite and push."
        )
    if not create_ok:
        _validate_db(PATHS.db)
    conn = sqlite3.connect(str(PATHS.db))
    try:
        _configure(conn)
        yield conn
    finally:
        conn.close()