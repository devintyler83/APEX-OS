from __future__ import annotations

import re
from typing import Optional, Tuple

_WS_RE = re.compile(r"\s+")

# Canonical NFL/ESPN position codes
CANON_POS = {
    "QB", "RB", "WR", "TE", "FB",
    "OT", "OG", "C",
    "DT", "LB", "EDGE",
    "CB", "S",
    "LS", "PK", "P",
}

# Deterministic alias map, BEFORE compound handling
# Keep this conservative and stable.
_ALIAS = {
    # Offense
    "HB": "RB",
    "TB": "RB",
    "TAILBACK": "RB",
    "RUNNING BACK": "RB",
    "FULLBACK": "FB",

    "WIDE RECEIVER": "WR",
    "RECEIVER": "WR",

    "TIGHT END": "TE",

    "CENTER": "C",
    "GUARD": "OG",
    "TACKLE": "OT",
    "OL": "OT",  # NOTE: if a source only gives OL, default to OT for canonical position.
               # We can later revise via a richer resolver using measurables or depth charts,
               # but do not drift rules midstream without a migration/backfill.

    # Defense
    "SAF": "S",
    "FS": "S",
    "SS": "S",
    "SAFETY": "S",

    "CORNER": "CB",
    "CBK": "CB",

    "NT": "DT",
    "NOSE": "DT",

    # Edge handling
    "DE": "EDGE",
    "ED": "EDGE",
    "EDGE RUSHER": "EDGE",
    "EDGE RUSHERS": "EDGE",
    "OLB": "LB",  # unless explicitly EDGE, keep LB for canonical

    # Special teams
    "K": "PK",
    "PK": "PK",
    "KICKER": "PK",
    "PUNTER": "P",
    "LONG SNAPPER": "LS",
}

# Common compound patterns that imply EDGE in draft media
_EDGE_COMPOUNDS = {
    "DE/ED", "ED/DE",
    "LB/ED", "ED/LB",
    "DE/LB", "LB/DE",
    "EDGE/LB", "LB/EDGE",
    "DE/EDGE", "EDGE/DE",
    "OLB/EDGE", "EDGE/OLB",
}

# Some sources use slash combos for DB
# We must pick a canonical NFL/ESPN position deterministically.
# Rule: if any token indicates CB-family, choose CB, else choose S.
_CB_TOKENS = {"CB", "NB", "NICKEL", "CORNER"}
_S_TOKENS = {"S", "FS", "SS", "SAF", "SAFETY"}


def normalize_position_raw(pos: str | None) -> str | None:
    """
    Raw cleaner only. Keeps the original semantics but normalizes formatting.
    This should remain stable and not do aggressive mapping.
    """
    if pos is None:
        return None
    s = _WS_RE.sub(" ", str(pos).strip().upper())
    s = s.replace(".", "")
    return s or None


def normalize_position_canonical(pos: str | None) -> str | None:
    """
    Map arbitrary source position labels to canonical NFL/ESPN codes.
    Returns None if we can't confidently map.
    """
    raw = normalize_position_raw(pos)
    if not raw:
        return None

    # Exact already-canonical
    if raw in CANON_POS:
        return raw

    # Normalize separators
    s = raw.replace("-", "/").replace("\\", "/")
    s = _WS_RE.sub(" ", s).strip()

    # Handle obvious EDGE compounds
    if s in _EDGE_COMPOUNDS:
        return "EDGE"

    # Tokenize slash compounds
    if "/" in s:
        tokens = [t.strip() for t in s.split("/") if t.strip()]
        tokset = set(tokens)

        # EDGE if any token indicates edge or DE/ED
        if any(t in {"DE", "ED", "EDGE"} for t in tokset):
            # If it's explicitly "EDGE" or has DE/ED, prefer EDGE.
            return "EDGE"

        # DB resolution
        if any(t in _CB_TOKENS for t in tokset):
            return "CB"
        if any(t in _S_TOKENS for t in tokset):
            return "S"

        # OL resolution (rare)
        if any(t in {"OT", "OG", "C", "OL"} for t in tokset):
            # Deterministic choice: OT
            return "OT"

        # Otherwise take first token if mappable via alias
        first = tokens[0]
        if first in CANON_POS:
            return first
        if first in _ALIAS:
            mapped = _ALIAS[first]
            return mapped if mapped in CANON_POS else None
        return None

    # Direct alias
    if s in _ALIAS:
        mapped = _ALIAS[s]
        return mapped if mapped in CANON_POS else None

    # Long-form / spaced labels
    if s in _ALIAS:
        mapped = _ALIAS[s]
        return mapped if mapped in CANON_POS else None

    return None


def position_group_from_canonical(pos_can: str | None) -> str | None:
    """
    Deterministic bucketing used across DraftOS.
    """
    if pos_can is None:
        return None

    if pos_can in {"QB"}:
        return "QB"
    if pos_can in {"RB", "FB"}:
        return "RB"
    if pos_can in {"WR"}:
        return "WR"
    if pos_can in {"TE"}:
        return "TE"
    if pos_can in {"OT", "OG", "C"}:
        return "OL"

    if pos_can in {"DT"}:
        return "DL"
    if pos_can in {"EDGE"}:
        return "EDGE"
    if pos_can in {"LB"}:
        return "LB"
    if pos_can in {"CB", "S"}:
        return "DB"

    if pos_can in {"LS", "PK", "P"}:
        return "ST"

    return None


def normalize_position(pos: str | None) -> Tuple[Optional[str], Optional[str]]:
    """
    Convenience: returns (position_canonical, position_group).
    """
    pos_can = normalize_position_canonical(pos)
    pos_group = position_group_from_canonical(pos_can) if pos_can else None
    return pos_can, pos_group