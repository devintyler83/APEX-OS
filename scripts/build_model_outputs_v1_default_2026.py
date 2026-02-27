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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    r = conn.execute("SELECT season_id FROM seasons WHERE draft_year = ?", (draft_year,)).fetchone()
    if not r:
        raise SystemExit(f"FAIL: season {draft_year} not found.")
    return int(r["season_id"])


def get_model_id(conn, season_id: int, model_ref: str) -> int:
    """
    Resolve model by model_key first (canonical), then by model_name as fallback.
    """
    r = conn.execute(
        "SELECT model_id FROM models WHERE season_id=? AND model_key=?",
        (season_id, model_ref),
    ).fetchone()
    if r:
        return int(r["model_id"])

    r = conn.execute(
        "SELECT model_id FROM models WHERE season_id=? AND model_name=?",
        (season_id, model_ref),
    ).fetchone()
    if r:
        return int(r["model_id"])

    # Helpful debug output for immediate grounding
    rows = conn.execute(
        "SELECT model_id, model_key, model_name FROM models WHERE season_id=? ORDER BY model_id",
        (season_id,),
    ).fetchall()
    available = [dict(x) for x in rows]
    raise SystemExit(
        f"FAIL: model not found for season_id={season_id}: {model_ref}. "
        f"Available models: {available}"
    )


def fetch_consensus(conn, season_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          c.prospect_id,
          c.score,
          c.tier,
          c.reason_chips_json,
          c.explain_json,
          c.consensus_rank,
          c.sources_covered,
          c.avg_rank,
          c.median_rank,
          c.min_rank,
          c.max_rank
        FROM prospect_consensus_rankings c
        WHERE c.season_id = ?
        ORDER BY c.consensus_rank
        """,
        (season_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_output(
    conn,
    *,
    season_id: int,
    model_id: int,
    row: Dict[str, Any],
) -> None:
    now = utcnow_iso()
    existing = conn.execute(
        """
        SELECT output_id
        FROM prospect_model_outputs
        WHERE season_id=? AND model_id=? AND prospect_id=?
        """,
        (season_id, model_id, row["prospect_id"]),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE prospect_model_outputs
            SET score=?,
                tier=?,
                reason_chips_json=?,
                explain_json=?,
                updated_at=?
            WHERE season_id=? AND model_id=? AND prospect_id=?
            """,
            (
                row["score"],
                row.get("tier"),
                row.get("reason_chips_json"),
                row.get("explain_json"),
                now,
                season_id,
                model_id,
                row["prospect_id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO prospect_model_outputs(
              season_id, model_id, prospect_id,
              score, tier, reason_chips_json, explain_json,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                season_id,
                model_id,
                row["prospect_id"],
                row["score"],
                row.get("tier"),
                row.get("reason_chips_json"),
                row.get("explain_json"),
                now,
                now,
            ),
        )


def build_explain_payload(cons: Dict[str, Any], model_ref: str) -> str:
    """
    Deterministic explain payload for v1_default.
    We repackage consensus explain + add model metadata.
    """
    base = {}
    try:
        if isinstance(cons.get("explain_json"), str) and cons["explain_json"]:
            base = json.loads(cons["explain_json"])
    except Exception:
        base = {}

    try:
        chips = json.loads(cons.get("reason_chips_json") or "[]")
        if not isinstance(chips, list):
            chips = []
    except Exception:
        chips = []

    payload = {
        "model_ref": model_ref,  # may be model_key or model_name input
        "version": "v1",
        "inputs": {
            "consensus_rank": cons.get("consensus_rank"),
            "sources_covered": cons.get("sources_covered"),
            "avg_rank": cons.get("avg_rank"),
            "median_rank": cons.get("median_rank"),
            "min_rank": cons.get("min_rank"),
            "max_rank": cons.get("max_rank"),
        },
        "consensus_explain": base,
        "outputs": {
            "score": cons.get("score"),
            "tier": cons.get("tier"),
            "reason_chips": chips,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-year", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default", help="Model key (preferred) or model name")
    ap.add_argument("--apply", type=int, default=0)
    args = ap.parse_args()

    if args.apply == 1:
        b = backup_db(f"build_model_outputs_{args.model}_{args.draft_year}")
        print(f"DB BACKUP: {b}")
    else:
        print("DRY RUN: no DB writes, no backup")

    with connect() as conn:
        season_id = get_season_id(conn, args.draft_year)
        model_id = get_model_id(conn, season_id, args.model)

        cons_rows = fetch_consensus(conn, season_id)
        print(f"PLAN: would write model outputs: {len(cons_rows)} rows for model_ref={args.model} (model_id={model_id})")

        if args.apply != 1:
            for r in cons_rows[:10]:
                print(f"TOP: prospect_id={r['prospect_id']} score={r['score']} tier={r.get('tier')}")
            return

        for r in cons_rows:
            explain = build_explain_payload(r, args.model)
            out_row = {
                "prospect_id": r["prospect_id"],
                "score": float(r["score"]),
                "tier": r.get("tier"),
                "reason_chips_json": r.get("reason_chips_json") or "[]",
                "explain_json": explain,
            }
            upsert_output(conn, season_id=season_id, model_id=model_id, row=out_row)

        conn.commit()
        print(f"OK: wrote model outputs: {len(cons_rows)} rows for model_ref={args.model} (model_id={model_id})")


if __name__ == "__main__":
    main()