from __future__ import annotations

import argparse
import json
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
    backup_path = backups_dir / f"{db_path.stem}.pre_mapping_review_queue.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone() is not None


def resolve_season_id(conn, draft_year: int) -> int:
    row = conn.execute("SELECT season_id FROM seasons WHERE draft_year=?;", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found: {draft_year}")
    return int(row["season_id"])


def load_prospect_canonical_map(conn, season_id: int) -> Dict[int, int]:
    if not table_exists(conn, "prospect_canonical_map"):
        return {}
    rows = conn.execute(
        "SELECT prospect_id, canonical_prospect_id FROM prospect_canonical_map WHERE season_id=?;",
        (season_id,),
    ).fetchall()
    return {int(r["prospect_id"]): int(r["canonical_prospect_id"]) for r in rows}


def to_canon(pid: int, pcm: Dict[int, int]) -> int:
    return pcm.get(pid, pid)


def norm_pos_hint(pos_hint: str) -> str:
    p = (pos_hint or "").strip().upper()
    if not p:
        return ""

    if p in ("K", "PK", "P", "LS"):
        return "ST"

    if p in ("SAF", "FS", "SS"):
        return "S"
    if p in ("DT", "NT", "IDL", "DI"):
        return "DL"
    if p in ("DE", "ED", "OLB", "EDGE"):
        return "EDGE"
    if p in ("ILB", "MLB"):
        return "LB"
    if p in ("OT", "OG", "C", "IOL"):
        return "OL"

    if p in ("QB", "RB", "WR", "TE", "OL", "DL", "EDGE", "LB", "CB", "S", "ST"):
        return p

    return ""


def build_candidates(
    conn,
    season_id: int,
    name_key: str,
    pcm: Dict[int, int],
) -> List[Dict[str, Any]]:
    """
    Return canonicalized candidates enriched with metadata needed for deterministic resolution.
    """
    rows = conn.execute(
        """
        SELECT
          p.prospect_id,
          p.display_name,
          p.position_group,
          p.school_canonical
        FROM prospects p
        WHERE p.season_id = ?
          AND p.name_key = ?
        ORDER BY p.prospect_id ASC;
        """,
        (season_id, name_key),
    ).fetchall()

    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for r in rows:
        pid_raw = int(r["prospect_id"])
        pid = to_canon(pid_raw, pcm)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(
            {
                "prospect_id": pid,
                "display_name": (r["display_name"] or "").strip(),
                "position_group": (r["position_group"] or "").strip().upper(),
                "school_canonical": (r["school_canonical"] or "").strip(),
            }
        )
    return out


def recommend(cands: List[Dict[str, Any]], school: str, posg: str) -> Optional[int]:
    """
    Deterministic recommendation for UI / triage, does NOT resolve status.
    Priority:
      1) school+pos unique
      2) pos unique
      3) school unique
      else None
    """
    if not cands:
        return None

    if school and posg:
        hits = [int(c["prospect_id"]) for c in cands if c.get("school_canonical") == school and c.get("position_group") == posg]
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            return hits[0]

    if posg:
        hits = [int(c["prospect_id"]) for c in cands if c.get("position_group") == posg]
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            return hits[0]

    if school:
        hits = [int(c["prospect_id"]) for c in cands if c.get("school_canonical") == school]
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            return hits[0]

    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/refresh mapping review queue (open rows only).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        for t in ("source_player_review_queue", "source_players", "source_player_map", "prospects", "seasons"):
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        pcm = load_prospect_canonical_map(conn, season_id)

        # Unmapped source_players are what we queue
        unmapped = conn.execute(
            """
            SELECT sp.source_player_id, sp.name_key, sp.pos_hint, sp.school_canonical, sp.raw_full_name
            FROM source_players sp
            LEFT JOIN source_player_map m ON m.source_player_id = sp.source_player_id
            WHERE sp.season_id = ?
              AND m.source_player_id IS NULL
              AND sp.name_key IS NOT NULL
              AND TRIM(sp.name_key) <> '';
            """,
            (season_id,),
        ).fetchall()

        # Also detect stale open rows that are already mapped (should be auto-closed)
        open_but_mapped = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM source_player_review_queue q
            JOIN source_player_map m ON m.source_player_id = q.source_player_id
            WHERE q.season_id = ?
              AND q.status = 'open';
            """,
            (season_id,),
        ).fetchone()
        open_but_mapped_n = int(open_but_mapped["n"]) if open_but_mapped else 0

        plan: List[Tuple[int, str, str, str, str, Optional[int]]] = []
        example: Optional[Dict[str, Any]] = None

        for r in unmapped:
            spid = int(r["source_player_id"])
            nk = (r["name_key"] or "").strip()
            raw_name = (r["raw_full_name"] or "").strip()
            school = (r["school_canonical"] or "").strip()
            posg = norm_pos_hint(r["pos_hint"] or "")

            cands = build_candidates(conn, season_id, nk, pcm)
            rec = recommend(cands, school, posg)

            if len(cands) == 0:
                reason = "no_candidates_for_name_key"
            elif len(cands) == 1:
                # We still queue it as open with a recommendation, NOT auto-resolve here.
                reason = "single_candidate"
            else:
                reason = f"ambiguous_name_key_{len(cands)}"

            cand_json = json.dumps(cands, ensure_ascii=False)
            plan.append((spid, nk, posg, reason, cand_json, rec))

            if example is None:
                example = {
                    "source_player_id": spid,
                    "raw_full_name": raw_name,
                    "name_key": nk,
                    "pos_group_norm": posg,
                    "reason": reason,
                    "cands": len(cands),
                    "recommended_prospect_id": rec,
                }

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"QUEUE_ROWS_UPSERT: {len(plan)}")
        if example:
            print(
                "EXAMPLE:",
                f"source_player_id={example['source_player_id']}",
                f"name_key={example['name_key']}",
                f"pos={example['pos_group_norm'] or '<blank>'}",
                f"reason={example['reason']}",
                f"cands={example['cands']}",
                f"recommended={example['recommended_prospect_id'] or ''}",
            )
        print(f"OPEN_BUT_ALREADY_MAPPED: {open_but_mapped_n}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    now = utc_now_iso()
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)

        # Auto-close stale open rows that are already mapped
        conn.execute(
            """
            UPDATE source_player_review_queue
            SET status='resolved',
                resolved_by='auto_close_mapped',
                resolved_at_utc=?,
                updated_at_utc=?
            WHERE season_id=?
              AND status='open'
              AND source_player_id IN (SELECT source_player_id FROM source_player_map);
            """,
            (now, now, season_id),
        )

        n_upsert = 0
        for spid, nk, posg, reason, cand_json, rec in plan:
            # Upsert only if row is absent or still open.
            conn.execute(
                """
                INSERT INTO source_player_review_queue(
                  season_id, source_player_id, name_key, pos_hint, reason, candidate_json,
                  recommended_prospect_id,
                  status,
                  created_at_utc, updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(season_id, source_player_id)
                DO UPDATE SET
                  name_key = excluded.name_key,
                  pos_hint = excluded.pos_hint,
                  reason = excluded.reason,
                  candidate_json = excluded.candidate_json,
                  recommended_prospect_id = excluded.recommended_prospect_id,
                  updated_at_utc = excluded.updated_at_utc
                WHERE source_player_review_queue.status = 'open';
                """,
                (season_id, spid, nk, posg, reason, cand_json, rec, now, now),
            )
            n_upsert += 1

        conn.commit()

    print("OK: review queue built/refreshed (open rows only) + stale open rows auto-closed.")


if __name__ == "__main__":
    main()