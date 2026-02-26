from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE = "https://www.nfldraftbuzz.com/positions/ALL/{page}/2026"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _to_int_from_floatish(s: str) -> Optional[int]:
    try:
        return int(float(s))
    except Exception:
        return None


def _extract_last_updated(soup: BeautifulSoup) -> Optional[str]:
    text = soup.get_text(" ", strip=True)
    m = re.search(r"LAST UPDATED:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text, re.IGNORECASE)
    if not m:
        return None
    mmddyyyy = m.group(1)
    try:
        return datetime.strptime(mmddyyyy, "%m/%d/%Y").date().isoformat()
    except Exception:
        return None


def _find_rankings_table(soup: BeautifulSoup):
    # Find the table that contains the key headers we care about.
    for table in soup.find_all("table"):
        header_text = table.get_text(" ", strip=True).upper()
        if "PLAYER" in header_text and "AVG POS RANK" in header_text and "AVG OVR RANK" in header_text:
            return table
    return None


def scrape(pages: int, sleep_s: float) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    out: list[dict] = []

    for page in range(1, pages + 1):
        url = BASE.format(page=page)
        r = session.get(url, timeout=30)

        # If they block requests, fail with a clear message.
        if r.status_code == 403:
            raise RuntimeError(
                f"403 Forbidden on {url}. "
                f"Site is blocking non-browser requests. Use the Playwright fallback."
            )
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        ranking_date = _extract_last_updated(soup)

        table = _find_rankings_table(soup)
        if table is None:
            raise RuntimeError(f"Could not locate rankings table on page {page}: {url}")

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        cols = [c.upper() for c in header_cells]

        def col_idx(name: str) -> int:
            u = name.upper()
            if u not in cols:
                raise RuntimeError(f"Missing column '{name}' on page {page}. Have: {cols}")
            return cols.index(u)

        i_player = col_idx("Player")
        i_pos = col_idx("Pos")
        i_team = col_idx("Team")
        i_avg_pos = col_idx("AVG POS RANK")
        i_rating = col_idx("Rating")
        i_summary = col_idx("Summary")

        for tr in rows[1:]:
            tds = tr.find_all("td")
            if not tds:
                continue

            player = tds[i_player].get_text(" ", strip=True)
            pos = tds[i_pos].get_text(" ", strip=True)
            team = tds[i_team].get_text(" ", strip=True)
            avg_pos_rank = tds[i_avg_pos].get_text(" ", strip=True)
            rating = tds[i_rating].get_text(" ", strip=True)
            summary = tds[i_summary].get_text(" ", strip=True)

            if not player:
                continue

            out.append(
                {
                    "raw_full_name": player,
                    "raw_school": team,
                    "raw_position": pos,
                    "overall_rank": None,  # fill after scrape
                    "position_rank": _to_int_from_floatish(avg_pos_rank),
                    "grade": _to_float(rating),
                    "tier": None,
                    "ranking_date": ranking_date,
                    # NOTE: summary intentionally NOT written to CSV to avoid quote/comma ragged lines.
                }
            )

        time.sleep(sleep_s)

    for i, row in enumerate(out, start=1):
        row["overall_rank"] = i

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=41)
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--out", type=str, default=r"C:\DraftOS\data\imports\rankings\nfldraftbuzz_2026.csv")
    args = ap.parse_args()

    rows = scrape(pages=args.pages, sleep_s=args.sleep)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "raw_full_name",
        "raw_school",
        "raw_position",
        "overall_rank",
        "position_rank",
        "grade",
        "tier",
        "ranking_date",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})

    print(f"OK: wrote {len(rows)} rows -> {out_path}")


if __name__ == "__main__":
    main()