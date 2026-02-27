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


def get_consensus_board(
    season_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    min_sources: int = 1,
) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              c.consensus_rank,
              c.score,
              c.tier,
              c.reason_chips_json,
              c.sources_covered,
              c.avg_rank,
              c.median_rank,
              c.min_rank,
              c.max_rank,
              c.explain_json,

              p.prospect_id,
              p.prospect_key,
              p.full_name,
              p.display_name,
              p.school_canonical,
              p.position_group,
              p.position_raw
            FROM prospect_consensus_rankings c
            JOIN prospects p
              ON p.prospect_id = c.prospect_id
             AND p.season_id = c.season_id
            WHERE c.season_id = ?
              AND c.sources_covered >= ?
            ORDER BY c.consensus_rank
            LIMIT ? OFFSET ?
            """,
            (season_id, min_sources, limit, offset),
        ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["reason_chips"] = _try_json(d.get("reason_chips_json")) or []
            d["explain"] = _try_json(d.get("explain_json"))
            out.append(d)
        return out


def get_consensus_row(season_id: int, prospect_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        r = conn.execute(
            """
            SELECT
              c.*,
              p.prospect_key,
              p.full_name,
              p.display_name,
              p.school_canonical,
              p.position_group,
              p.position_raw
            FROM prospect_consensus_rankings c
            JOIN prospects p
              ON p.prospect_id = c.prospect_id
             AND p.season_id = c.season_id
            WHERE c.season_id = ?
              AND c.prospect_id = ?
            """,
            (season_id, prospect_id),
        ).fetchone()

        if not r:
            return None

        d = dict(r)
        d["reason_chips"] = _try_json(d.get("reason_chips_json")) or []
        d["explain"] = _try_json(d.get("explain_json"))
        return d