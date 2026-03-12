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

# ── Dispersion tuning constants ────────────────────────────────────────────────
# Penalty formula: min(std_dev * DISPERSION_WEIGHT, MAX_PENALTY)
# std_dev is population std dev of normalized rank values (each in [0.0, 1.0]).
# A std_dev of 0.5 (half the full normalized range) × 0.5 weight = 0.25 penalty cap.
DISPERSION_WEIGHT: float = 0.5
MAX_PENALTY: float = 0.25          # Score reduction never exceeds 25%
MIN_SOURCES_FOR_DISPERSION: int = 2  # Dispersion undefined for k < 2; penalty = 0

# ── Source quality weights ─────────────────────────────────────────────────────
# Tier 1 — Premium analytics/editorial (weight 1.3)
# Tier 2 — Solid mainstream (weight 1.0)
# Tier 3 — Aggregator/community (weight 0.7)
# Any source not listed falls back to DEFAULT_WEIGHT.
SOURCE_WEIGHTS: Dict[str, float] = {
    # Tier 1
    "pff_2026":             1.3,
    "thedraftnetwork_2026": 1.3,
    "theringer_2026":       1.3,
    # Tier 2
    "nfldraftbuzz_2026_v2": 1.0,
    "cbssports_2026":       1.0,
    "espn_2026":            1.0,
    "nytimes_2026":         1.0,
    "pfsn_2026":            1.0,
    # Tier 3
    "bnbfootball_2026":     0.7,
    "tankathon_2026":       0.7,
    # Tier 2 (continued)
    "jfosterfilm_2026":     1.0,  # independent expert board 2026 — 293 ranked prospects
    "bleacherreport_2026":  1.0,  # B/R NFL Scouting Dept. post-combine big board. 250 ranked prospects.
    "combine_ranks_2026":   1.0,  # NFL.com Combine Rankings 2026. 735 ranked prospects. Renamed Session 23b.
    "nflcom_2026":          1.0,  # NFL.com Rankings 2026 (editorial big board). 303 ranked. Added Session 23b.
    # ngs_2026 is is_active=0 — model score, not a scout ranking. Stored but excluded from consensus.
}
DEFAULT_WEIGHT: float = 1.0  # fallback for any source not in the dict


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


