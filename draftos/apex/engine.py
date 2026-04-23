"""
APEX v2.3 deterministic math layer.
No AI calls. Pure computation only.

Functions:
  get_pvc(position_group) -> float
  get_archetype_weight(conn, position_group, archetype_code) -> float
  get_archetype_pvc(conn, position_group, archetype_code) -> float
  compute_apex_composite(raw_score, position_group) -> float
  compute_apex_tier(apex_composite) -> str
  compute_divergence(apex_composite, consensus_rank, apex_tier, consensus_tier) -> dict
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Positional Value Coefficient (PVC) table
# ---------------------------------------------------------------------------
PVC_TABLE: dict[str, float] = {
    "QB":   1.00,
    "CB":   1.00,
    "EDGE": 1.00,
    "WR":   0.90,   # slot/receiving premium era
    "OT":   0.90,
    "S":    0.90,
    "IDL":  0.90,
    "DT":   0.90,
    "ILB":  0.85,
    "OLB":  0.85,
    "LB":   0.85,
    "OG":   0.80,
    "TE":   0.80,
    "C":    0.80,
    "OL":   0.80,
    "RB":   0.70,
}

# ---------------------------------------------------------------------------
# Tier thresholds (applied to apex_composite = raw_score * PVC, 0-100 scale)
# Ordered highest to lowest. First match wins.
# Draft-capital vocabulary: ELITE | DAY1 | DAY2 | DAY3 | UDFA-P | UDFA
# ---------------------------------------------------------------------------
TIER_THRESHOLDS: list[tuple[str, float]] = [
    ("ELITE",  85.0),
    ("DAY1",   70.0),
    ("DAY2",   55.0),
    ("DAY3",   40.0),
    ("UDFA-P", 28.0),
    ("UDFA",    0.0),
]


def get_pvc(position_group: str) -> float:
    """Return PVC from table. Default 0.80 for unknown/unmapped positions."""
    if not position_group:
        return 0.80
    return PVC_TABLE.get(position_group.upper(), 0.80)


# ILB/OLB stored as LB in pvc_archetype_weights (weight builder normalizes them)
_LB_NORM: frozenset[str] = frozenset({"ILB", "OLB"})


def _weights_position_key(position_group: str) -> str:
    return "LB" if position_group.upper() in _LB_NORM else position_group.upper()


def get_archetype_weight(conn, position_group: str, archetype_code: str) -> float:
    """Return archetype weight multiplier from pvc_archetype_weights (trusted=1 rows only).
    Returns 1.0 if no trusted row found (falls back to position-group PVC)."""
    if not position_group or not archetype_code:
        return 1.0
    wt_pos = _weights_position_key(position_group)
    row = conn.execute(
        "SELECT weight FROM pvc_archetype_weights "
        "WHERE position_group=? AND archetype_code=? AND trusted=1",
        (wt_pos, archetype_code),
    ).fetchone()
    return row[0] if row else 1.0


def get_archetype_pvc(conn, position_group: str, archetype_code: str) -> float:
    """Return position_pvc * archetype_weight, rounded to 4 decimal places.
    Falls back to position_pvc alone if no trusted archetype row exists."""
    position_pvc = get_pvc(position_group)
    archetype_weight = get_archetype_weight(conn, position_group, archetype_code)
    return round(position_pvc * archetype_weight, 4)


def compute_apex_composite(raw_score: float, position_group: str) -> float:
    """
    apex_composite = raw_score * pvc, rounded to 1 decimal.
    raw_score is on 0-100 scale (as returned by Claude).
    """
    pvc = get_pvc(position_group)
    return round(raw_score * pvc, 1)


def compute_apex_tier(apex_composite: float) -> str:
    """Map composite score to draft-capital tier label."""
    for tier, floor in TIER_THRESHOLDS:
        if apex_composite >= floor:
            return tier
    return "UDFA"


def _apex_round_from_composite(apex_composite: float) -> float:
    """Rough draft round estimate from APEX composite score."""
    if apex_composite >= 90:
        return 1.0
    elif apex_composite >= 82:
        return 1.5
    elif apex_composite >= 75:
        return 2.0
    elif apex_composite >= 68:
        return 2.5
    elif apex_composite >= 60:
        return 3.0
    elif apex_composite >= 52:
        return 4.0
    elif apex_composite >= 44:
        return 5.5
    else:
        return 7.0


def _consensus_round_from_rank(consensus_rank: int) -> float:
    """Rough draft round estimate from consensus overall rank."""
    if consensus_rank <= 32:
        return 1.0
    elif consensus_rank <= 64:
        return 2.0
    elif consensus_rank <= 105:
        return 3.0
    elif consensus_rank <= 141:
        return 4.0
    elif consensus_rank <= 178:
        return 5.0
    elif consensus_rank <= 220:
        return 6.0
    else:
        return 7.0


def compute_divergence(
    apex_composite: float,
    consensus_rank: int,
    apex_tier: str,
    consensus_tier: str,
) -> dict:
    """
    Compute divergence between APEX composite and consensus-implied score.

    consensus_implied_score = max(0, (1 - consensus_rank / 500) * 100)
    divergence_score = apex_composite - consensus_implied_score

    divergence_flag:
      'APEX HIGH'  if divergence_score > 10
      'APEX LOW'   if divergence_score < -10
      'ALIGNED'    otherwise

    divergence_mag:
      'MAJOR'    if abs(divergence_score) > 25
      'MODERATE' if abs(divergence_score) > 10
      'MINOR'    otherwise

    apex_favors: +1 (APEX HIGH), -1 (APEX LOW), 0 (ALIGNED)
    rounds_diff: apex_round - consensus_round
    """
    consensus_implied = max(0.0, (1.0 - consensus_rank / 500.0) * 100.0)
    divergence_score  = round(apex_composite - consensus_implied, 2)

    if divergence_score > 10:
        flag        = "APEX HIGH"
        apex_favors = 1
    elif divergence_score < -10:
        flag        = "APEX LOW"
        apex_favors = -1
    else:
        flag        = "ALIGNED"
        apex_favors = 0

    abs_div = abs(divergence_score)
    if abs_div > 25:
        mag = "MAJOR"
    elif abs_div > 10:
        mag = "MODERATE"
    else:
        mag = "MINOR"

    apex_round      = _apex_round_from_composite(apex_composite)
    consensus_round = _consensus_round_from_rank(consensus_rank)
    rounds_diff     = round(apex_round - consensus_round, 1)

    return {
        "divergence_score":    divergence_score,
        "divergence_flag":     flag,
        "divergence_mag":      mag,
        "apex_favors":         apex_favors,
        "rounds_diff":         rounds_diff,
        "apex_round":          apex_round,
        "consensus_implied":   round(consensus_implied, 2),
    }
