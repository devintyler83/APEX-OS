"""
DraftOS — HTML Export: Report Pack + Prospect Card
Exports the HTML report pack (board, movers, etc.) and renders
the Card v2 (Classified Dossier × Panini Prizm aesthetic).
"""

from __future__ import annotations

import argparse
import csv
import html as _html
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from draftos.config import PATHS
from draftos.db.connect import connect
from draftos.queries.historical_comps import get_prospect_comps


# ---------------------------------------------------------------------------
# Utility helpers (shared)
# ---------------------------------------------------------------------------

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
    return _html.escape(x if x is not None else "")


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


# ---------------------------------------------------------------------------
# Report pack page renderer (used by main() for board/movers/etc. reports)
# ---------------------------------------------------------------------------

def html_report_page(title: str, subtitle: str, body_html: str, nav_html: str) -> str:
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


# ---------------------------------------------------------------------------
# Mock record — use for acceptance testing
# ---------------------------------------------------------------------------

MOCK_RUEBEN_BAIN = {
    "display_name":        "Rueben Bain",
    "school_canonical":    "Miami",
    "position_group":      "EDGE",
    "consensus_rank":      5,
    "raw_score":           85.6,
    "apex_composite":      85.6,
    "pvc":                 1.00,
    "apex_tier":           "ELITE",
    "apex_archetype":      "EDGE-4 Athletic Dominator",
    "position_rank_label": "#2 at EDGE",
    "eval_confidence":     "A",
    "divergence_delta":    1,
    "ras_score":           9.12,
    "v_processing":        7.8,
    "v_athleticism":       9.1,
    "v_comp_tough":        8.7,
    "v_injury":            9.2,
    "v_scheme_vers":       8.2,
    "v_production":        8.9,
    "v_dev_traj":          9.0,
    "v_character":         8.7,
    "fm_codes":            [3, 6],
    "fm_labels":           ["FM-3 Processing Wall", "FM-6 Role Mismatch"],
    "capital_base":        "R1 Picks 1\u201310",
    "capital_note":        "Franchise EDGE rushers drafted top-10 at 3\u00d7 rate of any other position",
    "tags":                "CRUSH,Two-Way Premium",
    "signature_play":      "Third-and-long vs Florida State \u2014 beats RT with pure first-step quickness and bends around the edge for strip-sack fumble that Miami recovered for touchdown. The athletic dominance in its purest form.",
    "strengths":           "First-step explosion generates consistent separation before tackles establish hand placement \u2014 12 sacks and 18.5 TFL in 2024 vs ACC competition\nNatural leverage at 6'2\" 245 lbs collapses pockets from multiple rush lanes \u2014 2.8 pressures per game vs Power 4\nMotor runs hot through four quarters \u2014 4 fourth-quarter sacks including game-winner vs Florida State with 2:14 remaining",
    "red_flags":           "Limited counter package development \u2014 tackles who survive initial rush can neutralize him on extended reps\nPursuit angles become inefficient when runners bounce outside gap responsibility \u2014 run defense liability in zone schemes\nHand technique remains raw \u2014 inconsistent placement and timing on power moves drew two holding calls vs Notre Dame",
    "translation_risk":    "If drafted by a team expecting immediate counter move mastery rather than developing his technique around elite athletic gifts, production could stagnate while learning complex hand sequences that don't match his natural win mechanism.",
    "comps": [
        {
            "type":       "hit",
            "type_label": "Archetype Ceiling",
            "name":       "Myles Garrett",
            "desc":       "EDGE-4 full development ceiling \u2014 generational tools plus confirmed character architecture produced EDGE-1 adjacent outcomes in NFL",
            "years":      "2017 \u2013 Present"
        },
        {
            "type":       "partial",
            "type_label": "FM Risk Comp",
            "name":       "Travon Walker",
            "desc":       "EDGE-4 unresolved development \u2014 tools justified #1 capital, technique below projection through Year 3. Outcome open as of 2026",
            "years":      "2022 \u2013 Present"
        }
    ],
    "snapshot_date":       "2026-03-18",
    "prospect_id":         1042,
}


# ---------------------------------------------------------------------------
# Prospect Card v2 renderer
# ---------------------------------------------------------------------------

