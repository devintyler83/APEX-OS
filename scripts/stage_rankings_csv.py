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
        cols = detect_columns(reader.fieldnames or [])
        if "rank" not in cols or "player_name" not in cols:
            return ("SKIP", None, 0, f"missing rank or player_name column (detected: {list(cols.keys())}, headers: {reader.fieldnames})")

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
                    raw_school = (row.get(cols["school"]) or "").strip()

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
