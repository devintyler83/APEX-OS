# scripts/stage_rankings_csv.py
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
import html
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS


def utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").strip().lower())


RANK_KEYS = {
    "rank",
    "rk",
    "overallrank",
    "overall",
    "bigboard",
    "boardrank",
    "overallrk",
    "overall_rk",
    "ovr",        # jfosterfilm_2026 and similar boards use OVR
}
NAME_KEYS = {
    "name",
    "player",
    "playername",
    "player_name",
    "full_name",
    "fullname",
    "prospect",
    "prospectname",
}
SCHOOL_KEYS = {
    "school",
    "college",
    "college_name",
    "collegename",
    "team",
    "team_name",
    "university",
}
POS_KEYS = {"pos", "position", "positiongroup", "position_group"}

# Bleacher Report combined column header normalizes to this value.
# Raw header: "Pos, School, Grade" → norm → "posschoolgrade"
BR_COMBINED_NORM = "posschoolgrade"


def detect_columns(fieldnames: List[str]) -> Dict[str, str]:
    """
    Returns mapping {logical: actual_header}
    logical keys: rank, player_name, school (optional), position (optional)
    """
    header_map = {norm(h): h for h in (fieldnames or [])}

    def pick(keys) -> Optional[str]:
        for k in keys:
            if k in header_map:
                return header_map[k]
        return None

    rank_h = pick(RANK_KEYS)
    name_h = pick(NAME_KEYS)
    school_h = pick(SCHOOL_KEYS)
    pos_h = pick(POS_KEYS)

    out: Dict[str, str] = {}
    if rank_h:
        out["rank"] = rank_h
    if name_h:
        out["player_name"] = name_h
    if school_h:
        out["school"] = school_h
    if pos_h:
        out["position"] = pos_h
    return out


def is_br_format(fieldnames: List[str]) -> bool:
    """
    Detect Bleacher Report combined column format.
    First column header 'Pos, School, Grade' normalizes to 'posschoolgrade'.
    Second column is the player name (empty-string key in DictReader).
    """
    return len(fieldnames) >= 2 and norm(fieldnames[0]) == BR_COMBINED_NORM


def parse_br_row(combined: str, second_col: str) -> Tuple[Optional[int], str, str, Optional[float], str]:
    """
    Parse a single Bleacher Report data row.

    Three format variants exist in the B/R CSV:
      Format A: combined='N. POS\\xa0, School (grade)'   second=player_name  (non-breaking space)
      Format C: combined='N. POS , School (grade)'       second=player_name  (regular space)
      Format B: combined='N. POS Player Name, School (grade)'  second=''    (player embedded)

    Detection: if second_col is non-empty, player name is in second column (Formats A and C).
               if second_col is empty, player name is embedded in combined field (Format B).

    Returns: (rank, position, school, analyst_grade, player_name)
    All strings are stripped. rank is None if the combined field cannot be parsed.
    """
    s = combined.strip()
    player_name = second_col.strip()

    # Extract rank: leading "N. " prefix
    rank_match = re.match(r'^(\d+)\.\s*', s)
    if not rank_match:
        return (None, '', '', None, '')
    rank = int(rank_match.group(1))
    s = s[rank_match.end():]

    # Extract grade: trailing "(N.N)" or "(N)"
    grade_match = re.search(r'\((\d+\.?\d*)\)\s*$', s)
    grade = float(grade_match.group(1)) if grade_match else None
    if grade_match:
        s = s[:grade_match.start()].strip()

    # Normalize non-breaking space to regular space
    s = s.replace('\xa0', ' ').strip()

    if player_name:
        # Formats A and C: player name is in second column.
        # Remaining s after rank and grade removal: "POS, School" or "POS , School"
        parts = s.split(',', 1)
        position = parts[0].strip()
        school = parts[1].strip() if len(parts) > 1 else ''
    else:
        # Format B: player name embedded — "POS Player Name, School"
        # First space-delimited token = position; remainder split on last comma.
        space_idx = s.find(' ')
        if space_idx == -1:
            # Only a position token, no player name or school
            return (rank, s.strip(), '', grade, '')
        position = s[:space_idx].strip()
        rest = s[space_idx + 1:].strip()  # "Player Name, School"
        comma_idx = rest.rfind(',')
        if comma_idx == -1:
            player_name = rest
            school = ''
        else:
            player_name = rest[:comma_idx].strip()
            school = rest[comma_idx + 1:].strip()

    return (rank, position, school, grade, player_name)


