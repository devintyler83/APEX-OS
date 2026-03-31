"""
DraftOS — export_reports_html.py  (share card version)
Replaces the existing html_page() function body.
Renders a simplified share card designed for PNG export via export_png.py.

Usage:
    from export_reports_html_share import html_page
    html_str = html_page(prospect_dict)
    # Then render to PNG:
    from export_png import export_from_prospect_dict
    png_path = export_from_prospect_dict(prospect_dict, html_page, output_dir="reports/")
"""

import html as _html
from datetime import datetime
from pathlib import Path

# ── Load embedded fonts once at module level ────────────────────────────────
# fonts_embedded.css lives next to this script (or set DRAFTOS_FONTS_PATH env var)
import os as _os
from archetype_defs import ARCHETYPE_DEFS as _ARCHETYPE_DEFS

_FONTS_CSS = ""
_FONT_PATHS = [
    _os.path.join(_os.path.dirname(__file__), "fonts_embedded.css"),
    _os.path.join(_os.path.dirname(__file__), "scripts", "fonts_embedded.css"),
    "C:/DraftOS/scripts/fonts_embedded.css",
    "fonts_embedded.css",
]
for _fp in _FONT_PATHS:
    if _os.path.exists(_fp):
        with open(_fp, "r", encoding="utf-8") as _f:
            _FONTS_CSS = _f.read()
        break

if not _FONTS_CSS:
    # Fall back to Google Fonts CDN — works in browser, not in headless render
    _FONTS_CSS = ""
    _GOOGLE_FONTS_LINK = '<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;500;600;700;800;900&family=Barlow:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&display=swap" rel="stylesheet">'
else:
    _GOOGLE_FONTS_LINK = ""


# ── Helper functions ─────────────────────────────────────────────────────────

def e(s) -> str:
    """Escape a value for safe HTML insertion."""
    if s is None:
        return ""
    return _html.escape(str(s))


def score_split(val) -> tuple[str, str]:
    """Split a float score into integer and decimal parts for display."""
    if val is None:
        return ("--", "0")
    s = f"{float(val):.1f}"
    parts = s.split(".")
    return (parts[0], parts[1] if len(parts) > 1 else "0")


def trait_class(val) -> str:
    """Return CSS fill class for a trait bar based on value."""
    if val is None:
        return "lo"
    v = float(val)
    if v >= 8.5:
        return "hi"
    elif v >= 7.0:
        return "mid"
    return "lo"


def trait_width(val) -> int:
    """Return bar fill percentage (0–100) for a trait value (0–10)."""
    if val is None:
        return 0
    return min(100, max(0, int(float(val) * 10)))


def tier_badge_html(tier: str, formula: str) -> str:
    """Build the tier badge + formula line HTML."""
    tier_map = {
        "ELITE": ("tier-badge-elite", "tier-text-elite", "tier-sub-elite", "★ Elite",   "Top Tier"),
        "DAY1":  ("tier-badge-day1",  "tier-text-day1",  "tier-sub-day1",  "Day 1",     "Round 1"),
        "DAY2":  ("tier-badge-day2",  "tier-text-day2",  "tier-sub-day2",  "Day 2",     "Round 2"),
        "DAY3":  ("tier-badge-day3",  "tier-text-day3",  "tier-sub-day3",  "Day 3",     "Round 3"),
        "UDFA-P":("tier-badge-udfa",  "tier-text-udfa",  "tier-sub-udfa",  "UDFA",      "Priority"),
        "UDFA":  ("tier-badge-udfa",  "tier-text-udfa",  "tier-sub-udfa",  "UDFA",      ""),
    }
    bd, tt, ts, label, sub = tier_map.get(tier.upper(), tier_map["DAY3"])
    sub_html = f'<span class="tier-sub {ts}">{e(sub)}</span>' if sub else ""
    return f"""
        <div class="tier-badge {bd}">
          <span class="tier-text {tt}">{label}</span>
          {sub_html}
        </div>
        <div class="formula-line">{e(formula)}</div>"""


def fm_pip_bar_html(fm_codes: list) -> str:
    """Build the 6-pip FM bar HTML."""
    pips = ""
    active = set(fm_codes or [])
    for i in range(1, 7):
        cls = f" p{i}" if i in active else ""
        pips += f'<div class="fm-pip{cls}"></div>'
    return f'<div class="fm-pip-bar">{pips}</div>'


