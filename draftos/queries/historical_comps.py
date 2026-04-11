"""
Historical comp query layer.
Read-only. No DB writes.

Functions:
  get_historical_comps          — positional comp library for an archetype
  get_archetype_translation_rate — HIT/PARTIAL/MISS rate for an archetype
  get_fm_reference_comps        — FM reference comps (is_fm_reference=1)
  get_prospect_comps            — analyst-curated comp cards per prospect (Migration 0047)
  upsert_prospect_comp          — write a prospect comp card row

Helpers:
  _extract_archetype_code       — 'WR-1 Route Technician' → 'WR-1'
  _extract_fm_code              — 'FM-1 Athleticism Mirage' → 'FM-1'
  _extract_position_prefix      — 'IDL-3' → 'IDL', 'QB-1' → 'QB'
  _normalize_archetype_code     — 'DT-3' → 'IDL-3'  (apex_scores uses DT; DB uses IDL)

ARCHETYPE NORMALIZATION NOTE
  apex_scores.matched_archetype stores interior DL archetypes as "DT-N ..." (the APEX
  engine prompt uses DT labels). historical_comps stores them as "IDL-N" (the canonical
  table-level position label). _normalize_archetype_code remaps DT-* → IDL-* so that
  get_historical_comps and get_archetype_translation_rate return correct results when
  called with a matched_archetype value from apex_scores.
"""
from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Archetype normalisation — DT (apex engine) → IDL (DB table)
# ---------------------------------------------------------------------------

# Maps archetype code prefix used by the APEX engine prompt / apex_scores column
# to the canonical prefix stored in historical_comps.
_ARCHETYPE_PREFIX_REMAP: dict[str, str] = {
    "DT": "IDL",
}


def _normalize_archetype_code(code: str) -> str:
    """
    Remap archetype code prefix to the canonical form used in historical_comps.
    'DT-3' → 'IDL-3'   (apex_scores uses DT; historical_comps stores IDL)
    All other codes pass through unchanged.
    """
    code = code.strip()
    if "-" not in code:
        return code
    prefix, suffix = code.split("-", 1)
    prefix_up = prefix.upper()
    canon = _ARCHETYPE_PREFIX_REMAP.get(prefix_up, prefix_up)
    return f"{canon}-{suffix}" if canon != prefix_up else code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_archetype_code(archetype: str) -> str:
    """
    Extract the short code prefix from a full archetype name.
    'WR-1 Route Technician' -> 'WR-1'
    'EDGE-3' -> 'EDGE-3'
    """
    m = re.match(r'^([A-Z]+-\d+)', (archetype or "").strip())
    return m.group(1) if m else (archetype or "").strip()


def _extract_fm_code(fm_str: Optional[str]) -> Optional[str]:
    """Extract FM code (e.g. 'FM-1') from full FM string like 'FM-1 Athleticism Mirage'."""
    if not fm_str:
        return None
    m = re.search(r'(FM-\d+)', fm_str.strip())
    return m.group(1) if m else None


def _extract_position_prefix(archetype_code: str) -> str:
    """
    Derive the canonical position string from an archetype code.
    'IDL-3' → 'IDL',  'DT-3' → 'IDL' (normalized),  'QB-1 Field General' → 'QB'
    Returns the full input stripped if no hyphen is found.
    """
    code = _normalize_archetype_code(_extract_archetype_code(archetype_code))
    if "-" in code:
        return code.split("-", 1)[0]
    return code.strip()


# ---------------------------------------------------------------------------
# Positional comp library
# ---------------------------------------------------------------------------