def try_open_reader(p: Path):
    """
    Try common encodings; return (reader, encoding_used, file_handle)
    Caller must close file_handle.
    """
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_err = None
    for enc in encodings:
        try:
            f = p.open("r", encoding=enc, newline="")
            reader = csv.DictReader(f)
            _ = reader.fieldnames
            return reader, enc, f
        except Exception as e:
            last_err = e
            try:
                f.close()  # type: ignore
            except Exception:
                pass
    raise last_err  # type: ignore


def _stage_br_file(
    reader: csv.DictReader,
    enc: str,
    src: Path,
    season: int,
    *,
    dry_run: bool = False,
) -> Tuple[str, Optional[Path], int, str]:
    """
    Handle Bleacher Report combined column format.
    Staged output includes analyst_grade column (float or empty string).
    """
    fieldnames = reader.fieldnames or []
    combined_col = fieldnames[0]  # "Pos, School, Grade"
    name_col = fieldnames[1]       # "" (empty-string key for second column)

    out_dir = PATHS.imports / "rankings" / "staged" / str(season)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = utcstamp()
    out_name = f"{src.stem}_staged_{ts}.csv"
    out_path = out_dir / out_name

    # B/R staged schema includes analyst_grade
    fieldnames_out = ["rank", "player_name", "school", "position", "analyst_grade"]

    rows_written = 0
    parse_errors = 0

    if dry_run:
        for row in reader:
            combined = (row.get(combined_col) or '').strip()
            second = (row.get(name_col) or '').strip()
            if not combined:
                continue
            rank, position, school, grade, player_name = parse_br_row(combined, second)
            if rank is None or not player_name:
                parse_errors += 1
                continue
            rows_written += 1
        msg = f"DRY_RUN encoding={enc} format=bleacherreport parse_errors={parse_errors}"
        return ("OK", out_path, rows_written, msg)

    with out_path.open("w", encoding="utf-8-sig", newline="") as out_f:
        w = csv.DictWriter(out_f, fieldnames=fieldnames_out)
        w.writeheader()

        for row in reader:
            combined = (row.get(combined_col) or '').strip()
            second = (row.get(name_col) or '').strip()
            if not combined:
                continue

            rank, position, school, grade, player_name = parse_br_row(combined, second)
            if rank is None or not player_name:
                parse_errors += 1
                continue

            w.writerow({
                "rank": rank,
                "player_name": player_name,
                "school": school,
                "position": position,
                "analyst_grade": grade if grade is not None else "",
            })
            rows_written += 1

    if rows_written == 0:
        try:
            out_path.unlink(missing_ok=True)  # type: ignore
        except Exception:
            pass
        return ("SKIP", None, 0, "no usable rows")

    if parse_errors > 0:
        print(f"  WARN: {parse_errors} B/R parse errors in {src.name}")

    return ("OK", out_path, rows_written, f"encoding={enc} format=bleacherreport parse_errors={parse_errors}")


