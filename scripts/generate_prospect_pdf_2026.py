"""
DraftOS Prospect One-Pager PDF Generator v4.
Playwright (Chromium) HTML → PDF. Premium dark scouting card.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from draftos.db.connect import connect
from draftos.config import PATHS
from draftos.queries.historical_comps import get_archetype_translation_rate, get_fm_reference_comps

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
            "DAY3":"#ffffff","UDFA":"#374151","UDFA-P":"#374151"}.get(
        (tier or "").upper(), "#ffffff")

def _fm_bg_border(fm: str) -> tuple[str,str]:
    n = int(m.group(1)) if (m := re.search(r"FM-(\d+)", fm or "")) else 0
    return {1:("#2a1005","#f97316"),2:("#1a0f2a","#a855f7"),3:("#0a1829","#3b82f6"),
            4:("#2a0505","#ef4444"),5:("#2a1a05","#f59e0b"),6:("#051a0f","#10b981")}.get(
        n, ("#1a1d2e","#ffffff"))

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
        f'<div style="font-size:8px;color:#ffffff;line-height:1.5;'
        f'margin-top:5px;">{note}</div>'
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
        "SELECT divergence_flag,divergence_rank_delta,divergence_score,rounds_diff,"
        "apex_favors,apex_favors_text "
        "FROM divergence_flags "
        "WHERE prospect_id=? AND season_id=? ORDER BY div_id DESC LIMIT 1",
        (prospect_id, season_id)).fetchone()
    data["divergence_flag"]       = d["divergence_flag"]       if d else None
    data["divergence_rank_delta"] = d["divergence_rank_delta"] if d else None
    data["divergence_score"]      = d["divergence_score"]      if d else None
    data["rounds_diff"]           = d["rounds_diff"]           if d else None
    data["apex_favors_text"]      = d["apex_favors_text"]      if d else None

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
    # Football traits (left column) — player mechanism traits
    left = [
        ("Processing",   "v_processing"),
        ("Athleticism",  "v_athleticism"),
        ("Comp. Tough",  "v_comp_tough"),
        ("Durability",   "v_injury"),
    ]
    # System traits (right column) — evaluation/projection traits
    right = [
        ("Scheme Vers.", "v_scheme_vers"),
        ("Production",   "v_production"),
        ("Dev. Traj.",   "v_dev_traj"),
        ("Character",    "v_character"),
    ]

    def row(label, key):
        val = data.get(key)
        if val is None:
            return (f'<tr><td class="tl">{label}</td>'
                    f'<td class="tbg"><div class="tbf" style="width:0;background:#1e2235;"></div></td>'
                    f'<td class="tv" style="color:#ffffff;">—</td></tr>')
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


def _build_lp_trait_grid(prospect_data: dict) -> str:
    """
    Two-column Football/System trait grid for PDF left panel.
    Uses flexbox row layout — reliable in headless Chromium.
    Font sizes are PDF-scale (8-9px), not app-scale (13px+).
    DB column names: v_injury (not v_durability), v_scheme_vers (not v_scheme).
    """
    FOOTBALL = [
        ("Processing",  "v_processing"),
        ("Athleticism", "v_athleticism"),
        ("Comp. Tough", "v_comp_tough"),
        ("Durability",  "v_injury"),
    ]
    SYSTEM = [
        ("Scheme Vers.", "v_scheme_vers"),
        ("Production",   "v_production"),
        ("Dev. Traj.",   "v_dev_traj"),
        ("Character",    "v_character"),
    ]

    def _color(val: float) -> str:
        if val >= 9.0:   return "#00bcd4"
        if val >= 8.0:   return "#1a7a1a"
        if val >= 6.5:   return "#b8860b"
        if val >= 5.0:   return "#cc5500"
        return "#cc2200"

    def _bar(label: str, key: str) -> str:
        raw = prospect_data.get(key)
        if raw is None:
            return (
                f'<div class="lp-bar-item">'
                f'<div class="lp-bar-label">{label}</div>'
                f'<div class="lp-bar-track">'
                f'<div class="lp-bar-outer"><div class="lp-bar-inner" style="width:0%;background:#334;"></div></div>'
                f'<div class="lp-bar-val" style="opacity:0.4;">—</div>'
                f'</div></div>'
            )
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = 0.0
        pct = min(100.0, max(0.0, val / 10.0 * 100.0))
        color = _color(val)
        return (
            f'<div class="lp-bar-item">'
            f'<div class="lp-bar-label">{label}</div>'
            f'<div class="lp-bar-track">'
            f'<div class="lp-bar-outer">'
            f'<div class="lp-bar-inner" style="width:{pct:.1f}%;background:{color};"></div>'
            f'</div>'
            f'<div class="lp-bar-val">{val:.1f}</div>'
            f'</div></div>'
        )

    football_bars = "\n".join(_bar(lbl, key) for lbl, key in FOOTBALL)
    system_bars   = "\n".join(_bar(lbl, key) for lbl, key in SYSTEM)

    return f"""
