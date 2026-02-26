from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

BASE = "https://www.nfldraftbuzz.com/positions/ALL/{page}/2026"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _to_int(s: str) -> Optional[int]:
    try:
        return int(float(_clean(s)))
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(_clean(s))
    except Exception:
        return None


def _extract_last_updated(text: str) -> Optional[str]:
    m = re.search(r"LAST UPDATED:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text, re.IGNORECASE)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()
    except Exception:
        return None


def _find_rankings_table(soup: BeautifulSoup):
    """
    Robust: locate the rankings table by scanning each table's text.
    This approach worked in your earlier successful run.
    """
    for table in soup.find_all("table"):
        t = table.get_text(" ", strip=True).upper()
        if (
            "PLAYER" in t
            and "POS" in t
            and "AVG POS RANK" in t
            and "AVG OVR RANK" in t
            and "RATING" in t
        ):
            return table
    return None


def _extract_headers(table) -> list[str]:
    """
    Try to find a header row (th preferred). If not present, fall back to first row's cell texts.
    """
    # Prefer explicit TH row
    for tr in table.find_all("tr", recursive=True)[:8]:
        ths = tr.find_all("th")
        if ths:
            return [_clean(th.get_text(" ", strip=True)).upper() for th in ths]

    # Fallback: first row cell texts
    tr0 = table.find("tr")
    if tr0:
        cells = tr0.find_all(["th", "td"])
        return [_clean(c.get_text(" ", strip=True)).upper() for c in cells]

    return []


def _col_idx(headers: list[str], wanted: list[str]) -> Optional[int]:
    """
    Return first matching header index for any alias in 'wanted'.
    """
    for w in wanted:
        w_u = w.upper()
        if w_u in headers:
            return headers.index(w_u)
    return None


def _school_from_team_cell(td) -> Optional[str]:
    # Team is often an image with alt="Ohio State Mascot"
    img = td.find("img")
    if img and img.get("alt"):
        alt = _clean(img.get("alt"))
        alt = re.sub(r"\s+Mascot$", "", alt, flags=re.IGNORECASE)
        return alt or None

    txt = _clean(td.get_text(" ", strip=True))
    return txt or None


def _strip_pos_prefix(player_text: str) -> tuple[str, Optional[str]]:
    """
    Some rows may show 'LB/ED David Bailey' in PLAYER column.
    If first token looks like a position code, treat it as a pos override.
    """
    t = _clean(player_text)
    if not t:
        return "", None
    parts = t.split(" ", 1)
    if len(parts) == 1:
        return t, None
    first = parts[0].upper()
    rest = parts[1].strip()
    if re.fullmatch(r"[A-Z/]{1,6}", first):
        return rest, first
    return t, None


def scrape(pages: int, sleep_s: float, headful: bool, timeout_ms: int, debug_dir: Path) -> list[dict]:
    out: list[dict] = []
    debug_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        # Reduce flakiness: block heavy resources but allow scripts/xhr
        def route_handler(route):
            rtype = route.request.resource_type
            if rtype in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        context.route("**/*", route_handler)

        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        for page_no in range(1, pages + 1):
            url = BASE.format(page=page_no)
            page.goto(url, wait_until="domcontentloaded")

            # Wait for ranking markers to appear in body text
            try:
                page.wait_for_function(
                    "() => document.body && document.body.innerText && document.body.innerText.includes('AVG OVR RANK')",
                    timeout=timeout_ms,
                )
            except PWTimeoutError:
                pass

            html = page.content()
            soup = BeautifulSoup(html, "lxml")

            ranking_date = _extract_last_updated(soup.get_text(" ", strip=True))

            table = _find_rankings_table(soup)
            if table is None:
                # Dump debug artifacts
                (debug_dir / f"page_{page_no:02d}.html").write_text(html, encoding="utf-8", errors="ignore")
                snippet = _clean(soup.get_text(" ", strip=True))[:800]
                (debug_dir / f"page_{page_no:02d}.txt").write_text(snippet, encoding="utf-8", errors="ignore")
                raise RuntimeError(
                    f"Could not find rankings table on page {page_no}: {url}\n"
                    f"Saved debug: {debug_dir}\\page_{page_no:02d}.html/.txt\n"
                    f"Snippet:\n{snippet}"
                )

            headers = _extract_headers(table)

            # Column indices by header labels (with aliases)
            i_rank = _col_idx(headers, ["#", "RK", "RANK"])
            i_player = _col_idx(headers, ["PLAYER"])
            i_pos = _col_idx(headers, ["POS", "POSITION"])
            i_team = _col_idx(headers, ["TEAM", "SCHOOL", "COLLEGE"])
            i_avg_pos = _col_idx(headers, ["AVG POS RANK"])
            i_avg_ovr = _col_idx(headers, ["AVG OVR RANK"])
            i_rating = _col_idx(headers, ["RATING"])
            i_summary = _col_idx(headers, ["SUMMARY"])

            # Validate minimum required columns
            if i_player is None or i_pos is None or i_avg_pos is None:
                (debug_dir / f"page_{page_no:02d}.headers.txt").write_text(
                    "\n".join(headers), encoding="utf-8", errors="ignore"
                )
                raise RuntimeError(
                    f"Header parsing failed on page {page_no}: {url}\n"
                    f"Have headers: {headers}\n"
                    f"Saved headers: {debug_dir}\\page_{page_no:02d}.headers.txt"
                )

            trs = table.find_all("tr")
            for tr in trs[1:]:
                tds = tr.find_all("td")
                if not tds:
                    continue

                # Guard against short rows
                max_idx = max(
                    x for x in [i_rank, i_player, i_pos, i_team, i_avg_pos, i_avg_ovr, i_rating, i_summary] if x is not None
                )
                if len(tds) <= max_idx:
                    continue

                overall_rank = None
                if i_rank is not None:
                    overall_rank = _to_int(tds[i_rank].get_text(" ", strip=True))

                player_text = _clean(tds[i_player].get_text(" ", strip=True))
                name, pos_override = _strip_pos_prefix(player_text)

                raw_position = _clean(tds[i_pos].get_text(" ", strip=True))
                if pos_override:
                    raw_position = pos_override

                raw_school = None
                if i_team is not None:
                    raw_school = _school_from_team_cell(tds[i_team])

                position_rank = _to_int(tds[i_avg_pos].get_text(" ", strip=True))

                grade = None
                if i_rating is not None:
                    grade = _to_float(tds[i_rating].get_text(" ", strip=True))

                avg_ovr_rank = None
                if i_avg_ovr is not None:
                    avg_ovr_rank = _to_float(tds[i_avg_ovr].get_text(" ", strip=True))

                summary = None
                if i_summary is not None:
                    summary = _clean(tds[i_summary].get_text(" ", strip=True)) or None

                if not name:
                    continue

                out.append(
                    {
                        "raw_full_name": name,
                        "raw_school": raw_school,
                        "raw_position": raw_position,
                        "overall_rank": overall_rank,
                        "position_rank": position_rank,
                        "grade": grade,
                        "tier": None,
                        "ranking_date": ranking_date,
                        "avg_ovr_rank": avg_ovr_rank,
                        "summary": summary,
                    }
                )

            time.sleep(sleep_s)

        context.close()
        browser.close()

    # Deterministic fill if rank missing
    for i, r in enumerate(out, start=1):
        if r.get("overall_rank") is None:
            r["overall_rank"] = i

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=41)
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--headful", type=int, default=0)
    ap.add_argument("--timeout-ms", type=int, default=30000)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--debug-dir", type=str, default=r"C:\DraftOS\data\exports\debug\nfldraftbuzz_v2")
    args = ap.parse_args()

    rows = scrape(
        pages=args.pages,
        sleep_s=args.sleep,
        headful=bool(args.headful),
        timeout_ms=args.timeout_ms,
        debug_dir=Path(args.debug_dir),
    )

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
        "avg_ovr_rank",
        "summary",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})

    print(f"OK: wrote {len(rows)} rows -> {out_path}")


if __name__ == "__main__":
    main()