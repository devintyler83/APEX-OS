from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from draftos.db.connect import connect
from draftos.queries.apex import get_apex_ranks

_APEX_MODEL_VERSION = "apex_v2.3"

# Tier/weight lookup — sources table has no tier/weight columns; inferred from CLAUDE.md canonical list
_SOURCE_TIER_WEIGHT: dict[str, tuple[str, float]] = {
    "pff_2026":              ("T1", 1.3),
    "thedraftnetwork_2026":  ("T1", 1.3),
    "theringer_2026":        ("T1", 1.3),
    "nfldraftbuzz_2026_v2":  ("T2", 1.0),
    "cbssports_2026":        ("T2", 1.0),
    "espn_2026":             ("T2", 1.0),
    "nytimes_2026":          ("T2", 1.0),
    "pfsn_2026":             ("T2", 1.0),
    "jfosterfilm_2026":      ("T2", 1.0),
    "combine_ranks_2026":    ("T2", 1.0),
    "nflcom_2026":           ("T2", 1.0),
    "bleacherreport_2026":   ("T2", 1.0),
    "bnbfootball_2026":      ("T3", 0.7),
    "tankathon_2026":        ("T3", 0.7),
}


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
             AND p.is_active = 1
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
             AND p.is_active = 1
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
    Rows where overall_rank IS NULL are skipped (some sources omit positional ranks).
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
          AND sr.overall_rank IS NOT NULL
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
      apex_rank, apex_delta,
      apex_composite, apex_tier, apex_archetype,
      v_processing, v_athleticism, v_scheme_vers, v_comp_tough,
      v_character, v_dev_traj, v_production, v_injury,
      c1_public_record, c2_motivation, c3_psych_profile,
      tag_names  (pipe-delimited string of tag_name values, "" if none)

    Notes:
      - Snapshot scope: latest snapshot only (MAX id for season_id + model_id).
      - coverage_count: sourced from prospect_board_snapshot_coverage (not snapshot_rows).
      - RAS: joined on prospect_id + season_id; column is ras_total.
      - divergence_delta: jfosterfilm_rank - consensus_rank
          negative = jf ranks prospect higher than consensus
          None if prospect not ranked by jfosterfilm
      - divergence_flag: 1 if abs(divergence_delta) >= 10, else 0
      - apex_delta: consensus_rank - apex_rank
          positive = analyst ranks prospect higher than consensus
          None if no apex rank set
      - apex_composite, apex_tier, apex_archetype: from apex_scores (APEX v2.2)
          None if not yet scored
      - tag_names: pipe-delimited accepted tag names from prospect_tags

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

          cov.coverage_count,
          ps.snapshot_date_utc   AS snapshot_date,

          r.ras_total            AS ras_score,

          aps.apex_composite,
          aps.apex_tier,
          aps.matched_archetype  AS apex_archetype,
          aps.gap_label,
          aps.eval_confidence,
          aps.raw_score,
          aps.pvc,
          aps.failure_mode_primary,
          aps.failure_mode_secondary,
          aps.bust_warning,
          aps.signature_play,
          aps.translation_risk,
          aps.v_processing,
          aps.v_athleticism,
          aps.v_scheme_vers,
          aps.v_comp_tough,
          aps.v_character,
          aps.v_dev_traj,
          aps.v_production,
          aps.v_injury,
          aps.c1_public_record,
          aps.c2_motivation,
          aps.c3_psych_profile,
          (
              SELECT GROUP_CONCAT(td2.tag_name, ', ')
              FROM prospect_tags pt2
              JOIN tag_definitions td2 ON td2.tag_def_id = pt2.tag_def_id
              WHERE pt2.prospect_id = p.prospect_id
                AND pt2.is_active   = 1
          ) AS apex_tags

        FROM prospect_board_snapshot_rows sr

        JOIN prospect_board_snapshots ps
          ON ps.id = sr.snapshot_id

        JOIN prospects p
          ON p.prospect_id = sr.prospect_id
         AND p.season_id   = sr.season_id
         AND p.is_active   = 1

        JOIN prospect_model_outputs pmo
          ON pmo.prospect_id = sr.prospect_id
         AND pmo.season_id   = sr.season_id
         AND pmo.model_id    = sr.model_id

        LEFT JOIN prospect_board_snapshot_confidence cf
          ON cf.snapshot_id  = sr.snapshot_id
         AND cf.prospect_id  = sr.prospect_id
         AND cf.season_id    = sr.season_id
         AND cf.model_id     = sr.model_id

        LEFT JOIN prospect_board_snapshot_coverage cov
          ON cov.snapshot_id  = sr.snapshot_id
         AND cov.prospect_id  = sr.prospect_id

        LEFT JOIN ras r
          ON r.prospect_id = sr.prospect_id
         AND r.ras_total IS NOT NULL

        LEFT JOIN apex_scores aps
          ON aps.prospect_id   = sr.prospect_id
         AND aps.season_id     = sr.season_id
         AND aps.model_version = ?

        WHERE sr.snapshot_id = ?
          AND sr.season_id   = ?
          AND sr.model_id    = ?

        ORDER BY sr.rank_overall ASC, p.prospect_id ASC
        """,
        (_APEX_MODEL_VERSION, latest_snapshot_id, season_id, model_id),
    ).fetchall()

    board = [dict(row) for row in rows]

    # --- Divergence: jfosterfilm_2026 vs consensus rank ---
    jf_ranks = get_source_ranks(conn, source_name="jfosterfilm_2026", season_id=season_id)

    for row in board:
        pid       = row["prospect_id"]
        consensus = row["consensus_rank"]
        jf_rank   = jf_ranks.get(pid)

        if jf_rank is not None:
            delta                  = jf_rank - consensus
            row["jfosterfilm_rank"] = jf_rank
            row["divergence_delta"] = delta
            row["divergence_flag"]  = 1 if abs(delta) >= 10 else 0
        else:
            row["jfosterfilm_rank"] = None
            row["divergence_delta"] = None
            row["divergence_flag"]  = 0

    # --- APEX analyst ranks (from prospect_tags) ---
    apex_ranks = get_apex_ranks(conn, season_id=season_id)

    for row in board:
        pid       = row["prospect_id"]
        apex_rank = apex_ranks.get(pid)
        row["apex_rank"] = apex_rank
        if apex_rank is not None:
            row["apex_delta"] = row["consensus_rank"] - apex_rank
        else:
            row["apex_delta"] = None

    # --- AUTO-APEX-RANK: derive rank from apex_composite sort order ---
    # Sort scored prospects descending by apex_composite, assign rank 1..N.
    # Manual override (apex_rank from prospect_tags) takes precedence if set.
    scored_rows = sorted(
        [r for r in board if r.get("apex_composite") is not None],
        key=lambda r: r["apex_composite"],
        reverse=True,
    )
    auto_rank_map: dict[int, int] = {
        r["prospect_id"]: (i + 1)
        for i, r in enumerate(scored_rows)
    }

    for row in board:
        pid = row["prospect_id"]
        manual = row.get("apex_rank")   # set by analyst, or None

        # Effective APEX rank: manual takes precedence over auto
        if manual is not None:
            row["auto_apex_rank"] = manual
        else:
            row["auto_apex_rank"] = auto_rank_map.get(pid)  # None if not scored

        # Δ APEX: consensus_rank - effective_apex_rank
        # Positive = APEX likes this prospect more than consensus
        consensus = row.get("consensus_rank")
        if row["auto_apex_rank"] is not None and consensus is not None:
            row["auto_apex_delta"] = consensus - row["auto_apex_rank"]
        else:
            row["auto_apex_delta"] = None

    # --- Tags: accepted tags per prospect (pipe-delimited tag_name string) ---
    tag_rows = conn.execute(
        """
        SELECT pt.prospect_id,
               GROUP_CONCAT(td.tag_name, '|') AS tag_names
        FROM prospect_tags pt
        JOIN tag_definitions td ON pt.tag_def_id = td.tag_def_id
        GROUP BY pt.prospect_id
        """
    ).fetchall()
    tags_by_pid: dict[int, str] = {
        int(r["prospect_id"]): r["tag_names"] for r in tag_rows
    }

    for row in board:
        row["tag_names"] = tags_by_pid.get(row["prospect_id"], "") or ""

    # Remove ghost duplicate PIDs: unscored rows where a scored sibling with the same
    # display_name already exists (LB ghost PID splits, prior-ingest duplicates).
    _scored_names = {r["display_name"] for r in board if r.get("apex_composite") is not None}
    board = [
        r for r in board
        if r.get("apex_composite") is not None or r["display_name"] not in _scored_names
    ]

    return board


def get_prospect_detail(
    conn,
    *,
    prospect_id: int,
    season_id: int = 1,
    model_version: str = "apex_v2.3",
) -> dict | None:
    """
    Return a full detail dict for a single prospect, joining all drawer-relevant tables.

    Returns None only if the prospect does not exist (is_active=1 required).
    All APEX / divergence / RAS / confidence fields are None if not yet computed.

    Keys returned:
      Identity: prospect_id, display_name, full_name, school_canonical, position_group
      Consensus: consensus_rank, consensus_tier, consensus_score, confidence_band,
                 confidence_score, coverage_count
      APEX: apex_composite, apex_tier, apex_archetype, archetype_gap, gap_label,
            raw_score, pvc, capital_base, capital_adjusted, eval_confidence,
            strengths, red_flags, v_processing, v_athleticism, v_scheme_vers,
            v_comp_tough, v_character, v_dev_traj, v_production, v_injury,
            c1_public_record, c2_motivation, c3_psych_profile,
            schwesinger_full, schwesinger_half, smith_rule, apex_tags,
            override_arch, override_delta, override_rationale, scored_at
      APEX RAS sub-scores: ras_ath, ras_size, ras_speed, ras_agility
      Divergence: divergence_flag, divergence_rank_delta, divergence_raw_delta,
                  divergence_mag
      RAS: ras_total, hand_size, arm_length, wingspan
      source_ranks: list[dict] — one entry per active source with a rank
      active_tags: list[dict] — all is_active=1 prospect_tags for this prospect
    """
    # ------------------------------------------------------------------ main query
    row = conn.execute(
        """
        SELECT
          p.prospect_id,
          p.display_name,
          p.full_name,
          p.school_canonical,
          p.position_group,

          cr.consensus_rank,
          cr.tier          AS consensus_tier,
          cr.score         AS consensus_score,
          cr.sources_covered AS coverage_count,

          cf.confidence_band,
          cf.confidence_score,

          aps.apex_composite,
          aps.apex_tier,
          aps.matched_archetype  AS apex_archetype,
          aps.archetype_gap,
          aps.gap_label,
          aps.raw_score,
          aps.pvc,
          aps.capital_base,
          aps.capital_adjusted,
          aps.eval_confidence,
          aps.strengths,
          aps.red_flags,
          aps.v_processing,
          aps.v_athleticism,
          aps.v_scheme_vers,
          aps.v_comp_tough,
          aps.v_character,
          aps.v_dev_traj,
          aps.v_production,
          aps.v_injury,
          aps.c1_public_record,
          aps.c2_motivation,
          aps.c3_psych_profile,
          COALESCE(aps.schwesinger_full, 0)  AS schwesinger_full,
          COALESCE(aps.schwesinger_half, 0)  AS schwesinger_half,
          COALESCE(aps.smith_rule, 0)         AS smith_rule,
          aps.tags           AS apex_tags,
          aps.failure_mode_primary,
          aps.failure_mode_secondary,
          aps.bust_warning,
          aps.signature_play,
          aps.translation_risk,
          aps.override_arch,
          aps.override_delta,
          aps.override_rationale,
          aps.scored_at,
          aps.ath_score      AS ras_ath,
          aps.size_score     AS ras_size,
          aps.speed_score    AS ras_speed,
          aps.agi_score      AS ras_agility,

          df.divergence_flag,
          df.divergence_rank_delta,
          df.divergence_raw_delta,
          df.divergence_mag,

          r.ras_total,
          r.hand_size,
          r.arm_length,
          r.wingspan

        FROM prospects p

        LEFT JOIN prospect_consensus_rankings cr
          ON cr.prospect_id = p.prospect_id
         AND cr.season_id   = ?

        LEFT JOIN prospect_model_outputs pmo
          ON pmo.prospect_id = p.prospect_id
         AND pmo.season_id   = ?
         AND pmo.model_id    = 1

        LEFT JOIN prospect_board_snapshot_confidence cf
          ON cf.prospect_id = p.prospect_id
         AND cf.season_id   = ?
         AND cf.model_id    = 1
         AND cf.snapshot_id = (
               SELECT MAX(id)
               FROM prospect_board_snapshots
               WHERE season_id = ? AND model_id = 1
             )

        LEFT JOIN apex_scores aps
          ON aps.prospect_id   = p.prospect_id
         AND aps.season_id     = ?
         AND aps.model_version = ?

        LEFT JOIN divergence_flags df
          ON df.prospect_id   = p.prospect_id
         AND df.season_id     = ?
         AND df.model_version = ?

        LEFT JOIN ras r
          ON r.prospect_id = p.prospect_id
         AND r.ras_total IS NOT NULL

        WHERE p.prospect_id = ?
          AND p.season_id   = ?
          AND p.is_active   = 1
        """,
        (
            season_id,       # cr
            season_id,       # pmo
            season_id,       # cf outer
            season_id,       # cf subquery
            season_id,       # aps
            model_version,   # aps
            season_id,       # df
            model_version,   # df
            prospect_id,     # WHERE
            season_id,       # WHERE
        ),
    ).fetchone()

    if row is None:
        return None

    detail = dict(row)

    # ------------------------------------------------------------------ source ranks
    source_rank_rows = conn.execute(
        """
        SELECT
          s.source_name,
          sr.overall_rank
        FROM sources s
        JOIN source_rankings sr
          ON sr.source_id = s.source_id
        JOIN source_player_map spm
          ON spm.source_player_id = sr.source_player_id
         AND spm.prospect_id = ?
        WHERE s.is_active = 1
          AND sr.season_id  = ?
          AND sr.overall_rank IS NOT NULL
          AND sr.ranking_date = (
                SELECT MAX(r2.ranking_date)
                FROM source_rankings r2
                WHERE r2.source_id  = s.source_id
                  AND r2.season_id  = ?
              )
        ORDER BY sr.overall_rank ASC
        """,
        (prospect_id, season_id, season_id),
    ).fetchall()

    source_ranks: list[dict] = []
    for sr in source_rank_rows:
        sname = sr["source_name"]
        tier, weight = _SOURCE_TIER_WEIGHT.get(sname, ("T2", 1.0))
        source_ranks.append(
            {
                "source_name":  sname,
                "source_tier":  tier,
                "weight":       weight,
                "overall_rank": int(sr["overall_rank"]),
            }
        )
    detail["source_ranks"] = source_ranks

    # ------------------------------------------------------------------ active tags
    tag_rows = conn.execute(
        """
        SELECT
          td.tag_name,
          td.tag_color,
          td.tag_category,
          pt.note,
          pt.created_at
        FROM prospect_tags pt
        JOIN tag_definitions td
          ON td.tag_def_id = pt.tag_def_id
        WHERE pt.prospect_id = ?
          AND pt.is_active   = 1
        ORDER BY td.display_order ASC
        """,
        (prospect_id,),
    ).fetchall()

    detail["active_tags"] = [dict(r) for r in tag_rows]

    return detail


def get_prospect_tags_map(
    conn,
    prospect_ids: list[int],
) -> dict[int, list[str]]:
    """
    Return {prospect_id: [tag_name, ...]} for the given prospect_ids.
    Only accepted (is_active=1) tags from active tag_definitions are included.
    Results are ordered by tag display_order within each prospect.
    """
    if not prospect_ids:
        return {}
    placeholders = ",".join("?" * len(prospect_ids))
    rows = conn.execute(
        f"""
        SELECT pt.prospect_id, td.tag_name
        FROM prospect_tags pt
        JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
        WHERE pt.prospect_id IN ({placeholders})
          AND pt.is_active   = 1
          AND td.is_active   = 1
        ORDER BY pt.prospect_id, td.display_order
        """,
        prospect_ids,
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        pid, tag_name = row[0], row[1]
        result.setdefault(pid, []).append(tag_name)
    return result
