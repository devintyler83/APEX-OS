from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from draftos.config import PATHS


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

    create_ok=False (default): raises FileNotFoundError if the DB does not exist.
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
    conn = sqlite3.connect(str(PATHS.db))
    try:
        _configure(conn)
        yield conn
    finally:
        conn.close()