def stage_file(src: Path, season: int, *, dry_run: bool = False) -> Tuple[str, Optional[Path], int, str]:
    """
    Returns (status, staged_path, rows_count, message)
    status: OK | SKIP | FAIL
    When dry_run=True, no file is written and staged_path is the would-be path.
    """
    try:
        reader, enc, fh = try_open_reader(src)
    except Exception as e:
        return ("SKIP", None, 0, f"unreadable_csv ({e.__class__.__name__})")

    with fh:
        fieldnames = reader.fieldnames or []

        # Detect Bleacher Report combined column format and delegate
        if is_br_format(fieldnames):
            return _stage_br_file(reader, enc, src, season, dry_run=dry_run)

        # Standard format
        cols = detect_columns(fieldnames)
        if "rank" not in cols or "player_name" not in cols:
            return ("SKIP", None, 0, f"missing rank or player_name column (detected: {list(cols.keys())}, headers: {fieldnames})")

        out_dir = PATHS.imports / "rankings" / "staged" / str(season)
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = utcstamp()
        out_name = f"{src.stem}_staged_{ts}.csv"
        out_path = out_dir / out_name

        # Canonical staged schema for ingest
        fieldnames_out = ["rank", "player_name", "school", "position"]

        rows_written = 0

        if dry_run:
            # Count rows without writing
            for row in reader:
                raw_rank = (row.get(cols["rank"]) or "").strip()
                raw_name = (row.get(cols["player_name"]) or "").strip()
                if not raw_rank or not raw_name:
                    continue
                rows_written += 1
            return ("OK", out_path, rows_written, f"DRY_RUN encoding={enc} col_map={cols}")

        with out_path.open("w", encoding="utf-8-sig", newline="") as out_f:
            w = csv.DictWriter(out_f, fieldnames=fieldnames_out)
            w.writeheader()

            for row in reader:
                raw_rank = (row.get(cols["rank"]) or "").strip()
                raw_name = (row.get(cols["player_name"]) or "").strip()

                raw_school = ""
                if cols.get("school"):
                    raw_school = html.unescape((row.get(cols["school"]) or "").strip())

                raw_pos = ""
                if cols.get("position"):
                    raw_pos = (row.get(cols["position"]) or "").strip()

                if not raw_rank or not raw_name:
                    continue

                w.writerow(
                    {
                        "rank": raw_rank,
                        "player_name": raw_name,
                        "school": raw_school,
                        "position": raw_pos,
                    }
                )
                rows_written += 1

        if rows_written == 0:
            try:
                out_path.unlink(missing_ok=True)  # type: ignore
            except Exception:
                pass
            return ("SKIP", None, 0, "no usable rows")

        return ("OK", out_path, rows_written, f"encoding={enc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage raw rankings CSVs for ingest.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dir", help="Folder containing raw rankings CSVs (batch mode)")
    grp.add_argument("--source", help="Stage a single source by name (looks in raw/{season}/{source}.csv)")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument(
        "--apply",
        type=int,
        default=1,
        choices=[0, 1],
        help="0 = dry run (no files written), 1 = write staged files (default=1)",
    )
    args = ap.parse_args()

    dry_run = args.apply == 0
    if dry_run:
        print("DRY RUN: no staged files will be written")
    else:
        print("APPLY: staged files will be written")

    if args.source:
        # Single-source mode: look for raw/{season}/{source}.csv
        raw_dir = PATHS.imports / "rankings" / "raw" / str(args.season)
        src_path = raw_dir / f"{args.source}.csv"
        if not src_path.exists():
            raise SystemExit(f"FAIL: source file not found: {src_path}")
        files = [src_path]
    else:
        src_dir = Path(args.dir)
        if not src_dir.exists():
            raise SystemExit(f"FAIL: dir not found: {src_dir}")
        files = sorted([p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])
        if not files:
            raise SystemExit(f"FAIL: no CSV files found in {src_dir}")

    ok = 0
    skip = 0
    fail = 0

    for f in files:
        status, staged, n, msg = stage_file(f, args.season, dry_run=dry_run)
        if status == "OK":
            ok += 1
            staged_label = staged.name if staged else "(would write)"
            print(f"OK: {f.name} -> {staged_label} rows={n} {msg}")
        elif status == "SKIP":
            skip += 1
            print(f"SKIP: {f.name} ({msg})")
        else:
            fail += 1
            print(f"FAIL: {f.name} ({msg})")

    print(f"DONE: ok_files={ok} skipped_files={skip} failed_files={fail}")
    if ok == 0:
        raise SystemExit("FAIL: no usable rankings CSVs staged (all files skipped/failed)")


if __name__ == "__main__":
    main()