def html_page(prospect: dict) -> str:
    """
    Renders a DraftOS prospect card as a self-contained HTML string.
    All CSS is embedded. No external dependencies except Google Fonts CDN.

    Args:
        prospect: Dict matching the DraftOS card schema (see DRAFTOS_CARD_HANDOFF.md)

    Returns:
        Complete HTML string ready to write to .html file
    """

    # -------------------------------------------------------------------------
    # Helper: escape user strings for safe HTML insertion
    # -------------------------------------------------------------------------
    def e(s):
        return _html.escape(str(s)) if s is not None else ""

    # -------------------------------------------------------------------------
    # 1. Unpack and normalize all fields with defaults
    # -------------------------------------------------------------------------
    display_name        = prospect.get("display_name") or "Unknown"
    school_canonical    = prospect.get("school_canonical") or ""
    position_group      = prospect.get("position_group") or ""
    consensus_rank      = prospect.get("consensus_rank")
    raw_score           = prospect.get("raw_score") or 0.0
    apex_composite      = prospect.get("apex_composite") or 0.0
    pvc                 = prospect.get("pvc") or 1.0
    apex_tier           = (prospect.get("apex_tier") or "DAY3").upper()
    apex_archetype      = prospect.get("apex_archetype") or ""
    position_rank_label = prospect.get("position_rank_label")
    eval_confidence     = prospect.get("eval_confidence") or "C"
    divergence_delta    = prospect.get("divergence_delta")
    ras_score           = prospect.get("ras_score")
    fm_codes            = prospect.get("fm_codes") or []
    fm_labels           = prospect.get("fm_labels") or []
    capital_base        = prospect.get("capital_base") or ""
    capital_note        = prospect.get("capital_note") or ""
    tags_raw            = prospect.get("tags")
    signature_play      = prospect.get("signature_play")
    strengths_raw       = prospect.get("strengths")
    red_flags_raw       = prospect.get("red_flags")
    translation_risk    = prospect.get("translation_risk")
    comps               = prospect.get("comps") or []
    snapshot_date       = prospect.get("snapshot_date") or "2026-01-01"
    prospect_id         = prospect.get("prospect_id") or 0

    # Live DB fallback: pull curated comps if caller passed none
    if not comps and prospect_id:
        try:
            with connect() as _db_conn:
                comps = get_prospect_comps(_db_conn, prospect_id)
        except Exception as _e:
            logging.warning("html_page: failed to load prospect_comps for pid=%s: %s", prospect_id, _e)

    # -------------------------------------------------------------------------
    # 2. Compute derived values
    # -------------------------------------------------------------------------

    # Name split
    name_parts = display_name.split(" ", 1)
    if len(name_parts) == 2:
        name_html = f"{e(name_parts[0])}<br>{e(name_parts[1])}"
    else:
        name_html = e(display_name)

    # Archetype split
    arch_parts = apex_archetype.split(" ", 1)
    arch_code  = arch_parts[0] if arch_parts else ""
    arch_label = arch_parts[1] if len(arch_parts) > 1 else ""
    # Archetype label may contain spaces — render with <br> on first space
    arch_label_parts = arch_label.split(" ", 1)
    if len(arch_label_parts) == 2:
        arch_label_html = f"{e(arch_label_parts[0])}<br>{e(arch_label_parts[1])}"
    else:
        arch_label_html = e(arch_label)

    # Score display split
    def split_score(val):
        s = f"{val:.1f}"
        parts = s.split(".")
        return parts[0], parts[1] if len(parts) > 1 else "0"

    raw_int, raw_dec       = split_score(raw_score)
    apex_int, apex_dec     = split_score(apex_composite)

    # Trait bar color class
    def trait_class(v):
        if v >= 8.5:
            return "hi"
        elif v >= 7.0:
            return "mid"
        return "lo"

    def trait_width(v):
        return int(v * 10)

    # Formula line
    formula = f"RPG {raw_score} \u00d7 PVC {pvc:.2f} ({e(position_group)}) = APEX {apex_composite}"

    # Confidence display
    conf_display = {"A": "Tier A", "B": "Tier B", "C": "Tier C"}.get(eval_confidence, e(eval_confidence))

    # Divergence display
    def fmt_divergence(delta):
        if delta is None:
            return ("", "N/A")
        if abs(delta) < 3:
            return ("", "Aligned")
        elif delta > 0:
            return ("amber", f"APEX High +{delta}")
        else:
            return ("amber", f"APEX Low {delta}")

    div_class, div_label = fmt_divergence(divergence_delta)

    # Watermark date
    try:
        wm_date = datetime.strptime(snapshot_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except Exception:
        wm_date = snapshot_date

    # Card stamp
    card_stamp = f"#{prospect_id:04d}"

    # Ghost rank
    ghost_rank = f"#{consensus_rank}" if consensus_rank is not None else ""

    # Watermark meta line
    rank_str = f"#{consensus_rank} \u00b7 " if consensus_rank is not None else ""
    wm_meta  = f"{rank_str}{e(position_group)} \u00b7 {e(school_canonical)}<br>Generated {wm_date}"

    # -------------------------------------------------------------------------
    # 3. Tier badge HTML
    # -------------------------------------------------------------------------
    TIER_CONFIG = {
        "ELITE":  ("tier-badge-elite",  "\u2605 Elite",  "Top Tier"),
        "DAY1":   ("tier-badge-day1",   "Day 1",         "Round 1"),
        "DAY2":   ("tier-badge-day2",   "Day 2",         "Round 2-3"),
        "DAY3":   ("tier-badge-day3",   "Day 3",         "Round 4-7"),
        "UDFA-P": ("tier-badge-udfa",   "UDFA",          "Priority"),
        "UDFA":   ("tier-badge-udfa",   "UDFA",          "Free Agent"),
    }
    tier_cfg = TIER_CONFIG.get(apex_tier, TIER_CONFIG["DAY3"])
    tier_badge_html = f"""
        <div class="{tier_cfg[0]}">
          <span class="tier-badge-text">{tier_cfg[1]}</span>
          <span class="tier-badge-sub">{tier_cfg[2]}</span>
        </div>"""

    # -------------------------------------------------------------------------
    # 4. Meta chips HTML
    # -------------------------------------------------------------------------
    meta_chips = []
    if school_canonical:
        meta_chips.append(f'<span class="meta-chip">{e(school_canonical)}</span>')
    if consensus_rank is not None:
        meta_chips.append(f'<span class="meta-chip">Consensus #{consensus_rank}</span>')
    if position_rank_label:
        meta_chips.append(f'<span class="meta-chip hi">{e(position_rank_label)}</span>')
    meta_chips_html = "\n        ".join(meta_chips)

    # -------------------------------------------------------------------------
    # 5. Trait rows HTML
    # -------------------------------------------------------------------------
    TRAITS = [
        ("Football Traits", [
            ("Processing",  prospect.get("v_processing",  0)),
            ("Athleticism", prospect.get("v_athleticism", 0)),
            ("Comp. Tough", prospect.get("v_comp_tough",  0)),
            ("Durability",  prospect.get("v_injury",      0)),
        ]),
        ("System Traits", [
            ("Scheme Vers.", prospect.get("v_scheme_vers", 0)),
            ("Production",   prospect.get("v_production",  0)),
            ("Dev. Traj.",    prospect.get("v_dev_traj",   0)),
            ("Character",    prospect.get("v_character",   0)),
        ]),
    ]

    def render_traits(label, rows):
        items = ""
        for name, val in rows:
            tc = trait_class(val)
            tw = trait_width(val)
            items += f"""
        <div class="trait-row">
          <span class="trait-lbl">{name}</span>
          <div class="trait-track"><div class="trait-fill {tc}" style="width:{tw}%"></div></div>
          <span class="trait-val">{val}</span>
        </div>"""
        return f"""
      <div class="traits-section">
        <div class="section-header">{label}</div>{items}
      </div>"""

    traits_html = render_traits("Football Traits", TRAITS[0][1]) + render_traits("System Traits", TRAITS[1][1])

    # -------------------------------------------------------------------------
    # 6. RAS block HTML (conditional)
    # -------------------------------------------------------------------------
    if ras_score is not None:
        ras_html = f"""
          <div class="ras-block">
            <div class="ras-lbl">RAS Score</div>
            <div class="ras-val">{ras_score}</div>
          </div>"""
    else:
        ras_html = ""

    # -------------------------------------------------------------------------
    # 7. FM Risk HTML (conditional)
    # -------------------------------------------------------------------------
    if fm_codes:
        pips = ""
        for i in range(1, 7):
            if i in fm_codes:
                pips += f'\n          <div class="fm-pip p{i}"></div>'
            else:
                pips += '\n          <div class="fm-pip"></div>'

        tag_items = ""
        for lbl in fm_labels:
            # Extract FM number from label like "FM-3 Processing Wall"
            fm_num = ""
            lbl_stripped = lbl.strip()
            if lbl_stripped.startswith("FM-") and len(lbl_stripped) > 3:
                try:
                    fm_num = lbl_stripped[3]
                except IndexError:
                    fm_num = ""
            tag_items += f'\n          <span class="fm-tag t{fm_num}">{e(lbl)}</span>'

        fm_section_html = f"""
      <div class="fm-section">
        <div class="sec-lbl">Failure Mode Risk</div>
        <div class="fm-pip-bar">{pips}
        </div>
        <div class="fm-tags">{tag_items}
        </div>
      </div>"""
    else:
        fm_section_html = ""

    # -------------------------------------------------------------------------
    # 8. Signature play HTML (conditional)
    # -------------------------------------------------------------------------
    if signature_play:
        sig_play_html = f"""
      <div class="sig-play">
        <div class="sig-lbl"><span class="sig-lbl-dot"></span>Signature Play</div>
        <div class="sig-text">{e(signature_play)}</div>
      </div>"""
    else:
        sig_play_html = ""

    # -------------------------------------------------------------------------
    # 9. Strengths / Red Flags HTML (conditional)
    # -------------------------------------------------------------------------
    def render_panel(color, header_text, items_raw):
        if not items_raw:
            return ""
        items_list = [x.strip() for x in items_raw.split("\n") if x.strip()][:3]
        item_html = ""
        for item in items_list:
            item_html += f"""
          <div class="panel-item">
            <span class="pi-dot {color}"></span>
            {e(item)}
          </div>"""
        return f"""
        <div class="panel">
          <div class="panel-hdr {color}">
            <span class="ph-ind {color}"></span>
            {header_text}
          </div>{item_html}
        </div>"""

    strengths_panel  = render_panel("g", "Strengths", strengths_raw)
    red_flags_panel  = render_panel("r", "Red Flags", red_flags_raw)

    if strengths_panel or red_flags_panel:
        two_col_html = f"""
      <div class="two-col">{strengths_panel}{red_flags_panel}
      </div>"""
    else:
        two_col_html = ""

    # -------------------------------------------------------------------------
    # 10. Translation risk HTML (conditional)
    # -------------------------------------------------------------------------
    if translation_risk:
        risk_banner_html = f"""
      <div class="risk-banner">
        <span class="risk-icon">!</span>
        <div class="risk-text">{e(translation_risk)}</div>
      </div>"""
    else:
        risk_banner_html = ""

    # -------------------------------------------------------------------------
    # 11. Historical comps HTML (conditional)
    # -------------------------------------------------------------------------
    def render_comp_card(comp):
        ctype      = comp.get("type", "partial")
        type_label = comp.get("type_label", "")
        name       = comp.get("name", "")
        desc       = comp.get("desc", "")
        years      = comp.get("years", "")
        badge_text = ctype.capitalize()
        return f"""
          <div class="comp-card {ctype}">
            <div class="comp-type-lbl {ctype}">{e(type_label)}</div>
            <div class="comp-name">{e(name)}</div>
            <span class="comp-badge {ctype}">{badge_text}</span>
            <div class="comp-desc">{e(desc)}</div>
            <div class="comp-year">{e(years)}</div>
          </div>"""

    if comps:
        comp_cards = "".join(render_comp_card(c) for c in comps[:2])
        comps_html = f"""
      <div class="comps-section">
        <div class="sec-lbl">Historical Comps</div>
        <div class="comps-row">{comp_cards}
        </div>
      </div>"""
    else:
        comps_html = ""

    # -------------------------------------------------------------------------
    # 12. Tags HTML (conditional)
    # -------------------------------------------------------------------------
    TAG_CLASSES = {
        "CRUSH":            "crush",
        "Two-Way Premium":  "tw",
        "Walk-On Flag":     "walkOn",
        "Schwesinger Full": "schwes",
    }

    if tags_raw:
        tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
        tag_items_html = ""
        for tag in tag_list:
            css_cls = TAG_CLASSES.get(tag, "neutral")
            tag_items_html += f'<span class="htag {css_cls}">{e(tag)}</span>\n          '
        tags_html = f"""
        <div class="header-tags">
          {tag_items_html}
        </div>"""
    else:
        tags_html = ""

    # -------------------------------------------------------------------------
    # 13. Capital note line (handle None)
    # -------------------------------------------------------------------------
    cap_note_html = f'<div class="capital-note">{e(capital_note)}</div>' if capital_note else ""

    # -------------------------------------------------------------------------
    # 14. Assemble final HTML
    # -------------------------------------------------------------------------
    html_string = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DraftOS \u2014 {e(display_name)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;500;600;700;800;900&family=Barlow:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&display=swap" rel="stylesheet">
<style>
:root {{
  --ink:       #0a0c0f;
  --ink2:      #0f1318;
  --ink3:      #161b22;
  --ink4:      #1c2330;
  --ink5:      #222b38;
  --wire:      rgba(255,255,255,0.06);
  --wire2:     rgba(255,255,255,0.11);
  --wire3:     rgba(255,255,255,0.20);
  --dim:       rgba(255,255,255,0.32);
  --mid:       rgba(255,255,255,0.52);
  --text:      rgba(255,255,255,0.88);
  --cold:      #7eb4e2;
  --cold2:     #4a90d4;
  --cold-dim:  rgba(126,180,226,0.10);
  --cold-dim2: rgba(126,180,226,0.20);
  --amber:     #e8a84a;
  --amber2:    #c98828;
  --amber-dim: rgba(232,168,74,0.13);
  --red:       #e05c5c;
  --red-dim:   rgba(224,92,92,0.12);
  --green:     #5ab87a;
  --green-dim: rgba(90,184,122,0.12);
  --elite:     #f0c040;
  --elite2:    #c89820;
  --elite-dim: rgba(240,192,64,0.12);
  --fm3:       #5b9cf0;
  --fm3-dim:   rgba(91,156,240,0.15);
  --fm6:       #a57ee0;
  --fm6-dim:   rgba(165,126,224,0.15);
  --prism-1:   #7eb4e2;
  --prism-2:   #a57ee0;
  --prism-3:   #e8a84a;
  --prism-4:   #5ab87a;
}}

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  background: #060809;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 40px 20px;
  font-family: 'Barlow', sans-serif;
}}

