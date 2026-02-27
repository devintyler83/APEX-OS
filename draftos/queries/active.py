from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Tuple
from draftos.db.connect import connect


def sources_has_is_active(conn) -> bool:
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(sources);").fetchall()]
    return "is_active" in cols


def list_sources() -> List[Dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT source_id, source_name, is_active, superseded_by_source_id "
            "FROM sources ORDER BY source_id"
        ).fetchall()
        return [dict(r) for r in rows]


def list_active_sources() -> List[Dict]:
    with connect() as conn:
        if sources_has_is_active(conn):
            rows = conn.execute(
                "SELECT source_id, source_name FROM sources WHERE is_active = 1 ORDER BY source_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT source_id, source_name FROM sources ORDER BY source_id"
            ).fetchall()
        return [dict(r) for r in rows]


def active_source_ids(conn) -> List[int]:
    if sources_has_is_active(conn):
        rows = conn.execute(
            "SELECT source_id FROM sources WHERE is_active = 1 ORDER BY source_id"
        ).fetchall()
    else:
        rows = conn.execute("SELECT source_id FROM sources ORDER BY source_id").fetchall()
    return [int(r["source_id"]) for r in rows]


def iter_active_source_players(season_id: int, *, conn=None) -> Iterator[Dict]:
    """
    Default seam: yields source_players for active sources only.
    """
    own = None
    try:
        if conn is None:
            own = connect()
            conn = own.__enter__()

        if sources_has_is_active(conn):
            sql = """
            SELECT sp.*
            FROM source_players sp
            JOIN sources s ON s.source_id = sp.source_id
            WHERE s.is_active = 1
              AND sp.season_id = ?
            ORDER BY sp.source_id, sp.source_player_id
            """
        else:
            sql = """
            SELECT sp.*
            FROM source_players sp
            WHERE sp.season_id = ?
            ORDER BY sp.source_id, sp.source_player_id
            """

        cur = conn.execute(sql, (season_id,))
        for r in cur:
            yield dict(r)
    finally:
        if own is not None:
            own.__exit__(None, None, None)


def iter_active_source_rankings(season_id: int, *, conn=None) -> Iterator[Dict]:
    """
    Default seam: yields source_rankings for active sources only.
    """
    own = None
    try:
        if conn is None:
            own = connect()
            conn = own.__enter__()

        if sources_has_is_active(conn):
            sql = """
            SELECT sr.*
            FROM source_rankings sr
            JOIN sources s ON s.source_id = sr.source_id
            WHERE s.is_active = 1
              AND sr.season_id = ?
            ORDER BY sr.source_id, sr.source_player_id
            """
        else:
            sql = """
            SELECT sr.*
            FROM source_rankings sr
            WHERE sr.season_id = ?
            ORDER BY sr.source_id, sr.source_player_id
            """

        cur = conn.execute(sql, (season_id,))
        for r in cur:
            yield dict(r)
    finally:
        if own is not None:
            own.__exit__(None, None, None)