def get_historical_comps(
    conn,
    archetype_code: str,
    limit: int = 3,
    season_id: int = 1,          # accepted for API consistency; table is not season-scoped
) -> list[dict]:
    """
    Return up to `limit` historical comps for an archetype (is_fm_reference=0),
    ordered by confidence (A > B > C) then outcome (HIT > PARTIAL > MISS).

    archetype_code may be a full matched_archetype string from apex_scores
    (e.g. 'DT-3 Two-Gap Anchor'). DT-* codes are normalised to IDL-* so that
    comps stored under IDL-* are correctly returned for IDL prospects.

    season_id is accepted for signature parity but is not used in the query —
    historical_comps is an archetype library, not a season-scoped table.
    """
    raw_code = _extract_archetype_code(archetype_code)
    code     = _normalize_archetype_code(raw_code)
    rows = conn.execute(
        """
        SELECT player_name, position, archetype_code,
               translation_outcome, fm_code, outcome_summary,
               era_bracket, peak_years, comp_confidence,
               scheme_context, signature_trait
        FROM   historical_comps
        WHERE  archetype_code = ?
          AND  is_fm_reference = 0
        ORDER BY
            CASE comp_confidence WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
            CASE translation_outcome WHEN 'HIT' THEN 1 WHEN 'PARTIAL' THEN 2 ELSE 3 END
        LIMIT ?
        """,
        (code, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Archetype translation rate
# ---------------------------------------------------------------------------

def get_archetype_translation_rate(
    conn,
    archetype_code: str,
    season_id: int = 1,          # accepted for API consistency; not used in query
) -> dict:
    """
    Compute HIT/PARTIAL/MISS counts and HIT rate for an archetype.
    Returns dict with: total, hit_count, partial_count, miss_count, hit_rate_pct.

    Only counts is_fm_reference=0 rows (positional comps, not FM reference records).
    DT-* codes are normalised to IDL-* before querying.
    """
    raw_code = _extract_archetype_code(archetype_code)
    code     = _normalize_archetype_code(raw_code)
    rows = conn.execute(
        """
        SELECT translation_outcome, COUNT(*) AS cnt
        FROM   historical_comps
        WHERE  archetype_code = ?
          AND  is_fm_reference = 0
        GROUP  BY translation_outcome
        """,
        (code,),
    ).fetchall()

    counts = {"HIT": 0, "PARTIAL": 0, "MISS": 0}
    for row in rows:
        counts[row["translation_outcome"]] = row["cnt"]

    total = sum(counts.values())
    hit_rate = round(counts["HIT"] / total * 100) if total > 0 else 0

    return {
        "total":         total,
        "hit_count":     counts["HIT"],
        "partial_count": counts["PARTIAL"],
        "miss_count":    counts["MISS"],
        "hit_rate_pct":  hit_rate,
    }


# ---------------------------------------------------------------------------
# FM reference comps
# ---------------------------------------------------------------------------

def get_fm_reference_comps(
    conn,
    fm_code: str,
    position_group: Optional[str] = None,
    limit: int = 2,
    season_id: int = 1,          # accepted for API consistency; not used in query
) -> list[dict]:
    """
    Get FM reference comps (is_fm_reference=1) for a given FM code.

    Optionally filter by position_group (the DB `position` column, e.g. 'QB', 'IDL', 'ILB').
    When position_group is provided, only comps from that position are returned.
    When None, all positions are returned ordered by confidence then outcome severity.

    Returned dict keys include `position_group` (aliased from `position`) so app-layer
    filters that check r.get("position_group") work correctly.

    Column mapping:
      outcome_summary  → concise comp summary for display
      fm_mechanism     → FM-specific bust mechanism text
      mechanism        → full mechanism description
      pre_draft_signal → observable pre-draft indicator
      position_group   → alias of position  (granular: 'IDL', 'ILB', 'OLB', …)
    """
    code     = _extract_fm_code(fm_code) or fm_code
    pos_filt = (position_group or "").strip()

    if pos_filt:
        rows = conn.execute(
            """
            SELECT comp_id, player_name, position, archetype_code,
                   translation_outcome, fm_code, outcome_summary,
                   fm_mechanism, mechanism, era_bracket, peak_years,
                   comp_confidence, pre_draft_signal, is_fm_reference
            FROM   historical_comps
            WHERE  fm_code LIKE ?
              AND  is_fm_reference = 1
              AND  position = ?
            ORDER BY
                CASE comp_confidence WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
                CASE translation_outcome WHEN 'MISS' THEN 0 WHEN 'PARTIAL' THEN 1 ELSE 2 END
            LIMIT ?
            """,
            (f"%{code}%", pos_filt, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT comp_id, player_name, position, archetype_code,
                   translation_outcome, fm_code, outcome_summary,
                   fm_mechanism, mechanism, era_bracket, peak_years,
                   comp_confidence, pre_draft_signal, is_fm_reference
            FROM   historical_comps
            WHERE  fm_code LIKE ?
              AND  is_fm_reference = 1
            ORDER BY
                CASE comp_confidence WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
                CASE translation_outcome WHEN 'MISS' THEN 0 WHEN 'PARTIAL' THEN 1 ELSE 2 END
            LIMIT ?
            """,
            (f"%{code}%", limit),
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        # Alias 'position' as 'position_group' so app-layer filters work correctly.
        # The DB column is granular (e.g. 'IDL', 'ILB', 'OLB') while the board uses
        # broader position_group labels ('DT', 'LB', 'OL'). app.py's _POS_GROUP_MAP
        # bridges the two.
        d["position_group"] = d.get("position", "")
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# prospect_comps — prospect-specific curated comp cards (Migration 0047)
# ---------------------------------------------------------------------------

def get_prospect_comps(conn, prospect_id: int, season_id: int = 1) -> list[dict]:
    """
    Return analyst-curated comp cards for a specific prospect, ordered by sort_order.
    Returns empty list if no comps exist.
    """
    rows = conn.execute(
        """
        SELECT comp_type, type_label, player_name, description, years, sort_order
        FROM   prospect_comps
        WHERE  prospect_id = ? AND season_id = ?
        ORDER  BY sort_order ASC
        """,
        (prospect_id, season_id),
    ).fetchall()
    return [
        {
            "type":       r["comp_type"],
            "type_label": r["type_label"],
            "name":       r["player_name"],
            "desc":       r["description"],
            "years":      r["years"],
            "order":      r["sort_order"],
        }
        for r in rows
    ]


def upsert_prospect_comp(
    conn,
    prospect_id: int,
    comp_type: str,
    type_label: str,
    player_name: str,
    description: str,
    years: Optional[str] = None,
    sort_order: int = 0,
    season_id: int = 1,
) -> None:
    """
    Upsert a single comp card row. Idempotent on (prospect_id, season_id, player_name).
    comp_type must be one of: 'hit', 'partial', 'miss'.
    """
    conn.execute(
        """
        INSERT INTO prospect_comps
            (prospect_id, season_id, comp_type, type_label, player_name,
             description, years, sort_order, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(prospect_id, season_id, player_name) DO UPDATE SET
            comp_type   = excluded.comp_type,
            type_label  = excluded.type_label,
            description = excluded.description,
            years       = excluded.years,
            sort_order  = excluded.sort_order,
            updated_at  = datetime('now')
        """,
        (prospect_id, season_id, comp_type, type_label, player_name,
         description, years, sort_order),
    )
    conn.commit()
