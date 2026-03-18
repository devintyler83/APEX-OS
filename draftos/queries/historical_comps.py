"""
Historical comp query layer.
Read-only. No DB writes.
"""
from __future__ import annotations
import re
from typing import Optional


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


def get_historical_comps(conn, archetype_code: str, limit: int = 3) -> list[dict]:
    """
    Return top N historical comps for an archetype, ordered by confidence then outcome.
    Confidence order: A > B > C. Outcome order: HIT > PARTIAL > MISS.
    """
    code = _extract_archetype_code(archetype_code)
    rows = conn.execute(
        """
        SELECT player_name, position, archetype_code,
               translation_outcome, fm_code, outcome_summary,
               era_bracket, peak_years, comp_confidence,
               scheme_context, signature_trait
        FROM historical_comps
        WHERE archetype_code = ?
          AND is_fm_reference = 0
        ORDER BY
            CASE comp_confidence WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
            CASE translation_outcome WHEN 'HIT' THEN 1 WHEN 'PARTIAL' THEN 2 ELSE 3 END
        LIMIT ?
        """,
        (code, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_fm_reference_comps(
    conn,
    fm_code: str,
    archetype_code: Optional[str] = None,
    limit: int = 2,
) -> list[dict]:
    """
    Get FM reference comps (is_fm_reference=1) for a given FM code.
    Optionally filter by archetype_code to prefer same-archetype FM refs.
    Returns up to `limit` records.

    Slot priority:
      1. Same archetype + same FM code (most specific)
      2. Same FM code, any archetype (cross-positional reference)

    Column mapping (actual DB columns):
      outcome_summary  → concise comp summary for display
      fm_mechanism     → FM-specific bust mechanism text
      mechanism        → full mechanism description
      pre_draft_signal → pre-draft signal text
    """
    code      = _extract_fm_code(fm_code) or fm_code
    arch_code = _extract_archetype_code(archetype_code) if archetype_code else ""

    rows = conn.execute(
        """
        SELECT comp_id, player_name, position, archetype_code,
               translation_outcome, fm_code, outcome_summary,
               fm_mechanism, mechanism, era_bracket, peak_years,
               comp_confidence, pre_draft_signal, is_fm_reference
        FROM historical_comps
        WHERE fm_code LIKE ?
          AND is_fm_reference = 1
        ORDER BY
            CASE WHEN archetype_code = ? THEN 0 ELSE 1 END,
            CASE comp_confidence WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
            CASE translation_outcome WHEN 'MISS' THEN 0 WHEN 'PARTIAL' THEN 1 ELSE 2 END
        LIMIT ?
        """,
        (f"%{code}%", arch_code, limit),
    ).fetchall()

    return [dict(r) for r in rows]


def get_archetype_translation_rate(conn, archetype_code: str) -> dict:
    """
    Compute HIT/PARTIAL/MISS counts and HIT rate for an archetype.
    Returns dict with total, hit_count, partial_count, miss_count, hit_rate_pct.
    """
    code = _extract_archetype_code(archetype_code)
    rows = conn.execute(
        """
        SELECT translation_outcome, COUNT(*) as cnt
        FROM historical_comps
        WHERE archetype_code = ?
        GROUP BY translation_outcome
        """,
        (code,),
    ).fetchall()

    counts = {"HIT": 0, "PARTIAL": 0, "MISS": 0}
    for row in rows:
        counts[row["translation_outcome"]] = row["cnt"]

    total = sum(counts.values())
    hit_rate = round(counts["HIT"] / total * 100) if total > 0 else 0

    return {
        "total": total,
        "hit_count": counts["HIT"],
        "partial_count": counts["PARTIAL"],
        "miss_count": counts["MISS"],
        "hit_rate_pct": hit_rate,
    }
