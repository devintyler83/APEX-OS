from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")


def normalize_position_raw(pos: str | None) -> str | None:
    if pos is None:
        return None
    s = _WS_RE.sub(" ", str(pos).strip().upper())
    s = s.replace(".", "")
    return s or None