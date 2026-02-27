from __future__ import annotations

# --- sys.path bootstrap so "python scripts\..." always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import json
import math
from datetime import datetime, timezone
from statistics import median, pstdev
from typing import Dict, List, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup_db(reason: str) -> Path:
    src = PATHS.db
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"draftos_{ts}_{reason}.sqlite"
    dst.write_bytes(Path(src).read_bytes())
    return dst


def get_season_id(conn, draft_year: int) -> int:
    row = conn.execute("SELECT season_id FROM seasons WHERE draft_year = ?", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season {draft_year} not found.")
    return int(row["season_id"])


def sources_has_is_active(conn) -> bool:
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(sources);").fetchall()]
    return "is_active" in cols


def active_sources(conn) -> List[Dict]:
    if sources_has_is_active(conn):
        rows = conn.execute(
            "SELECT source_id, source_name FROM sources WHERE is_active = 1 ORDER BY source_id"
        ).fetchall()
    else:
        rows = conn.execute("SELECT source_id, source_name FROM sources ORDER BY source_id").fetchall()
    return [dict(r) for r in rows]


def fetch_prospect_ranks(conn, season_id: int) -> Dict[int, List[Tuple[int, int]]]:
    """
    Returns: prospect_id -> list[(source_id, overall_rank)] for each active source's latest ranking_date.
    """
    if sources_has_is_active(conn):
        sql = """
        SELECT
          m.prospect_id,
          sr.source_id,
          sr.overall_rank
        FROM source_rankings sr
        JOIN sources s ON s.source_id = sr.source_id
        JOIN source_player_map m ON m.source_player_id = sr.source_player_id
        WHERE sr.season_id = ?
          AND s.is_active = 1
          AND sr.ranking_date = (
            SELECT MAX(ranking_date)
            FROM source_rankings sr2
            WHERE sr2.source_id = sr.source_id
              AND sr2.season_id = sr.season_id
          )
        """
    else:
        sql = """
        SELECT
          m.prospect_id,
          sr.source_id,
          sr.overall_rank
        FROM source_rankings sr
        JOIN source_player_map m ON m.source_player_id = sr.source_player_id
        WHERE sr.season_id = ?
          AND sr.ranking_date = (
            SELECT MAX(ranking_date)
            FROM source_rankings sr2
            WHERE sr2.source_id = sr.source_id
              AND sr2.season_id = sr.season_id
          )
        """
    rows = conn.execute(sql, (season_id,)).fetchall()
    out: Dict[int, List[Tuple[int, int]]] = {}
    for r in rows:
        out.setdefault(int(r["prospect_id"]), []).append((int(r["source_id"]), int(r["overall_rank"])))
    return out


def per_source_max_rank(conn, season_id: int, source_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(overall_rank) AS mx FROM source_rankings WHERE season_id=? AND source_id=?",
        (season_id, source_id),
    ).fetchone()
    return int(row["mx"] or 0)


def base_score_0_100(ranks: List[Tuple[int, int]], source_max: Dict[int, int]) -> float:
    """
    base = avg(1 - rank/max_rank_by_source) * 100
    """
    vals = []
    for sid, rk in ranks:
        mx = max(1, int(source_max.get(sid, 0) or 0))
        if mx <= 1:
            continue
        vals.append(1.0 - (rk / mx))
    if not vals:
        return 0.0
    return 100.0 * (sum(vals) / len(vals))


def coverage_factor(k: int, n_active: int) -> float:
    """
    coverage = sqrt(k / n_active)
    """
    if n_active <= 0:
        return 0.0
    k = max(0, min(k, n_active))
    if k == 0:
        return 0.0
    return math.sqrt(k / n_active)


def tier_from_score(score: float) -> str:
    """
    Deterministic tiers for Phase 1.
    Tune later, but keep stable once UI depends on it.
    """
    if score >= 90:
        return "Elite"
    if score >= 80:
        return "Strong"
    if score >= 65:
        return "Playable"
    return "Watch"


def compute_reason_chips(
    *,
    ranks: List[Tuple[int, int]],
    n_active: int,
    source_max: Dict[int, int],
) -> List[str]:
    """
    Produce 2–3 short, deterministic reason chips.
    """
    chips: List[str] = []
    k = len(ranks)
    coverage_pct = int(round(100.0 * (k / n_active))) if n_active else 0
    chips.append(f"{coverage_pct}% coverage")

    rvals = [rk for _, rk in ranks]
    if k >= 3:
        sd = pstdev(rvals)
        if sd <= 5:
            chips.append("Tight consensus")
        elif sd >= 20:
            chips.append("Wide variance")
        else:
            chips.append("Moderate variance")

    # “Top-10 density” across sources: how many sources rank him in top 10?
    top10 = sum(1 for _, rk in ranks if rk <= 10)
    if top10 >= max(2, math.ceil(0.33 * k)):
        chips.append(f"{top10} sources top-10")
    else:
        # fallback: highlight “high placement” if median is strong
        med = float(median(rvals)) if rvals else 999.0
        if med <= 25:
            chips.append("Median rank ≤ 25")
        elif med <= 50:
            chips.append("Median rank ≤ 50")

    # Limit to 3 chips, stable ordering
    return chips[:3]


def upsert_consensus_rows(conn, season_id: int, rows: List[Dict]) -> None:
    now = utcnow_iso()
    for row in rows:
        existing = conn.execute(
            "SELECT consensus_id FROM prospect_consensus_rankings WHERE season_id=? AND prospect_id=?",
            (season_id, row["prospect_id"]),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE prospect_consensus_rankings
                SET consensus_rank=?,
                    score=?,
                    sources_covered=?,
                    avg_rank=?,
                    median_rank=?,
                    min_rank=?,
                    max_rank=?,
                    tier=?,
                    reason_chips_json=?,
                    explain_json=?,
                    updated_at=?
                WHERE season_id=? AND prospect_id=?
                """,
                (
                    row["consensus_rank"],
                    row["score"],
                    row["sources_covered"],
                    row["avg_rank"],
                    row["median_rank"],
                    row["min_rank"],
                    row["max_rank"],
                    row["tier"],
                    row["reason_chips_json"],
                    row["explain_json"],
                    now,
                    season_id,
                    row["prospect_id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO prospect_consensus_rankings(
                  season_id, prospect_id,
                  consensus_rank, score,
                  sources_covered, avg_rank, median_rank, min_rank, max_rank,
                  tier, reason_chips_json,
                  explain_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season_id,
                    row["prospect_id"],
                    row["consensus_rank"],
                    row["score"],
                    row["sources_covered"],
                    row["avg_rank"],
                    row["median_rank"],
                    row["min_rank"],
                    row["max_rank"],
                    row["tier"],
                    row["reason_chips_json"],
                    row["explain_json"],
                    now,
                    now,
                ),
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-year", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0)
    args = ap.parse_args()

    if args.apply == 1:
        b = backup_db(f"build_consensus_{args.draft_year}")
        print(f"DB BACKUP: {b}")
    else:
        print("DRY RUN: no DB writes, no backup")

    with connect() as conn:
        season_id = get_season_id(conn, args.draft_year)
        srcs = active_sources(conn)
        src_ids = [s["source_id"] for s in srcs]
        n_active = len(src_ids)

        source_max = {sid: per_source_max_rank(conn, season_id, sid) for sid in src_ids}
        prospect_ranks = fetch_prospect_ranks(conn, season_id)

        computed = []
        for prospect_id, ranks in prospect_ranks.items():
            ranks_sorted = sorted(ranks, key=lambda x: x[0])
            rvals = [rk for _, rk in ranks_sorted]
            k = len(rvals)

            base = base_score_0_100(ranks_sorted, source_max)
            cov = coverage_factor(k, n_active)
            score = round(base * cov, 4)

            avg_rk = round(sum(rvals) / k, 4) if k else None
            med_rk = float(median(rvals)) if k else None

            chips = compute_reason_chips(ranks=ranks_sorted, n_active=n_active, source_max=source_max)
            tier = tier_from_score(score)

            explain = {
                "sources": [{"source_id": sid, "rank": rk} for sid, rk in ranks_sorted],
                "active_sources": n_active,
                "source_max_rank": {str(k): int(v) for k, v in source_max.items()},
                "scoring": {
                    "base": "avg(1 - rank/max_rank_by_source) * 100",
                    "coverage": "sqrt(sources_covered / active_sources)",
                    "final": "base * coverage",
                },
                "tier": tier,
                "reason_chips": chips,
            }

            computed.append(
                {
                    "prospect_id": int(prospect_id),
                    "score": float(score),
                    "sources_covered": int(k),
                    "avg_rank": avg_rk,
                    "median_rank": med_rk,
                    "min_rank": int(min(rvals)) if k else None,
                    "max_rank": int(max(rvals)) if k else None,
                    "tier": tier,
                    "reason_chips_json": json.dumps(chips, ensure_ascii=False),
                    "explain_json": json.dumps(explain, ensure_ascii=False),
                }
            )

        computed.sort(
            key=lambda r: (-r["score"], (r["avg_rank"] or 10**9), -r["sources_covered"], r["prospect_id"])
        )

        for i, row in enumerate(computed, start=1):
            row["consensus_rank"] = i

        print(f"PLAN: would write consensus rows: {len(computed)} (active sources: {n_active})")
        for row in computed[:10]:
            print(
                f"TOP: prospect_id={row['prospect_id']} rank={row['consensus_rank']} "
                f"score={row['score']} tier={row['tier']} sources={row['sources_covered']}"
            )

        if args.apply != 1:
            return

        upsert_consensus_rows(conn, season_id, computed)
        conn.commit()
        print(f"OK: wrote consensus rows: {len(computed)}")


if __name__ == "__main__":
    main()