/* CARD SHELL */
.card {{
  width: 900px;
  background: var(--ink);
  position: relative;
  overflow: hidden;
  border: 1px solid var(--wire2);
}}

.prism-strip {{
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: linear-gradient(
    180deg,
    var(--prism-1) 0%,
    var(--prism-2) 30%,
    var(--prism-3) 60%,
    var(--prism-4) 100%
  );
  z-index: 10;
}}

.top-bar {{
  height: 2px;
  background: linear-gradient(90deg,
    var(--cold2) 0%,
    var(--cold) 35%,
    rgba(126,180,226,0.3) 70%,
    transparent 100%
  );
  position: relative;
  z-index: 5;
}}

.card::after {{
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    repeating-linear-gradient(
      0deg,
      rgba(255,255,255,0.012) 0px,
      rgba(255,255,255,0.012) 1px,
      transparent 1px,
      transparent 3px
    );
  pointer-events: none;
  z-index: 2;
}}

.card::before {{
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
  z-index: 1;
}}

/* LAYOUT */
.layout {{
  display: grid;
  grid-template-columns: 256px 1fr;
  min-height: 680px;
  position: relative;
  z-index: 3;
}}

/* LEFT PANEL */
.left {{
  background: var(--ink2);
  border-right: 1px solid var(--wire2);
  padding: 30px 22px 26px 26px;
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
  overflow: hidden;
}}

