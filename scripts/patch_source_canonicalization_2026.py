"""
patch_source_canonicalization_2026.py

Explicit manual canonicalization of duplicate sources for the 2026 draft season.

Replaces the old auto-normalization approach (which missed _2026, _v2, and (1) variants)
with hardcoded mappings derived from confirmed DB inventory.

Dry run (default):
    python -m scripts.patch_source_canonicalization_2026 --apply 0

Apply:
    python -m scripts.patch_source_canonicalization_2026 --apply 1

Idempotent: safe to re-run. Uses INSERT OR REPLACE on source_canonical_map.

NOTE: IDs updated 2026-03-10 after Session 12 DB rebuild. New DB has different
source_id assignments than original DB.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect


# ---------------------------------------------------------------------------
# 11 canonical source IDs (these are authoritative — never map or deactivate)
# IDs as of 2026-03-10 rebuilt DB.
# ---------------------------------------------------------------------------
CANONICAL_SOURCE_IDS = {
    1,   # jfosterfilm_2026
    2,   # bnbfootball_2026
    3,   # cbssports_2026
    6,   # espn_2026
    9,   # nfldraftbuzz_2026_v2
    10,  # nytimes_2026
    13,  # pff_2026
    15,  # pfsn_2026
    23,  # tankathon_2026
    24,  # thedraftnetwork_2026
    25,  # theringer_2026
}

# ---------------------------------------------------------------------------
# Alias map: source_id -> canonical_source_id
# Every alias will be added to source_canonical_map AND set is_active=0.
# ---------------------------------------------------------------------------
ALIAS_MAP: dict[int, tuple[int, str, str]] = {
    # source_id: (canonical_source_id, source_name, canonical_name)

    # espn group -> espn_2026 (6)
    5:  (6,  "espn (1)",                   "espn_2026"),

    # pff group -> pff_2026 (13)
    12: (13, "pff (1)",                    "pff_2026"),

    # pfsn group -> pfsn_2026 (15)
    14: (15, "pfsn-consensus-2026-02-27",  "pfsn_2026"),

    # theringer group -> theringer_2026 (25)
    26: (25, "theringer",                  "theringer_2026"),
}

# ---------------------------------------------------------------------------
# Junk / artifact sources: deactivate only, no canonical map entry
# ---------------------------------------------------------------------------
JUNK_SOURCE_IDS: dict[int, str] = {
    4:  "deep_cleaned_player_list",
    7:  "fully_cleaned_player_list",
    8:  "harryknowsball_league_available",
    11: "overall (2026-shane)",
    16: "players (1)",
    17: "players",
    18: "profootballnetwork (1)",
    19: "repaired_player_list",
    20: "spamml - 6-16-25 football fantasy draft cheat sheet",
    21: "spamml 8-11-25 football fantasy draft cheat sheet",
    22: "spamml 8-4-25 football fantasy draft cheat sheet",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_source_canonicalization.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def validate_against_db(conn: sqlite3.Connection) -> None:
    """Sanity check: confirm canonical IDs exist and are not in alias/junk lists."""
    rows = {r[0]: r[1] for r in conn.execute("SELECT source_id, source_name FROM sources").fetchall()}

    for sid in CANONICAL_SOURCE_IDS:
        if sid not in rows:
            raise SystemExit(f"FAIL: canonical source_id={sid} not found in sources table")

    for sid in ALIAS_MAP:
        if sid not in rows:
            raise SystemExit(f"FAIL: alias source_id={sid} not found in sources table")
        if sid in CANONICAL_SOURCE_IDS:
            raise SystemExit(f"FAIL: source_id={sid} is in both CANONICAL_SOURCE_IDS and ALIAS_MAP")

    for sid in JUNK_SOURCE_IDS:
        if sid not in rows:
            raise SystemExit(f"FAIL: junk source_id={sid} not found in sources table")
        if sid in CANONICAL_SOURCE_IDS:
            raise SystemExit(f"FAIL: source_id={sid} is in both CANONICAL_SOURCE_IDS and JUNK_SOURCE_IDS")
        if sid in ALIAS_MAP:
            raise SystemExit(f"FAIL: source_id={sid} is in both ALIAS_MAP and JUNK_SOURCE_IDS")

    canonical_ids_in_alias = set(v[0] for v in ALIAS_MAP.values()) - CANONICAL_SOURCE_IDS
    if canonical_ids_in_alias:
        raise SystemExit(f"FAIL: alias map references non-canonical target IDs: {canonical_ids_in_alias}")


def print_plan(conn: sqlite3.Connection) -> None:
    rows = {r[0]: r[1] for r in conn.execute("SELECT source_id, source_name FROM sources").fetchall()}
    active = {r[0]: r[1] for r in conn.execute("SELECT source_id, is_active FROM sources").fetchall()}

    print()
    print("=== CANONICAL SOURCES (11 — will remain is_active=1) ===")
    for sid in sorted(CANONICAL_SOURCE_IDS):
        print(f"  id={sid:>3}  {rows.get(sid, '?')}")

    print()
    print(f"=== ALIAS MAPPINGS ({len(ALIAS_MAP)} entries -> source_canonical_map, set is_active=0) ===")
    for sid in sorted(ALIAS_MAP.keys()):
        canonical_id, source_name, canonical_name = ALIAS_MAP[sid]
        cur_active = active.get(sid, "?")
        print(f"  id={sid:>3}  {source_name:<42} -> id={canonical_id}  {canonical_name}  [is_active={cur_active}]")

    print()
    print(f"=== JUNK DEACTIVATIONS ({len(JUNK_SOURCE_IDS)} sources — set is_active=0, no map entry) ===")
    for sid in sorted(JUNK_SOURCE_IDS.keys()):
        cur_active = active.get(sid, "?")
        print(f"  id={sid:>3}  {JUNK_SOURCE_IDS[sid]:<42}  [is_active={cur_active}]")

    all_deactivated = set(ALIAS_MAP.keys()) | set(JUNK_SOURCE_IDS.keys())
    all_active_after = CANONICAL_SOURCE_IDS - all_deactivated
    print()
    print(f"EXPECTED sources.is_active=1 after apply: {len(CANONICAL_SOURCE_IDS)}")
    print(f"EXPECTED source_canonical_map entries: {len(ALIAS_MAP)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Explicit source canonicalization for 2026 season (non-destructive, idempotent)."
    )
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        if not table_exists(conn, "sources"):
            raise SystemExit("FAIL: missing table sources")
        if not table_exists(conn, "source_canonical_map"):
            raise SystemExit("FAIL: missing table source_canonical_map (apply migration 0008 first)")

        validate_against_db(conn)
        print_plan(conn)

    if args.apply != 1:
        print()
        print("DRY_RUN: no changes applied. Pass --apply 1 to execute.")
        return

    # ------------------------------------------------------------------
    # APPLY
    # ------------------------------------------------------------------
    backup_path = ensure_backup(PATHS.db)
    print()
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")
        ts = utc_now_iso()

        conn.execute("BEGIN;")
        try:
            # 1. Upsert alias -> canonical mappings
            for source_id, (canonical_source_id, source_name, canonical_name) in ALIAS_MAP.items():
                notes = f"manual-canonicalized: {source_name!r} -> {canonical_name!r}"
                conn.execute(
                    """
                    INSERT INTO source_canonical_map(source_id, canonical_source_id, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                        canonical_source_id = excluded.canonical_source_id,
                        notes               = excluded.notes,
                        updated_at          = excluded.updated_at;
                    """,
                    (source_id, canonical_source_id, notes, ts, ts),
                )

            # 2. Deactivate all alias sources
            alias_ids = list(ALIAS_MAP.keys())
            conn.execute(
                f"UPDATE sources SET is_active = 0 WHERE source_id IN ({','.join('?' * len(alias_ids))});",
                alias_ids,
            )

            # 3. Deactivate junk sources
            junk_ids = list(JUNK_SOURCE_IDS.keys())
            conn.execute(
                f"UPDATE sources SET is_active = 0 WHERE source_id IN ({','.join('?' * len(junk_ids))});",
                junk_ids,
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # Verify
    with connect() as conn:
        n_active = conn.execute("SELECT COUNT(*) FROM sources WHERE is_active = 1").fetchone()[0]
        n_map = conn.execute("SELECT COUNT(*) FROM source_canonical_map").fetchone()[0]
        active_names = conn.execute(
            "SELECT source_name FROM sources WHERE is_active = 1 ORDER BY source_name"
        ).fetchall()

    print()
    print(f"OK: source_canonical_map entries: {n_map}")
    print(f"OK: sources.is_active=1 count:    {n_active}  (expected: {len(CANONICAL_SOURCE_IDS)})")
    print("OK: active canonical sources:")
    for row in active_names:
        print(f"      {row[0]}")

    if n_active != len(CANONICAL_SOURCE_IDS):
        raise SystemExit(
            f"FAIL: expected {len(CANONICAL_SOURCE_IDS)} active sources, got {n_active}. Investigate."
        )

    print()
    print("OK: source canonicalization applied successfully.")


if __name__ == "__main__":
    main()
