# scripts/bootstrap_prospects_from_sources_2026.py
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.positions import normalize_position
from draftos.normalize.schools import school_key


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_bootstrap_prospects.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone() is not None


def table_cols(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def resolve_season_id(conn, draft_year: int) -> int:
    cols = table_cols(conn, "seasons")
    id_col = "season_id" if "season_id" in cols else "id"
    year_col = "draft_year" if "draft_year" in cols else "year"
    row = conn.execute(f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col}=?;", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found: {draft_year}")
    return int(row["season_id"])


_POS_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{1,4}(?:/[A-Za-z]{1,4})?)\b[ .]+(.+?)\s*$")


def strip_pos_prefix(raw_full_name: str) -> str:
    s = (raw_full_name or "").strip()
    if not s:
        return ""
    m = _POS_PREFIX_RE.match(s)
    if not m:
        return s
    return (m.group(2) or "").strip() or s


def make_display_name(name_norm: str, fallback_raw: str) -> str:
    nn = (name_norm or "").strip()
    if nn:
        parts = [p for p in re.split(r"\s+", nn) if p]
        return " ".join(p[:1].upper() + p[1:] for p in parts)
    return strip_pos_prefix(fallback_raw)


def make_prospect_key(season_id: int, name_key: str, school_canon: str, pos_group: str) -> str:
    sk = school_key(school_canon) or "noschool"
    return f"s{season_id}:{pos_group.lower()}:{name_key}:{sk}"


@dataclass(frozen=True)
class CandidateGroup:
    name_key: str
    school_canonical: str
    pos_group: str


