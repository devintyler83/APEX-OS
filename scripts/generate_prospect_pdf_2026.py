"""
DraftOS Prospect One-Pager PDF Generator v4.
Playwright (Chromium) HTML → PDF. Premium dark scouting card.
"""
from __future__ import annotations

import argparse
import math
import re
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from draftos.db.connect import connect
from draftos.config import PATHS
from draftos.queries.historical_comps import get_archetype_translation_rate

SEASON_ID = 1

POSITION_SCARCITY_NOTES: dict[str, str] = {
    "QB":   "Franchise QBs are the scarcest asset in pro football — 8-10 true starters exist at any time.",
    "RB":   "RB capital is structurally depressed — elite backs drafted R1 return value; volume backs do not.",
    "WR":   "WR-1 caliber separators number 12-15 NFL-wide — positional premium compresses at WR-2 and below.",
    "TE":   "Receiving TE-1s are the rarest skill position in the NFL — fewer than 8 true Y-receivers active at peak.",
    "OT":   "Blindside OTs with pass-pro ceiling drafted top-15 at 2x the rate of any other non-QB position.",
    "OG":   "Interior OL value is scheme-sensitive — elite guards in zone systems command R1 capital, power systems R2.",
    "C":    "Green Dot Centers are rarer than the position suggests — fewer than 10 play-callers trusted at the line NFL-wide.",
    "EDGE": "Franchise EDGE rushers drafted top-10 at 3x the rate of any other position — scarcity drives capital floor.",
    "IDL":  "3-tech disruptors command R1 capital in modern NFL — 1-tech anchors are valued R2-R3 regardless of profile.",
    "ILB":  "Coverage-capable ILBs are the fastest-rising positional premium — Green Dot players justify R1 capital.",
    "OLB":  "OLB value bifurcates sharply — pass-rush capable OLBs command R1-R2, pure run-stoppers fall to R3-UDFA.",
    "CB":   "CB-1 caliber man-cover corners number 8-10 NFL-wide — the position's scarcity justifies top-15 capital.",
    "S":    "Rangy single-high safeties are rarer than the position label implies — box safeties draft R3-UDFA regardless of athleticism.",
    "LB":   "Coverage-capable linebackers are the fastest-rising positional premium — scheme fit determines capital.",
    "DL":   "Positional value depends entirely on alignment — 3-tech capital diverges sharply from 1-tech at draft.",
    "OL":   "Interior OL value is scheme-sensitive — elite linemen in zone systems command R1 capital.",
}


def _slugify(t: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (t or "").lower().strip())

def _extract_arch_code(a: str) -> str:
    m = re.match(r"([A-Z]+-\d+)", (a or "").strip())
    return m.group(1) if m else ""

def _arch_label(a: str) -> str:
    m = re.match(r"[A-Z]+-\d+\s+(.*)", (a or "").strip())
    return m.group(1) if m else a

def _tier_color(tier: str) -> str:
    return {"ELITE":"#a855f7","DAY1":"#f5c518","DAY2":"#3b82f6",
            "DAY3":"#6b7280","UDFA":"#374151","UDFA-P":"#374151"}.get(
        (tier or "").upper(), "#6b7280")

def _fm_bg_border(fm: str) -> tuple[str,str]:
    n = int(m.group(1)) if (m := re.search(r"FM-(\d+)", fm or "")) else 0
    return {1:("#2a1005","#f97316"),2:("#1a0f2a","#a855f7"),3:("#0a1829","#3b82f6"),
            4:("#2a0505","#ef4444"),5:("#2a1a05","#f59e0b"),6:("#051a0f","#10b981")}.get(
        n, ("#1a1d2e","#6b7280"))

def _trunc(text: str, n: int) -> str:
    if not text or len(text) <= n: return text or ""
    t = text[:n]
    for sep in [". ","! ","? "]:
        i = t.rfind(sep)
        if i > n * 0.55: return t[:i+1]
    i = t.rfind(" ")
    return (t[:i]+"…") if i > n*0.4 else t+"…"

def _bullets(text: str, max_n: int=2, max_c: int=170) -> list[str]:
    if not text: return []
    if "\n" in text:
        lines = [l.strip().lstrip("•·▸-– ").strip() for l in text.split("\n") if l.strip()]
    else:
        # LLM stores bullets as a prose paragraph — split on sentence boundaries
        lines = [s.strip().lstrip("•·▸-– ").strip()
                 for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip()) if s.strip()]
    return [_trunc(l, max_c) for l in lines if l][:max_n]

