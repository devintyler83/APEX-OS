from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?;",
        (name,),
    ).fetchone()
    return row is not None


def colnames(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()]


def pick_first(cols: set[str], *cands: str) -> Optional[str]:
    for c in cands:
        if c in cols:
            return c
    return None


def resolve_season_id(conn, draft_year: int) -> int:
    if not table_exists(conn, "seasons"):
        raise SystemExit("FAIL: seasons table not found")

    cols = set(colnames(conn, "seasons"))
    id_col = pick_first(cols, "season_id", "id")
    year_col = pick_first(cols, "draft_year", "year")
    if not id_col or not year_col:
        raise SystemExit(f"FAIL: seasons missing expected cols. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col} = ?;",
        (draft_year,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found for draft_year={draft_year}")
    return int(row["season_id"])


def resolve_model_id(conn, season_id: int, model_key_or_name: str) -> int:
    if not table_exists(conn, "models"):
        raise SystemExit("FAIL: models table not found")

    cols = set(colnames(conn, "models"))
    id_col = pick_first(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models missing id column. found={sorted(cols)}")

    # season-scoped models if season_id exists
    if "season_id" in cols:
        key_col = pick_first(cols, "model_key", "model_name", "name")
        if not key_col:
            raise SystemExit(f"FAIL: models missing model key/name column. found={sorted(cols)}")

        row = conn.execute(
            f"SELECT {id_col} AS model_id FROM models WHERE season_id = ? AND {key_col} = ?;",
            (season_id, model_key_or_name),
        ).fetchone()
        if row:
            return int(row["model_id"])

        # fallback try alternates
        for alt in ("model_key", "model_name", "name"):
            if alt in cols and alt != key_col:
                row2 = conn.execute(
                    f"SELECT {id_col} AS model_id FROM models WHERE season_id = ? AND {alt} = ?;",
                    (season_id, model_key_or_name),
                ).fetchone()
                if row2:
                    return int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season_id={season_id} model='{model_key_or_name}'")

    # non-season-scoped models table
    name_col = pick_first(cols, "name", "model_key", "model_name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name/key column. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS model_id FROM models WHERE {name_col} = ?;",
        (model_key_or_name,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")
    return int(row["model_id"])


def get_latest_snapshot(conn, season_id: int, model_id: int) -> Tuple[int, str]:
    row = conn.execute(
        """
        SELECT id, snapshot_date_utc
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
        ORDER BY snapshot_date_utc DESC, id DESC
        LIMIT 1;
        """,
        (season_id, model_id),
    ).fetchone()
    if not row:
        raise SystemExit("FAIL: no snapshots found for this season/model")
    return int(row["id"]), str(row["snapshot_date_utc"])


def yyyymmdd_from_iso(dt: str) -> str:
    d = (dt or "")[:10].replace("-", "")
    return d if len(d) == 8 else datetime.now(timezone.utc).strftime("%Y%m%d")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build an immutable snapshot packet from current exports + reports.")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--model", type=str, required=True)
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    exports_dir = PATHS.root / "exports"
    reports_dir = exports_dir / "reports"
    packets_root = exports_dir / "packets"
    packets_root.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)
        snapshot_id, snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)

    stamp = yyyymmdd_from_iso(snapshot_date_utc)
    packet_dir = packets_root / f"packet_{stamp}_{args.season}_{args.model}_snap{snapshot_id}"
    packet_dir.mkdir(parents=True, exist_ok=True)

    # Copy all CSV exports for this season/model (including date-stamped ones)
    csvs: List[Path] = sorted([p for p in exports_dir.glob(f"*_{args.season}_{args.model}.csv") if p.is_file()])
    if not csvs:
        raise SystemExit(f"FAIL: no CSV exports found matching '*_{args.season}_{args.model}.csv' in {exports_dir}")

    for p in csvs:
        shutil.copy2(p, packet_dir / p.name)

    # Copy reports pack if present
    if reports_dir.exists() and reports_dir.is_dir():
        shutil.copytree(reports_dir, packet_dir / "reports", dirs_exist_ok=True)

    # Build manifest with hashes
    manifest = {
        "season": args.season,
        "model": args.model,
        "season_id": season_id,
        "model_id": model_id,
        "snapshot_id": snapshot_id,
        "snapshot_date_utc": snapshot_date_utc,
        "generated_at_utc": utc_now_iso(),
        "files": [],
    }

    for f in sorted(packet_dir.rglob("*")):
        if f.is_file():
            manifest["files"].append(
                {
                    "path": str(f.relative_to(packet_dir)).replace("\\", "/"),
                    "bytes": f.stat().st_size,
                    "sha256": sha256_file(f),
                }
            )

    (packet_dir / "packet_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"OK: snapshot packet created: {packet_dir}")


if __name__ == "__main__":
    main()
