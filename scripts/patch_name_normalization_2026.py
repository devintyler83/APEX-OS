from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.normalize.names import name_norm_and_key
from draftos.normalize.schools import school_key

# Captures a leading token like: "S A.J. Haulcy", "DE/ED Rueben Bain Jr.", "OG Ar'maj Reed-Adams"
# group(1) = token, group(2) = remainder
_POS_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{1,4}(?:/[A-Za-z]{1,4})?)\b[ .]+(.+?)\s*$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_backup(db_path: Path) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{db_path.stem}.pre_name_normalization.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone()
    return row is not None


def colnames(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()]


def pick_first(cols: Set[str], *cands: str) -> Optional[str]:
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
    row = conn.execute(f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col}=?;", (draft_year,)).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found for draft_year={draft_year}")
    return int(row["season_id"])


def load_name_alias_token_map(conn) -> Dict[str, str]:
    if not table_exists(conn, "name_aliases"):
        return {}
    rows = conn.execute("SELECT name_alias, name_canonical FROM name_aliases;").fetchall()
    out: Dict[str, str] = {}
    for r in rows:
        _a_norm, a_key = name_norm_and_key(r["name_alias"] or "", {})
        c_norm, _c_key = name_norm_and_key(r["name_canonical"] or "", {})
        if a_key and c_norm:
            out[a_key] = c_norm
    return out


def load_school_alias_map(conn) -> Dict[str, str]:
    if not table_exists(conn, "school_aliases"):
        return {}
    # NOTE: your schema uses (school_alias, school_canonical)
    rows = conn.execute("SELECT school_alias, school_canonical FROM school_aliases;").fetchall()
    out: Dict[str, str] = {}
    for r in rows:
        alias_raw = r["school_alias"] or ""
        k = school_key(alias_raw)
        canon = (r["school_canonical"] or "").strip()
        if not k or not canon:
            continue
        if k in out:
            # On key collision, prefer the plain (non-parenthetical) alias.
            # e.g. 'Miami' beats 'Miami (OH)' for key 'miami' because the plain
            # form is more general and avoids false canonicalization of raw
            # school values like 'Miami' to 'Miami OH'.
            incoming_has_paren = "(" in alias_raw
            if incoming_has_paren:
                continue  # do not overwrite a plain alias with a parenthetical one
        out[k] = canon
    return out


def build_canonical_school_by_key_from_prospects(conn, season_id: int) -> Dict[str, str]:
    rows = conn.execute("SELECT DISTINCT school_canonical FROM prospects WHERE season_id=?;", (season_id,)).fetchall()
    tmp: Dict[str, Set[str]] = {}
    for r in rows:
        canon = (r["school_canonical"] or "").strip()
        k = school_key(canon)
        if canon and k:
            tmp.setdefault(k, set()).add(canon)

    out: Dict[str, str] = {}
    for k, vals in tmp.items():
        if len(vals) == 1:
            out[k] = next(iter(vals))
    return out


def extract_school_from_raw_json(raw_json: str | None) -> str:
    if not raw_json:
        return ""
    try:
        obj = json.loads(raw_json)
    except Exception:
        return ""
    if not isinstance(obj, dict):
        return ""

    keys = (
        "school",
        "school_name",
        "college",
        "college_name",
        "collegeSchool",
        "team",
        "team_name",
        "university",
        "schoolDisplay",
    )
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    meta = obj.get("meta")
    if isinstance(meta, dict):
        for k in ("school", "college", "college_name", "school_name"):
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return ""


def parse_pos_hint(raw_full_name: str) -> str:
    s = (raw_full_name or "").strip()
    if not s:
        return ""
    m = _POS_PREFIX_RE.match(s)
    if not m:
        return ""
    tok = (m.group(1) or "").strip().upper()
    if not tok or len(tok) > 7:
        return ""
    return tok


def split_pos_parts(pos_hint: str) -> List[str]:
    tok = (pos_hint or "").strip().upper()
    if not tok:
        return []
    if "/" in tok:
        return [p.strip().upper() for p in tok.split("/") if p.strip()]
    return [tok]


