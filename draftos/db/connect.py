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
def connect():
    PATHS.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PATHS.db))
    try:
        _configure(conn)
        yield conn
    finally:
        conn.close()