def prospects_has_is_active(conn) -> bool:
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(prospects);").fetchall()]
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
    Filters to is_active=1 prospects when the column exists.
    """
    use_src_active = sources_has_is_active(conn)
    use_pro_active = prospects_has_is_active(conn)

    if use_src_active and use_pro_active:
        sql = """
        SELECT
          m.prospect_id,
          sr.source_id,
          sr.overall_rank
        FROM source_rankings sr
        JOIN sources s ON s.source_id = sr.source_id
        JOIN source_player_map m ON m.source_player_id = sr.source_player_id
        JOIN prospects p ON p.prospect_id = m.prospect_id
          AND p.season_id = sr.season_id
          AND p.is_active = 1
        WHERE sr.season_id = ?
          AND s.is_active = 1
          AND sr.overall_rank IS NOT NULL
          AND sr.ranking_date = (
            SELECT MAX(ranking_date)
            FROM source_rankings sr2
            WHERE sr2.source_id = sr.source_id
              AND sr2.season_id = sr.season_id
          )
        """
    elif use_src_active:
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
          AND sr.overall_rank IS NOT NULL
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
          AND sr.overall_rank IS NOT NULL
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


def normalized_ranks(ranks: List[Tuple[int, int]], source_max: Dict[int, int]) -> List[float]:
    """
    Returns a list of unweighted normalized rank values: norm_rank = 1 - (rank / max_rank_for_source).
    Range: 0.0 (worst) to ~1.0 (best). Sources with max_rank <= 1 are excluded.
    Used for dispersion calculation (dispersion measures disagreement, not quality).
    """
    vals = []
    for sid, rk in ranks:
        mx = max(1, int(source_max.get(sid, 0) or 0))
        if mx <= 1:
            continue
        vals.append(1.0 - (rk / mx))
    return vals


def base_score_0_100(norm_vals: List[float]) -> float:
    """
    Unweighted base = avg(norm_rank) * 100.
    Retained for auditability display alongside weighted_base.
    """
    if not norm_vals:
        return 0.0
    return 100.0 * (sum(norm_vals) / len(norm_vals))


def weighted_base_score_0_100(
    ranks: List[Tuple[int, int]],
    source_max: Dict[int, int],
    source_id_to_name: Dict[int, str],
) -> float:
    """
    Weighted base = sum(norm_rank * weight) / sum(weights) * 100.
    Weights come from SOURCE_WEIGHTS keyed by source_name; falls back to DEFAULT_WEIGHT.
    Sources with max_rank <= 1 are excluded (consistent with normalized_ranks).
    """
    total_weighted = 0.0
    total_weight = 0.0
    for sid, rk in ranks:
        mx = max(1, int(source_max.get(sid, 0) or 0))
        if mx <= 1:
            continue
        norm_val = 1.0 - (rk / mx)
        sname = source_id_to_name.get(sid, "")
        w = SOURCE_WEIGHTS.get(sname, DEFAULT_WEIGHT)
        total_weighted += norm_val * w
        total_weight += w
    if total_weight == 0.0:
        return 0.0
    return 100.0 * (total_weighted / total_weight)


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


def calc_dispersion(norm_vals: List[float]) -> Tuple[float, float]:
    """
    Returns (rank_std_dev, dispersion_penalty).

    rank_std_dev: population std dev of UNWEIGHTED normalized rank values.
    Dispersion measures disagreement between sources, not source quality.
    dispersion_penalty: min(std_dev * DISPERSION_WEIGHT, MAX_PENALTY).
    Penalty is 0.0 when fewer than MIN_SOURCES_FOR_DISPERSION sources cover the prospect.
    """
    if len(norm_vals) < MIN_SOURCES_FOR_DISPERSION:
        return 0.0, 0.0
    std_dev = pstdev(norm_vals)
    penalty = min(std_dev * DISPERSION_WEIGHT, MAX_PENALTY)
    return round(std_dev, 6), round(penalty, 6)


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

    # "Top-10 density" across sources: how many sources rank him in top 10?
    top10 = sum(1 for _, rk in ranks if rk <= 10)
    if top10 >= max(2, math.ceil(0.33 * k)):
        chips.append(f"{top10} sources top-10")
    else:
        # fallback: highlight "high placement" if median is strong
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
                    weighted_base_score=?,
                    sources_covered=?,
                    avg_rank=?,
                    median_rank=?,
                    min_rank=?,
                    max_rank=?,
                    tier=?,
                    reason_chips_json=?,
                    explain_json=?,
                    rank_std_dev=?,
                    dispersion_penalty=?,
                    is_active=1,
                    updated_at=?
                WHERE season_id=? AND prospect_id=?
                """,
                (
                    row["consensus_rank"],
                    row["score"],
                    row["weighted_base_score"],
                    row["sources_covered"],
                    row["avg_rank"],
                    row["median_rank"],
                    row["min_rank"],
                    row["max_rank"],
                    row["tier"],
                    row["reason_chips_json"],
                    row["explain_json"],
                    row["rank_std_dev"],
                    row["dispersion_penalty"],
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
                  consensus_rank, score, weighted_base_score,
                  sources_covered, avg_rank, median_rank, min_rank, max_rank,
                  tier, reason_chips_json,
                  explain_json,
                  rank_std_dev, dispersion_penalty,
                  is_active,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season_id,
                    row["prospect_id"],
                    row["consensus_rank"],
                    row["score"],
                    row["weighted_base_score"],
                    row["sources_covered"],
                    row["avg_rank"],
                    row["median_rank"],
                    row["min_rank"],
                    row["max_rank"],
                    row["tier"],
                    row["reason_chips_json"],
                    row["explain_json"],
                    row["rank_std_dev"],
                    row["dispersion_penalty"],
                    1,
                    now,
                    now,
                ),
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-year", type=int, default=2026)
    ap.add_argument("--season", type=int, default=None, help="Draft year alias (same as --draft-year)")
    ap.add_argument("--apply", type=int, default=0)
    args = ap.parse_args()

    draft_year = args.season if args.season is not None else args.draft_year

    if args.apply == 1:
        b = backup_db(f"build_consensus_{draft_year}")
        print(f"DB BACKUP: {b}")
    else:
        print("DRY RUN: no DB writes, no backup")

    print(f"CONFIG: DISPERSION_WEIGHT={DISPERSION_WEIGHT}  MAX_PENALTY={MAX_PENALTY}  MIN_SOURCES={MIN_SOURCES_FOR_DISPERSION}")

    with connect() as conn:
        season_id = get_season_id(conn, draft_year)
        srcs = active_sources(conn)
        src_ids = [s["source_id"] for s in srcs]
        n_active = len(src_ids)

        # Build source_id -> source_name for weight lookups
        source_id_to_name: Dict[int, str] = {s["source_id"]: s["source_name"] for s in srcs}

        # Log weight assignments for active sources
        print("\nSOURCE WEIGHTS (active sources):")
        for s in srcs:
            w = SOURCE_WEIGHTS.get(s["source_name"], DEFAULT_WEIGHT)
            tier = "T1" if w > 1.0 else ("T3" if w < 1.0 else "T2")
            print(f"  {s['source_name']:<30} weight={w}  ({tier})")

        source_max = {sid: per_source_max_rank(conn, season_id, sid) for sid in src_ids}

        # Fetch ranks for active prospects only (is_active=1 filter applied in fetch_prospect_ranks)
        prospect_ranks = fetch_prospect_ranks(conn, season_id)

        # Fetch prospect metadata — active prospects only for display and universe tracking
        use_pro_active = prospects_has_is_active(conn)
        meta_sql = (
            "SELECT prospect_id, display_name, position_raw FROM prospects WHERE season_id = ? AND is_active = 1"
            if use_pro_active
            else "SELECT prospect_id, display_name, position_raw FROM prospects WHERE season_id = ?"
        )
        prospect_meta: Dict[int, Dict] = {}
        meta_rows = conn.execute(meta_sql, (season_id,)).fetchall()
        for m in meta_rows:
            prospect_meta[int(m["prospect_id"])] = {
                "name": m["display_name"] or m["prospect_id"],
                "position": m["position_raw"] or "",
            }

        computed = []
        for prospect_id, ranks in prospect_ranks.items():
            ranks_sorted = sorted(ranks, key=lambda x: x[0])
            rvals = [rk for _, rk in ranks_sorted]
            k = len(rvals)

            # Unweighted norm_vals used for dispersion (measures disagreement, not quality)
            norm_vals = normalized_ranks(ranks_sorted, source_max)
            unweighted_base = base_score_0_100(norm_vals)

            # Weighted base uses source quality weights
            w_base = weighted_base_score_0_100(ranks_sorted, source_max, source_id_to_name)

            cov = coverage_factor(k, n_active)
            std_dev, disp_penalty = calc_dispersion(norm_vals)

            # score = weighted_base × coverage × (1 − dispersion_penalty)
            score = round(w_base * cov * (1.0 - disp_penalty), 4)

            avg_rk = round(sum(rvals) / k, 4) if k else None
            med_rk = float(median(rvals)) if k else None

            chips = compute_reason_chips(ranks=ranks_sorted, n_active=n_active, source_max=source_max)
            tier = tier_from_score(score)

            explain = {
                "sources": [{"source_id": sid, "rank": rk} for sid, rk in ranks_sorted],
                "active_sources": n_active,
                "source_max_rank": {str(k_): int(v) for k_, v in source_max.items()},
                "scoring": {
                    "unweighted_base": "avg(1 - rank/max_rank_by_source) * 100",
                    "weighted_base": "sum((1-rank/max)*weight) / sum(weights) * 100",
                    "coverage": "sqrt(sources_covered / active_sources)",
                    "dispersion_penalty": f"min(pstdev(unweighted_norm_ranks) * {DISPERSION_WEIGHT}, {MAX_PENALTY})",
                    "final": "weighted_base * coverage * (1 - dispersion_penalty)",
                },
                "unweighted_base": round(unweighted_base, 4),
                "weighted_base": round(w_base, 4),
                "rank_std_dev": std_dev,
                "dispersion_penalty": disp_penalty,
                "tier": tier,
                "reason_chips": chips,
            }

            computed.append(
                {
                    "prospect_id": int(prospect_id),
                    "score": float(score),
                    "weighted_base_score": round(float(w_base), 4),
                    "sources_covered": int(k),
                    "avg_rank": avg_rk,
                    "median_rank": med_rk,
                    "min_rank": int(min(rvals)) if k else None,
                    "max_rank": int(max(rvals)) if k else None,
                    "tier": tier,
                    "reason_chips_json": json.dumps(chips, ensure_ascii=False),
                    "explain_json": json.dumps(explain, ensure_ascii=False),
                    "rank_std_dev": float(std_dev),
                    "dispersion_penalty": float(disp_penalty),
                    # Display-only fields (not stored in DB separately)
                    "_unweighted_base": round(unweighted_base, 4),
                }
            )

        computed.sort(
            key=lambda r: (-r["score"], (r["avg_rank"] or 10**9), -r["sources_covered"], r["prospect_id"])
        )

        for i, row in enumerate(computed, start=1):
            row["consensus_rank"] = i

        print(f"\nPLAN: would write consensus rows: {len(computed)} (active sources: {n_active})")
        print(f"\n{'Rank':<5} {'Name':<28} {'Pos':<6} {'Unwt Base':>10} {'Wt Base':>8} {'StdDev':>8} {'Penalty':>9} {'Score':>8}")
        print("-" * 90)
        for row in computed[:20]:
            pid = row["prospect_id"]
            meta = prospect_meta.get(pid, {"name": f"id:{pid}", "position": "?"})
            print(
                f"{row['consensus_rank']:<5} {meta['name']:<28} {meta['position']:<6} "
                f"{row['_unweighted_base']:>10.2f} {row['weighted_base_score']:>8.2f} "
                f"{row['rank_std_dev']:>8.4f} {row['dispersion_penalty']:>9.4f} "
                f"{row['score']:>8.4f}"
            )

        # High-dispersion flags (penalty > 0.15) in top 100
        flagged = [r for r in computed[:100] if r["dispersion_penalty"] > 0.15]
        if flagged:
            print(f"\nHIGH-DISAGREEMENT flags (penalty > 0.15) in top 100: {len(flagged)}")
            for r in flagged:
                pid = r["prospect_id"]
                meta = prospect_meta.get(pid, {"name": f"id:{pid}", "position": "?"})
                print(
                    f"  #{r['consensus_rank']} {meta['name']} ({meta['position']})  "
                    f"std_dev={r['rank_std_dev']:.4f}  penalty={r['dispersion_penalty']:.4f}  score={r['score']:.4f}"
                )

        if args.apply != 1:
            print("\nDRY RUN complete. Rerun with --apply 1 to write.")
            return

        # ── Cleanup: full replace of consensus for this season ────────────────
        # Consensus is a derived table. Delete all existing rows for this season
        # and reinsert only the current computed set. This guarantees the table
        # count exactly equals len(computed) and eliminates stale rows for both
        # inactive prospects and active-but-unranked prospects.
        deleted_total = conn.execute(
            "DELETE FROM prospect_consensus_rankings WHERE season_id = ?",
            (season_id,),
        ).rowcount
        print(f"Deleted {deleted_total} old consensus rows (full replace).")

        upsert_consensus_rows(conn, season_id, computed)
        conn.commit()
        print(f"\nOK: wrote consensus rows: {len(computed)}")


if __name__ == "__main__":
    main()