.left::before {{
  content: '';
  position: absolute;
  top: -60px; right: -80px;
  width: 220px; height: 220px;
  background: radial-gradient(ellipse at center,
    rgba(126,180,226,0.06) 0%,
    transparent 70%
  );
  pointer-events: none;
}}

.pos-chip {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--cold-dim2);
  border: 1px solid rgba(74,144,212,0.5);
  border-radius: 3px;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--cold);
  text-transform: uppercase;
  margin-bottom: 12px;
  width: fit-content;
}}

.pos-chip-dot {{
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--cold);
  opacity: 0.7;
}}

.player-name {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 54px;
  font-weight: 900;
  line-height: 0.88;
  letter-spacing: -0.02em;
  text-transform: uppercase;
  color: var(--text);
  margin-bottom: 16px;
  position: relative;
}}

.name-slash {{
  width: 40px;
  height: 2px;
  background: linear-gradient(90deg, var(--cold2), transparent);
  margin-bottom: 16px;
  margin-top: -8px;
}}

.meta-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 22px;
}}

.meta-chip {{
  font-size: 10px;
  font-weight: 600;
  color: var(--mid);
  background: var(--wire);
  border: 1px solid var(--wire2);
  border-radius: 3px;
  padding: 2px 8px;
  letter-spacing: 0.04em;
}}