def _capital_context_html(position: str) -> str:
    """Returns a styled one-line scarcity note for the position, or empty string."""
    note = POSITION_SCARCITY_NOTES.get((position or "").upper(), "")
    if not note:
        return ""
    return (
        f'<div style="font-size:6.5px;color:#999;line-height:1.4;'
        f'margin-top:4px;font-style:italic;">{note}</div>'
    )


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_prospect_data(conn, prospect_id: int, season_id: int) -> dict:
    p = conn.execute(
        "SELECT prospect_id,display_name,full_name,position_group,school_canonical,name_key "
        "FROM prospects WHERE prospect_id=? AND season_id=?", (prospect_id, season_id)).fetchone()
    if not p: raise ValueError(f"Prospect {prospect_id} not found")
    data = dict(p)

    c = conn.execute(
        "SELECT consensus_rank,score,tier FROM prospect_consensus_rankings WHERE prospect_id=? AND season_id=?",
        (prospect_id, season_id)).fetchone()
    data["consensus_rank"]  = c["consensus_rank"] if c else None
    data["consensus_score"] = c["score"] if c else None
    data["consensus_tier"]  = c["tier"]  if c else None

    r = conn.execute("SELECT ras_total FROM ras WHERE prospect_id=? AND season_id=?",
                     (prospect_id, season_id)).fetchone()
    data["ras_total"] = r["ras_total"] if r else None

    a = conn.execute(
        "SELECT matched_archetype,archetype_gap,gap_label,raw_score,pvc,apex_composite,apex_tier,"
        "capital_base,capital_adjusted,eval_confidence,strengths,red_flags,failure_mode_primary,"
        "failure_mode_secondary,signature_play,translation_risk,v_processing,v_athleticism,"
        "v_scheme_vers,v_comp_tough,v_character,v_dev_traj,v_production,v_injury,"
        "model_version,smith_rule,schwesinger_full,tags "
        "FROM apex_scores WHERE prospect_id=? AND season_id=? "
        "ORDER BY CASE model_version WHEN 'apex_v2.3' THEN 1 WHEN 'apex_v2.2' THEN 2 ELSE 3 END LIMIT 1",
        (prospect_id, season_id)).fetchone()
    for k in ["matched_archetype","archetype_gap","gap_label","raw_score","pvc","apex_composite",
              "apex_tier","capital_base","capital_adjusted","eval_confidence","strengths","red_flags",
              "failure_mode_primary","failure_mode_secondary","signature_play","translation_risk",
              "v_processing","v_athleticism","v_scheme_vers","v_comp_tough","v_character",
              "v_dev_traj","v_production","v_injury","model_version","smith_rule","schwesinger_full","tags"]:
        data[k] = a[k] if a else None

    tags = conn.execute(
        "SELECT td.tag_name,td.tag_color FROM prospect_tags pt "
        "JOIN tag_definitions td ON td.tag_def_id=pt.tag_def_id "
        "WHERE pt.prospect_id=? AND pt.is_active=1 ORDER BY td.display_order LIMIT 5",
        (prospect_id,)).fetchall()
    data["tag_list"] = [(r["tag_name"],r["tag_color"]) for r in tags]

    d = conn.execute(
        "SELECT divergence_flag,divergence_rank_delta,divergence_score,rounds_diff,apex_favors "
        "FROM divergence_flags "
        "WHERE prospect_id=? AND season_id=? ORDER BY div_id DESC LIMIT 1",
        (prospect_id, season_id)).fetchone()
    data["divergence_flag"]       = d["divergence_flag"]       if d else None
    data["divergence_rank_delta"] = d["divergence_rank_delta"] if d else None
    data["divergence_score"]      = d["divergence_score"]      if d else None
    data["rounds_diff"]           = d["rounds_diff"]           if d else None
    data["apex_favors"]           = d["apex_favors"]           if d else None

    pr = conn.execute(
        "SELECT COUNT(*)+1 AS pr FROM prospect_consensus_rankings pcr "
        "JOIN prospects p ON p.prospect_id=pcr.prospect_id "
        "WHERE p.position_group=(SELECT position_group FROM prospects WHERE prospect_id=?) "
        "AND pcr.season_id=? AND pcr.consensus_rank<("
        "SELECT consensus_rank FROM prospect_consensus_rankings WHERE prospect_id=? AND season_id=?)",
        (prospect_id,season_id,prospect_id,season_id)).fetchone()
    data["position_rank"] = pr["pr"] if pr else None
    return data


# ── Comp selection ─────────────────────────────────────────────────────────────

def _get_best_comps(conn, archetype_code: str, fm_primary: str, data: dict) -> dict:
    """
    Ceiling: best HIT — selected by prospect trait affinity, not just confidence rank.
    FM Risk: MISS/PARTIAL with matching prospect FM codes.
    """
    if not archetype_code:
        return {"ceiling": None, "fm_risk": None}

    rows = conn.execute(
        "SELECT player_name,translation_outcome,fm_code,outcome_summary,mechanism,"
        "era_bracket,comp_confidence,signature_trait "
        "FROM historical_comps WHERE archetype_code=? "
        "ORDER BY CASE comp_confidence WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,"
        "CASE translation_outcome WHEN 'HIT' THEN 1 WHEN 'PARTIAL' THEN 2 ELSE 3 END",
        (archetype_code,)).fetchall()
    if not rows: return {"ceiling": None, "fm_risk": None}

    comps = [dict(r) for r in rows]
    prospect_fm = set(re.findall(r"FM-\d+", fm_primary or ""))

    def comp_fm(c): return set(re.findall(r"FM-\d+", c.get("fm_code") or ""))

    hits = [c for c in comps if c["translation_outcome"] == "HIT"]

    # Trait affinity: match prospect's dominant trait to comp mechanism keywords
    v_ath = float(data.get("v_athleticism") or 0)
    v_pro = float(data.get("v_processing")  or 0)

    def affinity_score(c):
        mech = (c.get("mechanism") or "").lower()
        sig  = (c.get("signature_trait") or "").lower()
        text = mech + " " + sig
        score = 0
        if v_ath >= 9.0:
            if any(w in text for w in ["speed","athletic","explosive","burst","4.","acceleration"]):
                score += 3
        if v_pro >= 9.0:
            if any(w in text for w in ["processing","technique","sequenced","plan","reads","anticipat"]):
                score += 3
        if abs(v_ath - v_pro) < 0.8:
            if any(w in text for w in ["complete","versatile","system-transcendent","every-down"]):
                score += 2
        return score

    hits_ranked = sorted(hits, key=affinity_score, reverse=True)
    ceiling = hits_ranked[0] if hits_ranked else None

    misses_partials = [c for c in comps
                       if c["translation_outcome"] in ("MISS","PARTIAL")
                       and (not ceiling or c["player_name"] != ceiling["player_name"])]

    fm_risk = None
    if prospect_fm:
        fm_risk = next((c for c in misses_partials if comp_fm(c) & prospect_fm), None)
    if not fm_risk:
        fm_risk = misses_partials[0] if misses_partials else None

    return {"ceiling": ceiling, "fm_risk": fm_risk}


