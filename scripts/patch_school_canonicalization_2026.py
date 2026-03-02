# scripts/patch_school_canonicalization_2026.py
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Set, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.schools import school_key


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_school_canonicalization.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (name,),
    ).fetchone() is not None


def resolve_season_id(conn, draft_year: int) -> int:
    row = conn.execute("SELECT season_id FROM seasons WHERE draft_year=?;", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found for draft_year={draft_year}")
    return int(row["season_id"])


def build_canon_by_key(conn, season_id: int) -> Dict[str, str]:
    # map: school_key(canonical) -> canonical string, but only where key maps uniquely
    rows = conn.execute(
        "SELECT DISTINCT school_canonical FROM prospects WHERE season_id=? AND TRIM(school_canonical)<>'';",
        (season_id,),
    ).fetchall()

    tmp: Dict[str, Set[str]] = {}
    for r in rows:
        canon = (r["school_canonical"] or "").strip()
        k = school_key(canon)
        if canon and k:
            tmp.setdefault(k, set()).add(canon)

    out: Dict[str, str] = {}
    for k, vals in tmp.items():
        if len(vals) == 1:
            out[k] = next(iter(vals))
    return out


def upsert_school_alias(conn, alias: str, canonical: str) -> None:
    # school_aliases is not season-scoped in your schema
    row = conn.execute(
        "SELECT 1 FROM school_aliases WHERE LOWER(TRIM(school_alias)) = LOWER(TRIM(?));",
        (alias,),
    ).fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO school_aliases(school_alias, school_canonical) VALUES(?, ?);",
        (alias, canonical),
    )


def build_alias_map(conn) -> Dict[str, str]:
    rows = conn.execute("SELECT school_alias, school_canonical FROM school_aliases;").fetchall()
    out: Dict[str, str] = {}
    for r in rows:
        a = (r["school_alias"] or "").strip()
        c = (r["school_canonical"] or "").strip()
        k = school_key(a)
        if k and c:
            out[k] = c
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministically backfill source_players.school_canonical (season-scoped), and grow school_aliases.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        for t in ("prospects", "source_players", "school_aliases", "seasons"):
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing table: {t}")

        season_id = resolve_season_id(conn, args.season)

        canon_by_key = build_canon_by_key(conn, season_id)
        alias_by_key = build_alias_map(conn)

        # Candidate rows: have raw_school, missing school_canonical
        rows = conn.execute(
            """
            SELECT source_player_id, raw_school
            FROM source_players
            WHERE season_id=?
              AND raw_school IS NOT NULL
              AND TRIM(raw_school) <> ''
              AND (school_canonical IS NULL OR TRIM(school_canonical)='');
            """,
            (season_id,),
        ).fetchall()

        # Plan updates using canonical keys first, then alias table
        plan_updates: Dict[int, str] = {}
        plan_alias_inserts: Set[Tuple[str, str]] = set()

        for r in rows:
            spid = int(r["source_player_id"])
            raw_school = (r["raw_school"] or "").strip()
            k = school_key(raw_school)
            if not k:
                continue

            # 1) direct key match to known canon (best)
            canon = canon_by_key.get(k, "")
            if canon:
                plan_updates[spid] = canon
                plan_alias_inserts.add((raw_school, canon))
                continue

            # 2) fallback: alias table by key
            canon2 = alias_by_key.get(k, "")
            if canon2:
                plan_updates[spid] = canon2

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"ROWS_NEEDING_CANON: {len(rows)}")
        print(f"PLAN_UPDATES: {len(plan_updates)}")
        print(f"PLAN_NEW_ALIASES: {len(plan_alias_inserts)}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)

        canon_by_key = build_canon_by_key(conn, season_id)
        alias_by_key = build_alias_map(conn)

        rows = conn.execute(
            """
            SELECT source_player_id, raw_school
            FROM source_players
            WHERE season_id=?
              AND raw_school IS NOT NULL
              AND TRIM(raw_school) <> ''
              AND (school_canonical IS NULL OR TRIM(school_canonical)='');
            """,
            (season_id,),
        ).fetchall()

        n_updates = 0
        n_alias = 0
        now = utc_now_iso()

        for r in rows:
            spid = int(r["source_player_id"])
            raw_school = (r["raw_school"] or "").strip()
            k = school_key(raw_school)
            if not k:
                continue

            canon = canon_by_key.get(k, "") or alias_by_key.get(k, "")
            if not canon:
                continue

            conn.execute(
                "UPDATE source_players SET school_canonical=? WHERE source_player_id=?;",
                (canon, spid),
            )
            n_updates += 1

            # grow alias table ONLY when we matched against known canon key (not alias-derived)
            if canon_by_key.get(k, ""):
                before = conn.execute(
                    "SELECT 1 FROM school_aliases WHERE LOWER(TRIM(school_alias))=LOWER(TRIM(?));",
                    (raw_school,),
                ).fetchone()
                if not before:
                    conn.execute(
                        "INSERT INTO school_aliases(school_alias, school_canonical) VALUES(?, ?);",
                        (raw_school, canon),
                    )
                    n_alias += 1

        conn.commit()

    print(f"OK: school canonicalization applied updates={n_updates} new_aliases={n_alias}")


if __name__ == "__main__":
    main()