.meta-chip.hi {{
  color: var(--cold);
  border-color: rgba(126,180,226,0.28);
  background: var(--cold-dim);
}}

/* APEX SCORE WINDOW */
.apex-window {{
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-radius: 6px;
  padding: 18px 18px 14px;
  margin-bottom: 18px;
  position: relative;
  overflow: hidden;
}}

.apex-window::before {{
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    135deg,
    rgba(126,180,226,0.04) 0%,
    transparent 40%,
    rgba(240,192,64,0.04) 100%
  );
  pointer-events: none;
}}

.score-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}}

.score-lbl {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 3px;
}}

.score-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 44px;
  font-weight: 800;
  line-height: 0.95;
  color: var(--cold);
  letter-spacing: -0.01em;
}}

.score-val.apex {{ color: var(--amber); }}

.score-decimal {{
  font-size: 22px;
  font-weight: 600;
  opacity: 0.7;
}}

/* TIER BADGES */
.tier-badge-elite {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--elite-dim);
  border: 1px solid rgba(240,192,64,0.35);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}}

.tier-badge-day1 {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(126,180,226,0.10);
  border: 1px solid rgba(126,180,226,0.32);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}}

.tier-badge-day1 .tier-badge-text {{ color: var(--cold); }}
.tier-badge-day1 .tier-badge-sub  {{ color: rgba(126,180,226,0.5); }}

.tier-badge-day2 {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(90,184,122,0.10);
  border: 1px solid rgba(90,184,122,0.28);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}}

.tier-badge-day2 .tier-badge-text {{ color: var(--green); }}
.tier-badge-day2 .tier-badge-sub  {{ color: rgba(90,184,122,0.45); }}

.tier-badge-day3 {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--wire);
  border: 1px solid var(--wire2);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}}

.tier-badge-day3 .tier-badge-text {{ color: var(--mid); }}
.tier-badge-day3 .tier-badge-sub  {{ color: var(--dim); }}

.tier-badge-udfa {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  border: 1px solid var(--wire);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}}

.tier-badge-udfa .tier-badge-text {{ color: var(--dim); }}
.tier-badge-udfa .tier-badge-sub  {{ color: rgba(255,255,255,0.18); }}

.tier-badge-text {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 0.12em;
  color: var(--elite);
  text-transform: uppercase;
}}

.tier-badge-sub {{
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: rgba(240,192,64,0.55);
  text-transform: uppercase;
}}

.formula-line {{
  font-size: 9px;
  color: var(--dim);
  font-family: 'Barlow Condensed', sans-serif;
  letter-spacing: 0.04em;
  opacity: 0.7;
}}

/* TRAIT METERS */
.traits-section {{ margin-bottom: 16px; }}

.section-header {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 9px;
  display: flex;
  align-items: center;
  gap: 8px;
}}

.section-header::after {{
  content: '';
  flex: 1;
  height: 1px;
  background: var(--wire);
}}

.trait-row {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}}

.trait-lbl {{
  font-size: 9px;
  font-weight: 500;
  color: var(--mid);
  width: 64px;
  flex-shrink: 0;
  letter-spacing: 0.02em;
}}

