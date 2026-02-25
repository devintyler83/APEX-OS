from __future__ import annotations

import re

_SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV|V)\b\.?$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def normalize_whitespace(s: str) -> str:
    return _WS_RE.sub(" ", s.strip())


def strip_suffix(full_name: str) -> tuple[str, str | None]:
    """
    Returns (name_without_suffix, suffix_or_none)
    """
    s = normalize_whitespace(full_name)
    m = _SUFFIX_RE.search(s)
    if not m:
        return s, None
    suffix = m.group(1).upper()
    s2 = _SUFFIX_RE.sub("", s).strip()
    s2 = normalize_whitespace(s2)
    return s2, suffix