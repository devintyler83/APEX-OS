from __future__ import annotations

import argparse
import csv
import html
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?;",
        (name,),
    ).fetchone()
    return row is not None


def colnames(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()]


def pick_first(cols: set[str], *cands: str) -> Optional[str]:
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

    row = conn.execute(
        f"SELECT {id_col} AS season_id FROM seasons WHERE {year_col} = ?;",
        (draft_year,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: season not found for draft_year={draft_year}")
    return int(row["season_id"])


def resolve_model_id(conn, season_id: int, model_key_or_name: str) -> int:
    cols = set(colnames(conn, "models"))
    id_col = pick_first(cols, "model_id", "id")
    if not id_col:
        raise SystemExit(f"FAIL: models missing id column. found={sorted(cols)}")

    if "season_id" in cols:
        key_col = pick_first(cols, "model_key", "model_name", "name")
        if not key_col:
            raise SystemExit(f"FAIL: models missing model key/name column. found={sorted(cols)}")
        row = conn.execute(
            f"""
            SELECT {id_col} AS model_id
            FROM models
            WHERE season_id = ? AND {key_col} = ?;
            """,
            (season_id, model_key_or_name),
        ).fetchone()
        if row:
            return int(row["model_id"])

        for alt in ("model_key", "model_name", "name"):
            if alt in cols and alt != key_col:
                row2 = conn.execute(
                    f"SELECT {id_col} AS model_id FROM models WHERE season_id = ? AND {alt} = ?;",
                    (season_id, model_key_or_name),
                ).fetchone()
                if row2:
                    return int(row2["model_id"])

        raise SystemExit(f"FAIL: model not found for season_id={season_id} model='{model_key_or_name}'")

    name_col = pick_first(cols, "name", "model_key", "model_name")
    if not name_col:
        raise SystemExit(f"FAIL: models missing name/key column. found={sorted(cols)}")

    row = conn.execute(
        f"SELECT {id_col} AS model_id FROM models WHERE {name_col} = ?;",
        (model_key_or_name,),
    ).fetchone()
    if not row:
        raise SystemExit(f"FAIL: model not found model='{model_key_or_name}'")
    return int(row["model_id"])


def get_latest_snapshot_date(conn, season_id: int, model_id: int) -> Tuple[int, str]:
    row = conn.execute(
        """
        SELECT id, snapshot_date_utc
        FROM prospect_board_snapshots
        WHERE season_id = ? AND model_id = ?
        ORDER BY snapshot_date_utc DESC, id DESC
        LIMIT 1;
        """,
        (season_id, model_id),
    ).fetchone()
    if not row:
        raise SystemExit("FAIL: no snapshots found for this season/model")
    return int(row["id"]), str(row["snapshot_date_utc"])


def yyyymmdd_from_iso(dt: str) -> str:
    # dt like "2026-03-01" or "2026-03-01T23:40:31+00:00"
    d = dt[:10].replace("-", "")
    if len(d) != 8:
        return datetime.now(timezone.utc).strftime("%Y%m%d")
    return d


def find_best_file(exports_dir: Path, patterns: List[str]) -> Optional[Path]:
    matches: List[Path] = []
    for pat in patterns:
        matches.extend(sorted(exports_dir.glob(pat)))
    matches = [p for p in matches if p.is_file()]
    if not matches:
        return None
    # Prefer newest by modified time for "best available"
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def read_csv(path: Path, limit_rows: Optional[int] = None) -> Tuple[List[str], List[List[str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        rows = list(r)

    if not rows:
        return [], []

    header = rows[0]
    body = rows[1:]
    if limit_rows is not None:
        body = body[:limit_rows]
    return header, body


def chip_class(value: str) -> str:
    v = (value or "").strip().lower()
    if v in ("high", "healthy"):
        return "chip chip-good"
    if v in ("medium",):
        return "chip chip-mid"
    if v in ("low", "noisy", "thin coverage", "stale"):
        return "chip chip-bad"
    return "chip"


def escape_cell(x: str) -> str:
    return html.escape(x if x is not None else "")


def render_table(header: List[str], rows: List[List[str]], chip_cols: Optional[set[str]] = None) -> str:
    chip_cols = chip_cols or set()
    th = "".join(f"<th>{escape_cell(h)}</th>" for h in header)

    trs = []
    for row in rows:
        tds = []
        for i, cell in enumerate(row):
            col = header[i] if i < len(header) else ""
            if col in chip_cols:
                cls = chip_class(cell)
                tds.append(f'<td><span class="{cls}">{escape_cell(cell)}</span></td>')
            else:
                tds.append(f"<td>{escape_cell(cell)}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")

    return f"""
    <div class="tablewrap">
      <table class="sortable">
        <thead><tr>{th}</tr></thead>
        <tbody>
          {''.join(trs)}
        </tbody>
      </table>
    </div>
    """


def html_page(title: str, subtitle: str, body_html: str, nav_html: str) -> str:
    css = """
    :root { --bg:#0b0f14; --panel:#111823; --text:#e7eef7; --muted:#9bb0c5; --line:#243246; }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:var(--bg); color:var(--text); }
    a { color:#7fb7ff; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .wrap { max-width: 1320px; margin: 0 auto; padding: 20px; }
    .top { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; }
    h1 { font-size: 22px; margin:0; }
    .sub { color: var(--muted); font-size: 13px; margin-top:6px; }
    .nav { margin: 16px 0 18px; padding: 12px; background:var(--panel); border:1px solid var(--line); border-radius: 12px; }
    .nav a { margin-right: 14px; font-size: 13px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius: 12px; padding: 14px; }
    .tablewrap { overflow:auto; border-radius: 10px; border:1px solid var(--line); }
    table { border-collapse: collapse; width: 100%; background: #0d131d; }
    th, td { border-bottom: 1px solid #1a273a; padding: 8px 10px; font-size: 12px; white-space: nowrap; }
    th { position: sticky; top:0; background:#0f1724; cursor:pointer; }
    tr:hover td { background:#0f1a2b; }
    .meta { color: var(--muted); font-size: 12px; }
    .chip { display:inline-block; padding: 2px 8px; border-radius: 999px; border:1px solid var(--line); font-size: 12px; }
    .chip-good { border-color:#1f6f3a; color:#a7f3c5; background:#0d2016; }
    .chip-mid { border-color:#6b5b1f; color:#ffe7a1; background:#221a0d; }
    .chip-bad { border-color:#7a2430; color:#ffc1c7; background:#230d12; }
    .missing { color:#ffb3ba; }
    """
    js = """
    // Simple client-side sortable tables. Deterministic HTML output, interactive sorting in browser.
    (function(){
      function asNumber(x){
        var t = (x || "").replace(/,/g,"").trim();
        if(t === "") return null;
        var n = Number(t);
        return isNaN(n) ? null : n;
      }
      function getCellText(td){
        if(!td) return "";
        var span = td.querySelector("span");
        return span ? span.textContent : td.textContent;
      }
      function sortTable(table, col, dir){
        var tbody = table.tBodies[0];
        var rows = Array.prototype.slice.call(tbody.rows, 0);
        rows.sort(function(a,b){
          var av = getCellText(a.cells[col]);
          var bv = getCellText(b.cells[col]);
          var an = asNumber(av);
          var bn = asNumber(bv);
          if(an !== null && bn !== null){
            return dir * (an - bn);
          }
          return dir * av.localeCompare(bv);
        });
        rows.forEach(function(r){ tbody.appendChild(r); });
      }
      document.querySelectorAll("table.sortable").forEach(function(table){
        var ths = table.tHead ? table.tHead.rows[0].cells : [];
        for(let i=0;i<ths.length;i++){
          let th = ths[i];
          th.addEventListener("click", function(){
            var dir = th.getAttribute("data-dir") === "asc" ? -1 : 1;
            th.setAttribute("data-dir", dir === 1 ? "asc" : "desc");
            sortTable(table, i, dir);
          });
        }
      });
    })();
    """
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_cell(title)}</title>
  <style>{css}</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>{escape_cell(title)}</h1>
        <div class="sub">{escape_cell(subtitle)}</div>
      </div>
      <div class="meta">Generated: {escape_cell(datetime.now(timezone.utc).replace(microsecond=0).isoformat())}</div>
    </div>
    <div class="nav">{nav_html}</div>
    <div class="card">
      {body_html}
    </div>
  </div>
  <script>{js}</script>
</body>
</html>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate deterministic HTML report pack from DraftOS exports.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--limit-board", type=int, default=300)
    ap.add_argument("--limit-movers", type=int, default=200)
    ap.add_argument("--limit-volatility", type=int, default=200)
    args = ap.parse_args()

    exports_dir = PATHS.root / "exports"
    reports_dir = exports_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL: DB not found: {PATHS.db}")

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        required = ["seasons", "models", "prospect_board_snapshots"]
        for t in required:
            if not table_exists(conn, t):
                raise SystemExit(f"FAIL: missing required table: {t}")

        season_id = resolve_season_id(conn, args.season)
        model_id = resolve_model_id(conn, season_id, args.model)
        snapshot_id, snapshot_date_utc = get_latest_snapshot_date(conn, season_id, model_id)

    stamp = yyyymmdd_from_iso(snapshot_date_utc)

    # Best-effort file discovery (stable names preferred, fallback to newest matching)
    board_file = find_best_file(
        exports_dir,
        [
            f"board_*_{args.season}_{args.model}.csv",
            f"board_{args.season}_{args.model}.csv",
            f"*board*_{args.season}_{args.model}.csv",
        ],
    )

    movers_daily = find_best_file(exports_dir, [f"movers_daily_{args.season}_{args.model}.csv"])
    movers_window = find_best_file(exports_dir, [f"movers_window{args.window}_{args.season}_{args.model}.csv"])
    volatility_window = find_best_file(exports_dir, [f"volatility_window{args.window}_{args.season}_{args.model}.csv"])

    source_health = find_best_file(exports_dir, [f"source_health_{stamp}_{args.season}_{args.model}.csv", f"source_health_*_{args.season}_{args.model}.csv"])
    conf_summary = find_best_file(exports_dir, [f"confidence_summary_{stamp}_{args.season}_{args.model}.csv", f"confidence_summary_*_{args.season}_{args.model}.csv"])

    pages: List[Tuple[str, str, Optional[Path]]] = [
        ("Board", "board.html", board_file),
        ("Movers Daily", "movers_daily.html", movers_daily),
        (f"Movers Window {args.window}", "movers_window.html", movers_window),
        (f"Volatility Window {args.window}", "volatility.html", volatility_window),
        ("Source Health", "source_health.html", source_health),
        ("Confidence Summary", "confidence.html", conf_summary),
    ]

    nav_links = " ".join([f'<a href="{html.escape(fname)}">{html.escape(label)}</a>' for (label, fname, _p) in pages] + ['<a href="index.html">Index</a>'])
    subtitle = f"Season {args.season}, model {args.model}, snapshot {snapshot_id} ({snapshot_date_utc})"

    # Build each page
    for label, fname, path in pages:
        if path is None:
            body = f'<div class="missing">Missing export file for {html.escape(label)}. Run the weekly pipeline to generate exports.</div>'
            page = html_page(f"DraftOS Report: {label}", subtitle, body, nav_links)
            write_text(reports_dir / fname, page)
            continue

        limit = None
        chip_cols: set[str] = set()
        if fname == "board.html":
            limit = int(args.limit_board)
            chip_cols = {"tier", "momentum_chip", "volatility_chip", "confidence_band", "health_chip"}
        elif fname in ("movers_daily.html", "movers_window.html"):
            limit = int(args.limit_movers)
            chip_cols = {"momentum_chip", "volatility_chip", "confidence_band"}
        elif fname == "volatility.html":
            limit = int(args.limit_volatility)
            chip_cols = {"volatility_chip", "confidence_band"}
        elif fname == "source_health.html":
            chip_cols = {"health_chip"}
        elif fname == "confidence.html":
            chip_cols = {"confidence_band"}

        header, rows = read_csv(path, limit_rows=limit)

        info = f"""
        <div class="meta">
          File: {escape_cell(str(path.name))}<br>
          Rows shown: {len(rows)}{(" (limited)" if limit is not None else "")}
        </div>
        """

        table_html = render_table(header, rows, chip_cols=chip_cols) if header else '<div class="missing">CSV was empty.</div>'
        body = info + table_html
        page = html_page(f"DraftOS Report: {label}", subtitle, body, nav_links)
        write_text(reports_dir / fname, page)

    # Index page
    items = []
    for label, fname, path in pages:
        status = "OK" if path and path.exists() else "Missing"
        cls = "chip chip-good" if status == "OK" else "chip chip-bad"
        items.append(
            f"""
            <tr>
              <td><a href="{html.escape(fname)}">{escape_cell(label)}</a></td>
              <td><span class="{cls}">{escape_cell(status)}</span></td>
              <td>{escape_cell(path.name if path else "")}</td>
            </tr>
            """
        )

    index_body = f"""
      <div class="meta">
        {escape_cell(subtitle)}<br>
        Reports directory: {escape_cell(str(reports_dir))}
      </div>
      <div class="tablewrap" style="margin-top:12px;">
        <table>
          <thead>
            <tr><th>Report</th><th>Status</th><th>Source CSV</th></tr>
          </thead>
          <tbody>
            {''.join(items)}
          </tbody>
        </table>
      </div>
      <div class="meta" style="margin-top:12px;">
        Tip: click any column header in a report table to sort.
      </div>
    """
    index_page = html_page("DraftOS Report Pack", subtitle, index_body, nav_links)
    write_text(reports_dir / "index.html", index_page)

    print(f"OK: HTML reports generated: {reports_dir}")
    print(f"OPEN: {reports_dir / 'index.html'}")


if __name__ == "__main__":
    main()