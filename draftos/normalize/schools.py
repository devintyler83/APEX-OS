from __future__ import annotations

import re
from typing import Optional

_WS_RE = re.compile(r"\s+")
_PARENS_RE = re.compile(r"\((.*?)\)")


def normalize_school_raw(school: str | None) -> str | None:
    """
    Light cleanup for display/storage.
    We do NOT apply alias tables here because aliases live in DB (school_aliases).
    """
    if school is None:
        return None
    s = _WS_RE.sub(" ", str(school).strip())
    return s or None


def school_key(school: str | None) -> Optional[str]:
    """
    Deterministic key used for matching.
    - lower
    - strip punctuation-ish
    - remove parenthetical qualifiers like "(FL)" for keying purposes
    """
    raw = normalize_school_raw(school)
    if not raw:
        return None

    s = raw.lower().strip()
    s = _PARENS_RE.sub("", s)          # remove "(FL)" etc
    s = re.sub(r"[^\w\s-]", "", s)     # drop punctuation
    s = _WS_RE.sub(" ", s).strip()
    return s or None