# ── Trait table (table-based — zero UA bullet risk) ────────────────────────────

def _trait_table(data: dict, tier_col: str) -> str:
    traits = [
        ("Processing",  "v_processing"),
        ("Athleticism", "v_athleticism"),
        ("Scheme",      "v_scheme_vers"),
        ("Comp. Tough", "v_comp_tough"),
        ("Character",   "v_character"),
        ("Dev. Traj.",  "v_dev_traj"),
        ("Production",  "v_production"),
        ("Durability",  "v_injury"),
    ]
    left  = traits[:4]
    right = traits[4:]

    def row(label, key):
        val = data.get(key)
        if val is None:
            return (f'<tr><td class="tl">{label}</td>'
                    f'<td class="tbg"><div class="tbf" style="width:0;background:#1e2235;"></div></td>'
                    f'<td class="tv" style="color:#6b7280;">—</td></tr>')
        pct  = float(val) * 10
        col  = ("#00d4aa" if val>=9.0 else   # teal — elite
                "#34d399" if val>=8.0 else   # green — above average
                "#f5c518" if val>=6.5 else   # gold — average
                "#f97316" if val>=5.0 else   # orange — below average
                "#ef4444")                    # red — concern
        return (f'<tr><td class="tl">{label}</td>'
                f'<td class="tbg"><div class="tbf" style="width:{pct}%;background:{col};"></div></td>'
                f'<td class="tv" style="color:{col};">{val:.1f}</td></tr>')

    left_rows  = "".join(row(l,k) for l,k in left)
    right_rows = "".join(row(l,k) for l,k in right)

    return f"""
    <table class="trait-table">
      <tr>
        <td class="trait-half">
          <table class="inner-trait">{left_rows}</table>
        </td>
        <td class="trait-gap"></td>
        <td class="trait-half">
          <table class="inner-trait">{right_rows}</table>
        </td>
      </tr>
    </table>"""


# ── Radar chart ────────────────────────────────────────────────────────────────

def _radar_chart_svg(data: dict) -> str:
    """
    Renders an 8-axis radar/spider chart as inline SVG.
    Axes: Processing, Athleticism, Scheme, Comp/Tough,
          Character, Dev Traj, Production, Durability.
    Each trait is 0-10. Chart scales to 10 = outer ring.
    Uses actual v_* DB key names from apex_scores.
    """
    traits = [
        ("Process",    float(data.get("v_processing")  or 0)),
        ("Athletic",   float(data.get("v_athleticism") or 0)),
        ("Scheme",     float(data.get("v_scheme_vers") or 0)),
        ("Comp/Tough", float(data.get("v_comp_tough")  or 0)),
        ("Character",  float(data.get("v_character")   or 0)),
        ("Dev Traj",   float(data.get("v_dev_traj")    or 0)),
        ("Production", float(data.get("v_production")  or 0)),
        ("Durability", float(data.get("v_injury")      or 0)),
    ]

    n = len(traits)
    cx, cy, r = 72, 72, 54  # center x, center y, max radius

    def point(angle_deg: float, value: float, max_val: float = 10.0):
        angle_rad = math.radians(angle_deg - 90)
        dist = r * (value / max_val)
        x = cx + dist * math.cos(angle_rad)
        y = cy + dist * math.sin(angle_rad)
        return x, y

    angles = [i * 360 / n for i in range(n)]

    # Grid rings at 25%, 50%, 75%, 100%
    grid_lines = ""
    for pct in [0.25, 0.5, 0.75, 1.0]:
        pts = " ".join(
            f"{cx + r * pct * math.cos(math.radians(a - 90)):.1f},"
            f"{cy + r * pct * math.sin(math.radians(a - 90)):.1f}"
            for a in angles
        )
        opacity = "0.8" if pct == 1.0 else "0.4"
        grid_lines += (f'<polygon points="{pts}" fill="none" '
                       f'stroke="#2a2f45" stroke-width="0.6" opacity="{opacity}"/>\n')

    # Axis spokes
    spokes = ""
    for a in angles:
        ex = cx + r * math.cos(math.radians(a - 90))
        ey = cy + r * math.sin(math.radians(a - 90))
        spokes += f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#2a2f45" stroke-width="0.6"/>\n'

    # Data polygon
    data_pts = [point(angles[i], traits[i][1]) for i in range(n)]
    poly_pts  = " ".join(f"{x:.1f},{y:.1f}" for x, y in data_pts)
    data_polygon = (f'<polygon points="{poly_pts}" '
                    f'fill="#1a7a1a33" stroke="#34d399" stroke-width="1.2"/>\n')

    # Dot at each vertex
    dots = ""
    for x, y in data_pts:
        dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.8" fill="#34d399"/>\n'

    # Axis labels — pushed outward with extra offset
    labels = ""
    for i, (label, _) in enumerate(traits):
        lx = cx + (r + 14) * math.cos(math.radians(angles[i] - 90))
        ly = cy + (r + 14) * math.sin(math.radians(angles[i] - 90))
        labels += (
            f'<text x="{lx:.1f}" y="{ly:.1f}" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'font-size="5.5" fill="#aaa">{label}</text>\n'
        )

    svg = (
        f'<svg width="100%" height="100%" viewBox="0 0 144 144" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;">\n'
        f'  {grid_lines}'
        f'  {spokes}'
        f'  {data_polygon}'
        f'  {dots}'
        f'  {labels}'
        f'</svg>'
    )
    return svg