def main() -> None:
    ap = argparse.ArgumentParser(description="Bootstrap new prospects from unmapped source_players groups.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--min-source-count", type=int, default=2)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        for t in ("prospects", "source_players", "sources", "source_player_map", "seasons"):
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)

        pcols = table_cols(conn, "prospects")
        required_pcols = {
            "season_id",
            "prospect_key",
            "full_name",
            "display_name",
            "position_group",
            "school_canonical",
            "created_at",
            "updated_at",
        }
        missing = sorted(list(required_pcols - pcols))
        if missing:
            raise SystemExit(f"FAIL: prospects missing required columns: {missing}")

        spcols = table_cols(conn, "source_players")
        required_spcols = {
            "season_id",
            "source_id",
            "source_player_id",
            "raw_full_name",
            "raw_school",
            "raw_position",
            "raw_json",
            "name_key",
            "name_norm",
            "school_canonical",
        }
        missing2 = sorted(list(required_spcols - spcols))
        if missing2:
            raise SystemExit(f"FAIL: source_players missing required columns: {missing2}")

        sp_rows = conn.execute(
            """
            SELECT
              sp.source_player_id,
              sp.source_id,
              sp.raw_full_name,
              sp.raw_school,
              sp.raw_position,
              sp.raw_json,
              sp.name_key,
              sp.name_norm,
              sp.school_canonical,
              sp.pos_hint
            FROM source_players sp
            LEFT JOIN source_player_map m ON m.source_player_id = sp.source_player_id
            WHERE sp.season_id = ?
              AND m.source_player_id IS NULL
              AND sp.name_key IS NOT NULL
              AND TRIM(sp.name_key) <> '';
            """,
            (season_id,),
        ).fetchall()

        group_sources: Dict[CandidateGroup, set[int]] = defaultdict(set)
        grouped_meta: Dict[CandidateGroup, Dict[str, List[str]]] = {}

        for r in sp_rows:
            name_key = (r["name_key"] or "").strip()
            if not name_key:
                continue

            school_canon = (r["school_canonical"] or "").strip()
            pos_input = (r["pos_hint"] or "").strip() or (r["raw_position"] or "").strip()
            pos_group = normalize_position(pos_input).group

            g = CandidateGroup(name_key=name_key, school_canonical=school_canon, pos_group=pos_group)
            group_sources[g].add(int(r["source_id"]))

            if g not in grouped_meta:
                grouped_meta[g] = {"name_norms": [], "raw_names": []}
            grouped_meta[g]["name_norms"].append((r["name_norm"] or "").strip())
            grouped_meta[g]["raw_names"].append((r["raw_full_name"] or "").strip())

        candidate_groups: List[Tuple[CandidateGroup, int]] = []
        for g, srcs in group_sources.items():
            if len(srcs) >= int(args.min_source_count):
                candidate_groups.append((g, len(srcs)))

        candidate_groups.sort(key=lambda x: (-x[1], x[0].pos_group, x[0].school_canonical, x[0].name_key))

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"CANDIDATE_GROUPS: {len(candidate_groups)}")
        print(f"MIN_SOURCE_COUNT: {args.min_source_count}")

        if args.apply == 0:
            if candidate_groups:
                g, nsrc = candidate_groups[0]
                print(
                    "EXAMPLE_GROUP:",
                    json.dumps(
                        {
                            "name_key": g.name_key,
                            "school_canonical": g.school_canonical,
                            "position_group": g.pos_group,
                            "distinct_sources": nsrc,
                        },
                        indent=2,
                    ),
                )
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    inserted = 0
    skipped_existing_key = 0
    skipped_existing_unique = 0
    now = utc_now_iso()

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)

        # Existing prospect_key set
        existing_keys = {
            (r["prospect_key"] or "").strip()
            for r in conn.execute("SELECT prospect_key FROM prospects WHERE season_id=?;", (season_id,)).fetchall()
        }

        # Existing UNIQUE tuple set (season_id, full_name, school_canonical, position_group)
        existing_unique = {
            (
                int(r["season_id"]),
                (r["full_name"] or "").strip(),
                (r["school_canonical"] or "").strip(),
                (r["position_group"] or "").strip().upper(),
            )
            for r in conn.execute(
                """
                SELECT season_id, full_name, school_canonical, position_group
                FROM prospects
                WHERE season_id=?;
                """,
                (season_id,),
            ).fetchall()
        }

        # Re-pull unmapped for write-pass (deterministic)
        sp_rows = conn.execute(
            """
            SELECT
              sp.source_player_id,
              sp.source_id,
              sp.raw_full_name,
              sp.raw_position,
              sp.name_key,
              sp.name_norm,
              sp.school_canonical,
              sp.pos_hint
            FROM source_players sp
            LEFT JOIN source_player_map m ON m.source_player_id = sp.source_player_id
            WHERE sp.season_id = ?
              AND m.source_player_id IS NULL
              AND sp.name_key IS NOT NULL
              AND TRIM(sp.name_key) <> '';
            """,
            (season_id,),
        ).fetchall()

        group_sources: Dict[CandidateGroup, set[int]] = defaultdict(set)
        grouped_meta: Dict[CandidateGroup, Dict[str, List[str]]] = {}

        for r in sp_rows:
            name_key = (r["name_key"] or "").strip()
            if not name_key:
                continue

            school_canon = (r["school_canonical"] or "").strip()
            pos_input = (r["pos_hint"] or "").strip() or (r["raw_position"] or "").strip()
            pos_group = normalize_position(pos_input).group

            g = CandidateGroup(name_key=name_key, school_canonical=school_canon, pos_group=pos_group)
            group_sources[g].add(int(r["source_id"]))

            if g not in grouped_meta:
                grouped_meta[g] = {"name_norms": [], "raw_names": []}
            grouped_meta[g]["name_norms"].append((r["name_norm"] or "").strip())
            grouped_meta[g]["raw_names"].append((r["raw_full_name"] or "").strip())

        candidate_groups: List[Tuple[CandidateGroup, int]] = []
        for g, srcs in group_sources.items():
            if len(srcs) >= int(args.min_source_count):
                candidate_groups.append((g, len(srcs)))

        candidate_groups.sort(key=lambda x: (-x[1], x[0].pos_group, x[0].school_canonical, x[0].name_key))

        for g, _nsrc in candidate_groups:
            name_norms = [x for x in grouped_meta[g]["name_norms"] if x]
            raw_names = [x for x in grouped_meta[g]["raw_names"] if x]

            rep_norm = ""
            if name_norms:
                c = Counter(name_norms)
                rep_norm = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

            rep_raw = ""
            if raw_names:
                stripped = [strip_pos_prefix(x) for x in raw_names if x]
                c2 = Counter(stripped)
                rep_raw = sorted(c2.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

            display = make_display_name(rep_norm, rep_raw)
            full_name = display

            school_canon = g.school_canonical if g.school_canonical else "Unknown"
            pos_group = (g.pos_group or "").strip().upper()

            prospect_key = make_prospect_key(season_id, g.name_key, school_canon, pos_group)

            # Skip if prospect_key already exists
            if prospect_key in existing_keys:
                skipped_existing_key += 1
                continue

            # Skip if UNIQUE tuple already exists
            uniq = (season_id, full_name.strip(), school_canon.strip(), pos_group)
            if uniq in existing_unique:
                skipped_existing_unique += 1
                continue

            conn.execute(
                """
                INSERT INTO prospects(
                  season_id, prospect_key,
                  first_name, last_name,
                  full_name, display_name, suffix,
                  position_group, position_raw,
                  school_canonical,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    season_id,
                    prospect_key,
                    None,
                    None,
                    full_name,
                    display,
                    None,
                    pos_group,
                    None,
                    school_canon,
                    now,
                    now,
                ),
            )

            existing_keys.add(prospect_key)
            existing_unique.add(uniq)
            inserted += 1

        conn.commit()

    print(f"OK: bootstrap prospects inserted={inserted}")
    print(f"OK: skipped existing prospect_key={skipped_existing_key}")
    print(f"OK: skipped existing unique tuple={skipped_existing_unique}")


if __name__ == "__main__":
    main()