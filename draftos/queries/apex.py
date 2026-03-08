"""
APEX rank query and write layer.

APEX ranks are analyst-assigned overrides to consensus rank, stored in prospect_tags
using tag_name='apex_rank_2026' with the rank stored in tag_value.

All write functions are idempotent (safe to re-run).
All read functions are read-only.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS

_APEX_TAG = "apex_rank_2026"
_APEX_TAG_TYPE = "analyst"


def _backup_db_once_today() -> None:
    """
    Back up the DB at most once per calendar day.
    Skips if a backup file for today already exists.
    """
    if not PATHS.db.exists():
        return

    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    existing = list(backup_dir.glob(f"draftos.sqlite.backup.{today}*"))
    if existing:
        return  # Already backed up today

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.{ts}"
    shutil.copy2(PATHS.db, backup_path)


def _ensure_apex_tag(conn) -> int:
    """
    Ensure the apex_rank_2026 tag exists in the tags table.
    Returns tag_id.
    """
    conn.execute(
        "INSERT OR IGNORE INTO tags(tag, tag_type) VALUES (?, ?)",
        (_APEX_TAG, _APEX_TAG_TYPE),
    )
    row = conn.execute("SELECT tag_id FROM tags WHERE tag = ?", (_APEX_TAG,)).fetchone()
    return int(row["tag_id"])


def get_apex_ranks(conn, *, season_id: int = 1) -> dict[int, int]:
    """
    Return prospect_id -> apex_rank for all saved APEX ranks this season.
    Returns {} if no APEX ranks have been saved yet.

    season_id is reserved for future multi-season support.
    Currently APEX ranks are scoped to the apex_rank_2026 tag.
    """
    rows = conn.execute(
        """
        SELECT pt.prospect_id, pt.tag_value
        FROM prospect_tags pt
        JOIN tags t ON t.tag_id = pt.tag_id
        WHERE t.tag = ?
          AND pt.tag_value IS NOT NULL
        """,
        (_APEX_TAG,),
    ).fetchall()

    result: dict[int, int] = {}
    for row in rows:
        try:
            result[int(row["prospect_id"])] = int(row["tag_value"])
        except (TypeError, ValueError):
            pass
    return result


def save_apex_rank(
    conn, *, prospect_id: int, apex_rank: int, season_id: int = 1
) -> None:
    """
    Upsert a single APEX rank for a prospect. Idempotent.

    Backs up the DB at most once per day before first write.
    """
    _backup_db_once_today()

    tag_id = _ensure_apex_tag(conn)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO prospect_tags(prospect_id, tag_id, tag_value, weight, notes, created_at)
        VALUES (?, ?, ?, 1.0, NULL, ?)
        ON CONFLICT(prospect_id, tag_id) DO UPDATE SET
          tag_value = excluded.tag_value,
          created_at = excluded.created_at
        """,
        (prospect_id, tag_id, str(apex_rank), now),
    )
    conn.commit()


def clear_apex_rank(conn, *, prospect_id: int, season_id: int = 1) -> None:
    """
    Remove the APEX rank for a prospect. No-op if not set.
    """
    row = conn.execute("SELECT tag_id FROM tags WHERE tag = ?", (_APEX_TAG,)).fetchone()
    if row is None:
        return

    conn.execute(
        "DELETE FROM prospect_tags WHERE prospect_id = ? AND tag_id = ?",
        (prospect_id, int(row["tag_id"])),
    )
    conn.commit()