# ── FM risk bar ────────────────────────────────────────────────────────────────

def _fm_risk_bar_html(fm_primary: str, fm_secondary: str = None) -> str:
    """
    6-segment horizontal bar representing FM-1 through FM-6 severity.
    Active FM(s) highlighted. Extracts FM code from full string
    (e.g. "FM-1 Athleticism Mirage" -> "FM-1").
    """
    FM_COLORS = {
        "FM-1": "#cc5500",   # orange — athleticism mirage
        "FM-2": "#b8860b",   # gold — scheme dependent
        "FM-3": "#005090",   # blue — processing wall
        "FM-4": "#8b0000",   # dark red — medical
        "FM-5": "#6a1a8a",   # purple — character
        "FM-6": "#1a7a1a",   # green — positional mismatch
    }
    FM_LABELS = ["FM-1", "FM-2", "FM-3", "FM-4", "FM-5", "FM-6"]

    # Extract bare code from full strings like "FM-1 Athleticism Mirage"
    def _extract_code(s: str) -> str:
        m = re.search(r"FM-\d+", s or "")
        return m.group(0) if m else ""

    primary_code   = _extract_code(fm_primary or "")
    secondary_code = _extract_code(fm_secondary or "")

    segments = ""
    for fm in FM_LABELS:
        is_primary   = (fm == primary_code)
        is_secondary = (fm == secondary_code)
        col = FM_COLORS.get(fm, "#555")

        if is_primary:
            bg          = col
            border      = f"2px solid {col}"
            opacity     = "1.0"
            label_color = "#fff"
        elif is_secondary:
            bg          = col + "55"
            border      = f"1px solid {col}"
            opacity     = "0.85"
            label_color = "#ccc"
        else:
            bg          = "#111318"
            border      = "1px solid #1c2035"
            opacity     = "1.0"
            label_color = "#888"

        segments += (
            f'<div style="flex:1;background:{bg};border:{border};opacity:{opacity};'
            f'border-radius:2px;display:flex;align-items:center;justify-content:center;">'
            f'<span style="font-size:5.5px;font-weight:700;color:{label_color};'
            f'letter-spacing:0.04em;font-family:monospace;">{fm}</span>'
            f'</div>'
        )

    return (
        f'<div style="margin:0 0 8px 0;flex-shrink:0;">'
        f'<div style="font-family:monospace;font-size:5.5pt;letter-spacing:1px;'
        f'color:#aaa;text-transform:uppercase;margin-bottom:4px;">Failure Mode Risk</div>'
        f'<div style="display:flex;gap:2px;height:18px;">{segments}</div>'
        f'</div>'
    )


# ── Divergence narrative ───────────────────────────────────────────────────────

def _build_divergence_narrative(data: dict) -> str | None:
    """
    Returns a one-sentence divergence narrative, or None if ALIGNED.

    Pulls from: divergence_flag, divergence_score, rounds_diff,
                apex_favors, matched_archetype, apex_composite.
    Note: apex_favors in DB is an INTEGER (0/1 boolean), not text —
    falls back to "mechanism traits" when not a human-readable string.
    Migration needed: convert apex_favors to TEXT in divergence_flags
    and populate from scoring pipeline.
    """
    flag = (data.get("divergence_flag") or "").strip()
    if flag == "ALIGNED" or not flag:
        return None

    name   = data.get("display_name") or data.get("full_name") or "This prospect"
    rounds = data.get("rounds_diff")

    # apex_favors in DB is INTEGER — only use if it's a non-empty string
    apex_favors_raw = data.get("apex_favors")
    apex_favors = (apex_favors_raw if isinstance(apex_favors_raw, str)
                   and apex_favors_raw.strip() else "")

    # Direction
    if flag == "APEX_HIGH":
        direction    = "above"
        market_verb  = "undervaluing"
        signal_end   = "upside"
    else:  # APEX_LOW or APEX_LOW_PVC_STRUCTURAL
        direction    = "below"
        market_verb  = "pricing in"
        signal_end   = "risk"

    # Rounds diff phrasing
    if rounds and abs(rounds) >= 1:
        rank_phrase = f"{abs(rounds):.0f} round{'s' if abs(rounds) != 1 else ''}"
    else:
        rank_phrase = "meaningfully"

    trait_phrase = apex_favors if apex_favors else "mechanism traits"

    sentence = (
        f"APEX rates {name} {rank_phrase} {direction} consensus because the model weights "
        f"{trait_phrase} higher than the market, which is {market_verb} the {signal_end}."
    )
    return sentence


