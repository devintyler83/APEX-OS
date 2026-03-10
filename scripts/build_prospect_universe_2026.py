from __future__ import annotations

# --- sys.path bootstrap so "python scripts\..." always works ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import csv
import re

from draftos.config import PATHS


def normalize_name(n: str) -> str:
    n = n.replace("\xa0", " ").strip()
    n = n.lower()
    n = re.sub(r"[^a-z0-9 '.\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def normalize_school(s: str) -> str:
    s = s.replace("\xa0", " ").strip()
    s = s.replace("&amp;", "&")
    return s


def main() -> None:
    ras_path = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "ras_2026.csv"
    jf_path  = PATHS.root / "data" / "imports" / "rankings" / "raw" / "2026" / "jfosterfilm_2026.csv"

    out_dir  = PATHS.root / "data" / "universe"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "prospect_universe_2026.csv"

    # ── Read RAS ──────────────────────────────────────────────────────────────
    ras_rows: dict[str, dict] = {}
    with open(ras_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["Name"].strip()
            if not name:
                continue
            norm = normalize_name(name)
            ras_rows[norm] = {
                "display_name": name,
                "pos":          row["Pos"].strip(),
                "school":       normalize_school(row["College"].strip()),
                "ras_score":    row["RAS"].strip(),
            }

    # ── Read jfosterfilm ──────────────────────────────────────────────────────
    jf_rows: dict[str, dict] = {}
    with open(jf_path, newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f):
            name = row["PLAYER"].strip()
            if not name:
                continue
            norm = normalize_name(name)
            jf_rows[norm] = {
                "display_name": name,
                "pos":          row["POS"].strip(),
                "school":       normalize_school(row["SCHOOL"].strip()),
                "jfoster_rank": row["OVR"].strip(),
            }

    # ── Build union ───────────────────────────────────────────────────────────
    all_norms = set(ras_rows.keys()) | set(jf_rows.keys())

    out_rows: list[dict] = []
    for norm in sorted(all_norms):
        in_ras = norm in ras_rows
        in_jf  = norm in jf_rows

        ras = ras_rows.get(norm, {})
        jf  = jf_rows.get(norm, {})

        # RAS school/name wins when both present (long-form school names match aliases better)
        if in_ras:
            display_name = ras["display_name"]
            pos          = ras["pos"]
            school       = ras["school"]
        else:
            display_name = jf["display_name"]
            pos          = jf["pos"]
            school       = jf["school"]

        out_rows.append({
            "normalized_name": norm,
            "display_name":    display_name,
            "pos":             pos,
            "school":          school,
            "in_ras":          "1" if in_ras else "0",
            "in_jfoster":      "1" if in_jf  else "0",
            "ras_score":       ras.get("ras_score", ""),
            "jfoster_rank":    jf.get("jfoster_rank", ""),
            "season_id":       "1",
        })

    # ── Write CSV ─────────────────────────────────────────────────────────────
    fieldnames = [
        "normalized_name", "display_name", "pos", "school",
        "in_ras", "in_jfoster", "ras_score", "jfoster_rank", "season_id",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    in_ras_count = sum(1 for r in out_rows if r["in_ras"]     == "1")
    in_jf_count  = sum(1 for r in out_rows if r["in_jfoster"] == "1")
    both_count   = sum(1 for r in out_rows if r["in_ras"] == "1" and r["in_jfoster"] == "1")
    ras_only     = in_ras_count - both_count
    jf_only      = in_jf_count  - both_count

    print(f"Total rows written: {len(out_rows)}")
    print(f"In RAS:     {in_ras_count}  (RAS only: {ras_only})")
    print(f"In jfoster: {in_jf_count}  (JF only: {jf_only})")
    print(f"In both:    {both_count}")
    print(f"Output:     {out_path}")


if __name__ == "__main__":
    main()