def normalize_pos_to_season_value(pos_hint: str, pos_values: Set[str]) -> str:
    """
    Best-effort deterministic conversion:
    1) If any hint part directly matches a season position_group value, return it.
    2) Else apply a small mapping, but only if the target exists in pos_values.
    """
    parts = split_pos_parts(pos_hint)

    # Direct match (best)
    for p in parts:
        if p in pos_values:
            return p

    mapping = {
        "ED": "EDGE",
        "DE": "EDGE",
        "OLB": "EDGE",
        "EDGE": "EDGE",
        "DT": "DL",
        "NT": "DL",
        "DL": "DL",
        "DB": "DB",
        "FS": "S",
        "SS": "S",
    }

    for p in parts:
        tgt = mapping.get(p)
        if tgt and tgt in pos_values:
            return tgt

    return ""


def strip_pos_prefix_from_name(raw_full_name: str, pos_values: Set[str]) -> str:
    """
    Remove leading position labels from raw_full_name before name normalization.

    Conservative rule:
    - Only strip if the leading token is clearly a position indicator:
      - token is in known position tokens, OR
      - token maps to a valid season position_group via normalize_pos_to_season_value, OR
      - slash token where all parts are known position tokens / mappable.
    - Otherwise return original string.
    """
    s = (raw_full_name or "").strip()
    if not s:
        return ""

    m = _POS_PREFIX_RE.match(s)
    if not m:
        return s

    tok = (m.group(1) or "").strip().upper()
    rest = (m.group(2) or "").strip()
    if not tok or not rest:
        return s

    # Base known tokens (do not rely on school or source)
    known: Set[str] = {
        "QB", "RB", "WR", "TE",
        "OL", "OT", "OG", "C", "IOL",
        "DL", "DT", "NT", "DE", "DI", "IDL",
        "EDGE", "ED",
        "LB", "ILB", "MLB", "OLB",
        "CB", "DB",
        "S", "FS", "SS",
        "K", "P", "LS", "ST",
        # sometimes sources include combined groups like "DE/ED" or "DT/NT"
    }

    # Also allow stripping if it directly matches season position groups (taxonomy-aware)
    # Example: if your season pos_values includes "S", "CB", "EDGE", "DL", etc.
    known |= set(pos_values)

    parts = split_pos_parts(tok)
    if not parts:
        return s

    # If every part is known OR mappable to a season position, strip
    ok_parts = True
    for p in parts:
        if p in known:
            continue
        mapped = normalize_pos_to_season_value(p, pos_values)
        if mapped:
            continue
        ok_parts = False
        break

    if not ok_parts:
        return s

    return rest


def load_prospect_canonical_map(conn, season_id: int) -> Dict[int, int]:
    if not table_exists(conn, "prospect_canonical_map"):
        return {}
    rows = conn.execute(
        "SELECT prospect_id, canonical_prospect_id FROM prospect_canonical_map WHERE season_id=?;",
        (season_id,),
    ).fetchall()
    return {int(r["prospect_id"]): int(r["canonical_prospect_id"]) for r in rows}


def canon_pid(pid: int, pcm: Dict[int, int]) -> int:
    return pcm.get(pid, pid)


