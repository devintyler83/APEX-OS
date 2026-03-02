# scripts/build_snapshot_packet.py
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
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
    cols = set(colnames(conn, "models"))
    id_col = pick_first(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models missing id column. found={sorted(cols)}")

    # season-scoped models
    if "season_id" in cols:
        key_col = pick_first(cols, "model_key", "model_name", "name")
        if not key_col:
            raise SystemExit(f"FAIL: models missing model key/name column. found={sorted(cols)}")

        row = conn.execute(
            f"""
            SELECT {id_col} AS model_id
            FROM models
            WHERE season_id = ? AND {key_col} = ?;
            """,
            (season_id, model_key_or_name),
        ).fetchone()
        if row:
            return int(row["model_id"])

        for alt in ("model_key", "model_name", "name"):
            if alt in cols and alt != key_col:
                row2 = conn.execute(
                    f"SELECT {id_col} AS model_id FROM models WHERE season_id = ? AND {alt} = ?;",
                    (season_id, model_key_or_name),
                ).fetchone()
                if row2:
                    return int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season_id={season_id} model='{model_key_or_name}'")

    # non-season-scoped models
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


def get_latest_snapshot_meta(conn, season_id: int, model_id: int) -> Tuple[int, str]:
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


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def pick_best(exports_dir: Path, patterns: List[str]) -> Optional[Path]:
    matches: List[Path] = []
    for pat in patterns:
        matches.extend(sorted(exports_dir.glob(pat)))
    matches = [p for p in matches if p.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def build_manifest(packet_dir: Path) -> Dict:
    files: List[Dict] = []

    for p in sorted(packet_dir.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(packet_dir).as_posix()
        if rel in ("packet_manifest.json",):
            # exclude; we write it last
            continue
        files.append(
            {
                "path": rel,
                "size": int(p.stat().st_size),
                "sha256": sha256_file(p),
            }
        )

    return {
        "schema": "draftos.packet_manifest.v1",
        "created_at_utc": utc_now_iso(),
        "files": files,
    }


def write_json(path: Path, obj: Dict) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build immutable snapshot packet (exports + reports + meta + manifest).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        for t in ("seasons", "models", "prospect_board_snapshots"):
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)
        snapshot_id, snapshot_date_utc = get_latest_snapshot_meta(conn, season_id, model_id)

    exports_dir = PATHS.root / "exports"
    packets_dir = exports_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)

    stamp = utc_stamp()
    packet_name = f"packet_{stamp}_{args.season}_{args.model}_snap{snapshot_id}"
    packet_dir = packets_dir / packet_name

    if packet_dir.exists():
        shutil.rmtree(packet_dir)
    packet_dir.mkdir(parents=True, exist_ok=True)

    # Required exports
    required_files: List[Tuple[str, Optional[Path]]] = []

    board = exports_dir / f"board_{args.season}_{args.model}.csv"
    movers_daily = exports_dir / f"movers_daily_{args.season}_{args.model}.csv"
    movers_window = exports_dir / f"movers_window3_{args.season}_{args.model}.csv"
    volatility = exports_dir / f"volatility_window3_{args.season}_{args.model}.csv"

    required_files.extend(
        [
            ("board.csv", board if board.exists() else None),
            ("movers_daily.csv", movers_daily if movers_daily.exists() else None),
            ("movers_window3.csv", movers_window if movers_window.exists() else None),
            ("volatility_window3.csv", volatility if volatility.exists() else None),
        ]
    )

    missing_required = [name for name, p in required_files if p is None]
    if missing_required:
        raise SystemExit(f"FAIL: missing required exports: {missing_required}")

    for name, src in required_files:
        copy_file(src, packet_dir / "exports" / name)

    # Optional best-available exports (date-stamped ones)
    source_health = pick_best(exports_dir, [f"source_health_*_{args.season}_{args.model}.csv"])
    conf_summary = pick_best(exports_dir, [f"confidence_summary_*_{args.season}_{args.model}.csv"])
    mapping_queue = exports_dir / "mapping_review_queue_2026.csv"

    if source_health:
        copy_file(source_health, packet_dir / "exports" / "source_health.csv")
    if conf_summary:
        copy_file(conf_summary, packet_dir / "exports" / "confidence_summary.csv")
    if mapping_queue.exists():
        copy_file(mapping_queue, packet_dir / "exports" / "mapping_review_queue.csv")

    # Reports dir (optional but expected)
    reports_src = exports_dir / "reports"
    if reports_src.exists() and reports_src.is_dir():
        copy_dir(reports_src, packet_dir / "reports")

    # Meta
    meta = {
        "schema": "draftos.snapshot_packet.v1",
        "created_at_utc": utc_now_iso(),
        "season": int(args.season),
        "model": str(args.model),
        "season_id": int(season_id),
        "model_id": int(model_id),
        "snapshot_id": int(snapshot_id),
        "snapshot_date_utc": str(snapshot_date_utc),
    }
    write_json(packet_dir / "packet_meta.json", meta)

    # Manifest (write last)
    manifest = build_manifest(packet_dir)
    write_json(packet_dir / "packet_manifest.json", manifest)

    print(f"OK: snapshot packet created: {packet_dir}")
    print(f"OK: manifest files={len(manifest.get('files', []))}")


if __name__ == "__main__":
    main()