def fm_tags_html(fm_labels: list) -> str:
    """Build FM tag chips HTML."""
    if not fm_labels:
        return ""
    chips = ""
    for label in fm_labels:
        # Extract FM number from label like "FM-3 Processing Wall"
        import re
        m = re.match(r"FM-(\d+)", str(label))
        t_class = f"t{m.group(1)}" if m else "t1"
        chips += f'<span class="fm-tag {t_class}">{e(label)}</span>'
    return f'<div class="fm-tags">{chips}</div>'


def tags_html(tags_str: str) -> str:
    """Build header tag chips from comma-separated tags string."""
    if not tags_str:
        return ""
    tag_class_map = {
        "CRUSH":            "crush",
        "Two-Way Premium":  "tw",
        "Walk-On Flag":     "walkOn",
        "Schwesinger Full": "schwes",
    }
    tag_list = [t.strip() for t in tags_str.split(",") if t.strip()]
    if not tag_list:
        return ""
    chips = ""
    for tag in tag_list:
        cls = tag_class_map.get(tag, "neutral")
        chips += f'<span class="htag {cls}">{e(tag)}</span>'
    return f'<div class="tags-row">{chips}</div>'


def fmt_divergence(delta) -> tuple[str, str]:
    """Return (css_class, display_label) for a divergence delta."""
    if delta is None:
        return ("", "N/A")
    d = int(delta)
    if abs(d) < 3:
        return ("", "Aligned")
    elif d > 0:
        return ("blue", f"APEX +{d}")
    else:
        return ("red", f"APEX {d}")


def fmt_confidence(conf: str) -> tuple[str, str]:
    """Return (css_class, display_label) for eval_confidence."""
    mapping = {
        "A":    ("green", "Tier A"),
        "B":    ("amber", "Tier B"),
        "C":    ("",      "Tier C"),
        "High": ("green", "High"),
        "Medium": ("amber", "Medium"),
        "Low":  ("red",   "Low"),
    }
    return mapping.get(str(conf), ("", str(conf)))


# ── Select 3 headline traits for share card ──────────────────────────────────
# Position-aware: surface the most signal-rich traits for the archetype

_POSITION_HEADLINE_TRAITS = {
    "QB":   [("Processing", "v_processing"), ("Athleticism", "v_athleticism"), ("Scheme Vers.", "v_scheme_vers")],
    "EDGE": [("Athleticism", "v_athleticism"), ("Processing", "v_processing"),  ("Production", "v_production")],
    "DT":   [("Athleticism", "v_athleticism"), ("Comp. Tough", "v_comp_tough"), ("Production", "v_production")],
    "CB":   [("Athleticism", "v_athleticism"), ("Processing", "v_processing"),  ("Comp. Tough", "v_comp_tough")],
    "S":    [("Processing", "v_processing"),   ("Athleticism", "v_athleticism"), ("Production", "v_production")],
    "WR":   [("Athleticism", "v_athleticism"), ("Production", "v_production"),  ("Processing", "v_processing")],
    "OT":   [("Athleticism", "v_athleticism"), ("Comp. Tough", "v_comp_tough"), ("Scheme Vers.", "v_scheme_vers")],
    "OG":   [("Comp. Tough", "v_comp_tough"),  ("Athleticism", "v_athleticism"), ("Production", "v_production")],
    "C":    [("Processing", "v_processing"),   ("Comp. Tough", "v_comp_tough"), ("Durability", "v_injury")],
    "OL":   [("Athleticism", "v_athleticism"), ("Comp. Tough", "v_comp_tough"), ("Production", "v_production")],
    "LB":   [("Processing", "v_processing"),   ("Athleticism", "v_athleticism"), ("Comp. Tough", "v_comp_tough")],
    "ILB":  [("Processing", "v_processing"),   ("Comp. Tough", "v_comp_tough"), ("Production", "v_production")],
    "OLB":  [("Athleticism", "v_athleticism"), ("Processing", "v_processing"),  ("Production", "v_production")],
    "TE":   [("Athleticism", "v_athleticism"), ("Production", "v_production"),  ("Comp. Tough", "v_comp_tough")],
    "RB":   [("Athleticism", "v_athleticism"), ("Comp. Tough", "v_comp_tough"), ("Production", "v_production")],
    "FB":   [("Comp. Tough", "v_comp_tough"),  ("Athleticism", "v_athleticism"), ("Production", "v_production")],
}

