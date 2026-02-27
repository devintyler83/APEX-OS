# scripts/patch_0007_bootstrap_prospects_2026.py
from __future__ import annotations

# --- sys.path bootstrap so "python scripts\..." always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # C:\DraftOS
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import hashlib
import re
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.positions import normalize_position

# Optional: use repo normalizers if discoverable.
# If not, deterministic fallbacks are used.
try:
    from draftos.normalize import names as names_norm  # type: ignore
except Exception:
    names_norm = None  # type: ignore

try:
    from draftos.normalize import schools as schools_norm  # type: ignore
except Exception:
    schools_norm = None  # type: ignore


_SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV|V)\b\.?$", re.IGNORECASE)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup_db(reason: str) -> Path:
    src = PATHS.db
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"draftos_{ts}_{reason}.sqlite"
    dst.write_bytes(Path(src).read_bytes())
    return dst


# -------------------------
# Deterministic fallbacks
# -------------------------

_NAME_PUNCT_RE = re.compile(r"[^A-Za-z0-9\s'\-\.]")
_WS_RE = re.compile(r"\s+")
_DOT_SPACE_RE = re.compile(r"\s*\.\s*")
_HYPHEN_SPACE_RE = re.compile(r"\s*-\s*")


def normalize_name_fallback(name: str) -> str:
    """
    Deterministic person-name normalization (fallback).
    - Strips weird punctuation
    - Normalizes whitespace
    - Preserves apostrophes and hyphens as part of names
    - Title-cases tokens deterministically
    """
    s = (name or "").strip()
    if not s:
        return ""

    s = _NAME_PUNCT_RE.sub(" ", s)
    s = _DOT_SPACE_RE.sub(".", s)
    s = _HYPHEN_SPACE_RE.sub("-", s)
    s = _WS_RE.sub(" ", s).strip()

    parts = []
    for token in s.split(" "):
        if not token:
            continue
        if token.isupper() and len(token) <= 3:
            parts.append(token)
        else:
            if "'" in token:
                sub = []
                for p in token.split("'"):
                    sub.append(p[:1].upper() + p[1:].lower() if p else "")
                parts.append("'".join(sub))
            else:
                parts.append(token[:1].upper() + token[1:].lower())
    return " ".join(parts).strip()


_SCHOOL_PUNCT_RE = re.compile(r"[^A-Za-z0-9\s&'\-\.]")
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_school_fallback(school: str) -> str:
    """
    Deterministic school normalization (fallback).
    """
    s = (school or "").strip()
    if not s:
        return ""
    s = _SCHOOL_PUNCT_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def pick_first_callable(mod, candidates: list[str]) -> Optional[Callable[[str], str]]:
    if mod is None:
        return None
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn  # type: ignore[return-value]
    return None


# Try to discover deterministic normalizers in-repo without blocking if names differ
NAME_NORMALIZE = pick_first_callable(
    names_norm,
    [
        "normalize",
        "normalize_name",
        "normalize_full_name",
        "canonicalize_name",
        "canonical_name",
        "clean_name",
        "to_display_name",
        "display_name",
        "name_normalize",
    ],
)

SCHOOL_NORMALIZE = pick_first_callable(
    schools_norm,
    [
        "normalize",
        "normalize_school",
        "canonicalize_school",
        "canonical_school",
        "clean_school",
        "school_normalize",
    ],
)


def normalize_full_name(raw_full_name: str) -> Tuple[str, Optional[str]]:
    """
    Returns (display_name, suffix or None).
    Suffix stripped for identity stability.
    """
    s = (raw_full_name or "").strip()
    if not s:
        return ("", None)

    m = _SUFFIX_RE.search(s)
    suffix = None
    if m:
        suffix = m.group(1).upper()
        s = _SUFFIX_RE.sub("", s).strip()

    if NAME_NORMALIZE is not None:
        try:
            s2 = NAME_NORMALIZE(s)
            if isinstance(s2, str):
                s2 = s2.strip()
                if s2:
                    return (s2, suffix)
        except Exception:
            pass

    return (normalize_name_fallback(s), suffix)


