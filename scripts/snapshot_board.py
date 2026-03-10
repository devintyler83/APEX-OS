# scripts/snapshot_board.py
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_today_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()  # YYYY-MM-DD


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_snapshot.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def column_names(conn, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return [r["name"] for r in rows]


def pick_first_existing(cols: set[str], *cands: str) -> Optional[str]:
    for c in cands:
        if c in cols:
            return c
    return None


def prospects_has_is_active(conn) -> bool:
    if not table_exists(conn, "prospects"):
        return False
    cols = set(column_names(conn, "prospects"))
    return "is_active" in cols


def resolve_season_id(conn, draft_year: int) -> int:
    if not table_exists(conn, "seasons"):
        raise SystemExit("FAIL: seasons table not found")

    cols = set(column_names(conn, "seasons"))
    id_col = pick_first_existing(cols, "season_id", "id")
    year_col = pick_first_existing(cols, "draft_year", "year")

    if not id_col or not year_col:
        raise SystemExit(f"FAIL: seasons table missing expected columns. found={sorted(cols)}")

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

    cols = set(column_names(conn, "models"))
    id_col = pick_first_existing(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models table missing id column. found={sorted(cols)}")

    if "season_id" in cols:
        key_col = pick_first_existing(cols, "model_key", "model_name", "name")
        if not key_col:
            raise SystemExit(f"FAIL: models table missing model key/name column. found={sorted(cols)}")

        row = conn.execute(
            f"""
            SELECT {id_col} AS model_id
            FROM models
            WHERE season_id = ?
              AND {key_col} = ?;
            """,
            (season_id, model_key_or_name),
        ).fetchone()
        if row:
            return int(row["model_id"])

        alt_cols = [c for c in ("model_key", "model_name", "name") if c in cols and c != key_col]
        for alt in alt_cols:
            row2 = conn.execute(
                f"""
                SELECT {id_col} AS model_id
                FROM models
                WHERE season_id = ?
                  AND {alt} = ?;
                """,
                (season_id, model_key_or_name),
            ).fetchone()
            if row2:
                return int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season_id={season_id} model='{model_key_or_name}'")

    name_col = pick_first_existing(cols, "name")
    if not name_col:
        raise SystemExit(f"FAIL: models table missing name column. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS model_id FROM models WHERE {name_col} = ?;",
        (model_key_or_name,),
    ).fetchone()

    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")

    return int(row["model_id"])


@dataclass(frozen=True)
class OutputSourceSpec:
    table: str
    cols: Dict[str, str]  # canonical -> actual col name


def pick_outputs_table(conn) -> OutputSourceSpec:
    if table_exists(conn, "prospect_model_outputs"):
        cols = set(column_names(conn, "prospect_model_outputs"))
        return OutputSourceSpec(table="prospect_model_outputs", cols=_map_outputs_columns(cols))
    if table_exists(conn, "model_outputs"):
        cols = set(column_names(conn, "model_outputs"))
        return OutputSourceSpec(table="model_outputs", cols=_map_outputs_columns(cols))
    raise SystemExit("FAIL: neither prospect_model_outputs nor model_outputs table exists")


def _map_outputs_columns(cols: set[str]) -> Dict[str, str]:
    def pick(*cands: str) -> Optional[str]:
        return pick_first_existing(cols, *cands)

    mapping: Dict[str, str] = {}

    mapping["season_id"] = pick("season_id")
    mapping["model_id"] = pick("model_id")
    mapping["prospect_id"] = pick("prospect_id")

    mapping["score"] = pick("score", "model_score", "consensus_score")
    mapping["tier"] = pick("tier", "tier_id")
    mapping["reason_chips_json"] = pick("reason_chips_json", "reason_chips", "chips_json")
    mapping["explain_json"] = pick("explain_json", "explain", "explain_payload_json")

    missing_required = [k for k in ("season_id", "model_id", "prospect_id", "score") if mapping.get(k) is None]
    if missing_required:
        raise SystemExit(f"FAIL: outputs table missing required columns: {missing_required}")

    return mapping  # type: ignore[return-value]


def _parse_json_maybe(s: Any) -> Optional[Any]:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    if not s2:
        return None
    try:
        return json.loads(s2)
    except Exception:
        return None


def extract_coverage_count(explain_json: Any, reason_chips_json: Any) -> Optional[int]:
    ej = _parse_json_maybe(explain_json)
    if isinstance(ej, dict):
        for k in (
            "coverage_count",
            "sources_covered",
            "active_sources_covered",
            "source_coverage_count",
            "source_count",
            "sources_count",
            "n_sources",
            "sources",
        ):
            v = ej.get(k)
            if isinstance(v, (int, float)):
                try:
                    return int(v)
                except Exception:
                    pass

        for path in (
            ("coverage", "count"),
            ("coverage", "sources"),
            ("sources", "count"),
            ("sources", "covered"),
            ("meta", "coverage_count"),
        ):
            cur: Any = ej
            ok = True
            for p in path:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, (int, float)):
                try:
                    return int(cur)
                except Exception:
                    pass

    chips = _parse_json_maybe(reason_chips_json)
    if isinstance(chips, list):
        for item in chips:
            if not isinstance(item, str):
                continue
            m = re.search(r"\b(\d+)\s+sources\b", item, flags=re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    continue

    return None


def read_outputs_rows(conn, spec: OutputSourceSpec, season_id: int, model_id: int) -> List[Dict[str, Any]]:
    c = spec.cols

    def sel(canon: str, default_sql: str = "NULL") -> str:
        actual = c.get(canon)
        if actual:
            return f"o.{actual} AS {canon}"
        return f"{default_sql} AS {canon}"

    # Filter to is_active=1 prospects when the column exists, to exclude
    # soft-deprecated universe orphans from the snapshot.
    use_active = prospects_has_is_active(conn)

    if use_active:
        sql = f"""
        SELECT
          {sel("prospect_id")},
          {sel("score")},
          {sel("tier")},
          {sel("reason_chips_json")},
          {sel("explain_json")}
        FROM {spec.table} o
        JOIN prospects p
          ON p.prospect_id = o.prospect_id
         AND p.season_id   = o.season_id
         AND p.is_active   = 1
        WHERE o.season_id = ? AND o.model_id = ?
        ORDER BY o.score DESC, o.prospect_id ASC;
        """
    else:
        sql = f"""
        SELECT
          {sel("prospect_id")},
          {sel("score")},
          {sel("tier")},
          {sel("reason_chips_json")},
          {sel("explain_json")}
        FROM {spec.table} o
        WHERE o.season_id = ? AND o.model_id = ?
        ORDER BY o.score DESC, o.prospect_id ASC;
        """

    rows = conn.execute(sql, (season_id, model_id)).fetchall()
    return [dict(r) for r in rows]


def upsert_snapshot(conn, season_id: int, model_id: int, snapshot_date_utc: str, note: Optional[str]) -> int:
    created_at = utc_now_iso()
    conn.execute(
        """
        INSERT INTO prospect_board_snapshots(season_id, model_id, snapshot_date_utc, created_at_utc, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(season_id, model_id, snapshot_date_utc)
        DO UPDATE SET note = COALESCE(excluded.note, prospect_board_snapshots.note);
        """,
        (season_id, model_id, snapshot_date_utc, created_at, note),
    )
    row = conn.execute(
        """
        SELECT id
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ? AND snapshot_date_utc = ?;
        """,
        (season_id, model_id, snapshot_date_utc),
    ).fetchone()
    if not row:
        raise SystemExit("FAIL: could not read back snapshot id after upsert")
    return int(row["id"])


def clear_snapshot_rows(conn, snapshot_id: int) -> None:
    conn.execute("DELETE FROM prospect_board_snapshot_rows WHERE snapshot_id = ?;", (snapshot_id,))


def insert_snapshot_rows(conn, snapshot_id: int, season_id: int, model_id: int, outputs: List[Dict[str, Any]]) -> int:
    created_at = utc_now_iso()
    n = 0

    for idx, r in enumerate(outputs, start=1):
        pid = int(r["prospect_id"])
        score = r.get("score")
        tier = r.get("tier")
        reason_chips_json = r.get("reason_chips_json")
        explain_json = r.get("explain_json")
        coverage_count = extract_coverage_count(explain_json, reason_chips_json)

        conn.execute(
            """
            INSERT INTO prospect_board_snapshot_rows(
              snapshot_id, season_id, model_id, prospect_id,
              position, rank_overall, score, tier, reason_chips_json, coverage_count,
              created_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_id, prospect_id)
            DO UPDATE SET
              position = excluded.position,
              rank_overall = excluded.rank_overall,
              score = excluded.score,
              tier = excluded.tier,
              reason_chips_json = excluded.reason_chips_json,
              coverage_count = excluded.coverage_count,
              created_at_utc = excluded.created_at_utc;
            """,
            (
                snapshot_id,
                season_id,
                model_id,
                pid,
                None,  # position not present in prospect_model_outputs today
                idx,   # derived rank_overall
                score,
                tier,
                reason_chips_json,
                coverage_count,
                created_at,
            ),
        )
        n += 1

    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Create deterministic daily (UTC) board snapshot from model outputs.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--snapshot-date", type=str, default=None, help="UTC date YYYY-MM-DD. Default: today (UTC).")
    ap.add_argument("--note", type=str, default=None)
    ap.add_argument("--force", action="store_true", help="Clear and rewrite snapshot rows for this snapshot_date.")
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1], help="--apply 1 writes. --apply 0 dry run.")
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    snapshot_date = args.snapshot_date or utc_today_date()

    with connect() as conn:
        # Snapshot tables' FKs may not match DraftOS PK column naming; we enforce determinism via UNIQUE constraints.
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        spec = pick_outputs_table(conn)
        outputs = read_outputs_rows(conn, spec, season_id, model_id)
        if not outputs:
            raise SystemExit(f"FAIL: no outputs found in {spec.table} for season_id={season_id}, model_id={model_id}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            print(f"PLAN: would upsert snapshot season_id={season_id} model_id={model_id} date_utc={snapshot_date}")
            print(f"PLAN: would write snapshot rows: {len(outputs)}")
            top = outputs[0]
            print(f"TOP: prospect_id={top['prospect_id']} derived_rank=1 score={top.get('score')} tier={top.get('tier')}")
            return

    # Only backup + write outside the conn context above (keeps dry-run clean)
    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        spec = pick_outputs_table(conn)
        outputs = read_outputs_rows(conn, spec, season_id, model_id)

        snapshot_id = upsert_snapshot(conn, season_id, model_id, snapshot_date, args.note)

        if args.force:
            clear_snapshot_rows(conn, snapshot_id)

        n = insert_snapshot_rows(conn, snapshot_id, season_id, model_id, outputs)
        conn.commit()

    print(f"OK: snapshot saved: snapshot_id={snapshot_id} date_utc={snapshot_date} rows={n}")


if __name__ == "__main__":
    main()
