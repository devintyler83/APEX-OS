"""
Historical comp query layer.
Read-only. No DB writes.
"""
from __future__ import annotations
import re


def _extract_archetype_code(archetype: str) -> str:
    """
    Extract the short code prefix from a full archetype name.
    'WR-1 Route Technician' -> 'WR-1'
    'EDGE-3' -> 'EDGE-3'
    """
    m = re.match(r'^([A-Z]+-\d+)', archetype.strip())
    return m.group(1) if m else archetype.strip()


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
        ORDER BY
            CASE comp_confidence WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
            CASE translation_outcome WHEN 'HIT' THEN 1 WHEN 'PARTIAL' THEN 2 ELSE 3 END
        LIMIT ?
        """,
        (code, limit),
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
