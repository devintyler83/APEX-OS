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


RANK_KEYS = {"rank", "rk", "overallrank", "overall", "bigboard", "boardrank"}
NAME_KEYS = {"name", "player", "playername", "full_name", "fullname"}
SCHOOL_KEYS = {"school", "college", "team"}
POS_KEYS = {"pos", "position"}


def detect_columns(fieldnames: List[str]) -> Dict[str, str]:
    """
    Returns mapping {logical: actual_header}
    logical keys: rank, name, school (optional), position (optional)
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
        out["name"] = name_h
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
            # force header read
            _ = reader.fieldnames
            return reader, enc, f
        except Exception as e:
            last_err = e
            try:
                f.close()  # type: ignore
            except Exception:
                pass
    raise last_err  # type: ignore


def stage_file(src: Path, season: int) -> Tuple[str, Optional[Path], int, str]:
    """
    Returns (status, staged_path, rows_count, message)
    status: OK | SKIP | FAIL
    """
    try:
        reader, enc, fh = try_open_reader(src)
    except Exception as e:
        return ("SKIP", None, 0, f"unreadable_csv ({e.__class__.__name__})")

    with fh:
        cols = detect_columns(reader.fieldnames or [])
        if "rank" not in cols or "name" not in cols:
            return ("SKIP", None, 0, "missing rank or name column")

        # Write staged output
        out_dir = PATHS.imports / "rankings" / "staged" / str(season)
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = utcstamp()
        out_name = f"{src.stem}_staged_{ts}.csv"
        out_path = out_dir / out_name

        # Normalize output headers to standard set
        fieldnames_out = ["rank", "name", "school", "position"]

        rows_written = 0
        with out_path.open("w", encoding="utf-8-sig", newline="") as out_f:
            w = csv.DictWriter(out_f, fieldnames=fieldnames_out)
            w.writeheader()

            for row in reader:
                raw_rank = (row.get(cols["rank"]) or "").strip()
                raw_name = (row.get(cols["name"]) or "").strip()
                raw_school = (row.get(cols.get("school", ""), "") or "").strip() if cols.get("school") else ""
                raw_pos = (row.get(cols.get("position", ""), "") or "").strip() if cols.get("position") else ""

                if not raw_rank or not raw_name:
                    continue

                w.writerow(
                    {
                        "rank": raw_rank,
                        "name": raw_name,
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Folder containing raw rankings CSVs")
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

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
        status, staged, n, msg = stage_file(f, args.season)
        if status == "OK":
            ok += 1
            print(f"OK: {f.name} -> {staged.name} rows={n} {msg}")
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