def _divergence_callout_html(narrative: str, flag: str) -> str:
    """Renders the divergence narrative as a styled HTML callout block."""
    if flag == "APEX_HIGH":
        border_color = "#1a7a1a"
        label        = "APEX DIVERGENCE · ABOVE CONSENSUS"
        label_color  = "#1a7a1a"
    else:
        border_color = "#cc5500"
        label        = "APEX DIVERGENCE · BELOW CONSENSUS"
        label_color  = "#cc5500"

    return (
        f'<div style="border-left:3px solid {border_color};background:rgba(255,255,255,0.04);'
        f'padding:6px 10px;margin:6px 0;border-radius:0 4px 4px 0;flex-shrink:0;">'
        f'<div style="font-size:7px;font-weight:700;letter-spacing:0.08em;'
        f'color:{label_color};margin-bottom:3px;">{label}</div>'
        f'<div style="font-size:8.5px;color:#d0d0d0;line-height:1.4;">{narrative}</div>'
        f'</div>'
    )


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_html(data: dict, comps: dict) -> str:
    name      = data.get("display_name") or "Unknown"
    position  = data.get("position_group") or "—"
    school    = data.get("school_canonical") or "—"
    rank      = data.get("consensus_rank")
    pos_rank  = data.get("position_rank")
    ras       = data.get("ras_total")
    rpg       = data.get("raw_score")
    apex      = data.get("apex_composite")
    tier      = (data.get("apex_tier") or "").upper()
    pvc       = data.get("pvc") or 1.0
    archetype = data.get("matched_archetype") or ""
    fm_pri    = data.get("failure_mode_primary") or ""
    fm_sec    = data.get("failure_mode_secondary") or ""
    cap_adj   = data.get("capital_adjusted") or data.get("capital_base")
    eval_conf = data.get("eval_confidence") or ""
    sig_play  = data.get("signature_play") or ""
    trans     = data.get("translation_risk") or ""
    strengths = data.get("strengths") or ""
    redflags  = data.get("red_flags") or ""
    div_flag  = data.get("divergence_flag") or ""
    div_delta = data.get("divergence_rank_delta")
    tag_list  = data.get("tag_list") or []
    date_str  = datetime.now(timezone.utc).strftime("%b %d, %Y")

    TIER_PALETTE = {
        "ELITE":  {"border": "#b8860b", "atm": "rgba(184,134,11,0.13)",  "badge": "rgba(184,134,11,0.22)"},
        "DAY1":   {"border": "#1a7a1a", "atm": "rgba(26,122,26,0.11)",   "badge": "rgba(26,122,26,0.22)"},
        "DAY2":   {"border": "#005090", "atm": "rgba(0,80,144,0.11)",    "badge": "rgba(0,80,144,0.22)"},
        "DAY3":   {"border": "#cc5500", "atm": "rgba(204,85,0,0.10)",    "badge": "rgba(204,85,0,0.20)"},
        "UDFA-P": {"border": "#6a1a8a", "atm": "rgba(106,26,138,0.10)", "badge": "rgba(106,26,138,0.20)"},
        "UDFA":   {"border": "#455a64", "atm": "rgba(69,90,100,0.08)",  "badge": "rgba(69,90,100,0.15)"},
    }
    pal      = TIER_PALETTE.get(tier, {"border":"#6b7280","atm":"transparent","badge":"rgba(107,114,128,0.12)"})
    tc       = pal["border"]
    atm      = pal["atm"]
    badge_bg = pal["badge"]

    arch_code  = _extract_arch_code(archetype)
    arch_label = _arch_label(archetype)

    rpg_s  = f"{rpg:.1f}"  if rpg  else "—"
    apex_s = f"{apex:.1f}" if apex else "Pending"

    if cap_adj:
        cap_clean = re.sub(r"\s*[—–]\s*[a-zA-Z].*$","",cap_adj).strip().rstrip(" —–-")
    elif rank:
        cap_clean = ("R1 Picks 1–32" if rank<=32 else "R2 / Day 2 Early" if rank<=64
                     else "R3 / Day 2 Late" if rank<=105 else "Day 3")
    else:
        cap_clean = "—"

    rank_s    = f"#{rank}" if rank else "NR"
    pos_badge = f"{position} {rank_s}"

    # Positional rank badge: only informative when it differs from overall consensus rank.
    # Suppressed when pos_rank == rank (e.g. #1 overall who is also #1 at their position).
    pos_rank_s = f"#{pos_rank} at {position}" if (pos_rank and pos_rank != rank) else ""

    ras_s     = f"RAS {ras:.2f}" if ras else ""

    sig_clean = _trunc(sig_play, 280)

    str_lines = _bullets(strengths, 3, 165)
    rf_lines  = _bullets(redflags,  3, 165)

    def bullet_rows(lines, dot_col):
        if not lines:
            return '<tr><td style="color:#999;font-style:italic;font-size:7pt;">Pending evaluation.</td></tr>'
        rows = ""
        for l in lines:
            rows += (f'<tr><td style="vertical-align:top;padding-right:6px;">'
                     f'<span style="color:{dot_col};font-size:8pt;">▸</span></td>'
                     f'<td style="font-size:7pt;line-height:1.45;color:#e8eaf0;padding-bottom:4px;">{l}</td></tr>')
        return rows

    trans_clean = _trunc(trans, 220)

    div_html = ""
    if div_flag:
        sign = "+" if (div_delta or 0) > 0 else ""
        dc   = "#00d4aa" if (div_delta or 0)>0 else "#ef4444" if (div_delta or 0)<-5 else "#f5c518"
        delta_str = f" ({sign}{div_delta})" if div_delta is not None else ""
        div_html = (f'<div style="font-size:6.5pt;font-family:monospace;color:#aaa;">'
                    f'Divergence <span style="color:{dc};font-weight:700;">{div_flag}{delta_str}</span></div>')

    tag_map = {"green":"#00d4aa","red":"#ef4444","blue":"#3b82f6","gold":"#f5c518"}
    tags_html = ""
    if tag_list:
        pills = ""
        for tn,tc2 in tag_list:
            c2 = tag_map.get(tc2,"#6b7280")
            pills += (f'<span style="font-size:5.5pt;font-weight:600;padding:2px 6px;border-radius:3px;'
                      f'border:1px solid {c2}22;background:{c2}11;color:{c2};margin-right:4px;">{tn}</span>')
        tags_html = f'<div style="margin-bottom:6px;flex-wrap:wrap;display:flex;gap:3px;">{pills}</div>'

    conf_html = (f'<div style="font-family:monospace;font-size:6.5pt;color:#aaa;margin-bottom:3px;">'
                 f'Eval Confidence <span style="color:#aaa;">{eval_conf}</span></div>') if eval_conf else ""

    def comp_block(comp, role_label, role_color, icon, active_fm):
        if not comp: return ""
        out = comp["translation_outcome"]
        oc  = {"HIT":"#00d4aa","PARTIAL":"#f5c518","MISS":"#ef4444"}.get(out,"#6b7280")

        fm_tag = ""
        for code in re.findall(r"FM-\d+", comp.get("fm_code") or ""):
            col = "#ef4444" if code in active_fm else "#aaa"
            fm_tag += f' <span style="color:{col};font-size:6pt;font-weight:700;">{code}</span>'

        summary = _trunc(comp.get("outcome_summary") or "", 210)
        mech    = _trunc((re.split(r"(?<=[.!?])\s+",
                          (comp.get("mechanism") or "").strip()) or [""])[0], 130)
        era     = comp.get("era_bracket") or ""

        return f"""
        <div style="background:#07090f;border:1px solid #1c2035;border-left:3px solid {oc};
                    border-radius:0 5px 5px 0;padding:8px 11px;margin-bottom:7px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:5px;flex-wrap:nowrap;">
            <span style="font-family:monospace;font-size:5.5pt;color:{role_color};
                         text-transform:uppercase;letter-spacing:0.5px;
                         white-space:nowrap;flex-shrink:0;">{icon} {role_label}</span>
            <span style="font-family:'Bebas Neue',sans-serif;font-size:12pt;
                         color:{oc};white-space:nowrap;flex-shrink:0;">{comp['player_name']}</span>
            <span style="font-family:monospace;font-size:6.5pt;color:{oc};
                         white-space:nowrap;flex-shrink:0;">{out}{fm_tag}</span>
            <span style="font-family:monospace;font-size:6pt;color:#aaa;
                         white-space:nowrap;margin-left:auto;flex-shrink:0;">{era}</span>
          </div>
          <div style="font-size:7.5pt;color:#bbb;line-height:1.5;">{summary}</div>
          {'<div style="font-size:6.5pt;color:#999;line-height:1.4;margin-top:3px;font-style:italic;">'+mech+'</div>' if mech else ''}
        </div>"""

    active_fm_set = set(re.findall(r"FM-\d+", fm_pri or ""))
    fm_codes_label = ""
    if comps.get("fm_risk") and comps["fm_risk"].get("fm_code"):
        match = [c for c in re.findall(r"FM-\d+", comps["fm_risk"]["fm_code"]) if c in active_fm_set]
        if match: fm_codes_label = " · " + " / ".join(match)

    ceiling_html = comp_block(comps.get("ceiling"), "ARCHETYPE CEILING", "#00d4aa", "✓", active_fm_set)
    fmrisk_html  = comp_block(comps.get("fm_risk"), f"ARCHETYPE FM RISK{fm_codes_label}", "#ef4444", "⚑", active_fm_set)

    comps_html = ""
    if ceiling_html or fmrisk_html:
        comps_html = f"""
        <div style="margin-top:auto;padding-top:8px;">
          <div style="font-family:monospace;font-size:5.5pt;letter-spacing:1.5px;
                      color:#aaa;text-transform:uppercase;margin-bottom:6px;">Historical Comps</div>
          {ceiling_html}{fmrisk_html}
        </div>"""

    trait_table_html = _trait_table(data, tc)
    radar_svg        = _radar_chart_svg(data)
    fm_bar           = _fm_risk_bar_html(fm_pri, fm_sec)
    capital_context  = _capital_context_html(position)

    pvc_note = (f'<div style="font-family:monospace;font-size:5.5pt;color:#999;text-align:center;margin-top:4px;">'
                f'RPG {rpg_s} × PVC {pvc:.2f} = APEX {apex_s}</div>') if rpg and apex else ""

    # Divergence callout — rendered inside comps-region above historical comps
    narrative = _build_divergence_narrative(data)
    divergence_callout_html = ""
    if narrative:
        divergence_callout_html = _divergence_callout_html(narrative, div_flag)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');