<div class="lp-profile-section">
  <div class="lp-profile-header">
    <div class="lp-col-label">Football</div>
    <div class="lp-col-label">System</div>
  </div>
  <div class="lp-bars-row">
    <div class="lp-bar-col">{football_bars}</div>
    <div class="lp-bar-col">{system_bars}</div>
  </div>
</div>
"""


# ── FM reference comp block (PDF right panel) ─────────────────────────────────

def _fm_ref_block_html(fm_comps: list[dict], prospect_position: str = "") -> str:
    """
    Compact FM reference for PDF right panel.
    One line per comp: outcome badge + name + archetype + mechanism.
    NO pre_draft_signal — that belongs in the app, not the print card.
    Must not overflow the right panel height budget.
    """
    if not fm_comps:
        return ""

    OUTCOME_COLOR = {
        "MISS":    "#cc3333",
        "PARTIAL": "#cc8800",
        "HIT":     "#228B22",
    }

    def _pos_from_arch(arch: str) -> str:
        return arch.split("-")[0].strip() if arch else ""

    parts = [
        '<div class="comp-section">',
        '<div class="section-label">FM RISK REFERENCE</div>',
    ]

    for comp in fm_comps:
        outcome  = comp.get("translation_outcome", "MISS")
        color    = OUTCOME_COLOR.get(outcome, "#888888")
        player   = comp.get("player_name", "")
        arch     = comp.get("archetype_code", "")
        fm       = comp.get("fm_code", "")
        era      = comp.get("era_bracket") or ""
        mech     = comp.get("outcome_summary") or ""

        # Truncate mechanism to one line
        mech_short = (mech[:110] + "…") if len(mech) > 113 else mech

        # Cross-position callout — one line only
        comp_pos = _pos_from_arch(arch)
        cross_note = ""
        if comp_pos and comp_pos != (prospect_position or "").upper():
            cross_note = (
                f'<div style="font-size:8px;color:#f0a500;margin-bottom:2px;">'
                f'Cross-position ref — {fm} mechanism is position-independent. '
                f'{comp_pos} shown as highest-severity pattern.'
                f'</div>'
            )

        parts.append(
            f'<div style="border-left:2px solid {color};padding-left:6px;margin-bottom:7px;">'
            f'<div class="comp-header" style="margin-bottom:2px;">'
            f'<span style="color:{color};font-size:8px;font-weight:700;">■ {outcome}</span> '
            f'<span class="comp-name">{player}</span> '
            f'<span class="comp-arch">{arch} · {fm}</span>'
            f'<span class="comp-era">{era}</span>'
            f'</div>'
            f'{cross_note}'
            f'<div class="comp-body" style="font-size:9px;">{mech_short}</div>'
            f'</div>'
        )

    parts.append('</div>')
    return "\n".join(parts)


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
            label_color = "#ffffff"
        else:
            bg          = "#111318"
            border      = "1px solid #1c2035"
            opacity     = "1.0"
            label_color = "#ffffff"

        segments += (
            f'<div style="flex:1;background:{bg};border:{border};opacity:{opacity};'
            f'border-radius:2px;display:flex;align-items:center;justify-content:center;">'
            f'<span style="font-size:8px;font-weight:700;color:{label_color};'
            f'letter-spacing:0.04em;font-family:monospace;">{fm}</span>'
            f'</div>'
        )

    # Build legend from active FM full strings (e.g. "FM-3 Processing Wall")
    legend_parts = []
    if primary_code and fm_primary:
        legend_parts.append(fm_primary.strip())
    if secondary_code and fm_secondary:
        legend_parts.append(fm_secondary.strip())
    legend_html = ""
    if legend_parts:
        legend_text = "  ·  ".join(legend_parts)
        legend_html = (
            f'<div style="font-family:monospace;font-size:6.5pt;color:#ffffff;'
            f'margin-top:3px;letter-spacing:0.02em;">{legend_text}</div>'
        )

    return (
        f'<div style="margin:0 0 8px 0;flex-shrink:0;">'
        f'<div style="font-family:monospace;font-size:5.5pt;letter-spacing:1px;'
        f'color:#ffffff;text-transform:uppercase;margin-bottom:4px;">Failure Mode Risk</div>'
        f'<div style="display:flex;gap:2px;height:18px;">{segments}</div>'
        f'{legend_html}'
        f'</div>'
    )


# ── Divergence narrative ───────────────────────────────────────────────────────

def _build_divergence_narrative(data: dict) -> str | None:
    """
    Returns a one-sentence divergence narrative, or None if ALIGNED.

    Pulls from: divergence_flag, divergence_rank_delta, rounds_diff, apex_favors_text.
    apex_favors_text is populated by run_apex_scoring_2026.py --batch divergence
    (migration 0045). Falls back to "mechanism traits" if not yet populated.
    """
    flag = (data.get("divergence_flag") or "").strip()
    if flag == "ALIGNED" or not flag:
        return None

    name   = data.get("display_name") or data.get("full_name") or "This prospect"
    rounds = data.get("rounds_diff")

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

    favors_text  = (data.get("apex_favors_text") or "").strip()
    trait_phrase = favors_text if favors_text else "mechanism traits"

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
        f'<div style="font-size:8px;font-weight:700;letter-spacing:0.08em;'
        f'color:{label_color};margin-bottom:3px;">{label}</div>'
        f'<div style="font-size:8.5px;color:#ffffff;line-height:1.4;">{narrative}</div>'
        f'</div>'
    )


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_html(data: dict, comps: dict, fm_ref_comps: list | None = None) -> str:
    """
    DraftOS Classified Dossier × Panini Prizm card for PDF export.
    Playwright HTML → PDF via generate_pdf(). 11in × 8.5in landscape.
    """
    import re
    from datetime import datetime, timezone

    # ── Unpack data ────────────────────────────────────────────────────────
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

    # ── DraftOS token system — tier-specific palette ───────────────────────
    TIER_PALETTE = {
        "ELITE":  {
            "border":   "#c89820",
            "text":     "#f0c040",
            "badge_bg": "rgba(240,192,64,0.12)",
            "badge_bd": "rgba(240,192,64,0.40)",
            "atm":      "rgba(240,192,64,0.05)",
        },
        "DAY1": {
            "border":   "#4a90d4",
            "text":     "#7eb4e2",
            "badge_bg": "rgba(126,180,226,0.10)",
            "badge_bd": "rgba(126,180,226,0.35)",
            "atm":      "rgba(126,180,226,0.04)",
        },
        "DAY2": {
            "border":   "#3d8a58",
            "text":     "#5ab87a",
            "badge_bg": "rgba(90,184,122,0.10)",
            "badge_bd": "rgba(90,184,122,0.35)",
            "atm":      "rgba(90,184,122,0.04)",
        },
        "DAY3": {
            "border":   "#c98828",
            "text":     "#e8a84a",
            "badge_bg": "rgba(232,168,74,0.10)",
            "badge_bd": "rgba(232,168,74,0.30)",
            "atm":      "rgba(232,168,74,0.04)",
        },
        "UDFA-P": {
            "border":   "#8a5ab8",
            "text":     "#c47ae0",
            "badge_bg": "rgba(196,122,224,0.10)",
            "badge_bd": "rgba(196,122,224,0.28)",
            "atm":      "rgba(196,122,224,0.03)",
        },
        "UDFA": {
            "border":   "rgba(255,255,255,0.20)",
            "text":     "rgba(255,255,255,0.45)",
            "badge_bg": "rgba(255,255,255,0.05)",
            "badge_bd": "rgba(255,255,255,0.12)",
            "atm":      "transparent",
        },
    }
    pal      = TIER_PALETTE.get(tier, TIER_PALETTE["UDFA"])
    tc       = pal["border"]
    tier_txt = pal["text"]
    badge_bg = pal["badge_bg"]
    badge_bd = pal["badge_bd"]
    atm      = pal["atm"]

    # ── Derived display values ─────────────────────────────────────────────
    arch_code  = _extract_arch_code(archetype)
    arch_label = _arch_label(archetype)

    rpg_s  = f"{rpg:.1f}"  if rpg  else "—"
    apex_s = f"{apex:.1f}" if apex else "Pending"

    if cap_adj:
        cap_clean = re.sub(r"\s*[—–]\s*[a-zA-Z].*$", "", cap_adj).strip().rstrip(" —–-")
    elif rank:
        cap_clean = (
            "R1 Picks 1–32"    if rank <= 32  else
            "R2 / Day 2 Early" if rank <= 64  else
            "R3 / Day 2 Late"  if rank <= 105 else "Day 3"
        )
    else:
        cap_clean = "—"

    rank_s     = f"#{rank}" if rank else "NR"
    pos_badge  = f"{position} {rank_s}"
    pos_rank_s = f"#{pos_rank} at {position}" if (pos_rank and pos_rank != rank) else ""
    ras_s      = f"RAS {ras:.2f}" if ras else ""
    sig_clean  = _trunc(sig_play, 280)
    trans_clean = _trunc(trans, 220)

    # ── Pre-computed conditionals (avoid nested f-strings) ─────────────────
    pos_rank_badge = f'<span class="badge">{pos_rank_s}</span>' if pos_rank_s else ""
    ras_badge      = f'<span class="badge">{ras_s}</span>'      if ras_s      else ""
    arch_code_div  = f'<div class="arch-code">{arch_code}</div>' if arch_code else ""
    arch_name_div  = (
        f'<div class="arch-name">{arch_label}</div>'
        if arch_label
        else '<div class="arch-name" style="color:rgba(255,255,255,0.35)">Archetype Pending</div>'
    )
    tier_star    = "★ " if tier == "ELITE" else ""
    tier_display = tier if tier else "Pending"

    # ── Trait color threshold — DraftOS 4-step token system ───────────────
    def _trait_color(val: float) -> str:
        if val >= 8.5: return "#5ab87a"   # --green
        if val >= 7.0: return "#7eb4e2"   # --cold
        if val >= 5.0: return "#e8a84a"   # --amber
        return "#e05c5c"                   # --red

    # ── Trait bar builder ─────────────────────────────────────────────────
    def _bar(label: str, key: str) -> str:
        raw = data.get(key)
        if raw is None:
            return (
                f'<div class="lp-bar-item">'
                f'<div class="lp-bar-label">{label}</div>'
                f'<div class="lp-bar-track">'
                f'<div class="lp-bar-outer">'
                f'<div class="lp-bar-inner" style="width:0%"></div>'
                f'</div>'
                f'<div class="lp-bar-val" style="color:rgba(255,255,255,0.22)">—</div>'
                f'</div></div>'
            )
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = 0.0
        pct   = min(100.0, max(0.0, val / 10.0 * 100.0))
        color = _trait_color(val)
        return (
            f'<div class="lp-bar-item">'
            f'<div class="lp-bar-label">{label}</div>'
            f'<div class="lp-bar-track">'
            f'<div class="lp-bar-outer">'
            f'<div class="lp-bar-inner" style="width:{pct:.1f}%;background:{color}"></div>'
            f'</div>'
            f'<div class="lp-bar-val" style="color:{color}">{val:.1f}</div>'
            f'</div></div>'
        )

    FOOTBALL = [
        ("Processing",  "v_processing"),
        ("Athleticism", "v_athleticism"),
        ("Comp. Tough", "v_comp_tough"),
        ("Durability",  "v_injury"),
    ]
    SYSTEM = [
        ("Scheme Vers.", "v_scheme_vers"),
        ("Production",   "v_production"),
        ("Dev. Traj.",   "v_dev_traj"),
        ("Character",    "v_character"),
    ]
    football_bars = "\n".join(_bar(lbl, key) for lbl, key in FOOTBALL)
    system_bars   = "\n".join(_bar(lbl, key) for lbl, key in SYSTEM)

    # ── FM pip bar ────────────────────────────────────────────────────────
    FM_PIP_COLORS = {
        "FM-1": "#e05c5c",
        "FM-2": "#e8a84a",
        "FM-3": "#5b9cf0",
        "FM-4": "#e05c5c",
        "FM-5": "#c47ae0",
        "FM-6": "#a57ee0",
    }

    def _extract_fm_code(s: str) -> str:
        m = re.search(r"FM-(\d+)", s or "")
        return m.group(0) if m else ""

    fm_pri_code = _extract_fm_code(fm_pri)
    fm_sec_code = _extract_fm_code(fm_sec)
    active_codes = {c for c in [fm_pri_code, fm_sec_code] if c}

    pips_html = ""
    for i in range(1, 7):
        code  = f"FM-{i}"
        color = FM_PIP_COLORS[code]
        if code in active_codes:
            pips_html += (
                f'<div style="flex:1;height:4px;border-radius:1.5px;'
                f'background:{color}"></div>'
            )
        else:
            pips_html += (
                f'<div style="flex:1;height:4px;border-radius:1.5px;'
                f'background:rgba(255,255,255,0.06)"></div>'
            )

    fm_chips_html = ""
    for code in [fm_pri_code, fm_sec_code]:
        if not code:
            continue
        col  = FM_PIP_COLORS.get(code, "#ffffff")
        full = fm_pri if code == fm_pri_code else fm_sec
        fm_chips_html += (
            f'<span style="display:inline-flex;align-items:center;'
            f'background:{col}22;border:1px solid {col}66;'
            f'color:{col};border-radius:3px;padding:2px 8px;'
            f'font-size:7pt;font-weight:700;letter-spacing:0.06em;'
            f'font-family:\'Barlow Condensed\',sans-serif;'
            f'text-transform:uppercase;margin-right:6px;">'
            f'{full.strip()}'
            f'</span>'
        )

    # ── Bullet rows for strengths / red flags ─────────────────────────────
    str_lines = _bullets(strengths, 3, 360)
    rf_lines  = _bullets(redflags,  3, 360)

    def bullet_rows(lines, dot_col):
        if not lines:
            return (
                '<tr><td style="font-family:\'Barlow\',sans-serif;font-size:7pt;'
                'color:rgba(255,255,255,0.28);font-style:italic">Pending evaluation.</td></tr>'
            )
        rows = ""
        for line in lines:
            rows += (
                f'<tr>'
                f'<td style="vertical-align:top;padding-right:5px;padding-top:1px">'
                f'<span style="color:{dot_col};font-size:7pt">▸</span>'
                f'</td>'
                f'<td style="font-family:\'Barlow\',sans-serif;font-size:7pt;'
                f'line-height:1.5;color:rgba(255,255,255,0.65);padding-bottom:4px">'
                f'{line}'
                f'</td>'
                f'</tr>'
            )
        return rows

    # ── Comp card builder ─────────────────────────────────────────────────
    def comp_block(comp, role_label, role_color, icon, active_fm):
        if not comp:
            return ""
        out    = comp["translation_outcome"]
        oc_map = {"HIT": "#5ab87a", "PARTIAL": "#e8a84a", "MISS": "#e05c5c"}
        oc     = oc_map.get(out, "#888888")
        grad   = f"linear-gradient(180deg, {oc} 0%, {oc}66 100%)"

        fm_tag = ""
        for code in re.findall(r"FM-\d+", comp.get("fm_code") or ""):
            col = FM_PIP_COLORS.get(code, "#ffffff")
            fm_tag += (
                f' <span style="color:{col};font-size:6pt;font-weight:700">{code}</span>'
            )

        summary = _trunc(comp.get("outcome_summary") or "", 210)
        era     = comp.get("era_bracket") or ""
        player  = comp.get("player_name") or ""

        return (
            f'<div style="background:#161b22;border:1px solid rgba(255,255,255,0.08);'
            f'border-radius:5px;padding:10px 12px;margin-bottom:7px;position:relative;'
            f'overflow:hidden;">'
            f'<div style="position:absolute;left:0;top:0;bottom:0;width:3px;'
            f'background:{grad}"></div>'
            f'<div style="padding-left:8px">'
            f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:7pt;'
            f'font-weight:700;letter-spacing:0.14em;text-transform:uppercase;'
            f'color:{role_color};margin-bottom:3px">{icon} {role_label}</div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;'
            f'flex-wrap:nowrap">'
            f'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:14pt;'
            f'font-weight:900;text-transform:uppercase;letter-spacing:0.02em;'
            f'color:rgba(255,255,255,0.92);white-space:nowrap">{player}</span>'
            f'<span style="display:inline-flex;align-items:center;gap:3px;'
            f'background:{oc}1a;border:1px solid {oc}44;color:{oc};'
            f'border-radius:2px;padding:1px 6px;font-family:\'Barlow\',sans-serif;'
            f'font-size:7pt;font-weight:700;letter-spacing:0.08em;white-space:nowrap">'
            f'<span style="width:4px;height:4px;border-radius:50%;background:{oc};'
            f'display:inline-block"></span>{out}{fm_tag}'
            f'</span>'
            f'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:7pt;'
            f'color:rgba(255,255,255,0.22);margin-left:auto;white-space:nowrap">{era}</span>'
            f'</div>'
            f'<div style="font-family:\'Barlow\',sans-serif;font-size:7.5pt;'
            f'color:rgba(255,255,255,0.55);line-height:1.5">{summary}</div>'
            f'</div>'
            f'</div>'
        )

    active_fm_set = set(re.findall(r"FM-\d+", fm_pri or ""))
    ceiling_html  = comp_block(comps.get("ceiling"),  "Archetype Ceiling", "#5ab87a", "✓", active_fm_set)
    fmrisk_html   = comp_block(comps.get("fm_risk"),  "FM Risk Comp",      "#e8a84a", "⚑", active_fm_set)

    comps_html = ""
    if ceiling_html or fmrisk_html:
        comps_html = (
            f'<div style="margin-top:auto;padding-top:8px">'
            f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:8pt;'
            f'font-weight:700;letter-spacing:0.16em;text-transform:uppercase;'
            f'color:rgba(255,255,255,0.32);margin-bottom:8px;padding-bottom:5px;'
            f'border-bottom:1px solid rgba(255,255,255,0.06)">Historical Comps</div>'
            f'{ceiling_html}{fmrisk_html}'
            f'</div>'
        )

    # ── Tags ──────────────────────────────────────────────────────────────
    TAG_COLORS = {
        "green": "#5ab87a",
        "red":   "#e05c5c",
        "blue":  "#7eb4e2",
        "gold":  "#e8a84a",
    }
    tags_html = ""
    if tag_list:
        pills = ""
        for tn, tc2 in tag_list:
            c2 = TAG_COLORS.get(tc2, "rgba(255,255,255,0.52)")
            pills += (
                f'<span style="font-family:\'Barlow Condensed\',sans-serif;'
                f'font-size:7pt;font-weight:700;padding:1px 7px;border-radius:3px;'
                f'border:1px solid {c2}44;background:{c2}15;color:{c2};'
                f'letter-spacing:0.06em;text-transform:uppercase">{tn}</span>'
            )
        tags_html = (
            f'<div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px">'
            f'{pills}'
            f'</div>'
        )

    # ── Confidence / divergence footer ────────────────────────────────────
    conf_html = ""
    if eval_conf:
        conf_color = {"Tier A": "#5ab87a", "Tier B": "#e8a84a", "Tier C": "#e05c5c"}.get(
            eval_conf, "rgba(255,255,255,0.35)"
        )
        conf_html = (
            f'<div style="font-family:\'Barlow\',sans-serif;font-size:7pt;'
            f'color:rgba(255,255,255,0.35);margin-bottom:2px">'
            f'Eval Confidence '
            f'<span style="color:{conf_color};font-weight:700">{eval_conf}</span>'
            f'</div>'
        )

    div_html = ""
    if div_flag:
        sign      = "+" if (div_delta or 0) > 0 else ""
        dc        = "#7eb4e2" if (div_delta or 0) > 0 else "#e05c5c" if (div_delta or 0) < -5 else "rgba(255,255,255,0.45)"
        delta_str = f" ({sign}{div_delta})" if div_delta is not None else ""
        div_html  = (
            f'<div style="font-family:\'Barlow\',sans-serif;font-size:7pt;'
            f'color:rgba(255,255,255,0.35)">'
            f'Divergence <span style="color:{dc};font-weight:700">'
            f'{div_flag}{delta_str}</span></div>'
        )

    # ── PVC formula line ──────────────────────────────────────────────────
    pvc_note = ""
    if rpg and apex:
        pvc_note = (
            f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:7pt;'
            f'color:rgba(255,255,255,0.28);text-align:center;margin-top:4px;'
            f'letter-spacing:0.04em">'
            f'RPG {rpg_s} × PVC {pvc:.2f} ({position}) = APEX {apex_s}'
            f'</div>'
        )

    # ── Translation risk block (pre-computed to avoid nested f-string) ────
    trans_block_html = ""
    if trans_clean:
        trans_block_html = (
            f'<div class="trans-block">'
            f'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:9pt;'
            f'font-weight:800;color:#e8a84a;flex-shrink:0;margin-top:1px">!</span>'
            f'<span style="font-family:\'Barlow\',sans-serif;font-size:7.5pt;'
            f'color:rgba(232,168,74,0.78);line-height:1.5">{trans_clean}</span>'
            f'</div>'
        )

    # ── Divergence callout ────────────────────────────────────────────────
    narrative = _build_divergence_narrative(data)
    divergence_callout_html = ""
    if narrative:
        divergence_callout_html = _divergence_callout_html(narrative, div_flag)

    # ── FM reference block ────────────────────────────────────────────────
    fm_ref_block = _fm_ref_block_html(fm_ref_comps or [], prospect_position=position)

    # ── Capital scarcity note ─────────────────────────────────────────────
    capital_context = _capital_context_html(position)

    # ─────────────────────────────────────────────────────────────────────
    # HTML ASSEMBLY
    # ─────────────────────────────────────────────────────────────────────

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;500;600;700;800;900&family=Barlow:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&display=swap" rel="stylesheet">
<style>

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
  background: #0a0c0f;
  font-family: 'Barlow', sans-serif;
  font-size: 8pt;
  color: rgba(255,255,255,0.88);
  overflow: hidden;
}}

.page {{
  width: 11in; height: 8.5in;
  display: grid;
  grid-template-columns: 2.6in 8.4in;
  background: #0a0c0f;
  position: relative;
}}

.page::before {{
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: linear-gradient(
    180deg,
    #7eb4e2 0%,
    #a57ee0 30%,
    #e8a84a 60%,
    #5ab87a 100%
  );
  z-index: 20;
}}

.page::after {{
  content: '';
  position: absolute;
  inset: 0;
  background-image: repeating-linear-gradient(
    0deg,
    rgba(255,255,255,0.012) 0px,
    rgba(255,255,255,0.012) 1px,
    transparent 1px,
    transparent 3px
  );
  pointer-events: none;
  z-index: 2;
}}

.lp {{
  background: #0f1318;
  border-right: 1px solid rgba(255,255,255,0.08);
  padding: 0.2in 0.18in 0.14in 0.22in;
  display: flex;
  flex-direction: column;
  height: 8.5in;
  overflow: hidden;
  position: relative;
  z-index: 3;
}}

.lp::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, {tc} 0%, {tc}66 50%, transparent 100%);
}}

.lp::after {{
  content: '';
  position: absolute;
  top: -50px; right: -60px;
  width: 180px; height: 180px;
  background: radial-gradient(ellipse at center,
    rgba(126,180,226,0.05) 0%,
    transparent 70%
  );
  pointer-events: none;
}}

.player-name {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 38pt;
  font-weight: 900;
  line-height: 0.88;
  letter-spacing: -0.02em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.92);
  word-break: break-word;
  margin-bottom: 10px;
  margin-top: 6px;
}}

.badges {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 10px;
}}

.badge {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 8pt;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 3px;
  border: 1px solid rgba(255,255,255,0.11);
  color: rgba(255,255,255,0.60);
  background: rgba(255,255,255,0.04);
}}

.badge.pos {{
  border-color: {tc}88;
  color: {tier_txt};
  background: {badge_bg};
}}

.score-box {{
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 6px;
  padding: 10px 12px 8px;
  margin-bottom: 10px;
  position: relative;
  overflow: hidden;
}}

.score-box::before {{
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    135deg,
    rgba(126,180,226,0.04) 0%,
    transparent 40%,
    {atm} 100%
  );
  pointer-events: none;
}}

.score-row {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-bottom: 7px;
}}

.snum {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 30pt;
  font-weight: 800;
  line-height: 0.92;
  letter-spacing: -0.01em;
  display: block;
  text-align: center;
}}

.slbl {{
  font-family: 'Barlow', sans-serif;
  font-size: 6pt;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.32);
  display: block;
  text-align: center;
  margin-top: 2px;
}}

.tier-badge {{
  display: block;
  text-align: center;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13pt;
  font-weight: 900;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: {tier_txt};
  background: {badge_bg};
  border: 1px solid {badge_bd};
  border-radius: 4px;
  padding: 3px 0;
  margin-bottom: 3px;
}}

.lp-profile-section {{
  margin: 6px 0 8px 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}}

.lp-profile-header {{
  display: flex;
  flex-direction: row;
  margin-bottom: 5px;
}}

.lp-col-label {{
  flex: 1;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 7pt;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.28);
}}

.lp-bars-row {{
  display: flex;
  flex-direction: row;
  gap: 10px;
}}

.lp-bar-col {{
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
}}

.lp-bar-item {{
  display: flex;
  flex-direction: column;
  gap: 2px;
}}

.lp-bar-label {{
  font-family: 'Barlow', sans-serif;
  font-size: 7.5pt;
  color: rgba(255,255,255,0.45);
  letter-spacing: 0.02em;
}}

.lp-bar-track {{
  display: flex;
  align-items: center;
  gap: 4px;
}}

.lp-bar-outer {{
  flex: 1;
  height: 3px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  overflow: hidden;
}}

.lp-bar-inner {{
  height: 3px;
  border-radius: 2px;
}}

.lp-bar-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9pt;
  font-weight: 700;
  min-width: 22px;
  text-align: right;
}}

.lp-footer {{
  margin-top: auto;
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 8px;
}}

.cap-val {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 14pt;
  font-weight: 700;
  color: rgba(255,255,255,0.88);
  letter-spacing: 0.02em;
  line-height: 1;
  margin-bottom: 4px;
}}

.rp {{
  background: #0a0c0f;
  padding: 0.2in 0.26in 0.16in 0.22in;
  display: flex;
  flex-direction: column;
  height: 8.5in;
  position: relative;
  z-index: 3;
}}

.rp::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, {tc} 0%, {tc}55 40%, transparent 100%);
}}

.rp::after {{
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 280px; height: 280px;
  background: conic-gradient(
    from 200deg at 100% 0%,
    {atm} 0deg,
    rgba(126,180,226,0.03) 60deg,
    transparent 120deg
  );
  pointer-events: none;
}}

.arch-row {{
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  margin-bottom: 8px;
  flex-shrink: 0;
  position: relative;
}}

.rank-ghost {{
  position: absolute;
  right: 0; top: -6px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 72pt;
  font-weight: 900;
  color: rgba(255,255,255,0.025);
  letter-spacing: -0.04em;
  line-height: 1;
  pointer-events: none;
  user-select: none;
}}

.arch-code {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9pt;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #7eb4e2;
  margin-bottom: 3px;
}}

.arch-name {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 22pt;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: #e8a84a;
  line-height: 0.92;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

.fm-section {{
  margin-bottom: 8px;
  flex-shrink: 0;
}}

.fm-sec-lbl {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 7.5pt;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.28);
  margin-bottom: 5px;
}}

.fm-pips {{
  display: flex;
  gap: 3px;
  margin-bottom: 6px;
}}

.sig-block {{
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.06);
  border-left: 3px solid #4a90d4;
  border-radius: 0 5px 5px 0;
  padding: 8px 12px;
  margin-bottom: 8px;
  flex-shrink: 0;
}}

.sig-lbl {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 7pt;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #7eb4e2;
  margin-bottom: 4px;
}}

.sig-text {{
  font-family: 'Barlow', sans-serif;
  font-size: 7.5pt;
  color: rgba(255,255,255,0.60);
  line-height: 1.5;
  font-style: italic;
}}

.sf-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 8px;
  flex-shrink: 0;
}}

.sf-box {{
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 5px;
  padding: 8px 10px;
}}

.sf-title {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 7.5pt;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}}

.sf-ind {{
  width: 5px; height: 5px;
  border-radius: 1px;
  display: inline-block;
}}

.trans-block {{
  background: rgba(232,168,74,0.07);
  border: 1px solid rgba(232,168,74,0.18);
  border-left: 3px solid #c98828;
  border-radius: 0 5px 5px 0;
  padding: 7px 12px;
  margin-bottom: 8px;
  flex-shrink: 0;
  display: flex;
  gap: 8px;
  align-items: flex-start;
}}

.comps-region {{
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}}

.rp-footer {{
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 7px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}}

.comp-section {{
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255,255,255,0.06);
}}

.section-label {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 7.5pt;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.28);
  margin-bottom: 6px;
}}

.comp-header {{
  font-family: 'Barlow', sans-serif;
  font-size: 8pt;
  color: rgba(255,255,255,0.70);
  display: flex;
  flex-wrap: nowrap;
  gap: 5px;
  align-items: baseline;
}}

.comp-name {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 12pt;
  font-weight: 900;
  text-transform: uppercase;
  color: rgba(255,255,255,0.88);
  white-space: nowrap;
}}

.comp-arch {{
  font-family: 'Barlow', sans-serif;
  font-size: 7pt;
  color: rgba(255,255,255,0.40);
  white-space: nowrap;
}}

.comp-era {{
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 7pt;
  color: rgba(255,255,255,0.22);
  margin-left: auto;
  white-space: nowrap;
  letter-spacing: 0.06em;
}}

.comp-body {{
  font-family: 'Barlow', sans-serif;
  font-size: 8pt;
  color: rgba(255,255,255,0.55);
  line-height: 1.5;
}}

body::before {{
  content: '';
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
  z-index: 1;
}}

</style>
</head>
<body>
<div class="page">

<!-- LEFT PANEL -->
<div class="lp">

  <div class="player-name">{name}</div>

  <div class="badges">
    <span class="badge pos">{pos_badge}</span>
    <span class="badge">{school}</span>
    {pos_rank_badge}
    {ras_badge}
  </div>

  <div class="score-box">
    <div class="score-row">
      <div>
        <span class="snum" style="color:#7eb4e2">{rpg_s}</span>
        <span class="slbl">Player Grade</span>
      </div>
      <div>
        <span class="snum" style="color:{tier_txt}">{apex_s}</span>
        <span class="slbl">Draft Value</span>
      </div>
    </div>
    <div class="tier-badge">{tier_star}{tier_display}</div>
    {pvc_note}
  </div>

  <div class="lp-profile-section">
    <div class="lp-profile-header">
      <div class="lp-col-label">Football</div>
      <div class="lp-col-label">System</div>
    </div>
    <div class="lp-bars-row">
      <div class="lp-bar-col">{football_bars}</div>
      <div class="lp-bar-col">{system_bars}</div>
    </div>
  </div>

  <div class="lp-footer">
    <div style="margin-bottom:6px">
      <div style="font-family:'Barlow Condensed',sans-serif;font-size:7.5pt;
                  font-weight:700;letter-spacing:0.14em;text-transform:uppercase;
                  color:rgba(255,255,255,0.28);margin-bottom:3px">Draft Capital</div>
      <div class="cap-val">{cap_clean}</div>
      {capital_context}
    </div>
    {tags_html}
    {conf_html}
    {div_html}
    <div style="margin-top:8px;display:flex;justify-content:space-between;
                align-items:flex-end">
      <span style="font-family:'Barlow Condensed',sans-serif;font-size:9pt;
                   font-weight:900;letter-spacing:0.20em;text-transform:uppercase;
                   color:rgba(255,255,255,0.14)">DraftOS</span>
      <span style="font-family:'Barlow Condensed',sans-serif;font-size:7pt;
                   color:rgba(255,255,255,0.12);letter-spacing:0.10em;
                   text-transform:uppercase">v2.3 · 2026</span>
    </div>
  </div>

</div>

<!-- RIGHT PANEL -->
<div class="rp">

  <div class="arch-row">
    <div class="rank-ghost">{rank_s}</div>
    <div style="min-width:0">
      {arch_code_div}
      {arch_name_div}
    </div>
  </div>

  <div class="fm-section">
    <div class="fm-sec-lbl">Failure Mode Risk</div>
    <div class="fm-pips">{pips_html}</div>
    <div>{fm_chips_html}</div>
  </div>

  <div class="sig-block">
    <div class="sig-lbl">◆ Signature Play</div>
    <div class="sig-text">{sig_clean if sig_clean else "Pending evaluation."}</div>
  </div>

  <div class="sf-grid">
    <div class="sf-box">
      <div class="sf-title" style="color:#5ab87a">
        <span class="sf-ind" style="background:#5ab87a"></span>
        Strengths
      </div>
      <table style="border-collapse:collapse;width:100%">
        {bullet_rows(str_lines, "#5ab87a")}
      </table>
    </div>
    <div class="sf-box">
      <div class="sf-title" style="color:#e05c5c">
        <span class="sf-ind" style="background:#e05c5c"></span>
        Red Flags
      </div>
      <table style="border-collapse:collapse;width:100%">
        {bullet_rows(rf_lines, "#e05c5c")}
      </table>
    </div>
  </div>

  {trans_block_html}

  <div class="comps-region">
    {divergence_callout_html}
    {comps_html}
    {fm_ref_block}
  </div>

  <div class="rp-footer">
    <span style="font-family:'Barlow Condensed',sans-serif;font-size:9pt;
                 font-weight:900;letter-spacing:0.20em;text-transform:uppercase;
                 color:rgba(255,255,255,0.14)">DraftOS 2026</span>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:7pt;
                color:rgba(255,255,255,0.28);text-align:right;line-height:1.8;
                letter-spacing:0.04em">
      Generated {date_str}<br>
      {rank_s} · {position} · {school}
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

        # FM reference comps — is_fm_reference=1 rows for the prospect's primary FM code
        fm_ref_comps = []
        fm_primary_str = data.get("failure_mode_primary") or ""
        fm_m = re.search(r"FM-\d+", fm_primary_str)
        if fm_m:
            fm_ref_comps = get_fm_reference_comps(conn, fm_m.group(0), arch, limit=2)

    html_str = _build_html(data, comps, fm_ref_comps=fm_ref_comps)
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
