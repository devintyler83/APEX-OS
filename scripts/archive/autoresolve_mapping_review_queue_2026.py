# scripts/autoresolve_mapping_review_queue_2026.py
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.positions import normalize_position


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_autoresolve_review_queue.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone() is not None


def table_cols(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def resolve_season_id(conn, draft_year: int) -> int:
    cols = table_cols(conn, "seasons")
    id_col = "season_id" if "season_id" in cols else "id"
    year_col = "draft_year" if "draft_year" in cols else "year"
    row = conn.execute(f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col}=?;", (draft_year,)).fetchone()
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


def pick_unique(candidates: List[Dict[str, Any]], pred) -> Optional[int]:
    hits: List[int] = []
    for c in candidates:
        try:
            if pred(c):
                hits.append(int(c["prospect_id"]))
        except Exception:
            continue
    # de-dupe preserve order
    hits = list(dict.fromkeys(hits))
    return hits[0] if len(hits) == 1 else None


def dominant_value(candidates: List[Dict[str, Any]], field: str) -> Optional[str]:
    """
    If candidates overwhelmingly share the same non-empty field value, return it.
    This is used to resolve when the queue row is missing school_canonical,
    but the candidate set is essentially single-school already.
    """
    vals = []
    for c in candidates:
        v = (c.get(field) or "").strip()
        if v:
            vals.append(v)
    if not vals:
        return None
    ctr = Counter(vals)
    # dominant means strictly > 50% and unique top
    top_val, top_n = sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if top_n <= (len(vals) // 2):
        return None
    # ensure uniqueness of dominance (no tie)
    ties = [v for v, n in ctr.items() if n == top_n]
    if len(ties) != 1:
        return None
    return top_val


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-resolve mapping review queue deterministically (bulk).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    ap.add_argument("--by", type=str, default="autoresolve_v2")
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        for t in ("source_player_review_queue", "source_players", "seasons"):
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        pcm = load_prospect_canonical_map(conn, season_id)

        q_rows = conn.execute(
            """
            SELECT
              q.source_player_id,
              q.candidate_json,
              q.reason,
              q.status,
              sp.school_canonical,
              sp.pos_hint,
              sp.raw_position
            FROM source_player_review_queue q
            JOIN source_players sp ON sp.source_player_id = q.source_player_id
            WHERE q.season_id = ?
              AND q.status = 'open';
            """,
            (season_id,),
        ).fetchall()

        resolved: List[Tuple[int, int, str]] = []  # (source_player_id, resolved_canon_pid, rule)
        rule_counts: Dict[str, int] = defaultdict(int)

        for r in q_rows:
            spid = int(r["source_player_id"])
            reason = (r["reason"] or "").strip()
            school = (r["school_canonical"] or "").strip()

            pos_input = (r["pos_hint"] or "").strip() or (r["raw_position"] or "").strip()
            posg = normalize_position(pos_input).group if pos_input else ""

            try:
                candidates = json.loads(r["candidate_json"] or "[]")
            except Exception:
                continue
            if not isinstance(candidates, list) or not candidates:
                continue

            # Canonicalize candidate prospect_ids for selection
            for c in candidates:
                if isinstance(c, dict) and "prospect_id" in c:
                    c["prospect_id"] = to_canon(int(c["prospect_id"]), pcm)

            # We operate only on ambiguous buckets (keep deterministic + conservative)
            if not reason.startswith("ambiguous_name_key_"):
                continue

            # Rule 1: school + pos unique
            if school and posg:
                pid = pick_unique(
                    candidates,
                    lambda c: (c.get("school_canonical") == school) and (c.get("position_group") == posg),
                )
                if pid is not None:
                    resolved.append((spid, pid, "rule_school_and_pos_unique"))
                    rule_counts["rule_school_and_pos_unique"] += 1
                    continue

            # Rule 2: school unique
            if school:
                pid = pick_unique(candidates, lambda c: (c.get("school_canonical") == school))
                if pid is not None:
                    resolved.append((spid, pid, "rule_school_unique"))
                    rule_counts["rule_school_unique"] += 1
                    continue

            # Rule 3: pos unique (only if school blank)
            if (not school) and posg:
                pid = pick_unique(candidates, lambda c: (c.get("position_group") == posg))
                if pid is not None:
                    resolved.append((spid, pid, "rule_pos_unique"))
                    rule_counts["rule_pos_unique"] += 1
                    continue

            # Rule 4: dominant school in candidates (even if sp.school_canonical blank)
            dom_school = dominant_value(candidates, "school_canonical")
            if dom_school:
                if posg:
                    pid = pick_unique(
                        candidates,
                        lambda c: (c.get("school_canonical") == dom_school) and (c.get("position_group") == posg),
                    )
                    if pid is not None:
                        resolved.append((spid, pid, "rule_dominant_school_and_pos_unique"))
                        rule_counts["rule_dominant_school_and_pos_unique"] += 1
                        continue

                pid = pick_unique(candidates, lambda c: (c.get("school_canonical") == dom_school))
                if pid is not None:
                    resolved.append((spid, pid, "rule_dominant_school_unique"))
                    rule_counts["rule_dominant_school_unique"] += 1
                    continue

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"OPEN_QUEUE_ROWS: {len(q_rows)}")
        print(f"AUTORESOLVE_ROWS: {len(resolved)}")
        print(f"RULE_COUNTS: {json.dumps(dict(rule_counts), sort_keys=True)}")
        if resolved:
            print(f"EXAMPLE: source_player_id={resolved[0][0]} -> prospect_id={resolved[0][1]} ({resolved[0][2]})")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            return

        if not resolved:
            print("OK: nothing to resolve.")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    now = utc_now_iso()
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)

        for spid, pid, rule in resolved:
            conn.execute(
                """
                UPDATE source_player_review_queue
                SET status='resolved',
                    resolved_prospect_id=?,
                    resolved_by=?,
                    resolved_at_utc=?,
                    updated_at_utc=?
                WHERE season_id=?
                  AND source_player_id=?
                  AND status='open';
                """,
                (pid, args.by, now, now, season_id, spid),
            )

        conn.commit()

    print("OK: autoresolve applied (open rows only).")


if __name__ == "__main__":
    main()