@page {{
  size: 11in 8.5in landscape;
  margin: 0;
}}

*, *::before, *::after {{
  margin: 0; padding: 0; box-sizing: border-box;
  list-style: none !important;
}}

html, body {{
  width: 11in; height: 8.5in;
  background: #07090f;
  font-family: 'DM Sans', sans-serif;
  font-size: 8pt;
  color: #e8eaf0;
  overflow: hidden;
}}

.page {{
  width: 11in; height: 8.5in;
  display: grid;
  grid-template-columns: 2.6in 8.4in;
  grid-template-rows: 8.5in;
}}

/* LEFT PANEL */
.lp {{
  background: #0b0e18;
  border-right: 1px solid #1c2035;
  border-top: 3px solid {tc};
  padding: 0.18in 0.18in 0.14in;
  display: flex;
  flex-direction: column;
  height: 8.5in;
  overflow: hidden;
}}

.player-name {{
  font-family: 'Bebas Neue', sans-serif;
  font-size: 34pt;
  line-height: 0.92;
  color: #ffffff;
  letter-spacing: 1px;
  word-break: break-word;
  margin-bottom: 7px;
}}

.badges {{
  display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px;
}}

.badge {{
  font-family: 'DM Mono', monospace;
  font-size: 6.5pt; font-weight: 500;
  padding: 2px 7px; border-radius: 3px;
  border: 1px solid #1c2035; color: #bbb;
}}