_DEFAULT_TRAITS = [
    ("Athleticism", "v_athleticism"),
    ("Processing",  "v_processing"),
    ("Production",  "v_production"),
]

_TRAIT_LABEL_OVERRIDES = {
    "v_injury":      "Durability",
    "v_scheme_vers": "Scheme Vers.",
    "v_dev_traj":    "Dev. Traj.",
    "v_comp_tough":  "Comp. Tough",
}


def headline_traits_html(prospect: dict) -> str:
    """Build the 3 headline trait meter rows, position-aware."""
    pos = str(prospect.get("position_group", "")).upper()
    trait_set = _POSITION_HEADLINE_TRAITS.get(pos, _DEFAULT_TRAITS)
    rows = ""
    for label, key in trait_set:
        display_label = _TRAIT_LABEL_OVERRIDES.get(key, label)
        val = prospect.get(key)
        w = trait_width(val)
        cls = trait_class(val)
        display_val = f"{float(val):.1f}" if val is not None else "--"
        rows += f"""
        <div class="trait-row">
          <span class="trait-lbl">{e(display_label)}</span>
          <div class="trait-track"><div class="trait-fill {cls}" style="width:{w}%"></div></div>
          <span class="trait-val">{display_val}</span>
        </div>"""
    return rows


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
:root {
  --ink:#0a0c0f;--ink2:#0f1318;--ink3:#161b22;
  --wire:rgba(255,255,255,0.06);--wire2:rgba(255,255,255,0.11);
  --dim:rgba(255,255,255,0.32);--mid:rgba(255,255,255,0.55);--text:rgba(255,255,255,0.90);
  --cold:#7eb4e2;--cold2:#4a90d4;--cold-dim:rgba(126,180,226,0.10);--cold-dim2:rgba(126,180,226,0.20);
  --amber:#e8a84a;--amber2:#c98828;
  --red:#e05c5c;--green:#5ab87a;--green-dim:rgba(90,184,122,0.12);
  --elite:#f0c040;--elite-dim:rgba(240,192,64,0.14);
  --prism-1:#7eb4e2;--prism-2:#a57ee0;--prism-3:#e8a84a;--prism-4:#5ab87a;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{background:#060809;display:flex;align-items:flex-start;justify-content:center;padding:40px 20px;font-family:'Barlow',sans-serif;}
.card{width:720px;background:var(--ink);position:relative;overflow:hidden;border:1px solid var(--wire2);}
.prism-strip{position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,var(--prism-1) 0%,var(--prism-2) 30%,var(--prism-3) 60%,var(--prism-4) 100%);z-index:10;}
.top-bar{height:2px;background:linear-gradient(90deg,var(--cold2) 0%,var(--cold) 35%,rgba(126,180,226,0.3) 70%,transparent 100%);}
.card::after{content:'';position:absolute;inset:0;background-image:repeating-linear-gradient(0deg,rgba(255,255,255,0.012) 0px,rgba(255,255,255,0.012) 1px,transparent 1px,transparent 3px);pointer-events:none;z-index:2;}
.card::before{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,0.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.018) 1px,transparent 1px);background-size:32px 32px;pointer-events:none;z-index:1;}
.layout{display:grid;grid-template-columns:230px 1fr;align-items:stretch;position:relative;z-index:3;}
.left{background:var(--ink2);border-right:1px solid var(--wire2);padding:22px 18px 20px 22px;display:flex;flex-direction:column;justify-content:space-between;position:relative;overflow:hidden;}
.left::before{content:'';position:absolute;top:-40px;right:-60px;width:160px;height:160px;background:radial-gradient(ellipse at center,rgba(126,180,226,0.05) 0%,transparent 70%);pointer-events:none;}
.left-top{display:flex;flex-direction:column;gap:11px;}
.left-bottom{display:flex;flex-direction:column;gap:10px;}
.pos-chip{display:inline-flex;align-items:center;gap:5px;background:var(--cold-dim2);border:1px solid rgba(74,144,212,0.5);border-radius:3px;padding:3px 9px;font-size:10px;font-weight:700;letter-spacing:0.10em;color:var(--cold);text-transform:uppercase;width:fit-content;}
.pos-dot{width:4px;height:4px;border-radius:50%;background:var(--cold);opacity:0.7;}
.player-name{font-family:'Barlow Condensed',sans-serif;font-size:44px;font-weight:900;line-height:0.87;letter-spacing:-0.03em;text-transform:uppercase;color:var(--text);word-break:break-word;}
.name-slash{width:32px;height:2px;margin-top:7px;background:linear-gradient(90deg,var(--cold2),transparent);}
.meta-row{display:flex;flex-wrap:wrap;gap:4px;}
.meta-chip{font-size:9px;font-weight:600;color:var(--mid);background:var(--wire);border:1px solid var(--wire2);border-radius:3px;padding:2px 7px;letter-spacing:0.04em;}
.meta-chip.hi{color:var(--cold);border-color:rgba(126,180,226,0.28);background:var(--cold-dim);}
.apex-window{background:var(--ink3);border:1px solid var(--wire2);border-radius:5px;padding:12px 14px 10px;position:relative;overflow:hidden;}
.apex-window::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(126,180,226,0.04) 0%,transparent 40%,rgba(240,192,64,0.04) 100%);pointer-events:none;}
.score-lbl{font-size:7px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:1px;}
.score-val{font-family:'Barlow Condensed',sans-serif;font-size:50px;font-weight:800;line-height:0.92;color:var(--amber);letter-spacing:-0.01em;margin-bottom:8px;}
.score-decimal{font-size:24px;font-weight:600;opacity:0.65;}
.score-dual{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;}
.score-dual .score-lbl{margin-bottom:1px;}
.score-dual .score-val{font-size:34px;margin-bottom:0;}
.score-dual .score-val.rpg{color:var(--cold);}
.score-dual .score-decimal{font-size:17px;}
.tier-badge{display:flex;align-items:center;justify-content:space-between;border-radius:3px;padding:5px 10px;margin-bottom:5px;}
.tier-badge-elite{background:var(--elite-dim);border:1px solid rgba(240,192,64,0.38);}
.tier-badge-day1{background:var(--cold-dim);border:1px solid rgba(126,180,226,0.32);}
.tier-badge-day2{background:var(--green-dim);border:1px solid rgba(90,184,122,0.28);}
.tier-badge-day3{background:var(--wire);border:1px solid var(--wire2);}
.tier-badge-udfa{background:transparent;border:1px solid var(--wire);}
.tier-text{font-family:'Barlow Condensed',sans-serif;font-size:15px;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;}
.tier-text-elite{color:var(--elite);}.tier-text-day1{color:var(--cold);}.tier-text-day2{color:var(--green);}.tier-text-day3{color:var(--mid);}.tier-text-udfa{color:var(--dim);}
.tier-sub{font-size:7px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;}
.tier-sub-elite{color:rgba(240,192,64,0.50);}.tier-sub-day1{color:rgba(126,180,226,0.45);}.tier-sub-day2{color:rgba(90,184,122,0.45);}
.formula-line{font-size:7px;color:var(--dim);font-family:'Barlow Condensed',sans-serif;letter-spacing:0.04em;opacity:0.65;}
.traits-block{}
.traits-lbl{font-size:7px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;color:var(--dim);margin-bottom:7px;display:flex;align-items:center;gap:6px;}
.traits-lbl::after{content:'';flex:1;height:1px;background:var(--wire);}
.trait-row{display:flex;align-items:center;gap:7px;margin-bottom:4px;}
.trait-lbl{font-size:9px;font-weight:500;color:var(--mid);width:64px;flex-shrink:0;}
.trait-track{flex:1;height:3px;background:var(--wire);border-radius:1.5px;overflow:hidden;}
.trait-fill{height:100%;border-radius:1.5px;}
.trait-fill.hi{background:var(--green);}.trait-fill.mid{background:var(--cold);}.trait-fill.lo{background:var(--amber);}
.trait-val{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700;color:var(--text);width:22px;text-align:right;}
.capital-block{background:var(--ink3);border:1px solid var(--wire);border-radius:4px;padding:7px 10px;}
.capital-lbl{font-size:7px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:2px;}
.capital-val{font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;color:var(--text);}
.watermark{padding-top:10px;border-top:1px solid var(--wire);display:flex;align-items:flex-end;justify-content:space-between;}
.brand-logo{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:900;letter-spacing:0.20em;text-transform:uppercase;color:rgba(255,255,255,0.13);}
.watermark-meta{font-size:7px;color:var(--dim);text-align:right;letter-spacing:0.04em;line-height:1.7;}
.right{padding:20px 24px 20px 20px;display:flex;flex-direction:column;gap:12px;position:relative;}
.right::before{content:'';position:absolute;top:0;right:0;width:200px;height:200px;background:conic-gradient(from 200deg at 100% 0%,rgba(232,168,74,0.04) 0deg,rgba(126,180,226,0.04) 60deg,transparent 120deg);pointer-events:none;}
.rank-ghost{position:absolute;right:16px;top:-4px;font-family:'Barlow Condensed',sans-serif;font-size:86px;font-weight:900;color:rgba(255,255,255,0.022);letter-spacing:-0.04em;line-height:1;pointer-events:none;user-select:none;}
.archetype-zone{border-bottom:1px solid var(--wire);padding-bottom:12px;}
.arch-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px;}
.archetype-code{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:var(--cold);margin-bottom:2px;}
.archetype-name{font-family:'Barlow Condensed',sans-serif;font-size:26px;font-weight:800;text-transform:uppercase;letter-spacing:0.02em;color:var(--amber);line-height:0.95;}
.archetype-def{font-size:10px;font-weight:400;color:var(--mid);line-height:1.4;margin-top:6px;font-style:italic;}
.ras-block{text-align:right;flex-shrink:0;}
.ras-lbl{font-size:7px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:1px;}
.ras-val{font-family:'Barlow Condensed',sans-serif;font-size:24px;font-weight:800;color:var(--green);line-height:1;}
.tags-row{display:flex;gap:5px;flex-wrap:wrap;}
.htag{display:inline-flex;align-items:center;padding:2px 8px;border-radius:3px;font-size:8px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;}
.htag.crush{background:rgba(90,184,122,0.12);border:1px solid rgba(90,184,122,0.30);color:var(--green);}
.htag.tw{background:rgba(126,180,226,0.10);border:1px solid rgba(126,180,226,0.28);color:var(--cold);}
.htag.walkOn{background:rgba(232,168,74,0.10);border:1px solid rgba(232,168,74,0.28);color:var(--amber);}
.htag.schwes{background:rgba(126,180,226,0.10);border:1px solid rgba(126,180,226,0.28);color:var(--cold);}
.htag.neutral{background:var(--wire);border:1px solid var(--wire2);color:var(--mid);}
.fm-section{}
.sec-lbl{font-size:7px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;color:var(--dim);margin-bottom:6px;display:flex;align-items:center;gap:6px;}
.sec-lbl::after{content:'';flex:1;height:1px;background:var(--wire);}
.fm-pip-bar{display:flex;gap:3px;margin-bottom:6px;}
.fm-pip{flex:1;height:5px;border-radius:1.5px;background:var(--wire);}
.fm-pip.p1{background:#e05c5c;}.fm-pip.p2{background:#e8a84a;}.fm-pip.p3{background:#5b9cf0;}
.fm-pip.p4{background:#e05c5c;}.fm-pip.p5{background:#c47ae0;}.fm-pip.p6{background:#a57ee0;}
.fm-tags{display:flex;gap:5px;flex-wrap:wrap;}
.fm-tag{display:inline-flex;align-items:center;padding:3px 8px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:0.04em;}
.fm-tag.t1{background:rgba(224,92,92,0.15);border:1px solid rgba(224,92,92,0.30);color:#f08080;}
.fm-tag.t2{background:rgba(232,168,74,0.15);border:1px solid rgba(232,168,74,0.30);color:#f0b85a;}
.fm-tag.t3{background:rgba(91,156,240,0.15);border:1px solid rgba(91,156,240,0.30);color:#8ab8f5;}
.fm-tag.t4{background:rgba(224,92,92,0.18);border:1px solid rgba(224,92,92,0.30);color:#f08080;}
.fm-tag.t5{background:rgba(196,122,224,0.18);border:1px solid rgba(196,122,224,0.30);color:#d4a5f5;}
.fm-tag.t6{background:rgba(165,126,224,0.15);border:1px solid rgba(165,126,224,0.30);color:#c4a5f5;}
.sig-play{background:var(--ink3);border:1px solid var(--wire);border-left:3px solid var(--cold2);border-radius:0 4px 4px 0;padding:9px 12px;}
.sig-lbl{font-size:7px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--cold);margin-bottom:4px;display:flex;align-items:center;gap:5px;}
.sig-dot{width:4px;height:4px;border-radius:50%;background:var(--cold2);}
.sig-text{font-size:9px;line-height:1.55;color:var(--mid);font-style:italic;}
.sf-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;align-items:start;}
.sf-panel{background:var(--ink3);border:1px solid var(--wire);border-radius:4px;padding:10px 11px;}
.sf-hdr{font-size:8px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:7px;display:flex;align-items:center;gap:5px;}
.sf-hdr.g{color:var(--green);}.sf-hdr.r{color:var(--red);}
.sf-ind{width:5px;height:5px;border-radius:1px;flex-shrink:0;}
.sf-ind.g{background:var(--green);}.sf-ind.r{background:var(--red);}
.sf-item{display:flex;gap:6px;align-items:flex-start;font-size:10px;line-height:1.5;color:var(--mid);padding-top:5px;}.sf-item+.sf-item{border-top:1px solid var(--wire);}
.sf-dot{width:3px;height:3px;border-radius:50%;margin-top:5px;flex-shrink:0;}
.sf-dot.g{background:var(--green);}.sf-dot.r{background:rgba(224,92,92,0.55);}
.conf-row{display:flex;gap:6px;}
.conf-item{flex:1;background:var(--ink3);border:1px solid var(--wire);border-radius:4px;padding:6px 8px;}
.conf-lbl{font-size:7px;letter-spacing:0.12em;text-transform:uppercase;color:var(--dim);margin-bottom:2px;font-weight:700;}
.conf-val{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;color:var(--text);}
.conf-val.green{color:var(--green);}.conf-val.amber{color:var(--amber);}.conf-val.blue{color:var(--cold);}.conf-val.red{color:var(--red);}
.card-stamp{position:absolute;bottom:12px;right:16px;font-family:'Barlow Condensed',sans-serif;font-size:8px;font-weight:700;letter-spacing:0.16em;color:rgba(255,255,255,0.08);text-transform:uppercase;z-index:4;}
"""


# ── Main function ─────────────────────────────────────────────────────────────

def html_page(prospect: dict) -> str:
    """
    Render a DraftOS share card as a self-contained HTML string.
    Designed for PNG export via Playwright (export_png.py).
    All CSS and fonts are embedded. No external dependencies.

    Args:
        prospect: Dict matching the DraftOS card schema.

    Returns:
        Complete HTML string ready for Playwright rendering.
    """
    # ── Unpack fields with defaults ──────────────────────────────────────────
    display_name     = prospect.get("display_name", "")
    school           = prospect.get("school_canonical", "")
    pos_group        = prospect.get("position_group", "")
    consensus_rank   = prospect.get("consensus_rank")
    raw_score        = prospect.get("raw_score")
    apex_composite   = prospect.get("apex_composite")
    pvc              = prospect.get("pvc", 1.0)
    apex_tier        = prospect.get("apex_tier", "DAY3")
    apex_archetype   = prospect.get("apex_archetype", "")
    # Auto-lookup from ARCHETYPE_DEFS using arch_code — caller can override by passing field explicitly
    apex_archetype_def = prospect.get("apex_archetype_def")
    pos_rank_label   = prospect.get("position_rank_label")
    eval_confidence  = prospect.get("eval_confidence", "")
    divergence_delta = prospect.get("divergence_delta")
    ras_score        = prospect.get("ras_score")
    fm_codes         = prospect.get("fm_codes") or []
    fm_labels        = prospect.get("fm_labels") or []
    capital_base     = prospect.get("capital_base", "")
    tags_str         = prospect.get("tags", "")
    signature_play   = prospect.get("signature_play")
    strengths_raw    = prospect.get("strengths", "")
    red_flags_raw    = prospect.get("red_flags", "")
    snapshot_date    = prospect.get("snapshot_date", "")
    prospect_id      = prospect.get("prospect_id", 0)

    # ── Derived values ───────────────────────────────────────────────────────
    # Name split
    name_parts = display_name.split(" ", 1) if display_name else ["", ""]
    first_name = name_parts[0]
    rest_name  = name_parts[1] if len(name_parts) > 1 else ""
    name_html  = f"{e(first_name)}<br>{e(rest_name)}" if rest_name else e(first_name)

    # Archetype split
    arch_parts = apex_archetype.split(" ", 1) if apex_archetype else ["", ""]
    arch_code  = arch_parts[0]
    arch_label = arch_parts[1] if len(arch_parts) > 1 else ""
    # Wrap archetype name on space for two-line display
    arch_label_html = arch_label.replace(" ", "<br>") if arch_label else ""

    # Auto-populate archetype def from library if not explicitly provided
    if apex_archetype_def is None and arch_code:
        apex_archetype_def = _ARCHETYPE_DEFS.get(arch_code)

    # Archetype definition line
    arch_def_html = f'<div class="archetype-def">{e(apex_archetype_def)}</div>' if apex_archetype_def else ""


    # Score display — single when RPG == APEX
    scores_match = (raw_score is not None and apex_composite is not None
                    and abs(float(raw_score) - float(apex_composite)) < 0.05)

    raw_int, raw_dec = score_split(raw_score)
    apex_int, apex_dec = score_split(apex_composite)

    if scores_match:
        score_html = f"""
        <div class="score-lbl">APEX Grade</div>
        <div class="score-val">{raw_int}<span class="score-decimal">.{raw_dec}</span></div>"""
    else:
        score_html = f"""
        <div class="score-dual">
          <div>
            <div class="score-lbl">Player Grade</div>
            <div class="score-val rpg">{raw_int}<span class="score-decimal">.{raw_dec}</span></div>
          </div>
          <div>
            <div class="score-lbl">APEX Score</div>
            <div class="score-val">{apex_int}<span class="score-decimal">.{apex_dec}</span></div>
          </div>
        </div>"""

    # Formula line
    pvc_val = float(pvc) if pvc is not None else 1.0
    formula = f"RPG {raw_score} × PVC {pvc_val:.2f} ({e(pos_group)}) = APEX {apex_composite}"

    # Meta chips
    meta_chips = f'<span class="meta-chip">{e(school)}</span>' if school else ""
    if consensus_rank:
        meta_chips += f'<span class="meta-chip">Consensus #{consensus_rank}</span>'
    if pos_rank_label:
        meta_chips += f'<span class="meta-chip hi">{e(pos_rank_label)}</span>'

    # RAS block
    ras_html = ""
    if ras_score is not None:
        ras_html = f"""
          <div class="ras-block">
            <div class="ras-lbl">RAS</div>
            <div class="ras-val">{e(str(ras_score))}</div>
          </div>"""

    # FM section
    fm_html = ""
    if fm_codes:
        fm_html = f"""
      <div class="fm-section">
        <div class="sec-lbl">Failure Mode Risk</div>
        {fm_pip_bar_html(fm_codes)}
        {fm_tags_html(fm_labels)}
      </div>"""

    # Signature play
    sig_html = ""
    if signature_play:
        sig_html = f"""
      <div class="sig-play">
        <div class="sig-lbl"><span class="sig-dot"></span>Signature Play</div>
        <div class="sig-text">{e(signature_play)}</div>
      </div>"""

    # Top strength (first item only)
    strength_items = [s.strip() for s in (strengths_raw or "").split("\n") if s.strip()]
    top_strength = strength_items[0] if strength_items else ""

    # Top red flag (first item only)
    flag_items = [s.strip() for s in (red_flags_raw or "").split("\n") if s.strip()]
    top_flag = flag_items[0] if flag_items else ""

    # Top 2 strengths
    strength_items2 = strength_items[:2]
    # Top 2 red flags
    flag_items2 = flag_items[:2]

    sf_html = ""
    if strength_items2 or flag_items2:
        s_items_html = "".join(
            f'<div class="sf-item"><span class="sf-dot g"></span>{e(s)}</div>'
            for s in strength_items2
        )
        r_items_html = "".join(
            f'<div class="sf-item"><span class="sf-dot r"></span>{e(s)}</div>'
            for s in flag_items2
        )
        s_panel = f"""
        <div class="sf-panel">
          <div class="sf-hdr g"><span class="sf-ind g"></span>Strengths</div>
          {s_items_html}
        </div>""" if s_items_html else ""
        r_panel = f"""
        <div class="sf-panel">
          <div class="sf-hdr r"><span class="sf-ind r"></span>Red Flags</div>
          {r_items_html}
        </div>""" if r_items_html else ""
        sf_html = f'<div class="sf-row">{s_panel}{r_panel}</div>'

    # Confidence + divergence
    conf_cls, conf_label = fmt_confidence(eval_confidence)
    div_cls, div_label = fmt_divergence(divergence_delta)
    conf_html = f"""
      <div class="conf-row">
        <div class="conf-item">
          <div class="conf-lbl">Confidence</div>
          <div class="conf-val {conf_cls}">{e(conf_label)}</div>
        </div>
        <div class="conf-item">
          <div class="conf-lbl">Divergence</div>
          <div class="conf-val {div_cls}">{e(div_label)}</div>
        </div>
      </div>"""

    # Watermark date
    try:
        wm_date = datetime.strptime(snapshot_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except Exception:
        wm_date = snapshot_date or ""

    # Card stamp
    card_stamp = f"DRAFTOS · 2026 · #{int(prospect_id):04d}"

    # Ghost rank
    ghost_rank = f"#{consensus_rank}" if consensus_rank else ""

    # ── Assemble HTML ────────────────────────────────────────────────────────
    font_block = f"<style>\n{_FONTS_CSS}\n</style>" if _FONTS_CSS else _GOOGLE_FONTS_LINK

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DraftOS — {e(display_name)}</title>
{font_block}
<style>{_CSS}</style>
</head>
<body>
<div class="card">
  <div class="prism-strip"></div>
  <div class="top-bar"></div>
  <div class="layout">

    <div class="left">
      <div class="left-top">
        <div class="pos-chip"><span class="pos-dot"></span>{e(pos_group)}</div>
        <div>
          <div class="player-name">{name_html}</div>
          <div class="name-slash"></div>
        </div>
        <div class="meta-row">{meta_chips}</div>
        <div class="apex-window">
          {score_html}
          {tier_badge_html(apex_tier, formula)}
        </div>
        <div class="traits-block">
          <div class="traits-lbl">Key Traits</div>
          {headline_traits_html(prospect)}
        </div>
      </div>
      <div class="left-bottom">
        {'<div class="capital-block"><div class="capital-lbl">Draft Capital</div><div class="capital-val">' + e(capital_base) + '</div></div>' if capital_base else ''}
        <div class="watermark">
          <span class="brand-logo">DraftOS</span>
          <div class="watermark-meta">{e(pos_group)} · {e(school)}<br>{wm_date}</div>
        </div>
      </div>
    </div>

    <div class="right">
      <div class="rank-ghost">{e(ghost_rank)}</div>

      <div class="archetype-zone">
        <div class="arch-row">
          <div>
            <div class="archetype-code">{e(arch_code)}</div>
            <div class="archetype-name">{arch_label_html}</div>
            {arch_def_html}
          </div>
          {ras_html}
        </div>
        {tags_html(tags_str)}
      </div>

      {fm_html}
      {sig_html}
      {sf_html}
      {conf_html}
    </div>

  </div>
  <div class="card-stamp">{e(card_stamp)}</div>
</div>
</body>
</html>"""


# ── Test ──────────────────────────────────────────────────────────────────────

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
    # apex_archetype_def auto-populated from ARCHETYPE_DEFS — no manual entry needed
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
    "comps":               [],
    "snapshot_date":       "2026-03-18",
    "prospect_id":         1042,
}

if __name__ == "__main__":
    out = html_page(MOCK_RUEBEN_BAIN)
    with open("/tmp/test_card.html", "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Test card written: {len(out)} chars")
    print("Run: python export_png.py /tmp/test_card.html /tmp/test_card.png")