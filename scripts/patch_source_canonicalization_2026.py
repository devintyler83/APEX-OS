from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


PREFERRED_CANONICAL_NAME: Dict[str, str] = {
    # normalized -> preferred display name
    "pff": "PFF",
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


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def norm(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def choose_canonical(rows: List[sqlite3.Row]) -> sqlite3.Row:
    """
    Deterministic canonical selection:
    1) If a preferred name exists for normalized key, pick exact name match.
    2) Else prefer is_active=1
    3) Else lowest source_id
    """
    k = norm(rows[0]["source_name"])
    preferred = PREFERRED_CANONICAL_NAME.get(k)

    if preferred:
        for r in rows:
            if (r["source_name"] or "").strip() == preferred:
                return r

    active = [r for r in rows if int(r["is_active"]) == 1]
    if active:
        return sorted(active, key=lambda r: int(r["source_id"]))[0]

    return sorted(rows, key=lambda r: int(r["source_id"]))[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Populate source_canonical_map for duplicate sources (non-destructive).")
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

        sources = conn.execute(
            """
            SELECT source_id, source_name, is_active
            FROM sources
            ORDER BY source_id;
            """
        ).fetchall()

        buckets: Dict[str, List[sqlite3.Row]] = {}
        for r in sources:
            k = norm(r["source_name"])
            if not k:
                continue
            buckets.setdefault(k, []).append(r)

        dups = {k: v for k, v in buckets.items() if len(v) > 1}

        plan: List[Dict[str, object]] = []
        for k in sorted(dups.keys()):
            rows = dups[k]
            canonical = choose_canonical(rows)
            for r in rows:
                if int(r["source_id"]) == int(canonical["source_id"]):
                    continue
                plan.append(
                    {
                        "source_id": int(r["source_id"]),
                        "canonical_source_id": int(canonical["source_id"]),
                        "normalized": k,
                        "source_name": r["source_name"],
                        "canonical_name": canonical["source_name"],
                    }
                )

        print(f"FOUND_DUP_GROUPS: {len(dups)}")
        print(f"ALIASES_TO_MAP: {len(plan)}")
        if plan:
            print(json.dumps(plan, indent=2, ensure_ascii=False))

        if args.apply != 1:
            print("DRY_RUN: no changes applied")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        ts = utc_now_iso()

        conn.execute("BEGIN;")
        try:
            # recompute plan inside write connection for determinism
            sources = conn.execute(
                """
                SELECT source_id, source_name, is_active
                FROM sources
                ORDER BY source_id;
                """
            ).fetchall()

            buckets = {}
            for r in sources:
                k = norm(r["source_name"])
                if not k:
                    continue
                buckets.setdefault(k, []).append(r)

            dups = {k: v for k, v in buckets.items() if len(v) > 1}

            plan = []
            for k in sorted(dups.keys()):
                rows = dups[k]
                canonical = choose_canonical(rows)
                for r in rows:
                    if int(r["source_id"]) == int(canonical["source_id"]):
                        continue
                    plan.append((int(r["source_id"]), int(canonical["source_id"]), f"auto-canonicalized normalized='{k}'"))

            for source_id, canonical_source_id, notes in plan:
                conn.execute(
                    """
                    INSERT INTO source_canonical_map(source_id, canonical_source_id, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                      canonical_source_id = excluded.canonical_source_id,
                      notes = excluded.notes,
                      updated_at = excluded.updated_at;
                    """,
                    (source_id, canonical_source_id, notes, ts, ts),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    print("OK: source canonicalization applied")


if __name__ == "__main__":
    main()