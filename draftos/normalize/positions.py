from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Canonical positions (NFL.com + ESPN requirement)
CANONICAL_POSITIONS = {
    "QB", "RB", "WR", "TE", "FB",
    "OT", "OG", "C",
    "DT", "LB", "EDGE",
    "CB", "S",
    "LS", "PK", "P",
}

# Deterministic position groups for UI, filtering, and identity
# Keep these stable once prospect_key is in use.
POSITION_GROUPS = {
    "QB", "RB", "WR", "TE", "FB",
    "OL", "DT", "EDGE", "LB", "CB", "S",
    "ST",
}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^A-Z0-9/]+")
_SLASH_SPLIT_RE = re.compile(r"\s*/\s*")


@dataclass(frozen=True)
class NormalizedPosition:
    raw: str
    canonical: str
    group: str


def _clean(raw: str) -> str:
    s = (raw or "").strip().upper()
    s = s.replace("-", "/")
    s = _WS_RE.sub(" ", s)
    s = _PUNCT_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def position_group_from_canonical(canonical: str) -> str:
    """
    Deterministic grouping derived from canonical position.
    """
    c = (canonical or "").strip().upper()

    if c in {"OT", "OG", "C"}:
        return "OL"
    if c in {"PK", "P", "LS"}:
        return "ST"
    if c in {"QB", "RB", "WR", "TE", "FB", "DT", "EDGE", "LB", "CB", "S"}:
        return c

    # Fallback is deterministic, but should be rare.
    return "ST"


def normalize_position(raw_position: str) -> NormalizedPosition:
    """
    Normalize raw source positions to canonical positions (NFL.com + ESPN).

    Canonical positions:
    QB, RB, WR, TE, FB, OT, OG, C, DT, LB, EDGE, CB, S, LS, PK, P

    Notes:
    - Hybrid labels like "DE/ED", "LB/EDGE", "OL", "IOL", "OT/OG" are normalized deterministically.
    - If a raw value is unknown, we return "LB" as a conservative defensive fallback only when
      the token contains "LB". Otherwise, we fallback to "S" if it contains "S/SAF".
      If no useful signal exists, we fallback to "LB". These fallbacks remain deterministic.
    """
    raw = raw_position or ""
    s = _clean(raw)

    # Fast exact canonical hit
    if s in CANONICAL_POSITIONS:
        c = s
        return NormalizedPosition(raw=raw, canonical=c, group=position_group_from_canonical(c))

    # Common synonyms and abbreviations (single-token)
    direct = {
        # offense
        "HB": "RB",
        "TB": "RB",
        "TAILBACK": "RB",
        "RUNNINGBACK": "RB",
        "WIDEOUT": "WR",
        "REC": "WR",
        "FL": "WR",
        "SE": "WR",
        "SLOT": "WR",

        # OL
        "OL": "OT",     # if only "OL" is given, prefer OT as the neutral OT/OL anchor
        "T": "OT",
        "LT": "OT",
        "RT": "OT",
        "G": "OG",
        "LG": "OG",
        "RG": "OG",
        "IOL": "OG",    # interior OL bucket mapped to OG deterministically

        # defense
        "DL": "DT",     # neutral DL anchor
        "IDL": "DT",
        "NT": "DT",
        "NOSE": "DT",
        "DT/NT": "DT",

        "DE": "EDGE",   # ESPN/NFL.com commonly treat DE prospects as EDGE in draft context
        "EDGE": "EDGE",
        "ED": "EDGE",
        "OLB": "LB",    # base OLB label maps to LB unless explicitly EDGE is present
        "ILB": "LB",
        "MLB": "LB",

        "DB": "CB",     # neutral DB anchor
        "CB": "CB",
        "NCB": "CB",
        "SLOT CB": "CB",

        "S": "S",
        "SS": "S",
        "FS": "S",
        "SAF": "S",
        "SAFETY": "S",

        # special teams
        "K": "PK",
        "PK": "PK",
        "KICKER": "PK",
        "PUNTER": "P",
        "LS": "LS",
        "LONGSNAPPER": "LS",
        "LONG SNAPPER": "LS",
    }

    if s in direct:
        c = direct[s]
        return NormalizedPosition(raw=raw, canonical=c, group=position_group_from_canonical(c))

    # Handle multi-token labels like "SLOT CB"
    if s.replace(" ", "") in direct:
        c = direct[s.replace(" ", "")]
        return NormalizedPosition(raw=raw, canonical=c, group=position_group_from_canonical(c))

    # Slash hybrids, pick deterministically by priority rules
    # Priority: QB,RB,WR,TE,FB,OT,OG,C,EDGE,LB,DT,CB,S,LS,PK,P
    priority = ["QB", "RB", "WR", "TE", "FB", "OT", "OG", "C", "EDGE", "LB", "DT", "CB", "S", "LS", "PK", "P"]

    parts = _SLASH_SPLIT_RE.split(s) if "/" in s else []
    if parts:
        expanded: list[str] = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p in CANONICAL_POSITIONS:
                expanded.append(p)
                continue
            if p in direct:
                expanded.append(direct[p])
                continue
            # common hybrids
            if p in {"DE", "ED", "DEED", "DE/ED"}:
                expanded.append("EDGE")
                continue
            if p in {"LB", "OLB", "ILB", "MLB"}:
                expanded.append("LB")
                continue
            if p in {"SAF", "SS", "FS"}:
                expanded.append("S")
                continue
            if p in {"T", "LT", "RT"}:
                expanded.append("OT")
                continue
            if p in {"G", "LG", "RG", "IOL"}:
                expanded.append("OG")
                continue
            if p in {"DL", "IDL", "NT"}:
                expanded.append("DT")
                continue

        # Choose the earliest by priority, deterministic
        for c in priority:
            if c in expanded:
                return NormalizedPosition(raw=raw, canonical=c, group=position_group_from_canonical(c))

    # Phrase heuristics, deterministic
    if "QUARTER" in s or s == "Q" or "QB" in s:
        c = "QB"
    elif "RUN" in s or "BACK" in s or s.endswith("HB") or "RB" in s:
        c = "RB"
    elif "WIDE" in s or "WR" in s:
        c = "WR"
    elif "TIGHT" in s or "TE" in s:
        c = "TE"
    elif "FULL" in s or "FB" in s:
        c = "FB"
    elif "CENTER" in s or s == "C":
        c = "C"
    elif "GUARD" in s or "OG" in s or "IOL" in s:
        c = "OG"
    elif "TACKLE" in s or "OT" in s:
        c = "OT"
    elif "NOSE" in s or "DT" in s or "TACKLE" in s and "DEF" in s:
        c = "DT"
    elif "EDGE" in s or "DE" in s or "ED" in s:
        c = "EDGE"
    elif "LINEBACK" in s or "LB" in s:
        c = "LB"
    elif "CORNER" in s or "CB" in s:
        c = "CB"
    elif "SAF" in s or s.endswith("S") or "FS" in s or "SS" in s:
        c = "S"
    elif "KICK" in s or "PK" in s or s == "K":
        c = "PK"
    elif "PUNT" in s or s == "P":
        c = "P"
    elif "SNAP" in s or "LS" in s:
        c = "LS"
    else:
        # Final deterministic fallback
        c = "LB"

    return NormalizedPosition(raw=raw, canonical=c, group=position_group_from_canonical(c))