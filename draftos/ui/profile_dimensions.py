"""
profile_dimensions.py — Madden-Style Player Profile Dimension Mapping

Translates APEX trait vectors into position-specific football-language dimensions.
Pure derivation layer — no DB access, no API calls, no side effects.

Usage:
    from draftos.ui.profile_dimensions import get_profile_dimensions
    dims = get_profile_dimensions("EDGE", traits)
    # Returns: [("Speed Rush", 8.7), ("Hand Technique", 9.0), ...]
"""
from __future__ import annotations


def _w(scores: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted blend of trait scores. Rounds to 1 decimal."""
    total = sum(scores.get(k, 0.0) * w for k, w in weights.items())
    return round(total, 1)


def _v(scores: dict[str, float], key: str) -> float:
    """Direct trait vector lookup. Returns 0.0 if missing."""
    return round(scores.get(key, 0.0), 1)


# ---------------------------------------------------------------------------
# POSITIONAL DIMENSION MAPS
# ---------------------------------------------------------------------------
# Each position maps to a list of (label, derivation_spec) tuples.
# derivation_spec is either:
#   - A string key: direct trait vector lookup (e.g., "v_processing")
#   - A dict of {trait_key: weight}: weighted blend
#
# Dimensions are ordered by importance for that position.
# Each position has exactly 5-6 dimensions for clean visual layout.
# ---------------------------------------------------------------------------

_DIMENSION_MAPS: dict[str, list[tuple[str, str | dict[str, float]]]] = {

    "EDGE": [
        ("Speed Rush",         "v_athleticism"),
        ("Hand Technique",     "v_processing"),
        ("Power / Anchor",     "v_comp_tough"),
        ("Bend & Flexibility", {"v_athleticism": 0.6, "v_scheme_vers": 0.4}),
        ("Run Defense",        "v_production"),
        ("Motor",              {"v_comp_tough": 0.5, "c2_motivation": 0.5}),
    ],

    "QB": [
        ("Arm Talent",          {"v_athleticism": 0.4, "v_production": 0.6}),
        ("Processing",          "v_processing"),
        ("Mobility",            "v_athleticism"),
        ("Poise / Toughness",   "v_comp_tough"),
        ("Command",             {"v_processing": 0.5, "c2_motivation": 0.5}),
        ("Decision-Making",     {"v_processing": 0.7, "v_scheme_vers": 0.3}),
    ],

    "RB": [
        ("Speed / Burst",   "v_athleticism"),
        ("Power",           "v_comp_tough"),
        ("Elusiveness",     {"v_athleticism": 0.5, "v_processing": 0.5}),
        ("Receiving",       "v_scheme_vers"),
        ("Vision",          "v_processing"),
        ("Durability",      "v_injury"),
    ],

    "WR": [
        ("Route Running",            "v_processing"),
        ("Speed / Separation",       "v_athleticism"),
        ("Hands / Contested Catch",  "v_comp_tough"),
        ("YAC Ability",              {"v_athleticism": 0.5, "v_comp_tough": 0.5}),
        ("Versatility",              "v_scheme_vers"),
    ],

    "TE": [
        ("Receiving",    {"v_athleticism": 0.4, "v_production": 0.6}),
        ("Blocking",     "v_comp_tough"),
        ("Athleticism",  "v_athleticism"),
        ("Versatility",  "v_scheme_vers"),
        ("Red Zone",     {"v_comp_tough": 0.5, "v_production": 0.5}),
    ],

    "OT": [
        ("Pass Protection", {"v_processing": 0.5, "v_comp_tough": 0.5}),
        ("Athleticism",     "v_athleticism"),
        ("Run Blocking",    {"v_comp_tough": 0.6, "v_athleticism": 0.4}),
        ("Technique",       "v_processing"),
        ("Durability",      "v_injury"),
    ],

    "OG": [
        ("Pass Protection", {"v_processing": 0.5, "v_comp_tough": 0.5}),
        ("Run Blocking",    {"v_comp_tough": 0.6, "v_athleticism": 0.4}),
        ("Pull Ability",    {"v_athleticism": 0.7, "v_scheme_vers": 0.3}),
        ("Technique",       "v_processing"),
        ("Durability",      "v_injury"),
    ],

    "CB": [
        ("Coverage IQ",          "v_processing"),
        ("Speed / Recovery",     "v_athleticism"),
        ("Press / Physicality",  "v_comp_tough"),
        ("Ball Skills",          "v_production"),
        ("Versatility",          "v_scheme_vers"),
    ],

    "S": [
        ("Range",       "v_athleticism"),
        ("Coverage IQ", "v_processing"),
        ("Run Support", "v_comp_tough"),
        ("Playmaking",  "v_production"),
        ("Versatility", "v_scheme_vers"),
    ],

    "ILB": [
        ("Processing / Instincts", "v_processing"),
        ("Range / Speed",          "v_athleticism"),
        ("Tackling",               "v_comp_tough"),
        ("Coverage",               {"v_scheme_vers": 0.5, "v_processing": 0.5}),
        ("Leadership",             {"c2_motivation": 0.5, "v_processing": 0.5}),
    ],

    "IDL": [
        ("Pass Rush",  {"v_athleticism": 0.5, "v_production": 0.5}),
        ("Run Stuff",  "v_comp_tough"),
        ("Power",      {"v_comp_tough": 0.6, "v_athleticism": 0.4}),
        ("Quickness",  "v_athleticism"),
        ("Motor",      {"v_comp_tough": 0.5, "c2_motivation": 0.5}),
    ],
}

# Position aliases — map variant position strings to canonical dimension map keys
_POSITION_ALIASES: dict[str, str] = {
    "DE":   "EDGE",
    "OLB":  "EDGE",   # OLB-EDGE defaults to EDGE dimensions
    "DT":   "IDL",
    "NT":   "IDL",
    "FS":   "S",
    "SS":   "S",
    "MLB":  "ILB",
    "LB":   "ILB",
    "C":    "OG",     # Center uses interior OL dimensions
    "OL":   "OG",     # Generic OL defaults to interior
    "FB":   "RB",     # Fullback gets RB dimensions
    "ST":   "ILB",    # Special teams fallback
}


def get_profile_dimensions(
    position_group: str,
    traits: dict[str, float],
) -> list[tuple[str, float]]:
    """
    Compute Madden-style positional profile dimensions from APEX trait vectors.

    Args:
        position_group: Position string from prospects table (e.g., "EDGE", "QB", "S")
        traits: Dict of trait vector scores. Expected keys:
            v_processing, v_athleticism, v_scheme_vers, v_comp_tough,
            v_character, v_dev_traj, v_production, v_injury,
            c1_public_record, c2_motivation, c3_psych_profile

    Returns:
        List of (dimension_label, score) tuples. Score is float 1.0-10.0.
        Returns empty list if position is unrecognized and has no alias.

    Example:
        >>> traits = {"v_processing": 9.5, "v_athleticism": 8.7, ...}
        >>> get_profile_dimensions("S", traits)
        [("Range", 8.7), ("Coverage IQ", 9.5), ("Run Support", 9.2), ...]
    """
    pos = (position_group or "").upper().strip()

    # Resolve alias
    canonical = _POSITION_ALIASES.get(pos, pos)

    dim_map = _DIMENSION_MAPS.get(canonical)
    if dim_map is None:
        # Unknown position — return empty, caller should fall back to raw trait vectors
        return []

    result: list[tuple[str, float]] = []
    for label, spec in dim_map:
        if isinstance(spec, str):
            score = _v(traits, spec)
        elif isinstance(spec, dict):
            score = _w(traits, spec)
        else:
            score = 0.0
        result.append((label, score))

    return result


def get_available_positions() -> list[str]:
    """Return list of positions with defined dimension maps (for testing/docs)."""
    return sorted(_DIMENSION_MAPS.keys())