def dedupe_preserve_order(xs: List[int]) -> List[int]:
    seen: Set[int] = set()
    out: List[int] = []
    for x in xs:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill normalization + conservative auto-mapping (season-scoped).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", type=int, default=0, choices=[0, 1])
    ap.add_argument("--export-diagnostics", type=int, default=1, choices=[0, 1])
    args = ap.parse_args()

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    exports_dir = PATHS.root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    diag_auto = exports_dir / f"mapping_autofix_{args.season}.csv"
    diag_amb = exports_dir / f"mapping_ambiguities_{args.season}.csv"

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")

        for t in ("prospects", "source_players", "source_player_map", "seasons"):
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)

        sp_cols = set(colnames(conn, "source_players"))
        if "raw_json" not in sp_cols:
            raise SystemExit("FAIL: source_players missing raw_json.")
        if "pos_hint" not in sp_cols:
            raise SystemExit("FAIL: source_players missing pos_hint. Run migration 0012_source_players_pos_hint first.")

        alias_token_map = load_name_alias_token_map(conn)
        school_alias_map = load_school_alias_map(conn)
        canon_school_by_key = build_canonical_school_by_key_from_prospects(conn, season_id)
        pcm = load_prospect_canonical_map(conn, season_id)

        # Season position taxonomy (actual stored values)
        pos_values = {
            (r["position_group"] or "").strip().upper()
            for r in conn.execute("SELECT DISTINCT position_group FROM prospects WHERE season_id=?;", (season_id,)).fetchall()
        }
        pos_values.discard("")

        # Prospect indexes (canonicalized)
        prospect_rows = conn.execute(
            "SELECT prospect_id, full_name, school_canonical, position_group FROM prospects WHERE season_id=?;",
            (season_id,),
        ).fetchall()

        p_index_school: Dict[Tuple[str, str], List[int]] = {}
        p_index_name: Dict[str, List[int]] = {}
        p_pos: Dict[int, str] = {}  # canonical_pid -> position_group

        for r in prospect_rows:
            pid_raw = int(r["prospect_id"])
            pid = canon_pid(pid_raw, pcm)
            school = (r["school_canonical"] or "").strip()
            pos = (r["position_group"] or "").strip().upper()
            _n_norm, n_key = name_norm_and_key(r["full_name"] or "", alias_token_map)
            if n_key:
                p_index_name.setdefault(n_key, []).append(pid)
            if school and n_key:
                p_index_school.setdefault((school, n_key), []).append(pid)
            if pos:
                p_pos[pid] = pos

        for k in list(p_index_name.keys()):
            p_index_name[k] = dedupe_preserve_order(p_index_name[k])
        for k in list(p_index_school.keys()):
            p_index_school[k] = dedupe_preserve_order(p_index_school[k])

        unmapped = conn.execute(
            """
            SELECT sp.source_player_id, sp.raw_full_name, sp.raw_school, sp.raw_json
            FROM source_players sp
            LEFT JOIN source_player_map m ON m.source_player_id = sp.source_player_id
            WHERE sp.season_id = ?
              AND m.source_player_id IS NULL;
            """,
            (season_id,),
        ).fetchall()

        plan_inserts: List[Tuple[int, int, str, float]] = []
        ambiguities: List[Tuple[int, str, str, str]] = []

        for r in unmapped:
            spid = int(r["source_player_id"])
            raw_name = (r["raw_full_name"] or "").strip()

            cleaned_name = strip_pos_prefix_from_name(raw_name, pos_values)
            _n_norm, n_key = name_norm_and_key(cleaned_name, alias_token_map)
            if not n_key:
                ambiguities.append((spid, raw_name, "", "no_name_key"))
                continue

            raw_school = (r["raw_school"] or "").strip()
            if not raw_school:
                raw_school = extract_school_from_raw_json(r["raw_json"])

            sk = school_key(raw_school)
            school_canon = ""
            if sk:
                school_canon = school_alias_map.get(sk, "") or canon_school_by_key.get(sk, "")

            # Rule A: school+name unique
            if school_canon:
                cands = p_index_school.get((school_canon, n_key), [])
                if len(cands) == 1:
                    plan_inserts.append((spid, cands[0], f"rule_norm_name_school ({school_canon})", 1.0))
                    continue
                if len(cands) > 1:
                    ambiguities.append((spid, raw_name, raw_school, f"ambiguous_school_name_{len(cands)}"))
                    continue

            # Rule B: unique name_key
            cands2 = p_index_name.get(n_key, [])
            if len(cands2) == 1:
                plan_inserts.append((spid, cands2[0], "rule_unique_name_key (no_school)", 0.85))
                continue
            if len(cands2) == 0:
                ambiguities.append((spid, raw_name, raw_school, "no_match_name_key"))
                continue

            # Rule C: position hint resolves (use parsed pos from raw_name, not cleaned)
            hint = parse_pos_hint(raw_name)
            pos_match = normalize_pos_to_season_value(hint, pos_values)
            if pos_match:
                matches = [pid for pid in cands2 if p_pos.get(pid, "") == pos_match]
                if len(matches) == 1:
                    plan_inserts.append((spid, matches[0], f"rule_name_key_pos ({pos_match})", 0.90))
                    continue
                if len(matches) > 1:
                    ambiguities.append((spid, raw_name, raw_school, f"ambiguous_pos_{pos_match}_{len(matches)}"))
                    continue

            ambiguities.append((spid, raw_name, raw_school, f"ambiguous_name_key_{len(cands2)}"))

        print(f"SEASON_ID: {season_id} (draft_year={args.season})")
        print(f"UNMAPPED_SOURCE_PLAYERS: {len(unmapped)}")
        print(f"PLAN_INSERTS: {len(plan_inserts)} (conservative)")
        print(f"PLAN_AMBIGUOUS: {len(ambiguities)}")

        if args.apply == 0:
            print("DRY RUN: no DB writes, no backup")
            if plan_inserts:
                spid, pid, notes, score = plan_inserts[0]
                print(f"EXAMPLE_INSERT: source_player_id={spid} -> prospect_id={pid} score={score} notes={notes}")
            if ambiguities:
                spid, rn, rs, reason = ambiguities[0]
                print(f"EXAMPLE_AMBIGUITY: source_player_id={spid} name='{rn}' school='{rs}' reason='{reason}'")
            return

    backup_path = ensure_backup(PATHS.db)
    print(f"OK: backup created: {backup_path}")

    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        season_id = resolve_season_id(conn, args.season)

        alias_token_map = load_name_alias_token_map(conn)
        school_alias_map = load_school_alias_map(conn)
        canon_school_by_key = build_canonical_school_by_key_from_prospects(conn, season_id)
        pcm = load_prospect_canonical_map(conn, season_id)

        pos_values = {
            (r["position_group"] or "").strip().upper()
            for r in conn.execute("SELECT DISTINCT position_group FROM prospects WHERE season_id=?;", (season_id,)).fetchall()
        }
        pos_values.discard("")

        # Backfill prospects name_norm/name_key
        p_rows = conn.execute("SELECT prospect_id, full_name FROM prospects WHERE season_id=?;", (season_id,)).fetchall()
        for r in p_rows:
            pid = int(r["prospect_id"])
            n_norm, n_key = name_norm_and_key(r["full_name"] or "", alias_token_map)
            conn.execute("UPDATE prospects SET name_norm=?, name_key=? WHERE prospect_id=?;", (n_norm, n_key, pid))

        # Backfill source_players name_norm/name_key/school_canonical/pos_hint
        sp_rows = conn.execute(
            "SELECT source_player_id, raw_full_name, raw_school, raw_json FROM source_players WHERE season_id=?;",
            (season_id,),
        ).fetchall()
        for r in sp_rows:
            spid = int(r["source_player_id"])
            raw_name = (r["raw_full_name"] or "").strip()

            raw_school = (r["raw_school"] or "").strip()
            if not raw_school:
                raw_school = extract_school_from_raw_json(r["raw_json"])

            cleaned_name = strip_pos_prefix_from_name(raw_name, pos_values)
            n_norm, n_key = name_norm_and_key(cleaned_name, alias_token_map)

            sk = school_key(raw_school)
            school_canon = ""
            if sk:
                school_canon = school_alias_map.get(sk, "") or canon_school_by_key.get(sk, "")

            pos_hint = parse_pos_hint(raw_name)
            conn.execute(
                "UPDATE source_players SET name_norm=?, name_key=?, school_canonical=?, pos_hint=? WHERE source_player_id=?;",
                (n_norm, n_key, school_canon, pos_hint, spid),
            )

        # Canonicalized indexes from stored values
        p2 = conn.execute(
            "SELECT prospect_id, school_canonical, name_key, position_group FROM prospects WHERE season_id=?;",
            (season_id,),
        ).fetchall()
        p_index_school: Dict[Tuple[str, str], List[int]] = {}
        p_index_name: Dict[str, List[int]] = {}
        p_pos: Dict[int, str] = {}

        for r in p2:
            pid_raw = int(r["prospect_id"])
            pid = canon_pid(pid_raw, pcm)
            school = (r["school_canonical"] or "").strip()
            key = (r["name_key"] or "").strip()
            pos = (r["position_group"] or "").strip().upper()
            if key:
                p_index_name.setdefault(key, []).append(pid)
            if school and key:
                p_index_school.setdefault((school, key), []).append(pid)
            if pos:
                p_pos[pid] = pos

        for k in list(p_index_name.keys()):
            p_index_name[k] = dedupe_preserve_order(p_index_name[k])
        for k in list(p_index_school.keys()):
            p_index_school[k] = dedupe_preserve_order(p_index_school[k])

        unmapped2 = conn.execute(
            """
            SELECT sp.source_player_id, sp.raw_full_name, sp.raw_school, sp.raw_json, sp.pos_hint, sp.school_canonical
            FROM source_players sp
            LEFT JOIN source_player_map m ON m.source_player_id = sp.source_player_id
            WHERE sp.season_id = ?
              AND m.source_player_id IS NULL;
            """,
            (season_id,),
        ).fetchall()

        inserts: List[Tuple[int, int, str, float]] = []
        ambiguities: List[Tuple[int, str, str, str]] = []

        for r in unmapped2:
            spid = int(r["source_player_id"])
            raw_name = (r["raw_full_name"] or "").strip()

            cleaned_name = strip_pos_prefix_from_name(raw_name, pos_values)
            _n_norm, n_key = name_norm_and_key(cleaned_name, alias_token_map)
            if not n_key:
                ambiguities.append((spid, raw_name, "", "no_name_key"))
                continue

            raw_school = (r["raw_school"] or "").strip()
            if not raw_school:
                raw_school = extract_school_from_raw_json(r["raw_json"])
            school = (r["school_canonical"] or "").strip()

            # Rule A
            if school:
                cands = p_index_school.get((school, n_key), [])
                if len(cands) == 1:
                    inserts.append((spid, cands[0], f"rule_norm_name_school ({school})", 1.0))
                    continue

            # Rule B
            cands2 = p_index_name.get(n_key, [])
            if len(cands2) == 1:
                inserts.append((spid, cands2[0], "rule_unique_name_key (no_school)", 0.85))
                continue
            if len(cands2) == 0:
                ambiguities.append((spid, raw_name, raw_school, "no_match_name_key"))
                continue

            # Rule C
            hint = (r["pos_hint"] or "").strip().upper()
            pos_match = normalize_pos_to_season_value(hint, pos_values)
            if pos_match:
                matches = [pid for pid in cands2 if p_pos.get(pid, "") == pos_match]
                if len(matches) == 1:
                    inserts.append((spid, matches[0], f"rule_name_key_pos ({pos_match})", 0.90))
                    continue

            ambiguities.append((spid, raw_name, raw_school, f"ambiguous_name_key_{len(cands2)}"))

        n_ins = 0
        for spid, pid, notes, score in inserts:
            conn.execute(
                """
                INSERT INTO source_player_map(
                  source_player_id, prospect_id, match_method, match_score, match_notes,
                  reviewed, reviewed_by, reviewed_at
                )
                VALUES (?, ?, ?, ?, ?, 0, NULL, NULL)
                ON CONFLICT(source_player_id) DO NOTHING;
                """,
                (spid, pid, "rule_auto", score, notes),
            )
            n_ins += 1

        conn.commit()

    print(f"OK: inserted conservative source_player_map rows={n_ins}")

    if args.export_diagnostics == 1:
        with diag_auto.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source_player_id", "prospect_id", "match_score", "notes"])
            for spid, pid, notes, score in inserts:
                w.writerow([spid, pid, score, notes])

        with diag_amb.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source_player_id", "raw_full_name", "raw_school_or_json", "reason"])
            for spid, rn, rs, reason in ambiguities:
                w.writerow([spid, rn, rs, reason])

        print(f"OK: diagnostics exported: {diag_auto}")
        print(f"OK: diagnostics exported: {diag_amb}")


if __name__ == "__main__":
    main()