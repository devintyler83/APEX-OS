from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from draftos.db.connect import connect
from draftos.queries.apex import get_apex_ranks


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


def get_source_ranks(
    conn, *, source_name: str, season_id: int = 1
) -> dict[int, int]:
    """
    Return prospect_id -> overall_rank for the named source, latest ranking_date.

    Joins source_rankings through source_player_map to resolve prospect_id.
    Prospects not mapped in source_player_map are excluded.
    If the source is not found, returns {}.
    """
    src_row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name = ?",
        (source_name,),
    ).fetchone()
    if src_row is None:
        return {}

    source_id = int(src_row["source_id"])

    latest_date_row = conn.execute(
        """
        SELECT MAX(ranking_date) AS latest_date
        FROM source_rankings
        WHERE source_id = ? AND season_id = ?
        """,
        (source_id, season_id),
    ).fetchone()

    if latest_date_row is None or latest_date_row["latest_date"] is None:
        return {}

    latest_date = latest_date_row["latest_date"]

    rows = conn.execute(
        """
        SELECT spm.prospect_id, sr.overall_rank
        FROM source_rankings sr
        JOIN source_player_map spm
          ON spm.source_player_id = sr.source_player_id
        WHERE sr.source_id = ?
          AND sr.season_id = ?
          AND sr.ranking_date = ?
          AND spm.prospect_id IS NOT NULL
        """,
        (source_id, season_id, latest_date),
    ).fetchall()

    return {int(row["prospect_id"]): int(row["overall_rank"]) for row in rows}


def get_big_board(
    conn, *, season_id: int = 1, model_id: int = 1
) -> list[dict]:
    """
    Return the full big board for the latest snapshot, joining all UI-relevant tables.

    Returns a list of dicts with keys:
      prospect_id, display_name, school_canonical, position_group,
      consensus_rank, consensus_score, consensus_tier,
      confidence_band, confidence_score, sources_present,
      coverage_count, snapshot_date,
      ras_score,
      divergence_flag, jfosterfilm_rank, divergence_delta,
      apex_rank, apex_delta

    Notes:
      - Snapshot scope: latest snapshot only (MAX id for season_id + model_id).
      - RAS: joined on prospect_id + season_id; column is ras_total.
      - divergence_delta: jfosterfilm_rank - consensus_rank
          negative = jf ranks prospect higher than consensus
          None if prospect not ranked by jfosterfilm
      - divergence_flag: 1 if abs(divergence_delta) >= 10, else 0
      - apex_delta: consensus_rank - apex_rank
          positive = analyst ranks prospect higher than consensus
          None if no apex rank set

    TODO Session 2 (completed): divergence_flag wired to jfosterfilm_2026 source delta.
    TODO Session 3: Prospect detail expander — click row, show explain_json breakdown,
      source-by-source rank table, confidence reasons, APEX notes field.
    TODO Session 3: Movers panel — delta_rank from snapshot comparison, top risers/fallers.
    """
    # Resolve latest snapshot id for this season + model
    snap_row = conn.execute(
        """
        SELECT MAX(id) AS latest_id
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
        """,
        (season_id, model_id),
    ).fetchone()

    if snap_row is None or snap_row["latest_id"] is None:
        return []

    latest_snapshot_id = snap_row["latest_id"]

    rows = conn.execute(
        """
        SELECT
          p.prospect_id,
          p.display_name,
          p.school_canonical,
          p.position_group,

          sr.rank_overall        AS consensus_rank,
          pmo.score              AS consensus_score,
          pmo.tier               AS consensus_tier,

          cf.confidence_band,
          cf.confidence_score,
          cf.sources_present,

          sr.coverage_count,
          ps.snapshot_date_utc   AS snapshot_date,

          r.ras_total            AS ras_score

        FROM prospect_board_snapshot_rows sr

        JOIN prospect_board_snapshots ps
          ON ps.id = sr.snapshot_id

        JOIN prospects p
          ON p.prospect_id = sr.prospect_id
         AND p.season_id   = sr.season_id

        JOIN prospect_model_outputs pmo
          ON pmo.prospect_id = sr.prospect_id
         AND pmo.season_id   = sr.season_id
         AND pmo.model_id    = sr.model_id

        LEFT JOIN prospect_board_snapshot_confidence cf
          ON cf.snapshot_id  = sr.snapshot_id
         AND cf.prospect_id  = sr.prospect_id
         AND cf.season_id    = sr.season_id
         AND cf.model_id     = sr.model_id

        LEFT JOIN ras r
          ON r.prospect_id = sr.prospect_id
         AND r.season_id   = sr.season_id

        WHERE sr.snapshot_id = ?
          AND sr.season_id   = ?
          AND sr.model_id    = ?

        ORDER BY sr.rank_overall ASC, p.prospect_id ASC
        """,
        (latest_snapshot_id, season_id, model_id),
    ).fetchall()

    board = [dict(row) for row in rows]

    # --- Divergence: jfosterfilm_2026 vs consensus rank ---
    jf_ranks = get_source_ranks(conn, source_name="jfosterfilm_2026", season_id=season_id)

    for row in board:
        pid = row["prospect_id"]
        consensus = row["consensus_rank"]
        jf_rank = jf_ranks.get(pid)

        if jf_rank is not None:
            delta = jf_rank - consensus
            row["jfosterfilm_rank"] = jf_rank
            row["divergence_delta"] = delta
            row["divergence_flag"] = 1 if abs(delta) >= 10 else 0
        else:
            row["jfosterfilm_rank"] = None
            row["divergence_delta"] = None
            row["divergence_flag"] = 0

    # --- APEX ranks ---
    apex_ranks = get_apex_ranks(conn, season_id=season_id)

    for row in board:
        pid = row["prospect_id"]
        apex_rank = apex_ranks.get(pid)
        row["apex_rank"] = apex_rank
        if apex_rank is not None:
            row["apex_delta"] = row["consensus_rank"] - apex_rank
        else:
            row["apex_delta"] = None

    return board
