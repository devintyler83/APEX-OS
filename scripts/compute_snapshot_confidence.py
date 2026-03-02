# scripts/compute_snapshot_confidence.py
from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_snapshot_confidence.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


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

    name_col = pick_first(cols, "name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name column. found={sorted(cols)}")

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


def mean(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    return sum(xs) / float(len(xs))


def stddev(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    if len(xs) == 1:
        return 0.0
    m = sum(xs) / float(len(xs))
    v = sum((x - m) ** 2 for x in xs) / float(len(xs))
    return math.sqrt(v)


def clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def health_weight(chip: str) -> float:
    """
    Deterministic quality weights per canonical source.
    These are v2 foundations, tune later with explicit versioning if desired.
    """
    c = (chip or "").strip()
    if c == "Healthy":
        return 1.0
    if c == "Thin Coverage":
        return 0.60
    if c == "Noisy":
        return 0.40
    if c == "Stale":
        return 0.20
    return 0.50  # unknown/other


def compute_confidence_v2(
    active_canon_sources: int,
    present_canon_sources: int,
    sum_present_weights: float,
    sum_active_weights: float,
    healthy_present: int,
    noisy_present: int,
    thin_present: int,
    stale_present: int,
    rank_std: Optional[float],
    rank_mad: Optional[float],
) -> Tuple[float, str, List[str]]:
    """
    v2: coverage is computed on canonical sources.
    Additionally uses health-weighted coverage so Healthy sources contribute more.
    """
    cov = float(present_canon_sources) / float(active_canon_sources) if active_canon_sources > 0 else 0.0
    cov = clamp01(cov)

    wcov = (float(sum_present_weights) / float(sum_active_weights)) if sum_active_weights > 0 else 0.0
    wcov = clamp01(wcov)

    noisy_share = (float(noisy_present) / float(present_canon_sources)) if present_canon_sources > 0 else 0.0
    stale_share = (float(stale_present) / float(present_canon_sources)) if present_canon_sources > 0 else 0.0
    thin_share = (float(thin_present) / float(present_canon_sources)) if present_canon_sources > 0 else 0.0

    mad = float(rank_mad) if rank_mad is not None else 0.0
    sd = float(rank_std) if rank_std is not None else 0.0

    mad_pen = clamp01(mad / 80.0)
    sd_pen = clamp01(sd / 80.0)

    base = wcov
    base *= (1.0 - 0.55 * clamp01(noisy_share))
    base *= (1.0 - 0.80 * clamp01(stale_share))
    base *= (1.0 - 0.25 * clamp01(thin_share))
    base *= (1.0 - 0.35 * mad_pen)
    base *= (1.0 - 0.20 * sd_pen)

    base = clamp01(base)
    score = round(base * 100.0, 1)

    reasons: List[str] = []

    if cov >= 0.80:
        reasons.append("High coverage")
    elif cov >= 0.50:
        reasons.append("Moderate coverage")
    else:
        reasons.append("Low coverage")

    if wcov >= 0.80:
        reasons.append("High quality-weighted coverage")
    elif wcov >= 0.50:
        reasons.append("Moderate quality-weighted coverage")
    else:
        reasons.append("Low quality-weighted coverage")

    if healthy_present >= max(1, present_canon_sources // 2):
        reasons.append("Healthy source mix")
    if noisy_present > 0:
        reasons.append("Noisy sources present")
    if stale_present > 0:
        reasons.append("Stale sources present")
    if mad >= 60.0:
        reasons.append("High rank dispersion")
    elif mad >= 30.0:
        reasons.append("Moderate rank dispersion")
    else:
        reasons.append("Tight rank agreement")

    if score >= 70.0:
        band = "High"
    elif score >= 40.0:
        band = "Medium"
    else:
        band = "Low"

    return score, band, reasons


def load_canonical_map(conn) -> Dict[int, int]:
    if not table_exists(conn, "source_canonical_map"):
        return {}
    rows = conn.execute("SELECT source_id, canonical_source_id FROM source_canonical_map;").fetchall()
    m: Dict[int, int] = {}
    for r in rows:
        m[int(r["source_id"])] = int(r["canonical_source_id"])
    return m


def canon_of(source_id: int, cmap: Dict[int, int]) -> int:
    return int(cmap.get(int(source_id), int(source_id)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute prospect-level confidence for the latest snapshot (v2 foundations).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--snapshot-id", type=int, default=None)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1], help="--apply 1 writes. --apply 0 dry run.")
    ap.add_argument(
        "--prune-coverage-extras",
        type=int,
        default=1,
        choices=[0, 1],
        help="If coverage has prospect_ids not in snapshot rows, optionally delete those extras when --apply 1.",
    )
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    # DRY RUN: compute + report, no writes
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        required = [
            "prospect_board_snapshots",
            "prospect_board_snapshot_rows",
            "source_board_snapshot_metrics",
            "prospect_board_snapshot_confidence",
            "sources",
            "source_rankings",
            "source_player_map",
        ]
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, _snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)
        else:
            row = conn.execute(
                """
                SELECT id, snapshot_date_utc
                FROM prospect_board_snapshots
                WHERE id = ? AND season_id = ? AND model_id = ?;
                """,
                (args.snapshot_id, season_id, model_id),
            ).fetchone()
            if not row:
                raise SystemExit("FAIL: snapshot_id not found for this season/model")
            snapshot_id = int(row["id"])

        cmap = load_canonical_map(conn)
        has_coverage = table_exists(conn, "prospect_board_snapshot_coverage")

        src_rows = conn.execute(
            """
            SELECT
              s.source_id,
              m.ranking_date_used,
              m.health_chip
            FROM sources s
            JOIN source_board_snapshot_metrics m
              ON m.source_id = s.source_id
            WHERE s.is_active = 1 AND m.snapshot_id = ?
            ORDER BY s.source_id;
            """,
            (snapshot_id,),
        ).fetchall()
        if not src_rows:
            raise SystemExit("FAIL: no active sources found for this snapshot")

        canon_members: Dict[int, List[Tuple[int, str, str]]] = {}
        for r in src_rows:
            sid = int(r["source_id"])
            canon = canon_of(sid, cmap)
            rdu = (r["ranking_date_used"] or "").strip()[:10]
            chip = (r["health_chip"] or "").strip() or "Thin Coverage"
            canon_members.setdefault(canon, []).append((sid, rdu, chip))

        canon_representative: Dict[int, Tuple[int, str, str]] = {}
        for canon_id, members in canon_members.items():
            members_sorted = sorted(members, key=lambda x: x[0])
            rep = None
            for m in members_sorted:
                if m[0] == canon_id:
                    rep = m
                    break
            if rep is None:
                rep = members_sorted[0]
            canon_representative[canon_id] = rep

        active_canon_sources = len(canon_representative)
        if active_canon_sources == 0:
            raise SystemExit("FAIL: no canonical active sources resolved")

        active_canon_weight_sum = 0.0
        for _canon_id, (_sid, _rdu, chip) in canon_representative.items():
            active_canon_weight_sum += health_weight(chip)

        board_rows = conn.execute(
            """
            SELECT prospect_id
            FROM prospect_board_snapshot_rows
            WHERE snapshot_id = ?;
            """,
            (snapshot_id,),
        ).fetchall()
        board_pids = [int(r["prospect_id"]) for r in board_rows]
        board_pid_set = set(board_pids)

        rep_ranks: Dict[int, Dict[int, int]] = {}
        for _canon_id, (rep_sid, rdu, _chip) in canon_representative.items():
            if not rdu:
                rep_ranks[rep_sid] = {}
                continue
            rows = conn.execute(
                """
                SELECT spm.prospect_id, sr.overall_rank
                FROM source_rankings sr
                JOIN source_player_map spm
                  ON spm.source_player_id = sr.source_player_id
                WHERE sr.source_id = ?
                  AND sr.season_id = ?
                  AND substr(sr.ranking_date, 1, 10) = substr(?, 1, 10)
                  AND sr.overall_rank IS NOT NULL;
                """,
                (rep_sid, season_id, rdu),
            ).fetchall()
            d: Dict[int, int] = {}
            for rr in rows:
                d[int(rr["prospect_id"])] = int(rr["overall_rank"])
            rep_ranks[rep_sid] = d

        coverage_map: Dict[int, List[int]] = {}
        extra_coverage_pids: List[int] = []
        if has_coverage:
            cov_rows = conn.execute(
                """
                SELECT prospect_id, source_ids_json
                FROM prospect_board_snapshot_coverage
                WHERE snapshot_id = ?;
                """,
                (snapshot_id,),
            ).fetchall()
            for cr in cov_rows:
                pid = int(cr["prospect_id"])
                if pid not in board_pid_set:
                    extra_coverage_pids.append(pid)
                    continue
                raw = cr["source_ids_json"]
                if not raw:
                    continue
                try:
                    arr = json.loads(raw)
                    if isinstance(arr, list):
                        coverage_map[pid] = [int(x) for x in arr if x is not None]
                except Exception:
                    continue

        computed_at = utc_now_iso()

        out_rows: List[Dict[str, Any]] = []
        for pid in board_pids:
            present_canon_ids: List[int] = []

            if pid in coverage_map:
                present_canon_ids = [c for c in coverage_map[pid] if c in canon_representative]
            else:
                for canon_id, (rep_sid, _rdu, _chip) in canon_representative.items():
                    if rep_ranks.get(rep_sid, {}).get(pid) is not None:
                        present_canon_ids.append(canon_id)

            ranks: List[float] = []

            present = 0
            healthy = 0
            noisy = 0
            thin = 0
            stale = 0

            sum_present_weights = 0.0

            for canon_id in present_canon_ids:
                rep_sid, _rdu, chip = canon_representative[canon_id]
                srank = rep_ranks.get(rep_sid, {}).get(pid)
                if srank is None:
                    continue

                present += 1
                ranks.append(float(srank))

                c = (chip or "").strip()
                if c == "Healthy":
                    healthy += 1
                elif c == "Noisy":
                    noisy += 1
                elif c == "Stale":
                    stale += 1
                else:
                    thin += 1

                sum_present_weights += health_weight(chip)

            cov_pct = (float(present) / float(active_canon_sources)) if active_canon_sources > 0 else 0.0

            sd = stddev(ranks)
            mad = mean([abs(x - (mean(ranks) or 0.0)) for x in ranks]) if ranks else None

            score, band, reasons = compute_confidence_v2(
                active_canon_sources=active_canon_sources,
                present_canon_sources=present,
                sum_present_weights=sum_present_weights,
                sum_active_weights=active_canon_weight_sum,
                healthy_present=healthy,
                noisy_present=noisy,
                thin_present=thin,
                stale_present=stale,
                rank_std=sd,
                rank_mad=mad,
            )

            out_rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "season_id": season_id,
                    "model_id": model_id,
                    "prospect_id": pid,
                    "active_sources": active_canon_sources,
                    "sources_present": present,
                    "coverage_pct": cov_pct,
                    "sources_healthy_present": healthy,
                    "sources_noisy_present": noisy,
                    "sources_thin_present": thin,
                    "sources_stale_present": stale,
                    "rank_std": sd,
                    "rank_mad": mad,
                    "confidence_score": score,
                    "confidence_band": band,
                    "confidence_reasons_json": json.dumps(reasons, ensure_ascii=False),
                    "computed_at_utc": computed_at,
                }
            )

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            print(
                "PLAN:",
                f"would compute snapshot confidence v2 snapshot_id={snapshot_id}",
                f"snapshot_rows={len(board_pids)}",
                f"confidence_rows={len(out_rows)}",
                f"active_canon_sources={active_canon_sources}",
                f"coverage_table={'YES' if has_coverage else 'NO'}",
                f"coverage_extras_not_in_snapshot_rows={len(extra_coverage_pids)}",
                f"canonical_map={'YES' if table_exists(conn, 'source_canonical_map') else 'NO'}",
            )
            if extra_coverage_pids:
                print(f"EXAMPLE_COVERAGE_EXTRA_PROSPECT_ID: {extra_coverage_pids[0]}")
            if out_rows:
                ex = out_rows[0]
                print(
                    "EXAMPLE:",
                    f"prospect_id={ex['prospect_id']}",
                    f"sources_present={ex['sources_present']}/{ex['active_sources']}",
                    f"coverage_pct={round(ex['coverage_pct']*100.0,1)}",
                    f"score={ex['confidence_score']}",
                    f"band={ex['confidence_band']}",
                    f"reasons={ex['confidence_reasons_json']}",
                )
            return

    # APPLY: backup before write
    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)

        if args.snapshot_id is None:
            snapshot_id, _snapshot_date_utc = get_latest_snapshot(conn, season_id, model_id)
        else:
            row = conn.execute(
                "SELECT id FROM prospect_board_snapshots WHERE id = ? AND season_id = ? AND model_id = ?;",
                (args.snapshot_id, season_id, model_id),
            ).fetchone()
            if not row:
                raise SystemExit("FAIL: snapshot_id not found for this season/model")
            snapshot_id = int(row["id"])

        cmap = load_canonical_map(conn)
        has_coverage = table_exists(conn, "prospect_board_snapshot_coverage")

        src_rows = conn.execute(
            """
            SELECT
              s.source_id,
              m.ranking_date_used,
              m.health_chip
            FROM sources s
            JOIN source_board_snapshot_metrics m
              ON m.source_id = s.source_id
            WHERE s.is_active = 1 AND m.snapshot_id = ?
            ORDER BY s.source_id;
            """,
            (snapshot_id,),
        ).fetchall()
        if not src_rows:
            raise SystemExit("FAIL: no active sources found for this snapshot")

        canon_members: Dict[int, List[Tuple[int, str, str]]] = {}
        for r in src_rows:
            sid = int(r["source_id"])
            canon = canon_of(sid, cmap)
            rdu = (r["ranking_date_used"] or "").strip()[:10]
            chip = (r["health_chip"] or "").strip() or "Thin Coverage"
            canon_members.setdefault(canon, []).append((sid, rdu, chip))

        canon_representative: Dict[int, Tuple[int, str, str]] = {}
        for canon_id, members in canon_members.items():
            members_sorted = sorted(members, key=lambda x: x[0])
            rep = None
            for m in members_sorted:
                if m[0] == canon_id:
                    rep = m
                    break
            if rep is None:
                rep = members_sorted[0]
            canon_representative[canon_id] = rep

        active_canon_sources = len(canon_representative)
        if active_canon_sources == 0:
            raise SystemExit("FAIL: no canonical active sources resolved")

        active_canon_weight_sum = 0.0
        for _canon_id, (_sid, _rdu, chip) in canon_representative.items():
            active_canon_weight_sum += health_weight(chip)

        board_rows = conn.execute(
            "SELECT prospect_id FROM prospect_board_snapshot_rows WHERE snapshot_id = ?;",
            (snapshot_id,),
        ).fetchall()
        board_pids = [int(r["prospect_id"]) for r in board_rows]
        board_pid_set = set(board_pids)

        rep_ranks: Dict[int, Dict[int, int]] = {}
        for _canon_id, (rep_sid, rdu, _chip) in canon_representative.items():
            if not rdu:
                rep_ranks[rep_sid] = {}
                continue
            rows = conn.execute(
                """
                SELECT spm.prospect_id, sr.overall_rank
                FROM source_rankings sr
                JOIN source_player_map spm
                  ON spm.source_player_id = sr.source_player_id
                WHERE sr.source_id = ?
                  AND sr.season_id = ?
                  AND substr(sr.ranking_date, 1, 10) = substr(?, 1, 10)
                  AND sr.overall_rank IS NOT NULL;
                """,
                (rep_sid, season_id, rdu),
            ).fetchall()
            d: Dict[int, int] = {}
            for rr in rows:
                d[int(rr["prospect_id"])] = int(rr["overall_rank"])
            rep_ranks[rep_sid] = d

        coverage_map: Dict[int, List[int]] = {}
        extra_coverage_pids: List[int] = []
        if has_coverage:
            cov_rows = conn.execute(
                """
                SELECT prospect_id, source_ids_json
                FROM prospect_board_snapshot_coverage
                WHERE snapshot_id = ?;
                """,
                (snapshot_id,),
            ).fetchall()
            for cr in cov_rows:
                pid = int(cr["prospect_id"])
                if pid not in board_pid_set:
                    extra_coverage_pids.append(pid)
                    continue
                raw = cr["source_ids_json"]
                if not raw:
                    continue
                try:
                    arr = json.loads(raw)
                    if isinstance(arr, list):
                        coverage_map[pid] = [int(x) for x in arr if x is not None]
                except Exception:
                    continue

            if extra_coverage_pids and args.prune_coverage_extras == 1:
                conn.execute(
                    """
                    DELETE FROM prospect_board_snapshot_coverage
                    WHERE snapshot_id = ?
                      AND prospect_id NOT IN (
                        SELECT prospect_id FROM prospect_board_snapshot_rows WHERE snapshot_id = ?
                      );
                    """,
                    (snapshot_id, snapshot_id),
                )
                print(f"OK: pruned coverage extras not in snapshot rows: deleted={len(extra_coverage_pids)}")

        computed_at = utc_now_iso()

        # Idempotent on snapshot: remove then reinsert for this snapshot_id
        conn.execute("DELETE FROM prospect_board_snapshot_confidence WHERE snapshot_id = ?;", (snapshot_id,))

        n = 0
        for pid in board_pids:
            present_canon_ids: List[int] = []
            if pid in coverage_map:
                present_canon_ids = [c for c in coverage_map[pid] if c in canon_representative]
            else:
                for canon_id, (rep_sid, _rdu, _chip) in canon_representative.items():
                    if rep_ranks.get(rep_sid, {}).get(pid) is not None:
                        present_canon_ids.append(canon_id)

            ranks: List[float] = []
            present = 0
            healthy = 0
            noisy = 0
            thin = 0
            stale = 0
            sum_present_weights = 0.0

            for canon_id in present_canon_ids:
                rep_sid, _rdu, chip = canon_representative[canon_id]
                srank = rep_ranks.get(rep_sid, {}).get(pid)
                if srank is None:
                    continue
                present += 1
                ranks.append(float(srank))

                c = (chip or "").strip()
                if c == "Healthy":
                    healthy += 1
                elif c == "Noisy":
                    noisy += 1
                elif c == "Stale":
                    stale += 1
                else:
                    thin += 1

                sum_present_weights += health_weight(chip)

            cov_pct = (float(present) / float(active_canon_sources)) if active_canon_sources > 0 else 0.0
            sd = stddev(ranks)
            mad = mean([abs(x - (mean(ranks) or 0.0)) for x in ranks]) if ranks else None

            score, band, reasons = compute_confidence_v2(
                active_canon_sources=active_canon_sources,
                present_canon_sources=present,
                sum_present_weights=sum_present_weights,
                sum_active_weights=active_canon_weight_sum,
                healthy_present=healthy,
                noisy_present=noisy,
                thin_present=thin,
                stale_present=stale,
                rank_std=sd,
                rank_mad=mad,
            )

            conn.execute(
                """
                INSERT INTO prospect_board_snapshot_confidence(
                  snapshot_id, season_id, model_id, prospect_id,
                  active_sources, sources_present, coverage_pct,
                  sources_healthy_present, sources_noisy_present, sources_thin_present, sources_stale_present,
                  rank_std, rank_mad,
                  confidence_score, confidence_band, confidence_reasons_json,
                  computed_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id, prospect_id)
                DO UPDATE SET
                  active_sources = excluded.active_sources,
                  sources_present = excluded.sources_present,
                  coverage_pct = excluded.coverage_pct,
                  sources_healthy_present = excluded.sources_healthy_present,
                  sources_noisy_present = excluded.sources_noisy_present,
                  sources_thin_present = excluded.sources_thin_present,
                  sources_stale_present = excluded.sources_stale_present,
                  rank_std = excluded.rank_std,
                  rank_mad = excluded.rank_mad,
                  confidence_score = excluded.confidence_score,
                  confidence_band = excluded.confidence_band,
                  confidence_reasons_json = excluded.confidence_reasons_json,
                  computed_at_utc = excluded.computed_at_utc;
                """,
                (
                    snapshot_id,
                    season_id,
                    model_id,
                    pid,
                    active_canon_sources,
                    present,
                    cov_pct,
                    healthy,
                    noisy,
                    thin,
                    stale,
                    sd,
                    mad,
                    score,
                    band,
                    json.dumps(reasons, ensure_ascii=False),
                    computed_at,
                ),
            )
            n += 1

        conn.commit()

    print(f"OK: snapshot confidence saved (v2): snapshot_id={snapshot_id} rows={n}")


if __name__ == "__main__":
    main()