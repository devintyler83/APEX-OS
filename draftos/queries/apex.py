"""
APEX rank query and write layer.

APEX ranks are analyst-assigned overrides to consensus rank, stored in
tag_definitions (tag_name='apex_rank_2026') + prospect_tags (tag_value=rank).

All write functions are idempotent (safe to re-run).
All read functions are read-only.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS

_APEX_TAG = "apex_rank_2026"
_DEFAULT_USER_ID = 1


def _backup_db_once_today() -> None:
    """Back up the DB at most once per calendar day."""
    if not PATHS.db.exists():
        return

    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    existing = list(backup_dir.glob(f"draftos.sqlite.backup.{today}*"))
    if existing:
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.{ts}"
    shutil.copy2(PATHS.db, backup_path)


def _ensure_apex_tag(conn) -> int:
    """
    Ensure the apex_rank_2026 tag exists in tag_definitions.
    Returns tag_def_id.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO tag_definitions(
            tag_name, tag_category, tag_color, tag_source_type,
            description, note_required, is_active, display_order
        ) VALUES (?, 'informational', 'blue', 'analyst',
                  'Analyst-assigned APEX rank override', 0, 1, 999)
        """,
        (_APEX_TAG,),
    )
    row = conn.execute(
        "SELECT tag_def_id FROM tag_definitions WHERE tag_name = ?", (_APEX_TAG,)
    ).fetchone()
    return int(row["tag_def_id"])


def get_apex_ranks(conn, *, season_id: int = 1) -> dict[int, int]:
    """
    Return prospect_id -> apex_rank for all saved APEX ranks this season.
    Returns {} if no APEX ranks have been saved yet.
    """
    rows = conn.execute(
        """
        SELECT pt.prospect_id, pt.tag_value
        FROM prospect_tags pt
        JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
        WHERE td.tag_name = ?
          AND pt.tag_value IS NOT NULL
          AND pt.is_active = 1
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

    tag_def_id = _ensure_apex_tag(conn)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO prospect_tags(
            prospect_id, tag_def_id, user_id, source, tag_value, is_active, created_at
        )
        VALUES (?, ?, ?, 'analyst', ?, 1, ?)
        ON CONFLICT(prospect_id, tag_def_id, user_id) DO UPDATE SET
            tag_value     = excluded.tag_value,
            is_active     = 1,
            created_at    = excluded.created_at
        """,
        (prospect_id, tag_def_id, _DEFAULT_USER_ID, str(apex_rank), now),
    )
    conn.commit()


def clear_apex_rank(conn, *, prospect_id: int, season_id: int = 1) -> None:
    """
    Soft-delete the APEX rank for a prospect (set is_active=0). No-op if not set.
    """
    row = conn.execute(
        "SELECT tag_def_id FROM tag_definitions WHERE tag_name = ?", (_APEX_TAG,)
    ).fetchone()
    if row is None:
        return

    conn.execute(
        """
        UPDATE prospect_tags SET is_active = 0, deactivated_at = ?
        WHERE prospect_id = ? AND tag_def_id = ? AND user_id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), prospect_id, int(row["tag_def_id"]), _DEFAULT_USER_ID),
    )
    conn.commit()
