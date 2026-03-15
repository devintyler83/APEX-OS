"""
DraftOS Prospect One-Pager PDF Generator v2.
HTML → PDF via WeasyPrint. Dark theme, landscape, premium scouting card layout.

Usage (CLI):
    python -m scripts.generate_prospect_pdf_2026 --prospect-id 1 --season 2026

Usage (programmatic / Streamlit):
    from scripts.generate_prospect_pdf_2026 import generate_pdf
    pdf_path = generate_pdf(prospect_id=1, season_id=1)

Output: C:\\DraftOS\\exports\\reports\\pdf\\{prospect_id}_{name_key}_{date}.pdf
Idempotent — overwrites prior PDF for same prospect.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from draftos.db.connect import connect
from draftos.config import PATHS
from draftos.queries.historical_comps import (
    _extract_archetype_code,
    get_historical_comps,
    get_archetype_translation_rate,
)

SEASON_ID = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (text or "").lower().strip())


def _safe(v, fmt: str = "") -> str:
    """Format a numeric value, return '—' if None / NaN."""
    if v is None:
        return "—"
    try:
        f = float(v)
        if math.isnan(f):
            return "—"
        return format(f, fmt) if fmt else str(f)
    except (TypeError, ValueError):
        return str(v) if v else "—"


def _tier_hex(tier: str) -> str:
    return {
        "ELITE":  "#b44fe8",
        "DAY1":   "#f5c518",
        "DAY2":   "#3498db",
        "DAY3":   "#7f8c8d",
        "UDFA-P": "#555566",
        "UDFA":   "#444455",
    }.get((tier or "").upper(), "#667085")


def _fm_hex(fm: str) -> str:
    if not fm:
        return "#e67e22"
    code = fm[:4].upper()
    return {
        "FM-1": "#e05c5c",
        "FM-4": "#e05c5c",
        "FM-5": "#e05c5c",
        "FM-2": "#e67e22",
        "FM-3": "#e8c94b",
        "FM-6": "#9b8fe0",
    }.get(code, "#e67e22")


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_prospect_data(conn, prospect_id: int, season_id: int) -> dict:
    """Pull all PDF data from DB. Missing fields → None, never KeyError."""
    p = conn.execute(
        """
        SELECT prospect_id, display_name, full_name, position_group,
               school_canonical, name_key
        FROM prospects
        WHERE prospect_id = ? AND season_id = ?
        """,
        (prospect_id, season_id),
    ).fetchone()
    if not p:
        raise ValueError(f"Prospect {prospect_id} not found in season {season_id}")

    data = dict(p)

    cons = conn.execute(
        """
        SELECT consensus_rank, score AS consensus_score, tier AS consensus_tier
        FROM prospect_consensus_rankings
        WHERE prospect_id = ? AND season_id = ?
        """,
        (prospect_id, season_id),
    ).fetchone()
    data["consensus_rank"]  = cons["consensus_rank"]  if cons else None
    data["consensus_score"] = cons["consensus_score"] if cons else None
    data["consensus_tier"]  = cons["consensus_tier"]  if cons else None

    ras = conn.execute(
        "SELECT ras_total FROM ras WHERE prospect_id = ? AND ras_total IS NOT NULL LIMIT 1",
        (prospect_id,),
    ).fetchone()
    data["ras_total"] = ras["ras_total"] if ras else None

    apex = conn.execute(
        """
        SELECT matched_archetype, archetype_gap, gap_label,
               raw_score, pvc, apex_composite, apex_tier,
               capital_base, capital_adjusted, eval_confidence,
               strengths, red_flags, tags,
               failure_mode_primary, failure_mode_secondary,
               signature_play, translation_risk, bust_warning,
               v_processing, v_athleticism, v_scheme_vers, v_comp_tough,
               v_character, v_dev_traj, v_production, v_injury,
               model_version, smith_rule, schwesinger_full
        FROM apex_scores
        WHERE prospect_id = ? AND season_id = ?
        ORDER BY CASE model_version
            WHEN 'apex_v2.3' THEN 1
            WHEN 'apex_v2.2' THEN 2
            ELSE 3
        END
        LIMIT 1
        """,
        (prospect_id, season_id),
    ).fetchone()

    _apex_keys = [
        "matched_archetype", "archetype_gap", "gap_label",
        "raw_score", "pvc", "apex_composite", "apex_tier",
        "capital_base", "capital_adjusted", "eval_confidence",
        "strengths", "red_flags", "tags",
        "failure_mode_primary", "failure_mode_secondary",
        "signature_play", "translation_risk", "bust_warning",
        "v_processing", "v_athleticism", "v_scheme_vers", "v_comp_tough",
        "v_character", "v_dev_traj", "v_production", "v_injury",
        "model_version", "smith_rule", "schwesinger_full",
    ]
    if apex:
        for k in _apex_keys:
            data[k] = apex[k]
    else:
        for k in _apex_keys:
            data[k] = None

    div = conn.execute(
        """
        SELECT divergence_flag, divergence_rank_delta
        FROM divergence_flags
        WHERE prospect_id = ? AND season_id = ?
        ORDER BY div_id DESC LIMIT 1
        """,
        (prospect_id, season_id),
    ).fetchone()
    data["divergence_flag"]       = div["divergence_flag"]       if div else None
    data["divergence_rank_delta"] = div["divergence_rank_delta"] if div else None

    return data


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

_TRAITS = [
    ("Processing",   "v_processing"),
    ("Athleticism",  "v_athleticism"),
    ("Scheme Vers.", "v_scheme_vers"),
    ("Comp. Tough",  "v_comp_tough"),
    ("Character",    "v_character"),
    ("Dev. Traj.",   "v_dev_traj"),
    ("Production",   "v_production"),
    ("Durability",   "v_injury"),
]


def _trait_bar_color(val: float | None) -> str:
    if val is None:
        return "#2a2d42"
    if val >= 8.5:
        return "#00d4aa"
    if val >= 7.0:
        return "#4caf82"
    if val >= 5.0:
        return "#f5c518"
    return "#e05c5c"


def _trait_bars_html(data: dict) -> str:
    has_data = any(data.get(k) is not None for _, k in _TRAITS)
    if not has_data:
        return '<p style="color:#555a6e;font-style:italic;font-size:8pt;">Trait data pending evaluation.</p>'

    rows = []
    for label, key in _TRAITS:
        val = data.get(key)
        pct = min(100, max(0, float(val) * 10)) if val is not None else 0
        score_str = f"{val:.1f}" if val is not None else "—"
        bar_color = _trait_bar_color(val)
        rows.append(f"""
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:5px;">
          <span style="font-size:7pt;color:#7a8097;width:62px;flex-shrink:0;font-weight:500;">{label}</span>
          <div style="flex:1;height:5px;background:#1e2235;border-radius:3px;overflow:hidden;">
            <div style="width:{pct:.1f}%;height:100%;background:{bar_color};border-radius:3px;"></div>
          </div>
          <span style="font-size:8.5pt;font-weight:700;color:{bar_color};width:24px;text-align:right;">{score_str}</span>
        </div>""")

    return "".join(rows)


def _strengths_html(raw: str, color: str, bullet_color: str, limit: int = 4) -> str:
    lines = [l.strip() for l in (raw or "").split("\n") if l.strip()][:limit]
    if not lines:
        return '<span style="color:#555a6e;font-style:italic;font-size:7.5pt;">None recorded.</span>'
    items = "".join(
        f'<div style="display:flex;gap:7px;margin-bottom:5px;">'
        f'<span style="color:{bullet_color};flex-shrink:0;font-weight:700;font-size:8pt;">▸</span>'
        f'<span style="color:{color};font-size:7.5pt;line-height:1.4;">{l}</span>'
        f'</div>'
        for l in lines
    )
    return items


def _esc(s: str) -> str:
    """Minimal HTML-escape for text inserted into HTML."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_html(data: dict, comps: list[dict], rate: dict) -> str:
    # ── Core fields ─────────────────────────────────────────────────────────
    name      = _esc(data.get("display_name") or "Unknown")
    position  = _esc(data.get("position_group") or "—")
    school    = _esc(data.get("school_canonical") or "—")
    cons_rank = data.get("consensus_rank")
    ras       = data.get("ras_total")
    rpg       = data.get("raw_score")
    apex_comp = data.get("apex_composite")
    apex_tier = (data.get("apex_tier") or "").upper()
    pvc       = data.get("pvc") or 1.0
    archetype = _esc(data.get("matched_archetype") or "")
    fm_pri    = _esc(data.get("failure_mode_primary") or "")
    fm_sec    = _esc(data.get("failure_mode_secondary") or "")
    cap_adj   = data.get("capital_adjusted") or data.get("capital_base")
    eval_conf = data.get("eval_confidence") or ""
    sig_play  = _esc(data.get("signature_play") or "")
    trans_risk = _esc(data.get("translation_risk") or "")
    bust_warn  = _esc(data.get("bust_warning") or "")
    strengths  = data.get("strengths") or ""
    red_flags  = data.get("red_flags") or ""
    div_flag   = data.get("divergence_flag") or ""
    div_delta  = data.get("divergence_rank_delta")
    model_ver  = data.get("model_version") or "apex_v2.3"
    date_str   = datetime.now(timezone.utc).strftime("%b %d, %Y")

    tier_col  = _tier_hex(apex_tier)
    fm_col    = _fm_hex(fm_pri)

    # ── Derived display values ────────────────────────────────────────────────
    rank_str  = f"#{cons_rank}" if cons_rank else "Unranked"
    ras_str   = f"RAS {ras:.2f}" if ras else ""
    rpg_str   = _safe(rpg, ".1f")
    apex_str  = _safe(apex_comp, ".1f")
    pvc_str   = _safe(pvc, ".2f")
    pvc_line  = (
        f"RPG {rpg_str} × PVC {pvc_str} = APEX {apex_str}"
        if rpg and apex_comp else ""
    )

    if not cap_adj and cons_rank:
        if cons_rank <= 32:    cap_adj = "Round 1 — Day 1 Capital"
        elif cons_rank <= 64:  cap_adj = "Round 2 — Day 2 Early"
        elif cons_rank <= 105: cap_adj = "Round 3 — Day 2 Late"
        else:                  cap_adj = "Day 3 Capital"
    cap_adj = _esc(cap_adj or "—")

    # ── Divergence badge ─────────────────────────────────────────────────────
    div_html = ""
    if div_flag and div_delta is not None:
        sign = "+" if div_delta > 0 else ""
        d_col = "#00d4aa" if div_delta > 0 else "#e05c5c"
        div_html = (
            f'<span style="background:{d_col}22;border:1px solid {d_col};color:{d_col};'
            f'padding:2px 9px;border-radius:4px;font-size:7pt;font-weight:700;letter-spacing:0.5px;">'
            f'{_esc(div_flag)} {sign}{div_delta}</span>'
        )

    # ── Eval confidence badge ─────────────────────────────────────────────────
    conf_col = {"Tier A": "#00d4aa", "Tier B": "#f5c518", "Tier C": "#e05c5c"}.get(eval_conf, "#667085")
    conf_html = (
        f'<span style="color:{conf_col};font-size:7pt;font-weight:700;">{_esc(eval_conf)}</span>'
        if eval_conf else ""
    )

    # ── Trait bars ────────────────────────────────────────────────────────────
    trait_bars = _trait_bars_html(data)

    # ── Strengths / Red Flags ─────────────────────────────────────────────────
    str_html = _strengths_html(strengths, "#9ecbb0", "#4caf82")
    rf_html  = _strengths_html(red_flags, "#c9a0a0", "#e05c5c")

    # ── Signature play ────────────────────────────────────────────────────────
    sig_html = ""
    if sig_play:
        sig_html = f"""
        <div class="card full-width" style="border-left:3px solid #4299e1;background:#0c1020;">
          <div class="card-label">SIGNATURE PLAY</div>
          <div style="color:#b8c8e0;font-size:8pt;line-height:1.5;font-style:italic;">{sig_play}</div>
        </div>"""

    # ── Translation risk ──────────────────────────────────────────────────────
    trans_html = ""
    if trans_risk:
        trans_html = f"""
        <div class="card full-width" style="border-left:3px solid #f5c518;background:#0f0e08;">
          <div class="card-label" style="color:#f5c518;">⚠ TRANSLATION RISK</div>
          <div style="color:#c8b870;font-size:7.5pt;line-height:1.5;">{trans_risk}</div>
        </div>"""

    # ── FM section ────────────────────────────────────────────────────────────
    fm_html = ""
    if fm_pri:
        fm_desc = bust_warn or ""
        fm_pills = f'<span style="background:{fm_col}28;border:1px solid {fm_col};color:{fm_col};padding:3px 11px;border-radius:4px;font-size:8.5pt;font-weight:700;letter-spacing:0.5px;">{fm_pri}</span>'
        if fm_sec:
            sec_col = _fm_hex(fm_sec)
            fm_pills += f' <span style="background:{sec_col}28;border:1px solid {sec_col};color:{sec_col};padding:3px 11px;border-radius:4px;font-size:8.5pt;font-weight:700;margin-left:6px;">{fm_sec}</span>'
        fm_html = f"""
        <div class="card" style="border-left:3px solid {fm_col};background:#100a0a;">
          <div class="card-label" style="color:{fm_col};">FAILURE MODE RISK</div>
          <div style="margin-bottom:7px;">{fm_pills}</div>
          {"<div style='color:#c0a0a0;font-size:7.5pt;line-height:1.5;'>" + fm_desc + "</div>" if fm_desc else ""}
        </div>"""

    # ── Historical comps ──────────────────────────────────────────────────────
    comps_html = ""
    if comps and rate.get("total", 0) > 0:
        hit_pct = rate.get("hit_rate_pct", 0)
        hit_cnt = rate.get("hit_count", 0)
        total   = rate.get("total", 0)
        r_col   = "#00d4aa" if hit_pct >= 67 else "#f5c518" if hit_pct >= 40 else "#e05c5c"

        pills = ""
        for c in comps:
            oc = c["translation_outcome"]
            pc = {"HIT": "#0d2a1e", "PARTIAL": "#2a200a", "MISS": "#2a0d0d"}.get(oc, "#111827")
            tc = {"HIT": "#00d4aa", "PARTIAL": "#f5c518", "MISS": "#e05c5c"}.get(oc, "#8892a4")
            fm_note = f" · {c['fm_code']}" if c.get("fm_code") else ""
            pills += (
                f'<span style="background:{pc};border:1px solid {tc}44;color:{tc};'
                f'padding:3px 10px;border-radius:4px;font-size:7.5pt;font-weight:600;'
                f'margin-right:6px;margin-bottom:4px;display:inline-block;">'
                f'{_esc(c["player_name"])} ({oc}{_esc(fm_note)})</span>'
            )

        # short archetype code for label
        arch_code_str = _extract_archetype_code(archetype) if archetype else ""

        comps_html = f"""
        <div class="card full-width" style="background:#080e1c;border-color:#1a2a4a;">
          <div class="card-label">HISTORICAL COMPS</div>
          <div style="margin-bottom:8px;">
            <span style="color:#8892a4;font-size:7.5pt;">{arch_code_str} translation rate: </span>
            <span style="color:{r_col};font-size:8pt;font-weight:700;">{hit_pct}% HIT</span>
            <span style="color:#555a6e;font-size:7pt;"> ({hit_cnt} of {total})</span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;">{pills}</div>
        </div>"""

    # ── Tier badge ────────────────────────────────────────────────────────────
    tier_badge = ""
    if apex_tier:
        tier_badge = (
            f'<div style="display:inline-block;background:{tier_col}22;border:1px solid {tier_col};'
            f'color:{tier_col};padding:4px 16px;border-radius:4px;font-size:11pt;font-weight:700;'
            f'letter-spacing:2px;margin-top:6px;">{apex_tier}</div>'
        )

    # ── Meta badges ───────────────────────────────────────────────────────────
    meta_badges = (
        f'<span class="mbadge pos">{position}</span>'
        f'<span class="mbadge">{rank_str}</span>'
        f'<span class="mbadge">{school}</span>'
        + (f'<span class="mbadge">{ras_str}</span>' if ras_str else "")
    )

    # ── Archetype + FM header ─────────────────────────────────────────────────
    arch_display = (
        f'<span style="font-size:17pt;font-weight:700;color:#00d4aa;line-height:1;">{archetype}</span>'
        if archetype else
        '<span style="font-size:13pt;color:#555a6e;font-style:italic;">Archetype Pending Evaluation</span>'
    )
    fm_badge = (
        f'<span style="background:{fm_col}28;border:1px solid {fm_col};color:{fm_col};'
        f'padding:3px 10px;border-radius:4px;font-size:8.5pt;font-weight:700;'
        f'margin-left:10px;letter-spacing:0.5px;">{fm_pri}</span>'
        if fm_pri else ""
    )

    # ── Right-panel grid: determine which full-width blocks appear ────────────
    # We use a definition-based approach: sig + str/rf side-by-side + trans + fm + comps
    str_rf_grid = f"""
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="card">
          <div class="card-label" style="color:#4caf82;">✓ STRENGTHS</div>
          {str_html}
        </div>
        <div class="card">
          <div class="card-label" style="color:#e05c5c;">⚑ RED FLAGS</div>
          {rf_html}
        </div>
      </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}

@page {{
  size: 11in 8.5in landscape;
  margin: 0;
}}

body {{
  width: 11in;
  height: 8.5in;
  background: #090c18;
  color: #e0e4f0;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 9pt;
  overflow: hidden;
}}

.layout {{
  display: grid;
  grid-template-columns: 2.65in 8.35in;
  height: 8.5in;
  width: 11in;
}}

/* ── LEFT PANEL ─────────────────────── */
.left {{
  background: #0c0f1e;
  border-right: 1px solid #1a1e32;
  padding: 0.28in 0.22in 0.2in 0.22in;
  display: flex;
  flex-direction: column;
  gap: 0.14in;
  overflow: hidden;
}}

.player-name {{
  font-size: 26pt;
  font-weight: 900;
  color: #ffffff;
  line-height: 1.0;
  letter-spacing: -0.5px;
  font-family: Arial Narrow, Arial, sans-serif;
}}

.meta-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 5px;
}}

.mbadge {{
  background: #161929;
  border: 1px solid #252840;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 7pt;
  color: #7a8097;
  font-weight: 600;
  letter-spacing: 0.3px;
}}

.mbadge.pos {{
  background: #0a1e1a;
  border-color: #00d4aa55;
  color: #00d4aa;
  font-weight: 700;
}}

.scores-box {{
  background: #060810;
  border: 1px solid #1a1e32;
  border-radius: 7px;
  padding: 11px 10px 8px 10px;
}}

.scores-row {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-bottom: 6px;
}}

.score-block {{
  text-align: center;
}}

.score-num {{
  font-family: Arial Narrow, Arial, sans-serif;
  font-size: 36pt;
  font-weight: 900;
  line-height: 1.0;
  letter-spacing: -1px;
}}

.score-lbl {{
  font-size: 6pt;
  color: #555a6e;
  letter-spacing: 1px;
  text-transform: uppercase;
  margin-top: 2px;
}}

.pvc-line {{
  font-size: 6.5pt;
  color: #3a3f58;
  text-align: center;
  margin-top: 4px;
}}

.traits-section {{
  flex: 1;
  overflow: hidden;
}}

.section-title {{
  font-size: 6pt;
  letter-spacing: 1.5px;
  color: #3a3f58;
  text-transform: uppercase;
  margin-bottom: 8px;
  font-weight: 700;
}}

.left-footer {{
  border-top: 1px solid #1a1e32;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}}

.left-footer-row {{
  font-size: 6.5pt;
  color: #3a3f58;
  display: flex;
  justify-content: space-between;
}}

.left-footer-row span {{
  color: #667085;
}}

/* ── RIGHT PANEL ─────────────────────── */
.right {{
  padding: 0.22in 0.28in 0.18in 0.22in;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}}

.arch-bar {{
  display: flex;
  align-items: center;
  padding-bottom: 10px;
  border-bottom: 1px solid #1a1e32;
  gap: 8px;
  flex-wrap: nowrap;
}}

.arch-spacer {{ flex: 1; }}

/* Cards */
.card {{
  background: #0c0f1e;
  border: 1px solid #1a1e32;
  border-radius: 6px;
  padding: 9px 11px;
}}

.card-label {{
  font-size: 6pt;
  letter-spacing: 1.5px;
  color: #3a3f58;
  text-transform: uppercase;
  margin-bottom: 7px;
  font-weight: 700;
}}

.full-width {{
  /* used within a flex column — naturally full width */
}}

.right-body {{
  display: flex;
  flex-direction: column;
  gap: 9px;
  flex: 1;
  overflow: hidden;
}}

/* Footer */
.right-footer {{
  border-top: 1px solid #1a1e32;
  padding-top: 8px;
  display: flex;
  align-items: center;
  gap: 0.2in;
  flex-shrink: 0;
}}

.cap-label {{
  font-size: 6pt;
  color: #3a3f58;
  letter-spacing: 1px;
  text-transform: uppercase;
  margin-bottom: 2px;
}}

.cap-value {{
  font-family: Arial Narrow, Arial, sans-serif;
  font-size: 13pt;
  font-weight: 700;
  color: #e0e4f0;
  letter-spacing: -0.3px;
}}

.watermark {{
  font-family: Arial Narrow, Arial, sans-serif;
  font-size: 7.5pt;
  color: #1e2235;
  letter-spacing: 3px;
  text-transform: uppercase;
  font-weight: 700;
}}

.footer-meta {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}}

.footer-meta-line {{
  font-size: 6.5pt;
  color: #3a3f58;
}}

.footer-meta-line span {{
  color: #555a6e;
}}
</style>
</head>
<body>
<div class="layout">

  <!-- ── LEFT PANEL ──────────────────────────────────────────────────────── -->
  <div class="left">

    <!-- Name + meta -->
    <div>
      <div class="player-name">{name}</div>
      <div class="meta-row">{meta_badges}</div>
    </div>

    <!-- Scores -->
    <div class="scores-box">
      <div class="scores-row">
        <div class="score-block">
          <div class="score-num" style="color:#63b3ed;">{rpg_str}</div>
          <div class="score-lbl">Player Grade</div>
        </div>
        <div class="score-block">
          <div class="score-num" style="color:{tier_col};">{apex_str}</div>
          <div class="score-lbl">Draft Value</div>
        </div>
      </div>
      {tier_badge}
      {"<div class='pvc-line'>" + pvc_line + "</div>" if pvc_line else ""}
    </div>

    <!-- Trait bars -->
    <div class="traits-section">
      <div class="section-title">Player Profile</div>
      {trait_bars}
    </div>

    <!-- Left footer -->
    <div class="left-footer">
      {"<div class='left-footer-row'>Eval confidence: " + conf_html + "</div>" if conf_html else ""}
      {"<div class='left-footer-row'>Divergence: <span>" + div_html + "</span></div>" if div_html else ""}
      <div class="left-footer-row">Model: <span>{_esc(model_ver)}</span></div>
    </div>

  </div>

  <!-- ── RIGHT PANEL ─────────────────────────────────────────────────────── -->
  <div class="right">

    <!-- Archetype + FM bar -->
    <div class="arch-bar">
      {arch_display}
      {fm_badge}
      <div class="arch-spacer"></div>
    </div>

    <!-- Main content body -->
    <div class="right-body">

      {sig_html}

      {str_rf_grid}

      {trans_html}

      {fm_html}

      {comps_html}

    </div>

    <!-- Footer -->
    <div class="right-footer">
      <div style="flex:1;">
        <div class="cap-label">Draft Capital</div>
        <div class="cap-value">{cap_adj}</div>
      </div>
      <div class="footer-meta">
        <div class="watermark">DraftOS 2026</div>
        <div class="footer-meta-line">Generated <span>{date_str}</span></div>
        <div class="footer-meta-line">{rank_str} · {position} · <span>{school}</span></div>
      </div>
    </div>

  </div>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Playwright render helper (runs in its own thread to avoid asyncio conflicts
# with Streamlit's SelectorEventLoop on Windows)
# ---------------------------------------------------------------------------

def _playwright_render_thread(html_uri: str, out_path_str: str, error_box: list) -> None:
    try:
        import asyncio
        import sys
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(html_uri, wait_until="networkidle")
            page.pdf(
                path=out_path_str,
                width="11in",
                height="8.5in",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
    except Exception as exc:
        error_box.append(exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_pdf(prospect_id: int, season_id: int = SEASON_ID) -> Path:
    """
    Generate a one-pager PDF for the given prospect.
    Callable from Streamlit or CLI. Returns the output Path.
    Uses Playwright (Chromium) for HTML → PDF rendering.
    """
    out_dir = PATHS.root / "exports" / "reports" / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        data = _fetch_prospect_data(conn, prospect_id, season_id)

        archetype = data.get("matched_archetype") or ""
        comps: list[dict] = []
        rate: dict = {}
        if archetype:
            try:
                comps = get_historical_comps(conn, archetype, limit=3)
                rate  = get_archetype_translation_rate(conn, archetype)
            except Exception:
                pass

    html_str = _build_html(data, comps, rate)

    name_key = _slugify(data.get("display_name") or str(prospect_id))
    date_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = out_dir / f"{prospect_id}_{name_key}_{date_key}.pdf"

    # Write HTML to a temp file so Playwright can load it via file:// URI.
    # Playwright runs in a daemon thread so sync_playwright() gets a clean
    # event-loop scope, avoiding the NotImplementedError raised by Streamlit's
    # SelectorEventLoop on Windows when subprocess pipes are created.
    tmp_html = out_dir / f"_tmp_{prospect_id}.html"
    try:
        tmp_html.write_text(html_str, encoding="utf-8")

        html_uri = "file:///" + tmp_html.as_posix()
        error_box: list = []
        t = threading.Thread(
            target=_playwright_render_thread,
            args=(html_uri, str(out_path), error_box),
            daemon=True,
        )
        t.start()
        t.join(timeout=60)
        if t.is_alive():
            raise TimeoutError("PDF rendering timed out after 60 seconds")
        if error_box:
            raise error_box[0]
    finally:
        if tmp_html.exists():
            tmp_html.unlink()

    print(f"  [PDF] {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate DraftOS prospect one-pager PDF"
    )
    parser.add_argument("--prospect-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    path = generate_pdf(prospect_id=args.prospect_id, season_id=1)
    print(f"OK: {path}")


if __name__ == "__main__":
    main()
