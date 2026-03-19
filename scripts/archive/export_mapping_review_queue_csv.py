from __future__ import annotations

import argparse
import csv
from pathlib import Path

from draftos.db.connect import connect


def main() -> None:
    ap = argparse.ArgumentParser(description="Export mapping review queue to CSV.")
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    out_dir = Path("exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"mapping_review_queue_{args.season}.csv"

    with connect() as conn:
        row = conn.execute("SELECT season_id FROM seasons WHERE draft_year=?;", (args.season,)).fetchone()
        if not row:
            raise SystemExit(f"FAIL: season not found: {args.season}")
        season_id = int(row["season_id"])

        rows = conn.execute(
            """
            SELECT
              q.source_player_id,
              sp.raw_full_name,
              sp.raw_school,
              sp.school_canonical,
              q.pos_hint,
              q.name_key,
              q.reason,
              q.status,
              q.resolved_prospect_id,
              q.candidate_json
            FROM source_player_review_queue q
            JOIN source_players sp ON sp.source_player_id = q.source_player_id
            WHERE q.season_id = ?
            ORDER BY q.status ASC, q.reason ASC, q.source_player_id ASC;
            """,
            (season_id,),
        ).fetchall()

    header = [
        "source_player_id",
        "raw_full_name",
        "raw_school",
        "school_canonical",
        "pos_hint",
        "name_key",
        "reason",
        "status",
        "resolved_prospect_id",
        "candidate_json",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            d = dict(r)
            w.writerow({k: d.get(k, "") for k in header})

    print(f"OK: exported: {out_path}")


if __name__ == "__main__":
    main()