.badge.pos {{ border-color: {tc}; color: {tc}; font-weight: 700; }}
.badge.hi  {{ border-color: #6b7280; color: #e8eaf0; }}

.score-box {{
  border: 1px solid #1c2035;
  border-radius: 6px;
  padding: 8px 10px 5px;
  margin-bottom: 10px;
  background: linear-gradient(135deg, {atm} 0%, #060810 60%);
}}

.score-row {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-bottom: 5px;
}}

.snum {{
  font-family: 'Bebas Neue', sans-serif;
  font-size: 28pt; line-height: 1; display: block; text-align: center;
}}

.slbl {{
  font-family: 'DM Mono', monospace;
  font-size: 5.5pt; color: #aaa; letter-spacing: 1px;
  text-transform: uppercase; display: block; text-align: center; margin-top: 1px;
}}

.tier-badge {{
  display: block; text-align: center;
  font-family: 'Bebas Neue', sans-serif;
  font-size: 12pt; letter-spacing: 3px; color: {tc};
  background: {badge_bg}; border: 1px solid {tc}88;
  border-radius: 4px; padding: 2px 0; margin-bottom: 3px;
}}

/* Traits via table — zero UA bullet risk */
.trait-table {{
  width: 100%; border-collapse: collapse; table-layout: fixed;
}}
.trait-half {{ width: 48%; vertical-align: top; }}
.trait-gap  {{ width: 4%; }}
.inner-trait {{ width: 100%; border-collapse: collapse; }}
.inner-trait tr {{ height: auto; }}
.tl {{
  font-size: 6pt; color: #bbb; font-weight: 500;
  white-space: nowrap; padding-right: 5px; width: 52px;
  font-family: 'DM Sans', sans-serif; vertical-align: middle;
  padding-bottom: 4px;
}}
.tbg {{
  padding-bottom: 4px; vertical-align: middle;
}}
.tbf {{
  height: 4px; border-radius: 2px; display: block; min-width: 1px;
}}
.tv {{
  font-family: 'DM Mono', monospace;
  font-size: 6.5pt; font-weight: 500; text-align: right;
  width: 22px; padding-left: 4px; vertical-align: middle;
  padding-bottom: 4px; white-space: nowrap;
}}

.radar-wrap {{
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
}}

.lp-footer {{
  margin-top: auto;
  border-top: 1px solid #1c2035;
  padding-top: 8px;
}}

/* RIGHT PANEL */
.rp {{
  background: linear-gradient(160deg, {atm} 0%, #0d1020 35%);
  border-top: 3px solid {tc};
  padding: 0.2in 0.26in 0.16in;
  display: flex;
  flex-direction: column;
  height: 8.5in;
  overflow: hidden;
}}

.arch-row {{
  display: flex; align-items: flex-start;
  gap: 10px; padding-bottom: 8px;
  border-bottom: 1px solid #1c2035;
  margin-bottom: 8px; flex-shrink: 0;
}}

.arch-code {{
  font-family: 'DM Mono', monospace; font-size: 7pt; color: #aaa;
  background: #060810; border: 1px solid #1c2035;
  border-radius: 3px; padding: 2px 7px; margin-top: 3px;
  flex-shrink: 0; white-space: nowrap;
}}

.arch-name {{
  font-family: 'Bebas Neue', sans-serif; font-size: 20pt;
  color: {tc}; line-height: 1; letter-spacing: 0.5px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}

.sig-block {{
  background: #060d1a; border-left: 3px solid #1e4080;
  border-radius: 0 4px 4px 0; padding: 7px 12px;
  margin-bottom: 8px; flex-shrink: 0;
}}

.sf-grid {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 9px; margin-bottom: 8px; flex-shrink: 0;
}}

.sf-box {{
  background: #07090f; border: 1px solid #1c2035;
  border-radius: 4px; padding: 7px 9px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
}}

.sf-title {{
  font-family: 'DM Mono', monospace;
  font-size: 5.5pt; letter-spacing: 1.2px;
  text-transform: uppercase; margin-bottom: 4px; font-weight: 600;
}}

.trans-block {{
  background: #110e00; border: 1px solid #f5c51825;
  border-left: 3px solid #f5c518;
  border-radius: 0 4px 4px 0;
  padding: 7px 12px; margin-bottom: 8px; flex-shrink: 0;
  display: flex; gap: 10px; align-items: flex-start;
}}

.comps-region {{
  flex: 1; display: flex; flex-direction: column;
  min-height: 0;
}}

.rp-footer {{
  border-top: 1px solid #1c2035; padding-top: 7px;
  display: flex; align-items: center; justify-content: space-between;
  flex-shrink: 0;
}}
</style>
</head>
<body>
<div class="page">

<!-- LEFT -->
<div class="lp">
  <div class="player-name">{name}</div>

  <div class="badges">
    <span class="badge pos">{pos_badge}</span>
    <span class="badge">{school}</span>
    {'<span class="badge hi">'+pos_rank_s+'</span>' if pos_rank_s else ''}
    {'<span class="badge">'+ras_s+'</span>' if ras_s else ''}
  </div>

  <div class="score-box">
    <div class="score-row">
      <div>
        <span class="snum" style="color:#00d4aa;">{rpg_s}</span>
        <span class="slbl">Player Grade</span>
      </div>
      <div>
        <span class="snum" style="color:{tc};">{apex_s}</span>
        <span class="slbl">Draft Value</span>
      </div>
    </div>
    <div class="tier-badge">{tier if tier else 'Pending'}</div>
    {pvc_note}
  </div>

  <div style="font-family:'DM Mono',monospace;font-size:5.5pt;letter-spacing:1.5px;
              color:#aaa;text-transform:uppercase;margin-bottom:6px;">Player Profile</div>
  {trait_table_html}
  <div class="radar-wrap">{radar_svg}</div>

  <div class="lp-footer">
    <div style="margin-bottom:5px;">
      <div style="font-family:'DM Mono',monospace;font-size:5.5pt;letter-spacing:1px;
                  color:#aaa;text-transform:uppercase;margin-bottom:2px;">Draft Capital</div>
      <div style="font-family:'Bebas Neue',sans-serif;font-size:13pt;
                  color:#ffffff;letter-spacing:0.5px;line-height:1;">{cap_clean}</div>
      {capital_context}
    </div>
    {tags_html}
    {conf_html}
    {div_html}
  </div>
</div>

<!-- RIGHT -->
<div class="rp">

  <div class="arch-row">
    <div style="min-width:0;">
      {'<div class="arch-code">'+arch_code+'</div>' if arch_code else ''}
      {'<div class="arch-name">'+arch_label+'</div>' if arch_label
       else '<div style="font-family:Bebas Neue,sans-serif;font-size:14pt;color:#aaa;">Archetype Pending</div>'}
    </div>
  </div>

  {fm_bar}

  <div class="sig-block">
    <div style="font-family:'DM Mono',monospace;font-size:5.5pt;letter-spacing:1.5px;
                color:#3b82f6;text-transform:uppercase;margin-bottom:4px;">Signature Play</div>
    <div style="font-size:8pt;color:#b8c4d8;line-height:1.5;font-style:italic;">{sig_clean if sig_clean else "Pending evaluation."}</div>
  </div>

  <div class="sf-grid">
    <div class="sf-box">
      <div class="sf-title" style="color:#34d399;">&#10003; Strengths</div>
      <table style="border-collapse:collapse;width:100%;">{bullet_rows(str_lines,"#34d399")}</table>
    </div>
    <div class="sf-box">
      <div class="sf-title" style="color:#ef4444;">&#9873; Red Flags</div>
      <table style="border-collapse:collapse;width:100%;">{bullet_rows(rf_lines,"#ef4444")}</table>
    </div>
  </div>

  {'<div class="trans-block"><span style="color:#f5c518;font-size:8pt;flex-shrink:0;margin-top:1px;">&#9888;</span><span style="font-size:7.5pt;color:#d4b84a;line-height:1.45;">'+trans_clean+'</span></div>' if trans_clean else ''}

  <div class="comps-region">
    {divergence_callout_html}
    {comps_html}
  </div>

  <div class="rp-footer">
    <div style="font-family:'Bebas Neue',sans-serif;font-size:9pt;
                letter-spacing:3px;color:#aaa;">DraftOS 2026</div>
    <div style="font-family:'DM Mono',monospace;font-size:6pt;
                color:#aaa;text-align:right;line-height:1.6;">
      Generated {date_str}<br>{rank_s} · {position} · {school}
    </div>
  </div>

</div>
</div>
</body>
</html>"""


# ── PDF renderer ──────────────────────────────────────────────────────────────

def generate_pdf(prospect_id: int, season_id: int = SEASON_ID) -> Path:
    out_dir = PATHS.root / "exports" / "reports" / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        data  = _fetch_prospect_data(conn, prospect_id, season_id)
        arch  = _extract_arch_code(data.get("matched_archetype") or "")
        fm    = data.get("failure_mode_primary") or ""
        comps = _get_best_comps(conn, arch, fm, data) if arch else {"ceiling": None, "fm_risk": None}

    html_str = _build_html(data, comps)
    Path("C:/DraftOS/debug_render.html").write_text(html_str, encoding="utf-8")
    name_key = _slugify(data.get("display_name") or str(prospect_id))
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = out_dir / f"{prospect_id}_{name_key}_{date_str}.pdf"

    exc = [None]

    def _render():
        import asyncio, sys
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        async def _do():
            from playwright.async_api import async_playwright
            tmp = Path(tempfile.mktemp(suffix=".html"))
            try:
                tmp.write_text(html_str, encoding="utf-8")
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch()
                    page    = await browser.new_page()
                    await page.set_viewport_size({"width": 1056, "height": 816})  # 11in × 8.5in at 96dpi
                    await page.goto(f"file:///{tmp.as_posix()}", wait_until="networkidle")
                    await page.pdf(
                        path=str(out_path),
                        width="11in", height="8.5in",
                        print_background=True,
                        margin={"top":"0","bottom":"0","left":"0","right":"0"},
                    )
                    await browser.close()
            finally:
                if tmp.exists(): tmp.unlink()
        asyncio.run(_do())

    t = threading.Thread(target=_render)
    t.start(); t.join()
    if exc[0]: raise exc[0]
    print(f"  [PDF] {out_path}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prospect-id", "--pid", dest="prospect_id", type=int, required=True)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    print(f"OK: {generate_pdf(prospect_id=args.prospect_id, season_id=1)}")

if __name__ == "__main__":
    main()
