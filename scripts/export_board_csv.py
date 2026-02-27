from __future__ import annotations

# --- sys.path bootstrap ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from draftos.db.connect import connect
from draftos.queries import get_model_board


def utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def get_season_id(conn, draft_year: int) -> int:
    r = conn.execute("SELECT season_id FROM seasons WHERE draft_year=?", (draft_year,)).fetchone()
    if not r:
        raise SystemExit(f"FAIL: season {draft_year} not found.")
    return int(r["season_id"])


def fetch_sources_covered_map(conn, season_id: int) -> Dict[int, int]:
    rows = conn.execute(
        "SELECT prospect_id, sources_covered FROM prospect_consensus_rankings WHERE season_id=?",
        (season_id,),
    ).fetchall()
    return {int(r["prospect_id"]): int(r["sources_covered"]) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-year", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default", help="model_key or model_name")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--min-sources", type=int, default=1)
    ap.add_argument("--tier", type=str, default="", help="Elite|Strong|Playable|Watch (optional)")
    ap.add_argument("--position-group", type=str, default="", help="QB|RB|WR|TE|OL|DL|LB|DB|ST (optional)")
    args = ap.parse_args()

    out_dir = ROOT / "data" / "exports" / "boards"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = utcstamp()
    name_parts = [f"{args.draft_year}", args.model, "board", ts]
    out_path = out_dir / ("_".join([p for p in name_parts if p]) + ".csv")

    with connect() as conn:
        season_id = get_season_id(conn, args.draft_year)
        sources_map = fetch_sources_covered_map(conn, season_id)

        rows = get_model_board(season_id, args.model, limit=args.limit, offset=0)

        # filters
        tier_filter = args.tier.strip()
        pg_filter = args.position_group.strip().upper()

        filtered: List[Dict[str, Any]] = []
        for r in rows:
            pid = int(r["prospect_id"])
            sources_covered = int(sources_map.get(pid, 0))
            if sources_covered < int(args.min_sources):
                continue
            if tier_filter and str(r.get("tier") or "") != tier_filter:
                continue
            if pg_filter and str(r.get("position_group") or "").upper() != pg_filter:
                continue

            r2 = dict(r)
            r2["sources_covered"] = sources_covered
            filtered.append(r2)

        fieldnames = [
            "score",
            "tier",
            "sources_covered",
            "display_name",
            "full_name",
            "school_canonical",
            "position_group",
            "prospect_key",
            "prospect_id",
            "reason_chips",
        ]

        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in filtered:
                w.writerow(
                    {
                        "score": r.get("score"),
                        "tier": r.get("tier"),
                        "sources_covered": r.get("sources_covered"),
                        "display_name": r.get("display_name"),
                        "full_name": r.get("full_name"),
                        "school_canonical": r.get("school_canonical"),
                        "position_group": r.get("position_group"),
                        "prospect_key": r.get("prospect_key"),
                        "prospect_id": r.get("prospect_id"),
                        "reason_chips": "; ".join(r.get("reason_chips") or []),
                    }
                )

    print(f"OK: wrote {len(filtered)} rows -> {out_path}")


if __name__ == "__main__":
    main()