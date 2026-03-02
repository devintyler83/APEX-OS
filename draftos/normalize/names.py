from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

_SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV|V|2ND|3RD|4TH|5TH)\.?\s*$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

# Common football position codes. Used ONLY to strip leading prefixes like "S " or "DE/ED ".
# Deterministic, conservative: only strips the first token if it is clearly a position code.
_POS_CODES = {
    "qb", "rb", "wr", "te",
    "ot", "og", "c", "ol",
    "dt", "de", "dl", "edge",
    "lb", "ilb", "olb",
    "cb", "db", "s", "fs", "ss",
    "k", "p", "ls",
}


def normalize_whitespace(s: str) -> str:
    return _WS_RE.sub(" ", s.strip())


def strip_suffix(full_name: str) -> tuple[str, str | None]:
    """
    Returns (name_without_suffix, suffix_or_none)
    """
    s = normalize_whitespace(full_name or "")
    m = _SUFFIX_RE.search(s)
    if not m:
        return s, None
    suffix = m.group(1).upper()
    s2 = _SUFFIX_RE.sub("", s).strip()
    s2 = normalize_whitespace(s2)
    return s2, suffix


def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _strip_leading_position_prefix(raw: str) -> str:
    """
    Removes a single leading token if it is clearly a position code.
    Examples:
      "S A.J. Haulcy" -> "A.J. Haulcy"
      "DE/ED Rueben Bain Jr." -> "Rueben Bain Jr."
      "OT/OG Ar'maj Reed-Adams" -> "Ar'maj Reed-Adams"
    """
    s = normalize_whitespace(raw or "")
    if not s:
        return s

    parts = s.split(" ", 1)
    if len(parts) == 1:
        return s

    first, rest = parts[0], parts[1]

    # Normalize the token for evaluation: letters and slashes only
    tok = re.sub(r"[^A-Za-z/]", "", first).lower()
    if not tok:
        return s

    # Single code
    if tok in _POS_CODES:
        return rest.strip()

    # Slash-separated codes, all must be known
    if "/" in tok:
        subs = [t for t in tok.split("/") if t]
        if subs and all(t in _POS_CODES for t in subs):
            return rest.strip()

    return s


def _clean_basic(s: str) -> str:
    """
    Deterministic cleanup used for downstream tokenization:
      - lower
      - strip diacritics
      - normalize separators to spaces
      - remove punctuation except spaces/alphanumerics
      - drop apostrophes entirely: o'neal -> oneal
      - collapse whitespace
    """
    s = (s or "").strip()
    if not s:
        return ""
    s = _strip_diacritics(s)
    s = s.lower()

    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"[^a-z0-9\s']", " ", s)
    s = s.replace("'", "")
    s = normalize_whitespace(s)
    return s


def _combine_initials(tokens: List[str]) -> List[str]:
    """
    Combine consecutive single-letter tokens into one:
      ["a", "j", "haulcy"] -> ["aj", "haulcy"]
    """
    out: List[str] = []
    buf: List[str] = []
    for t in tokens:
        if len(t) == 1 and t.isalpha():
            buf.append(t)
            continue
        if buf:
            out.append("".join(buf))
            buf = []
        out.append(t)
    if buf:
        out.append("".join(buf))
    return out


def name_norm_and_key(full_name: str, alias_token_map: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """
    Deterministic name normalization.

    Returns:
      name_norm: tokenized + suffix removed + initials combined + aliases applied
      name_key : name_norm with spaces removed (stable join key)
    """
    alias_token_map = alias_token_map or {}

    # Strip position prefix first (handles "S A.J. Haulcy", "DE/ED Rueben Bain Jr.")
    stripped = _strip_leading_position_prefix(full_name or "")

    # Remove suffix (JR/SR/II/III/...)
    base, _suffix = strip_suffix(stripped)
    cleaned = _clean_basic(base)
    if not cleaned:
        return "", ""

    tokens = cleaned.split(" ")
    tokens = _combine_initials(tokens)

    expanded: List[str] = []
    for t in tokens:
        repl = alias_token_map.get(t)
        if repl:
            repl_clean = _clean_basic(repl)
            expanded.extend(repl_clean.split(" ") if repl_clean else [])
        else:
            expanded.append(t)

    expanded = [t for t in expanded if t]
    name_norm = normalize_whitespace(" ".join(expanded))
    name_key = name_norm.replace(" ", "")
    return name_norm, name_key