# scripts/compute_snapshot_metrics.py
from __future__ import annotations

import argparse
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_snapshot_metrics.{stamp}{db_path.suffix}"
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


def resolve_season_id(conn, draft_year: int) -> int:
    if not table_exists(conn, "seasons"):
        raise SystemExit("FAIL: seasons table not found")

    cols = set(column_names(conn, "seasons"))
    id_col = pick_first_existing(cols, "season_id", "id")
    year_col = pick_first_existing(cols, "draft_year", "year")
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

    cols = set(column_names(conn, "models"))
    id_col = pick_first_existing(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models missing id column. found={sorted(cols)}")

    if "season_id" in cols:
        key_col = pick_first_existing(cols, "model_key", "model_name", "name")
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
        # fallbacks
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
    name_col = pick_first_existing(cols, "name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name column. found={sorted(cols)}")
    row = conn.execute(
        f"SELECT {id_col} AS model_id FROM models WHERE {name_col} = ?;",
        (model_key_or_name,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")
    return int(row["model_id"])


def latest_snapshots(conn, season_id: int, model_id: int, limit_n: int) -> List[Tuple[int, str]]:
    """
    Returns list of (snapshot_id, snapshot_date_utc) ascending by date.
    """
    rows = conn.execute(
        """
        SELECT id, snapshot_date_utc
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
        ORDER BY snapshot_date_utc DESC, id DESC
        LIMIT ?;
        """,
        (season_id, model_id, limit_n),
    ).fetchall()

    # reverse to ascending
    out = [(int(r["id"]), str(r["snapshot_date_utc"])) for r in rows][::-1]
    return out


def load_snapshot_series(
    conn,
    snapshot_ids: List[int],
) -> Dict[int, List[Tuple[int, Optional[float], Optional[int]]]]:
    """
    Returns dict prospect_id -> list aligned to snapshot_ids:
      [(rank_overall, score, coverage_count), ...]

    Deterministic behavior:
    - Only includes prospects that exist in ALL snapshots for rank_overall.
    - Does not pre-populate empty series.
    """
    if not snapshot_ids:
        return {}

    placeholders = ",".join(["?"] * len(snapshot_ids))
    rows = conn.execute(
        f"""
        SELECT snapshot_id, prospect_id, rank_overall, score, coverage_count
        FROM prospect_board_snapshot_rows
        WHERE snapshot_id IN ({placeholders});
        """,
        snapshot_ids,
    ).fetchall()

    # index by snapshot_id then prospect_id
    by_snap: Dict[int, Dict[int, Tuple[int, Optional[float], Optional[int]]]] = {sid: {} for sid in snapshot_ids}
    for r in rows:
        sid = int(r["snapshot_id"])
        pid = int(r["prospect_id"])
        rank = r["rank_overall"]
        score = r["score"]
        cov = r["coverage_count"]
        # rank should be present; if not, skip (deterministic)
        if rank is None:
            continue
        by_snap[sid][pid] = (
            int(rank),
            float(score) if score is not None else None,
            int(cov) if cov is not None else None,
        )

    # union of prospects across snapshots
    all_pids: set[int] = set()
    for sid in snapshot_ids:
        all_pids |= set(by_snap[sid].keys())

    # Build aligned lists (only include prospects that exist in ALL snapshots for rank)
    series: Dict[int, List[Tuple[int, Optional[float], Optional[int]]]] = {}
    for pid in all_pids:
        aligned: List[Tuple[int, Optional[float], Optional[int]]] = []
        ok = True
        for sid in snapshot_ids:
            tup = by_snap[sid].get(pid)
            if tup is None:
                ok = False
                break
            aligned.append(tup)
        if ok:
            series[pid] = aligned

    return series


def mean_abs_deltas(ints: List[int]) -> float:
    if len(ints) < 2:
        return 0.0
    deltas = [abs(ints[i] - ints[i - 1]) for i in range(1, len(ints))]
    return sum(deltas) / float(len(deltas))


def std_dev(ints: List[int]) -> float:
    n = len(ints)
    if n <= 1:
        return 0.0
    mu = sum(ints) / float(n)
    var = sum((x - mu) ** 2 for x in ints) / float(n)  # population std dev (deterministic)
    return math.sqrt(var)


def momentum_chip(delta_rank: int, thresh: int) -> str:
    # delta_rank = oldest_rank - current_rank (positive is improving)
    if delta_rank >= thresh:
        return "Rising"
    if delta_rank <= -thresh:
        return "Falling"
    return "Stable"


def volatility_chip(mad: float, thresh: float) -> str:
    if mad >= thresh:
        return "Volatile"
    return "Calm"


def upsert_metrics(
    conn,
    snapshot_id: int,
    season_id: int,
    model_id: int,
    window_n: int,
    computed_at: str,
    metrics_rows: List[Tuple[int, int, float, float, float, str, str]],
) -> int:
    """
    metrics_rows tuple:
      (prospect_id, momentum_rank, momentum_score, volatility_mad, volatility_std, momentum_chip, volatility_chip)
    """
    # Clear existing metrics for this snapshot/window to be idempotent
    conn.execute(
        """
        DELETE FROM prospect_board_snapshot_metrics
        WHERE snapshot_id = ? AND window_n = ?;
        """,
        (snapshot_id, window_n),
    )

    for pid, m_rank, m_score, v_mad, v_std, m_chip, v_chip in metrics_rows:
        conn.execute(
            """
            INSERT INTO prospect_board_snapshot_metrics(
              snapshot_id, season_id, model_id, prospect_id,
              window_n,
              momentum_rank, momentum_score,
              volatility_rank_mad, volatility_rank_std,
              momentum_chip, volatility_chip,
              computed_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                snapshot_id,
                season_id,
                model_id,
                pid,
                window_n,
                m_rank,
                m_score,
                v_mad,
                v_std,
                m_chip,
                v_chip,
                computed_at,
            ),
        )

    return len(metrics_rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute snapshot-derived momentum + volatility metrics.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--window", type=int, default=3, help="Number of snapshots to use (including current).")
    ap.add_argument("--momentum-thresh", type=int, default=10, help="Ranks improved/worsened over window to trigger chip.")
    ap.add_argument("--volatility-thresh", type=float, default=5.0, help="Mean abs delta rank threshold to trigger Volatile.")
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1], help="--apply 1 writes. --apply 0 dry run.")
    args = ap.parse_args()

    if args.window < 2:
        raise SystemExit("FAIL: --window must be >= 2")

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        if not table_exists(conn, "prospect_board_snapshot_metrics"):
            raise SystemExit("FAIL: prospect_board_snapshot_metrics table not found. Apply migration 0003 first.")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        snaps = latest_snapshots(conn, season_id, model_id, args.window)
        if len(snaps) < args.window:
            raise SystemExit(f"FAIL: need {args.window} snapshots, found {len(snaps)} for season_id={season_id} model_id={model_id}")

        snapshot_ids = [sid for sid, _ in snaps]
        current_snapshot_id = snapshot_ids[-1]

        series = load_snapshot_series(conn, snapshot_ids)
        if not series:
            raise SystemExit("FAIL: no aligned snapshot series found (unexpected)")

        computed_at = utc_now_iso()
        metrics: List[Tuple[int, int, float, float, float, str, str]] = []

        for pid, aligned in series.items():
            if not aligned:
                continue

            ranks = [t[0] for t in aligned if t and t[0] is not None]
            scores = [t[1] for t in aligned if t]

            if len(ranks) < 2:
                continue

            oldest_rank = ranks[0]
            current_rank = ranks[-1]
            m_rank = int(oldest_rank - current_rank)

            oldest_score = scores[0] if scores else None
            current_score = scores[-1] if scores else None
            if oldest_score is None or current_score is None:
                m_score = 0.0
            else:
                m_score = float(current_score - oldest_score)

            v_mad = float(mean_abs_deltas(ranks))
            v_std = float(std_dev(ranks))

            m_chip = momentum_chip(m_rank, args.momentum_thresh)
            v_chip = volatility_chip(v_mad, args.volatility_thresh)

            metrics.append((pid, m_rank, m_score, v_mad, v_std, m_chip, v_chip))

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            print(f"PLAN: would compute metrics for snapshot_id={current_snapshot_id} window_n={args.window} prospects={len(metrics)}")
            print(f"PLAN: thresholds momentum={args.momentum_thresh} volatility_mad={args.volatility_thresh}")
            if metrics:
                top = metrics[0]
                print(
                    f"EXAMPLE: prospect_id={top[0]} momentum_rank={top[1]} momentum_score={top[2]} volatility_mad={top[3]} chip={top[5]}/{top[6]}"
                )
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        snaps = latest_snapshots(conn, season_id, model_id, args.window)
        snapshot_ids = [sid for sid, _ in snaps]
        current_snapshot_id = snapshot_ids[-1]

        series = load_snapshot_series(conn, snapshot_ids)

        computed_at = utc_now_iso()
        metrics: List[Tuple[int, int, float, float, float, str, str]] = []
        for pid, aligned in series.items():
            if not aligned:
                continue

            ranks = [t[0] for t in aligned if t and t[0] is not None]
            scores = [t[1] for t in aligned if t]

            if len(ranks) < 2:
                continue

            m_rank = int(ranks[0] - ranks[-1])

            if not scores or scores[0] is None or scores[-1] is None:
                m_score = 0.0
            else:
                m_score = float(scores[-1] - scores[0])

            v_mad = float(mean_abs_deltas(ranks))
            v_std = float(std_dev(ranks))

            m_chip = momentum_chip(m_rank, args.momentum_thresh)
            v_chip = volatility_chip(v_mad, args.volatility_thresh)

            metrics.append((pid, m_rank, m_score, v_mad, v_std, m_chip, v_chip))

        n = upsert_metrics(
            conn=conn,
            snapshot_id=current_snapshot_id,
            season_id=season_id,
            model_id=model_id,
            window_n=args.window,
            computed_at=computed_at,
            metrics_rows=metrics,
        )
        conn.commit()

    print(f"OK: snapshot metrics saved: snapshot_id={current_snapshot_id} window_n={args.window} rows={n}")


if __name__ == "__main__":
    main()