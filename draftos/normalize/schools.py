from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")


def normalize_school_raw(school: str | None) -> str | None:
    if school is None:
        return None
    s = _WS_RE.sub(" ", str(school).strip())
    return s or None