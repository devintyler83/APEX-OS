# scripts/repair_snapshot_orphans.py
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from typing import Optional, Tuple

from draftos.db.connect import connect


def run_mod(module: str, *args: str) -> None:
    cmd = [sys.executable, "-m", module, *args]
    print("RUN:", " ".join(cmd))
    subprocess.check_call(cmd)


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def colnames(conn, table: str) -> list[str]:
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

    if "season_id" in cols:
        key_col = pick_first(cols, "model_key", "model_name", "name")
        if not key_col:
            raise SystemExit(f"FAIL: models missing model key/name column. found={sorted(cols)}")

        row = conn.execute(
            f"""
            SELECT {id_col} AS model_id
            FROM models
            WHERE season_id = ? AND {key_col} = ?
            ORDER BY {id_col} DESC
            LIMIT 1;
            """,
            (season_id, model_key_or_name),
        ).fetchone()
        if row:
            return int(row["model_id"])

        for alt in ("model_key", "model_name", "name"):
            if alt in cols and alt != key_col:
                row2 = conn.execute(
                    f"""
                    SELECT {id_col} AS model_id
                    FROM models
                    WHERE season_id = ? AND {alt} = ?
                    ORDER BY {id_col} DESC
                    LIMIT 1;
                    """,
                    (season_id, model_key_or_name),
                ).fetchone()
                if row2:
                    return int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season_id={season_id} model='{model_key_or_name}'")

    name_col = pick_first(cols, "name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name column. found={sorted(cols)}")

    row = conn.execute(
        f"""
        SELECT {id_col} AS model_id
        FROM models
        WHERE {name_col} = ?
        ORDER BY {id_col} DESC
        LIMIT 1;
        """,
        (model_key_or_name,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")
    return int(row["model_id"])


def latest_snapshot_id_and_date(conn, season_id: int, model_id: int) -> Tuple[int, str]:
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


def count_for_snapshot(conn, table: str, snapshot_id: int) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE snapshot_id = ?;", (snapshot_id,)).fetchone()
    return int(row["n"])


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Attempt deterministic repair of snapshot orphans (coverage/confidence) for a snapshot_id, then re-verify."
    )
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--snapshot-id", type=int, default=None)
    ap.add_argument("--apply", type=int, default=1, choices=[0, 1], help="--apply 1 performs repair writes. --apply 0 is verify-only.")
    args = ap.parse_args()

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        required = [
            "seasons",
            "models",
            "prospect_board_snapshots",
            "prospect_board_snapshot_rows",
            "prospect_board_snapshot_coverage",
            "prospect_board_snapshot_confidence",
        ]
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, snapshot_date = latest_snapshot_id_and_date(conn, season_id, model_id)
        else:
            snapshot_id = int(args.snapshot_id)
            row = conn.execute(
                """
                SELECT snapshot_date_utc
                FROM prospect_board_snapshots
                WHERE id = ? AND season_id = ? AND model_id = ?;
                """,
                (snapshot_id, season_id, model_id),
            ).fetchone()
            if not row:
                raise SystemExit("FAIL: snapshot_id not found for this season/model")
            snapshot_date = str(row["snapshot_date_utc"])

        n_rows = count_for_snapshot(conn, "prospect_board_snapshot_rows", snapshot_id)
        n_cov = count_for_snapshot(conn, "prospect_board_snapshot_coverage", snapshot_id)
        n_conf = count_for_snapshot(conn, "prospect_board_snapshot_confidence", snapshot_id)

        print(f"SNAPSHOT_REPAIR: snapshot_id={snapshot_id} snapshot_date_utc={snapshot_date}")
        print(f"COUNTS_BEFORE: rows={n_rows} coverage={n_cov} confidence={n_conf}")

        if n_rows == n_cov == n_conf:
            print("OK: nothing to repair (already consistent)")
            return

    if args.apply == 0:
        raise SystemExit("FAIL: snapshot integrity mismatch (apply=0; not repairing)")

    # Repair strategy (deterministic, SNAPSHOTS-only):
    # - Recompute coverage for this snapshot_id
    # - Recompute confidence for this snapshot_id
    # - Verify again; fail hard if still mismatched
    run_mod("scripts.compute_snapshot_coverage", "--season", str(args.season), "--model", args.model, "--snapshot-id", str(snapshot_id), "--apply", "1")
    run_mod("scripts.compute_snapshot_confidence", "--season", str(args.season), "--model", args.model, "--apply", "1")

    # Re-check counts
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF;")

        n_rows = count_for_snapshot(conn, "prospect_board_snapshot_rows", snapshot_id)
        n_cov = count_for_snapshot(conn, "prospect_board_snapshot_coverage", snapshot_id)
        n_conf = count_for_snapshot(conn, "prospect_board_snapshot_confidence", snapshot_id)

        print(f"COUNTS_AFTER: rows={n_rows} coverage={n_cov} confidence={n_conf}")

        if not (n_rows == n_cov == n_conf):
            raise SystemExit("FAIL: snapshot repair attempted but integrity mismatch remains")

    print("OK: snapshot repair successful and integrity restored")


if __name__ == "__main__":
    main()