def normalize_school(raw_school: str) -> str:
    s = (raw_school or "").strip()
    if not s:
        return ""
    if SCHOOL_NORMALIZE is not None:
        try:
            s2 = SCHOOL_NORMALIZE(s)
            if isinstance(s2, str):
                s2 = s2.strip()
                if s2:
                    return s2
        except Exception:
            pass
    return normalize_school_fallback(s)


def name_key(display_name: str) -> str:
    s = (display_name or "").lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def school_key(school_canonical: str) -> str:
    s = (school_canonical or "").lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def make_prospect_key(
    draft_year: int,
    display_name: str,
    school_canonical: str,
    pos_group: str,
) -> str:
    """
    prospect_key must align with schema uniqueness:
      UNIQUE(season_id, full_name, school_canonical, position_group)

    Therefore v1 prospect_key is keyed at the *position_group* level (not canonical position):
      SHA1("{draft_year}|{name_key}|{school_key}|{pos_group}")
      stored as: "p{draft_year}_{sha1[:16]}"

    Once prospects exist, this rule is sacred.
    """
    base = f"{draft_year}|{name_key(display_name)}|{school_key(school_canonical)}|{pos_group}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"p{draft_year}_{h}"


def get_season_id(conn, draft_year: int) -> int:
    row = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?",
        (draft_year,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season {draft_year} not found. Seed it first.")
    return int(row["season_id"])


def sources_has_is_active(conn) -> bool:
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(sources);").fetchall()]
    return "is_active" in cols


def iter_active_source_players(conn, season_id: int):
    """
    Iterates source_players for active sources only (if sources.is_active exists),
    otherwise iterates all sources (legacy compatibility).
    Uses real column names: raw_full_name/raw_school/raw_position.
    """
    has_active = sources_has_is_active(conn)

    if has_active:
        sql = """
        SELECT
          sp.source_player_id,
          sp.source_id,
          sp.raw_full_name,
          sp.raw_school,
          sp.raw_position
        FROM source_players sp
        JOIN sources s ON s.source_id = sp.source_id
        WHERE s.is_active = 1
          AND sp.season_id = ?
        ORDER BY sp.source_id, sp.source_player_id
        """
    else:
        sql = """
        SELECT
          sp.source_player_id,
          sp.source_id,
          sp.raw_full_name,
          sp.raw_school,
          sp.raw_position
        FROM source_players sp
        WHERE sp.season_id = ?
        ORDER BY sp.source_id, sp.source_player_id
        """

    cur = conn.execute(sql, (season_id,))
    for r in cur:
        yield r


def upsert_prospect(
    conn,
    season_id: int,
    draft_year: int,
    raw_full_name: str,
    raw_school: str,
    raw_pos: str,
) -> int:
    display_name, suffix = normalize_full_name(raw_full_name)
    if not display_name:
        raise ValueError("empty display_name after normalization")

    school_canon = normalize_school(raw_school)

    raw_pos = raw_pos or ""
    pos_norm = normalize_position(raw_pos)
    pos_group = pos_norm.group

    # First, respect schema-unique identity tuple
    existing_by_tuple = conn.execute(
        """
        SELECT prospect_id, prospect_key
        FROM prospects
        WHERE season_id = ?
          AND full_name = ?
          AND school_canonical = ?
          AND position_group = ?
        """,
        (season_id, display_name, school_canon, pos_group),
    ).fetchone()
    if existing_by_tuple:
        return int(existing_by_tuple["prospect_id"])

    prospect_key = make_prospect_key(draft_year, display_name, school_canon, pos_group)
    now = utcnow_iso()

    # If a row exists by prospect_key (should not happen if rules are consistent), return it.
    existing_by_key = conn.execute(
        "SELECT prospect_id FROM prospects WHERE prospect_key = ?",
        (prospect_key,),
    ).fetchone()
    if existing_by_key:
        return int(existing_by_key["prospect_id"])

    parts = display_name.split()
    first_name = parts[0] if parts else None
    last_name = parts[-1] if len(parts) > 1 else None

    conn.execute(
        """
        INSERT INTO prospects(
          season_id, prospect_key, first_name, last_name, full_name, display_name, suffix,
          position_group, position_raw, school_canonical,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            season_id,
            prospect_key,
            first_name,
            last_name,
            display_name,  # normalized stable value
            display_name,
            suffix,
            pos_group,
            pos_norm.canonical,  # stored as position_raw field per current schema usage
            school_canon,
            now,
            now,
        ),
    )

    row = conn.execute(
        "SELECT prospect_id FROM prospects WHERE prospect_key = ?",
        (prospect_key,),
    ).fetchone()
    return int(row["prospect_id"])


def upsert_source_map(conn, source_player_id: int, prospect_id: int) -> bool:
    existing = conn.execute(
        "SELECT map_id FROM source_player_map WHERE source_player_id = ?",
        (source_player_id,),
    ).fetchone()
    if existing:
        return False

    conn.execute(
        """
        INSERT INTO source_player_map(
          source_player_id, prospect_id, match_method, match_score,
          match_notes, reviewed, reviewed_by, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_player_id,
            prospect_id,
            "rule",
            1.0,
            "bootstrap_v1 prospect_key (group-keyed)",
            0,
            None,
            None,
        ),
    )
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", type=int, default=0, help="1 to apply, 0 to dry-run")
    ap.add_argument("--draft-year", type=int, default=2026)
    args = ap.parse_args()

    draft_year = args.draft_year

    if args.apply == 1:
        backup_path = backup_db(f"patch_0007_bootstrap_{draft_year}")
        print(f"DB BACKUP: {backup_path}")
    else:
        print("DRY RUN: no DB writes, no backup")

    with connect() as conn:
        season_id = get_season_id(conn, draft_year)

        # Dry run: compute keys + count rows
        if args.apply != 1:
            scanned = 0
            for r in iter_active_source_players(conn, season_id):
                display_name, _ = normalize_full_name(r["raw_full_name"])
                school_canon = normalize_school(r["raw_school"])
                pos_norm = normalize_position(r["raw_position"] or "")
                _ = make_prospect_key(draft_year, display_name, school_canon, pos_norm.group)
                scanned += 1
            print(f"ACTIVE source_players scanned: {scanned}")
            return

        prospects_before = conn.execute(
            "SELECT COUNT(*) AS n FROM prospects WHERE season_id = ?",
            (season_id,),
        ).fetchone()["n"]

        if sources_has_is_active(conn):
            mapped_before = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM source_player_map m
                JOIN source_players sp ON sp.source_player_id = m.source_player_id
                JOIN sources s ON s.source_id = sp.source_id
                WHERE sp.season_id = ?
                  AND s.is_active = 1
                """,
                (season_id,),
            ).fetchone()["n"]
        else:
            mapped_before = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM source_player_map m
                JOIN source_players sp ON sp.source_player_id = m.source_player_id
                WHERE sp.season_id = ?
                """,
                (season_id,),
            ).fetchone()["n"]

        new_maps = 0

        for r in iter_active_source_players(conn, season_id):
            pid = upsert_prospect(
                conn,
                season_id,
                draft_year,
                r["raw_full_name"],
                r["raw_school"],
                r["raw_position"],
            )
            if upsert_source_map(conn, int(r["source_player_id"]), pid):
                new_maps += 1

        conn.commit()

        prospects_after = conn.execute(
            "SELECT COUNT(*) AS n FROM prospects WHERE season_id = ?",
            (season_id,),
        ).fetchone()["n"]

        if sources_has_is_active(conn):
            mapped_after = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM source_player_map m
                JOIN source_players sp ON sp.source_player_id = m.source_player_id
                JOIN sources s ON s.source_id = sp.source_id
                WHERE sp.season_id = ?
                  AND s.is_active = 1
                """,
                (season_id,),
            ).fetchone()["n"]
        else:
            mapped_after = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM source_player_map m
                JOIN source_players sp ON sp.source_player_id = m.source_player_id
                WHERE sp.season_id = ?
                """,
                (season_id,),
            ).fetchone()["n"]

    print(
        f"OK: prospects(season={draft_year}) before: {prospects_before}, after: {prospects_after}, "
        f"delta: {prospects_after - prospects_before}"
    )
    print(
        f"OK: active source_player_map before: {mapped_before}, after: {mapped_after}, "
        f"delta: {mapped_after - mapped_before}"
    )
    print(f"OK: new maps inserted this run: {new_maps}")


if __name__ == "__main__":
    main()