.trait-track {{
  flex: 1;
  height: 2px;
  background: var(--wire);
  border-radius: 1px;
  overflow: hidden;
  position: relative;
}}

.trait-fill {{ height: 100%; border-radius: 1px; }}
.trait-fill.hi  {{ background: var(--green); }}
.trait-fill.mid {{ background: var(--cold); }}
.trait-fill.lo  {{ background: var(--amber); }}

.trait-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 11px;
  font-weight: 700;
  color: var(--text);
  width: 24px;
  text-align: right;
}}

/* CONFIDENCE / DIVERGENCE */
.conf-row {{
  display: flex;
  gap: 7px;
  margin-bottom: 16px;
}}

.conf-item {{
  flex: 1;
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-radius: 5px;
  padding: 8px 10px;
}}

.conf-lbl {{
  font-size: 8px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 3px;
  font-weight: 700;
}}

.conf-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.03em;
}}

.conf-val.green {{ color: var(--green); }}
.conf-val.amber {{ color: var(--amber); }}

/* CAPITAL */
.capital-block {{
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-radius: 5px;
  padding: 10px 12px;
  margin-bottom: 14px;
}}

.capital-lbl {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 4px;
}}

.capital-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 3px;
}}

.capital-note {{
  font-size: 9px;
  color: var(--dim);
  line-height: 1.5;
}}

/* WATERMARK */
.watermark {{
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--wire);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}}

.brand-lockup {{
  display: flex;
  flex-direction: column;
  gap: 1px;
}}

.brand-logo {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 15px;
  font-weight: 900;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.15);
  line-height: 1;
}}

.brand-version {{
  font-size: 8px;
  color: rgba(255,255,255,0.12);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}

.watermark-meta {{
  font-size: 8px;
  color: var(--dim);
  text-align: right;
  letter-spacing: 0.04em;
  line-height: 1.7;
}}

/* RIGHT PANEL */
.right {{
  padding: 26px 30px 26px 28px;
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
}}

.right::before {{
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 280px; height: 280px;
  background: conic-gradient(
    from 200deg at 100% 0%,
    rgba(232,168,74,0.04) 0deg,
    rgba(126,180,226,0.04) 60deg,
    transparent 120deg
  );
  pointer-events: none;
}}

/* HEADER ZONE */
.header-zone {{
  border-bottom: 1px solid var(--wire);
  padding-bottom: 20px;
  margin-bottom: 20px;
  position: relative;
}}

.rank-ghost {{
  position: absolute;
  right: 0; top: -8px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 110px;
  font-weight: 900;
  color: rgba(255,255,255,0.025);
  letter-spacing: -0.04em;
  line-height: 1;
  pointer-events: none;
  user-select: none;
}}

.header-row {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 6px;
}}

.archetype-code {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--cold);
  margin-bottom: 4px;
}}

.archetype-name {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 34px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--amber);
  line-height: 0.95;
}}

.ras-block {{ text-align: right; flex-shrink: 0; }}

.ras-lbl {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 2px;
}}

.ras-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 28px;
  font-weight: 800;
  color: var(--green);
  line-height: 1;
}}

.header-tags {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}}

.htag {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}}

.htag.crush   {{ background: rgba(90,184,122,0.12); border: 1px solid rgba(90,184,122,0.3); color: var(--green); }}
.htag.tw      {{ background: rgba(126,180,226,0.10); border: 1px solid rgba(126,180,226,0.28); color: var(--cold); }}
.htag.walkOn  {{ background: rgba(232,168,74,0.10); border: 1px solid rgba(232,168,74,0.28); color: var(--amber); }}
.htag.schwes  {{ background: rgba(126,180,226,0.10); border: 1px solid rgba(126,180,226,0.28); color: var(--cold); }}
.htag.neutral {{ background: var(--wire); border: 1px solid var(--wire2); color: var(--mid); }}

/* FM RISK */
.fm-section {{ margin-bottom: 18px; }}

.sec-lbl {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 9px;
  display: flex;
  align-items: center;
  gap: 8px;
}}

.sec-lbl::after {{
  content: '';
  flex: 1;
  height: 1px;
  background: var(--wire);
}}

.fm-pip-bar {{
  display: flex;
  gap: 3px;
  margin-bottom: 9px;
}}

.fm-pip {{
  flex: 1;
  height: 5px;
  border-radius: 1.5px;
  background: var(--wire);
}}

