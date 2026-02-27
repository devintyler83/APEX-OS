from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from draftos.db.connect import connect


def _try_json(s: Any):
    if isinstance(s, str) and s:
        try:
            return json.loads(s)
        except Exception:
            return None
    return None


def _resolve_model_id(conn, season_id: int, model_ref: str) -> Optional[int]:
    """
    Resolve model by model_key first (canonical), then model_name.
    """
    r = conn.execute(
        "SELECT model_id FROM models WHERE season_id=? AND model_key=?",
        (season_id, model_ref),
    ).fetchone()
    if r:
        return int(r["model_id"])

    r = conn.execute(
        "SELECT model_id FROM models WHERE season_id=? AND model_name=?",
        (season_id, model_ref),
    ).fetchone()
    if r:
        return int(r["model_id"])

    return None


def get_model_board(
    season_id: int,
    model_ref: str = "v1_default",
    *,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with connect() as conn:
        model_id = _resolve_model_id(conn, season_id, model_ref)
        if model_id is None:
            return []

        rows = conn.execute(
            """
            SELECT
              o.score,
              o.tier,
              o.reason_chips_json,
              o.explain_json,

              p.prospect_id,
              p.prospect_key,
              p.display_name,
              p.full_name,
              p.school_canonical,
              p.position_group
            FROM prospect_model_outputs o
            JOIN prospects p
              ON p.prospect_id = o.prospect_id
             AND p.season_id = o.season_id
            WHERE o.season_id = ?
              AND o.model_id = ?
            ORDER BY o.score DESC, p.prospect_id ASC
            LIMIT ? OFFSET ?
            """,
            (season_id, model_id, limit, offset),
        ).fetchall()

        out: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["reason_chips"] = _try_json(d.get("reason_chips_json")) or []
            d["explain"] = _try_json(d.get("explain_json"))
            out.append(d)
        return out


def get_model_output(
    season_id: int,
    prospect_id: int,
    model_ref: str = "v1_default",
) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        model_id = _resolve_model_id(conn, season_id, model_ref)
        if model_id is None:
            return None

        row = conn.execute(
            """
            SELECT
              o.*,
              p.prospect_key,
              p.display_name,
              p.full_name,
              p.school_canonical,
              p.position_group
            FROM prospect_model_outputs o
            JOIN prospects p
              ON p.prospect_id = o.prospect_id
             AND p.season_id = o.season_id
            WHERE o.season_id = ?
              AND o.model_id = ?
              AND o.prospect_id = ?
            """,
            (season_id, model_id, prospect_id),
        ).fetchone()

        if not row:
            return None

        d = dict(row)
        d["reason_chips"] = _try_json(d.get("reason_chips_json")) or []
        d["explain"] = _try_json(d.get("explain_json"))
        return d