.fm-pip.p1 {{ background: #e05c5c; }}
.fm-pip.p2 {{ background: #e8a84a; }}
.fm-pip.p3 {{ background: #5b9cf0; }}
.fm-pip.p4 {{ background: #e05c5c; }}
.fm-pip.p5 {{ background: #c47ae0; }}
.fm-pip.p6 {{ background: #a57ee0; }}

.fm-tags {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}}

.fm-tag {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
}}

.fm-tag.t1 {{ background: rgba(224,92,92,0.15);   border: 1px solid rgba(224,92,92,0.3);   color: #f08080; }}
.fm-tag.t2 {{ background: rgba(232,168,74,0.13);  border: 1px solid rgba(232,168,74,0.3);  color: #f0b866; }}
.fm-tag.t3 {{ background: var(--fm3-dim);          border: 1px solid rgba(91,156,240,0.3);  color: #8ab8f5; }}
.fm-tag.t4 {{ background: rgba(224,92,92,0.15);   border: 1px solid rgba(224,92,92,0.3);   color: #f08080; }}
.fm-tag.t5 {{ background: rgba(196,122,224,0.15); border: 1px solid rgba(196,122,224,0.3); color: #d4a0f0; }}
.fm-tag.t6 {{ background: var(--fm6-dim);          border: 1px solid rgba(165,126,224,0.3); color: #c4a5f5; }}

/* SIGNATURE PLAY */
.sig-play {{
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-left: 3px solid var(--cold2);
  border-radius: 0 5px 5px 0;
  padding: 12px 16px;
  margin-bottom: 18px;
}}

.sig-lbl {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--cold);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}}

.sig-lbl-dot {{
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--cold2);
}}

.sig-text {{
  font-size: 11px;
  line-height: 1.6;
  color: var(--mid);
  font-style: italic;
}}

/* STRENGTHS & RED FLAGS */
.two-col {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}}

.panel {{
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-radius: 5px;
  padding: 12px 13px;
}}

.panel-hdr {{
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 9px;
  display: flex;
  align-items: center;
  gap: 6px;
}}

.panel-hdr.g {{ color: var(--green); }}
.panel-hdr.r {{ color: var(--red); }}

.ph-ind {{ width: 6px; height: 6px; border-radius: 1px; flex-shrink: 0; }}
.ph-ind.g {{ background: var(--green); }}
.ph-ind.r {{ background: var(--red); }}

.panel-item {{
  font-size: 10px;
  line-height: 1.55;
  color: var(--mid);
  padding: 5px 0;
  border-top: 1px solid var(--wire);
  display: flex;
  gap: 7px;
  align-items: flex-start;
}}

.panel-item:first-of-type {{ border-top: none; }}

.pi-dot {{ width: 3px; height: 3px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }}
.pi-dot.g {{ background: var(--green); }}
.pi-dot.r {{ background: rgba(224,92,92,0.55); }}

/* TRANSLATION RISK */
.risk-banner {{
  background: var(--amber-dim);
  border: 1px solid rgba(232,168,74,0.22);
  border-left: 3px solid var(--amber2);
  border-radius: 0 5px 5px 0;
  padding: 10px 14px;
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 18px;
}}

.risk-icon {{
  font-size: 12px;
  line-height: 1.4;
  flex-shrink: 0;
  color: var(--amber);
  font-weight: 800;
  font-family: 'Barlow Condensed', sans-serif;
  margin-top: 1px;
}}

.risk-text {{
  font-size: 10px;
  line-height: 1.6;
  color: rgba(232,168,74,0.80);
}}

/* COMP CARDS */
.comps-section {{ flex: 1; }}

.comps-row {{ display: flex; gap: 10px; }}

.comp-card {{
  flex: 1;
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-radius: 5px;
  padding: 14px 14px;
  position: relative;
  overflow: hidden;
}}

.comp-card::before {{
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
}}

.comp-card.hit::before     {{ background: linear-gradient(180deg, var(--green), rgba(90,184,122,0.4)); }}
.comp-card.partial::before {{ background: linear-gradient(180deg, var(--amber), rgba(232,168,74,0.4)); }}
.comp-card.miss::before    {{ background: linear-gradient(180deg, var(--red), rgba(224,92,92,0.4)); }}

.comp-card::after {{
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.025) 0%, transparent 50%);
  pointer-events: none;
}}

.comp-type-lbl {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 4px;
}}

.comp-type-lbl.hit     {{ color: var(--green); }}
.comp-type-lbl.partial {{ color: var(--amber); }}
.comp-type-lbl.miss    {{ color: var(--red); }}

.comp-name {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 22px;
  font-weight: 900;
  letter-spacing: 0.01em;
  text-transform: uppercase;
  color: var(--text);
  line-height: 1;
  margin-bottom: 6px;
}}

.comp-badge {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 2px;
  margin-bottom: 8px;
}}

.comp-badge.hit     {{ background: var(--green-dim); color: var(--green); border: 1px solid rgba(90,184,122,0.25); }}
.comp-badge.partial {{ background: var(--amber-dim); color: var(--amber); border: 1px solid rgba(232,168,74,0.25); }}
.comp-badge.miss    {{ background: var(--red-dim);   color: var(--red);   border: 1px solid rgba(224,92,92,0.25); }}

.comp-badge::before {{
  content: '';
  width: 4px; height: 4px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.8;
}}

.comp-desc {{
  font-size: 9px;
  line-height: 1.6;
  color: var(--dim);
  margin-bottom: 6px;
}}

.comp-year {{
  font-size: 8px;
  color: rgba(255,255,255,0.18);
  font-family: 'Barlow Condensed', sans-serif;
  letter-spacing: 0.06em;
}}

/* CARD NUMBER STAMP */
.card-stamp {{
  position: absolute;
  bottom: 18px;
  right: 24px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: rgba(255,255,255,0.10);
  text-transform: uppercase;
  z-index: 4;
}}
</style>
</head>
<body>

<div class="card">
  <div class="prism-strip"></div>
  <div class="top-bar"></div>

  <div class="layout">

    <!-- LEFT PANEL -->
    <div class="left">

      <div class="pos-chip">
        <span class="pos-chip-dot"></span>
        {e(position_group)}
      </div>

      <div class="player-name">
        {name_html}
      </div>
      <div class="name-slash"></div>

      <div class="meta-row">
        {meta_chips_html}
      </div>

      <div class="apex-window">
        <div class="score-grid">
          <div class="score-item">
            <div class="score-lbl">Player Grade</div>
            <div class="score-val">{raw_int}<span class="score-decimal">.{raw_dec}</span></div>
          </div>
          <div class="score-item">
            <div class="score-lbl">APEX Score</div>
            <div class="score-val apex">{apex_int}<span class="score-decimal">.{apex_dec}</span></div>
          </div>
        </div>
        {tier_badge_html}
        <div class="formula-line">{formula}</div>
      </div>

      {traits_html}

      <div class="conf-row">
        <div class="conf-item">
          <div class="conf-lbl">Confidence</div>
          <div class="conf-val green">{conf_display}</div>
        </div>
        <div class="conf-item">
          <div class="conf-lbl">Divergence</div>
          <div class="conf-val {div_class}">{div_label}</div>
        </div>
      </div>

      <div class="capital-block">
        <div class="capital-lbl">Draft Capital</div>
        <div class="capital-val">{e(capital_base)}</div>
        {cap_note_html}
      </div>

      <div class="watermark">
        <div class="brand-lockup">
          <span class="brand-logo">DraftOS</span>
          <span class="brand-version">v2.3 \u00b7 2026</span>
        </div>
        <div class="watermark-meta">
          {wm_meta}
        </div>
      </div>

    </div>
    <!-- end left -->

    <!-- RIGHT PANEL -->
    <div class="right">

      <div class="header-zone">
        <div class="rank-ghost">{ghost_rank}</div>

        <div class="header-row">
          <div>
            <div class="archetype-code">{e(arch_code)}</div>
            <div class="archetype-name">{arch_label_html}</div>
          </div>{ras_html}
        </div>
        {tags_html}
      </div>

      {fm_section_html}

      {sig_play_html}

      {two_col_html}

      {risk_banner_html}

      {comps_html}

    </div>
    <!-- end right -->

  </div>
  <!-- end layout -->

  <div class="card-stamp">DRAFTOS \u00b7 2026 DRAFT CLASS \u00b7 {card_stamp}</div>

</div>

</body>
</html>"""

    return html_string


# ---------------------------------------------------------------------------
# Report pack CLI (unchanged logic — calls html_report_page)
# ---------------------------------------------------------------------------

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

    source_health = find_best_file(
        exports_dir,
        [f"source_health_{stamp}_{args.season}_{args.model}.csv", f"source_health_*_{args.season}_{args.model}.csv"],
    )
    conf_summary = find_best_file(
        exports_dir,
        [f"confidence_summary_{stamp}_{args.season}_{args.model}.csv", f"confidence_summary_*_{args.season}_{args.model}.csv"],
    )

    pages: List[Tuple[str, str, Optional[Path]]] = [
        ("Board", "board.html", board_file),
        ("Movers Daily", "movers_daily.html", movers_daily),
        (f"Movers Window {args.window}", "movers_window.html", movers_window),
        (f"Volatility Window {args.window}", "volatility.html", volatility_window),
        ("Source Health", "source_health.html", source_health),
        ("Confidence Summary", "confidence.html", conf_summary),
    ]

    nav_links = " ".join(
        [f'<a href="{_html.escape(fname)}">{_html.escape(label)}</a>' for (label, fname, _p) in pages]
        + ['<a href="index.html">Index</a>']
    )
    subtitle = f"Season {args.season}, model {args.model}, snapshot {snapshot_id} ({snapshot_date_utc})"

    for label, fname, path in pages:
        if path is None:
            body = f'<div class="missing">Missing export file for {_html.escape(label)}. Run the weekly pipeline to generate exports.</div>'
            page = html_report_page(f"DraftOS Report: {label}", subtitle, body, nav_links)
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
        page = html_report_page(f"DraftOS Report: {label}", subtitle, body, nav_links)
        write_text(reports_dir / fname, page)

    items = []
    for label, fname, path in pages:
        status = "OK" if path and path.exists() else "Missing"
        cls = "chip chip-good" if status == "OK" else "chip chip-bad"
        items.append(
            f"""
            <tr>
              <td><a href="{_html.escape(fname)}">{escape_cell(label)}</a></td>
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
    index_page = html_report_page("DraftOS Report Pack", subtitle, index_body, nav_links)
    write_text(reports_dir / "index.html", index_page)

    print(f"OK: HTML reports generated: {reports_dir}")
    print(f"OPEN: {reports_dir / 'index.html'}")


if __name__ == "__main__":
    main()
