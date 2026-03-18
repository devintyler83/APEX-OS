"""
DraftOS Big Board — Session 40
Read-only Streamlit UI with divergence flags, APEX rank input, APEX scores,
tag display, prospect detail drawer, stacking filters, and side-by-side comparison.
No DB writes except through save_apex_rank() and clear_apex_rank(). No business logic.
"""

import math
import re

import pandas as pd
import streamlit as st

from draftos.db.connect import connect
from draftos.queries.apex import save_apex_rank, clear_apex_rank, get_apex_detail
from draftos.queries.historical_comps import get_historical_comps, get_archetype_translation_rate, get_fm_reference_comps
from draftos.queries.model_outputs import get_big_board, get_prospect_detail, get_prospect_tags_map
from draftos.ui.profile_dimensions import get_profile_dimensions
from scripts.generate_prospect_pdf_2026 import generate_pdf

# Streamlit ≥ 1.35 supports on_select / selection_mode on st.dataframe
_ON_SELECT_AVAILABLE = tuple(
    int(x) for x in st.__version__.split(".")[:2]
) >= (1, 35)

st.set_page_config(layout="wide", page_title="DraftOS Big Board")

DRAFTOS_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;500;600;700;800;900&family=Barlow:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&display=swap');

/* ── DraftOS token system ── */
:root {
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
  --elite-dim: rgba(240,192,64,0.12);
}

/* ── Page title ── */
h1 {
  font-family: 'Barlow Condensed', sans-serif !important;
  font-weight: 800 !important;
  letter-spacing: -0.02em !important;
  text-transform: uppercase !important;
  color: rgba(255,255,255,0.92) !important;
}

/* ── Tab labels ── */
.stTabs [data-baseweb="tab"] {
  font-family: 'Barlow Condensed', sans-serif !important;
  font-weight: 700 !important;
  font-size: 13px !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  color: rgba(255,255,255,0.52) !important;
}
.stTabs [aria-selected="true"] {
  color: #7eb4e2 !important;
  border-bottom: 2px solid #7eb4e2 !important;
}

/* ── Sidebar header ── */
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stMarkdown h3 {
  font-family: 'Barlow Condensed', sans-serif !important;
  font-size: 10px !important;
  font-weight: 700 !important;
  letter-spacing: 0.16em !important;
  text-transform: uppercase !important;
  color: rgba(255,255,255,0.32) !important;
}

/* ── Divider ── */
hr {
  border-color: rgba(255,255,255,0.06) !important;
  margin: 10px 0 !important;
}

/* ── DraftOS detail panel classes ── */

.dos-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 48px;
  font-weight: 900;
  line-height: 0.92;
  letter-spacing: -0.02em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.92);
}

.dos-pos-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(126,180,226,0.15);
  border: 1px solid rgba(74,144,212,0.45);
  border-radius: 3px;
  padding: 3px 10px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #7eb4e2;
  text-transform: uppercase;
  margin-right: 10px;
  vertical-align: middle;
}

.dos-score-block {
  text-align: right;
}
.dos-score-num {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 52px;
  font-weight: 800;
  line-height: 0.92;
  letter-spacing: -0.02em;
}
.dos-score-num.rpg   { color: #7eb4e2; }
.dos-score-num.apex  { color: #e8a84a; }
.dos-score-lbl {
  font-family: 'Barlow', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.32);
  margin-top: 2px;
}

.dos-tier-ELITE  { background: rgba(240,192,64,0.12); border: 1px solid rgba(240,192,64,0.40); color: #f0c040; }
.dos-tier-DAY1   { background: rgba(126,180,226,0.10); border: 1px solid rgba(126,180,226,0.35); color: #7eb4e2; }
.dos-tier-DAY2   { background: rgba(90,184,122,0.10); border: 1px solid rgba(90,184,122,0.35); color: #5ab87a; }
.dos-tier-DAY3   { background: rgba(232,168,74,0.10); border: 1px solid rgba(232,168,74,0.30); color: #e8a84a; }
.dos-tier-UDFAP  { background: rgba(196,122,224,0.10); border: 1px solid rgba(196,122,224,0.30); color: #c47ae0; }
.dos-tier-UDFA   { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.45); }

.dos-tier-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 16px;
  border-radius: 4px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.dos-sec-lbl {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.32);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.dos-panel {
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  padding: 14px 16px;
  margin: 8px 0;
}

.dos-arch-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 22px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #e8a84a;
  line-height: 1;
}

.dos-fit-CLEAN       { background: rgba(90,184,122,0.12); border: 1px solid rgba(90,184,122,0.30); color: #5ab87a; }
.dos-fit-SOLID       { background: rgba(90,184,122,0.10); border: 1px solid rgba(90,184,122,0.25); color: #5ab87a; }
.dos-fit-TWEENER     { background: rgba(232,168,74,0.12); border: 1px solid rgba(232,168,74,0.30); color: #e8a84a; }
.dos-fit-COMPRESSION { background: rgba(91,156,240,0.12); border: 1px solid rgba(91,156,240,0.30); color: #5b9cf0; }
.dos-fit-NO_FIT      { background: rgba(224,92,92,0.12); border: 1px solid rgba(224,92,92,0.30); color: #e05c5c; }

.dos-fit-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 3px;
  font-family: 'Barlow', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.dos-fm-1 { background: rgba(224,92,92,0.12); border: 1px solid rgba(224,92,92,0.35); color: #e05c5c; }
.dos-fm-2 { background: rgba(232,168,74,0.12); border: 1px solid rgba(232,168,74,0.35); color: #e8a84a; }
.dos-fm-3 { background: rgba(91,156,240,0.14); border: 1px solid rgba(91,156,240,0.35); color: #5b9cf0; }
.dos-fm-4 { background: rgba(224,92,92,0.14); border: 1px solid rgba(224,92,92,0.38); color: #e05c5c; }
.dos-fm-5 { background: rgba(196,122,224,0.14); border: 1px solid rgba(196,122,224,0.35); color: #c47ae0; }
.dos-fm-6 { background: rgba(165,126,224,0.14); border: 1px solid rgba(165,126,224,0.35); color: #a57ee0; }

.dos-fm-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 3px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-right: 8px;
}

.dos-fm-pips {
  display: flex;
  gap: 3px;
  margin-bottom: 10px;
}
.dos-fm-pip {
  flex: 1;
  height: 4px;
  border-radius: 1.5px;
  background: rgba(255,255,255,0.06);
}
.dos-pip-1 { background: #e05c5c; }
.dos-pip-2 { background: #e8a84a; }
.dos-pip-3 { background: #5b9cf0; }
.dos-pip-4 { background: #e05c5c; }
.dos-pip-5 { background: #c47ae0; }
.dos-pip-6 { background: #a57ee0; }

.dos-trait-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
}
.dos-trait-lbl {
  font-family: 'Barlow', sans-serif;
  font-size: 11px;
  font-weight: 500;
  color: rgba(255,255,255,0.52);
  width: 160px;
  flex-shrink: 0;
  letter-spacing: 0.01em;
}
.dos-trait-track {
  flex: 1;
  height: 3px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  overflow: hidden;
}
.dos-trait-fill {
  height: 100%;
  border-radius: 2px;
}
.dos-tf-hi  { background: #5ab87a; }
.dos-tf-mid { background: #7eb4e2; }
.dos-tf-lo  { background: #e8a84a; }
.dos-tf-red { background: #e05c5c; }
.dos-trait-val {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13px;
  font-weight: 700;
  width: 28px;
  text-align: right;
  color: rgba(255,255,255,0.88);
}

.dos-sig-play {
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.06);
  border-left: 3px solid #4a90d4;
  border-radius: 0 5px 5px 0;
  padding: 12px 16px;
  margin: 10px 0;
}
.dos-sig-lbl {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #7eb4e2;
  margin-bottom: 6px;
}
.dos-sig-text {
  font-family: 'Barlow', sans-serif;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255,255,255,0.60);
  font-style: italic;
}

.dos-risk-banner {
  background: rgba(232,168,74,0.08);
  border: 1px solid rgba(232,168,74,0.18);
  border-left: 3px solid #c98828;
  border-radius: 0 5px 5px 0;
  padding: 10px 14px;
  margin: 10px 0;
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.dos-risk-icon {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13px;
  font-weight: 800;
  color: #e8a84a;
  flex-shrink: 0;
  margin-top: 1px;
}
.dos-risk-text {
  font-family: 'Barlow', sans-serif;
  font-size: 12px;
  line-height: 1.6;
  color: rgba(232,168,74,0.78);
}

.dos-sf-panel {
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 5px;
  padding: 12px 14px;
}
.dos-sf-hdr {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.dos-sf-hdr.g { color: #5ab87a; }
.dos-sf-hdr.r { color: #e05c5c; }
.dos-sf-ind { width: 5px; height: 5px; border-radius: 1px; flex-shrink: 0; }
.dos-sf-ind.g { background: #5ab87a; }
.dos-sf-ind.r { background: #e05c5c; }
.dos-sf-item {
  font-family: 'Barlow', sans-serif;
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255,255,255,0.55);
  padding: 5px 0;
  border-top: 1px solid rgba(255,255,255,0.05);
  display: flex;
  gap: 7px;
  align-items: flex-start;
}
.dos-sf-item:first-of-type { border-top: none; }
.dos-dot { width: 3px; height: 3px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.dos-dot.g { background: #5ab87a; }
.dos-dot.r { background: rgba(224,92,92,0.55); }

.dos-comp-card {
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 5px;
  padding: 14px;
  position: relative;
  overflow: hidden;
  flex: 1;
}
.dos-comp-card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
}
.dos-comp-card.hit::before     { background: linear-gradient(180deg, #5ab87a, rgba(90,184,122,0.3)); }
.dos-comp-card.partial::before { background: linear-gradient(180deg, #e8a84a, rgba(232,168,74,0.3)); }
.dos-comp-card.miss::before    { background: linear-gradient(180deg, #e05c5c, rgba(224,92,92,0.3)); }

.dos-comp-type {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.dos-comp-type.hit     { color: #5ab87a; }
.dos-comp-type.partial { color: #e8a84a; }
.dos-comp-type.miss    { color: #e05c5c; }

.dos-comp-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 20px;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: rgba(255,255,255,0.92);
  line-height: 1;
  margin-bottom: 6px;
}
.dos-comp-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: 'Barlow', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 2px;
  margin-bottom: 8px;
}
.dos-comp-badge.hit     { background: rgba(90,184,122,0.10); color: #5ab87a; border: 1px solid rgba(90,184,122,0.25); }
.dos-comp-badge.partial { background: rgba(232,168,74,0.10); color: #e8a84a; border: 1px solid rgba(232,168,74,0.25); }
.dos-comp-badge.miss    { background: rgba(224,92,92,0.10);  color: #e05c5c; border: 1px solid rgba(224,92,92,0.25); }

.dos-comp-desc {
  font-family: 'Barlow', sans-serif;
  font-size: 11px;
  line-height: 1.6;
  color: rgba(255,255,255,0.35);
  margin-bottom: 6px;
}
.dos-comp-year {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 9px;
  color: rgba(255,255,255,0.18);
  letter-spacing: 0.06em;
}

.dos-formula {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 10px;
  color: rgba(255,255,255,0.28);
  letter-spacing: 0.04em;
  margin-top: 6px;
}

.dos-meta {
  font-family: 'Barlow', sans-serif;
  font-size: 12px;
  color: rgba(255,255,255,0.38);
  letter-spacing: 0.02em;
  margin-top: 4px;
}
.dos-meta span {
  color: rgba(255,255,255,0.52);
}

.dos-div-bar {
  background: rgba(91,156,240,0.08);
  border: 1px solid rgba(91,156,240,0.18);
  border-left: 3px solid #4a90d4;
  border-radius: 0 4px 4px 0;
  padding: 8px 14px;
  margin: 8px 0 12px 0;
  font-family: 'Barlow', sans-serif;
  font-size: 12px;
  line-height: 1.55;
  color: rgba(255,255,255,0.52);
}

.dos-cap-row {
  display: flex;
  gap: 40px;
  flex-wrap: wrap;
}
.dos-cap-lbl {
  font-family: 'Barlow', sans-serif;
  font-size: 10px;
  color: rgba(255,255,255,0.32);
  margin-bottom: 3px;
  letter-spacing: 0.04em;
}
.dos-cap-val {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 18px;
  font-weight: 700;
  color: rgba(255,255,255,0.88);
}

.dos-eval-footer {
  font-family: 'Barlow', sans-serif;
  font-size: 11px;
  color: rgba(255,255,255,0.28);
  letter-spacing: 0.04em;
  margin-top: 6px;
}

.dos-fm-ref-card {
  border-radius: 4px;
  padding: 10px 14px;
  margin-bottom: 6px;
  background: #0d1117;
}
.dos-fm-ref-outcome {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.dos-fm-ref-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 18px;
  font-weight: 800;
  text-transform: uppercase;
  color: rgba(255,255,255,0.88);
  letter-spacing: 0.02em;
}
.dos-fm-ref-meta {
  font-family: 'Barlow', sans-serif;
  font-size: 12px;
  color: rgba(255,255,255,0.38);
}
.dos-fm-ref-era {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 10px;
  color: rgba(255,255,255,0.22);
  letter-spacing: 0.06em;
}
.dos-bust-mech {
  font-family: 'Barlow', sans-serif;
  font-size: 12px;
  line-height: 1.6;
  padding: 8px 12px;
  margin: 4px 0 10px 0;
  border-left: 3px solid #e05c5c;
  background: rgba(224,92,92,0.05);
  color: rgba(224,92,92,0.80);
}
.dos-bust-lbl {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(224,92,92,0.55);
  margin-right: 4px;
}
</style>
"""
st.markdown(DRAFTOS_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tag display maps
# ---------------------------------------------------------------------------

# Frontend display labels — used in board column text AND pill labels (unified)
_TAGS_DISPLAY_MAP: dict[str, str] = {
    # Athletic scores
    "Elite RAS":          "🌟 Elite Athlete",
    "Great RAS":          "✅ Good Athlete",
    "Poor RAS":           "⚠️ Ath. Concern",
    "Terrible RAS":       "🚫 Poor Athlete",
    # Risk
    "Injury Flag":        "🚨 Injury Risk",
    "Injury Risk":        "🚨 Injury Risk",
    "Character Watch":    "🔴 Char. Watch",
    "Off-Field Concerns": "🔴 Off-Field",
    "Film Concern":       "🎬 Film Concern",
    "Possible Bust":      "💣 Bust Risk",
    # Informational
    "Compression Flag":   "🔀 Tweener",
    "Divergence Alert":   "⚡ Divergence",
    "Scheme Dependent":   "🎯 Scheme Dep.",
    "Development Bet":    "📈 Dev Bet",
    "Floor Play":         "🛡️ Floor Play",
    "Riser":              "📈 Riser",
    "Faller":             "📉 Faller",
    "Scheme Fit":         "✅ Scheme Fit",
    # Conviction
    "Want":               "💚 Want",
    "Do Not Want":        "❌ Do Not Want",
    "Sleeper":            "👀 Sleeper",
    "Top 5 NextGen":      "🏆 Top 5",
    # Editorial
    "Film Favorite":      "🎬 Film Fav",
    "Great Combine":      "💪 Great Combine",
    "Great Pro Day":      "💪 Great Pro Day",
    "Trade-Up Target":    "🔝 Trade-Up",
    "Value Zone":         "💰 Value Zone",
    # Legacy engine tags
    "Smith Rule":         "⚠️ Char. Cap",
    "CRUSH":              "💎 Crush",
    "Walk-On Flag":       "🏃 Walk-On",
    "Two-Way Premium":    "🔄 Two-Way",
    "Schwesinger Rule":   "🚀 Elite Char.",
}

# Pill colors: (background, border, text) — dark theme styled
_TAG_PILL_COLORS: dict[str, tuple[str, str, str]] = {
    "Elite RAS":          ("#1a2e1a", "#2d5a2d", "#7defa7"),
    "Great RAS":          ("#1a2e28", "#2d5040", "#5de8a0"),
    "Poor RAS":           ("#2e1a1a", "#5a2d2d", "#ef7d7d"),
    "Terrible RAS":       ("#1e0a0a", "#4a1a1a", "#ef5252"),
    "Injury Flag":        ("#2e1a00", "#5a3500", "#ef9f44"),
    "Injury Risk":        ("#2e1a00", "#5a3500", "#ef9f44"),
    "Character Watch":    ("#2e0000", "#5a0000", "#ef4444"),
    "Off-Field Concerns": ("#2e0000", "#5a0000", "#ef4444"),
    "Film Concern":       ("#1a1a2e", "#2d2d5a", "#9898ef"),
    "Possible Bust":      ("#2e1a00", "#5a3800", "#ef8844"),
    "Compression Flag":   ("#1e1a2e", "#3d2d5a", "#c4a8ef"),
    "Divergence Alert":   ("#2e2400", "#5a4800", "#ffd666"),
    "Scheme Dependent":   ("#1a1a2e", "#2d2d5a", "#7d7def"),
    "Development Bet":    ("#1a1f2e", "#2d3d5a", "#7ab8ef"),
    "Floor Play":         ("#1a2e1a", "#2d5a2d", "#7def7d"),
    "Riser":              ("#1a2e1a", "#2d5a2d", "#7def7d"),
    "Faller":             ("#2e1a1a", "#5a2d2d", "#ef7d7d"),
    "Scheme Fit":         ("#1a2e28", "#2d5040", "#5de8a0"),
    "Want":               ("#1a2e1a", "#2d5a2d", "#7defa7"),
    "Do Not Want":        ("#2e1a1a", "#5a2d2d", "#ef7d7d"),
    "Sleeper":            ("#1a2400", "#385500", "#b8ef44"),
    "Top 5 NextGen":      ("#2e2400", "#5a4800", "#ffd666"),
    "Film Favorite":      ("#1a1a2e", "#2d2d5a", "#9898ef"),
    "Great Combine":      ("#1a2e28", "#2d5040", "#5de8a0"),
    "Great Pro Day":      ("#1a2e28", "#2d5040", "#5de8a0"),
    "Trade-Up Target":    ("#2e2400", "#5a4800", "#ffd666"),
    "Value Zone":         ("#1a2e1a", "#2d5a2d", "#7defa7"),
    "Smith Rule":         ("#2e0000", "#5a0000", "#ef4444"),
    "CRUSH":              ("#2e2400", "#5a4800", "#ffd666"),
    "Walk-On Flag":       ("#1a1a1a", "#333333", "#ffffff"),
    "Two-Way Premium":    ("#1a2e28", "#2d5040", "#5de8a0"),
    "Schwesinger Rule":   ("#1a2e1a", "#2d5a2d", "#7defa7"),
}
_TAG_PILL_DEFAULT: tuple[str, str, str] = ("#1e1e2e", "#3d3d5a", "#9d9dba")

# Short labels for sidebar checkboxes (concise UI)
_TAG_LABEL_MAP: dict[str, str] = {
    "Divergence Alert":  "⚡ DIV",
    "Development Bet":   "📈 DEV",
    "Compression Flag":  "⚖ COMP",
    "Elite RAS":         "🔥 ERAS",
    "Great RAS":         "✓ GRAS",
    "Poor RAS":          "⚠ PRAS",
    "Injury Flag":       "🩹 INJ",
}

# Ordered list for sidebar checkboxes
_SIDEBAR_TAGS: list[str] = [
    "Divergence Alert",
    "Development Bet",
    "Compression Flag",
    "Elite RAS",
    "Great RAS",
    "Poor RAS",
    "Injury Flag",
]

# APEX tier canonical sort order
_APEX_TIER_ORDER: dict[str, int] = {
    "ELITE":  0,
    "DAY1":   1,
    "DAY2":   2,
    "DAY3":   3,
    "UDFA-P": 4,
    "UDFA":   5,
}

_GAP_LABEL_DISPLAY_MAP: dict[str, str] = {
    "CLEAN":       "✅ Clean Fit",
    "SOLID":       "🟢 Solid Fit",
    "TWEENER":     "⚠️ Tweener",
    "COMPRESSION": "🔵 Elite Tweener",
    "NO_FIT":      "🔴 No Dominant Fit",
}

_GAP_LABEL_EXPLANATIONS: dict[str, str] = {
    "CLEAN":       "Dominant single-archetype match. High translation confidence — this player's NFL role is clear.",
    "SOLID":       "Clear primary archetype fit. Good translation confidence with a defined NFL projection.",
    "TWEENER":     "Split identity between archetypes. Landing spot determines which version you get.",
    "COMPRESSION": "Elite traits compress multiple archetypes. Positive signal — versatile deployment ceiling.",
    "NO_FIT":      "No dominant archetype. Significant role clarity risk — deployment context unclear.",
}

_FM_COLORS: dict[str, str] = {
    "FM-1": "#F56565",   # red — Athleticism Mirage
    "FM-2": "#ED8936",   # orange — Scheme Ghost
    "FM-3": "#ECC94B",   # yellow — Processing Wall
    "FM-4": "#F6AD55",   # amber — Body Breakdown
    "FM-5": "#FC8181",   # light red — Motivation Cliff
    "FM-6": "#9F7AEA",   # purple — Role Mismatch
}

_FM_DESCRIPTIONS: dict[str, str] = {
    "FM-1": "Athleticism Mirage — tests well, functional athleticism does not survive NFL speed.",
    "FM-2": "Scheme Ghost — production manufactured by system; remove scheme, production collapses.",
    "FM-3": "Processing Wall — college instincts hit NFL complexity ceiling; read-to-action gap becomes fatal.",
    "FM-4": "Body Breakdown — physical profile cannot sustain NFL volume; great when healthy, healthy is not sustainable.",
    "FM-5": "Motivation Cliff — external driver disappears post-contract; effort becomes variable.",
    "FM-6": "Role Mismatch — skills real but deployment context never materializes on the NFL roster.",
}

_INTERNAL_TAG_NAMES: frozenset[str] = frozenset({
    "apex_rank_2026",
})

# ---------------------------------------------------------------------------
# Divergence narrative — deterministic one-sentence explanation
# ---------------------------------------------------------------------------

_TRAIT_LABELS: dict[str, str] = {
    "v_processing":  "Processing & Instincts",
    "v_athleticism": "Athleticism",
    "v_scheme_vers": "Scheme Versatility",
    "v_comp_tough":  "Competitive Toughness",
    "v_character":   "Character & Intangibles",
    "v_dev_traj":    "Development Trajectory",
    "v_production":  "Production",
    "v_injury":      "Injury & Durability",
}

# Positional average baselines — traits above these are "model sees",
# traits below are "market discounting"
_POSITIONAL_BASELINES: dict[str, dict[str, float]] = {
    "QB":   {"v_processing":8.0,"v_athleticism":7.0,"v_scheme_vers":7.5,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.5,
             "v_production":7.5,"v_injury":7.5},
    "EDGE": {"v_processing":7.0,"v_athleticism":8.0,"v_scheme_vers":6.5,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "CB":   {"v_processing":7.5,"v_athleticism":8.0,"v_scheme_vers":7.0,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "OT":   {"v_processing":7.0,"v_athleticism":7.5,"v_scheme_vers":7.0,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "IDL":  {"v_processing":7.0,"v_athleticism":7.5,"v_scheme_vers":6.5,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "ILB":  {"v_processing":7.5,"v_athleticism":7.0,"v_scheme_vers":7.0,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "OLB":  {"v_processing":7.0,"v_athleticism":7.5,"v_scheme_vers":7.0,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "S":    {"v_processing":7.5,"v_athleticism":7.5,"v_scheme_vers":7.5,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "OG":   {"v_processing":7.0,"v_athleticism":7.0,"v_scheme_vers":7.0,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "C":    {"v_processing":7.5,"v_athleticism":7.0,"v_scheme_vers":7.0,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "TE":   {"v_processing":7.0,"v_athleticism":7.5,"v_scheme_vers":7.5,
             "v_comp_tough":7.0,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.0,"v_injury":7.5},
    "RB":   {"v_processing":7.0,"v_athleticism":8.0,"v_scheme_vers":6.5,
             "v_comp_tough":7.5,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.5,"v_injury":7.0},
    "WR":   {"v_processing":7.5,"v_athleticism":8.0,"v_scheme_vers":7.0,
             "v_comp_tough":7.0,"v_character":7.0,"v_dev_traj":7.0,
             "v_production":7.5,"v_injury":7.5},
}
_DEFAULT_BASELINE: dict[str, float] = {k: 7.5 for k in _TRAIT_LABELS}


def _fallback_narrative(name: str, delta: int, fm: str | None, position: str) -> str:
    direction = "above" if delta > 0 else "below"
    abs_delta = abs(delta)
    if fm and delta < 0:
        return (
            f"APEX ranks {abs_delta} spots {direction} consensus: "
            f"model flags {fm} bust risk not priced into market ranking."
        )
    return (
        f"APEX ranks {abs_delta} spots {direction} consensus: "
        f"positional value framework ({position}) diverges from market consensus ranking."
    )


def build_divergence_narrative(
    display_name: str,
    position: str,
    divergence_delta: int,
    trait_scores: dict,
    fm_primary: str | None,
) -> str | None:
    """
    Return a one-sentence divergence narrative, or None if abs(delta) < 5.
    Deterministic: same inputs always produce the same sentence.
    """
    if abs(divergence_delta) < 5:
        return None

    baseline = _POSITIONAL_BASELINES.get(position, _DEFAULT_BASELINE)

    # Compute delta-from-baseline for each trait that has a value
    deltas = {
        k: round((trait_scores.get(k) or 0.0) - baseline.get(k, 7.5), 1)
        for k in _TRAIT_LABELS
        if trait_scores.get(k) is not None
    }

    if not deltas:
        return _fallback_narrative(display_name, divergence_delta, fm_primary, position)

    sorted_deltas = sorted(deltas.items(), key=lambda x: x[1], reverse=True)

    # Top 2 above baseline = "model sees"
    model_sees = [(k, v) for k, v in sorted_deltas if v > 0][:2]
    # Bottom 1-2 below baseline = "market discounting"
    market_discounts = [(k, v) for k, v in sorted_deltas if v < 0][-2:]

    direction = "above" if divergence_delta > 0 else "below"
    abs_delta = abs(divergence_delta)

    if model_sees and market_discounts:
        sees_str = " and ".join(
            f"{_TRAIT_LABELS[k]} ({trait_scores[k]:.1f})"
            for k, _ in model_sees
        )
        discount_str = " and ".join(
            f"{_TRAIT_LABELS[k]} ({trait_scores[k]:.1f})"
            for k, _ in market_discounts
        )
        return (
            f"APEX ranks {abs_delta} spots {direction} consensus: "
            f"model weights {sees_str} above positional norm; "
            f"market is discounting {discount_str}."
        )
    elif model_sees and divergence_delta > 0:
        # APEX higher than consensus and traits are uniformly strong: cite top traits
        sees_str = " and ".join(
            f"{_TRAIT_LABELS[k]} ({trait_scores[k]:.1f})"
            for k, _ in model_sees
        )
        return (
            f"APEX ranks {abs_delta} spots {direction} consensus: "
            f"model weights {sees_str} significantly above positional norm."
        )
    else:
        # APEX lower than consensus with strong traits = PVC structural discount,
        # or no interpretable pattern — use positional framework fallback
        return _fallback_narrative(display_name, divergence_delta, fm_primary, position)


# ---------------------------------------------------------------------------
# Position and tier visual config (detail card)
# ---------------------------------------------------------------------------

_POS_BADGE_COLORS: dict[str, str] = {
    "QB":   "#7b2fff",
    "EDGE": "#ff5e3a",
    "CB":   "#00b4d8",
    "ILB":  "#f4a261",
    "OLB":  "#f4a261",
    "OT":   "#48cae4",
    "OG":   "#48cae4",
    "C":    "#48cae4",
    "S":    "#06d6a0",
    "WR":   "#ff9f1c",
    "TE":   "#e9c46a",
    "RB":   "#ef476f",
    "IDL":  "#a8dadc",
}

# (badge background, badge text)
_APEX_TIER_BADGE: dict[str, tuple[str, str]] = {
    "ELITE":  ("#ffd700", "#000000"),
    "DAY1":   ("#1a73e8", "#ffffff"),
    "DAY2":   ("#2e7d32", "#ffffff"),
    "DAY3":   ("#f57f17", "#000000"),
    "UDFA-P": ("#546e7a", "#ffffff"),
    "UDFA":   ("#37474f", "#ffffff"),
}

# Score text colors by tier
_APEX_SCORE_COLORS: dict[str, str] = {
    "ELITE":  "#ffd700",
    "DAY1":   "#7ab8ef",
    "DAY2":   "#69f0ae",
    "DAY3":   "#ffd740",
    "UDFA-P": "#90a4ae",
    "UDFA":   "#78909c",
}

# Archetype fit badge: (bg, text)
_GAP_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "CLEAN":       ("#00e676", "#000000"),
    "SOLID":       ("#69f0ae", "#000000"),
    "TWEENER":     ("#ffd740", "#000000"),
    "COMPRESSION": ("#82b1ff", "#000000"),
    "NO_FIT":      ("#ff5252", "#ffffff"),
}


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def _render_tag_pill(tag_name: str) -> str:
    """
    Return a styled HTML pill for a single tag_name.
    Uses _TAGS_DISPLAY_MAP for label — consistent with board column text.
    """
    label = _TAGS_DISPLAY_MAP.get(tag_name, tag_name)
    bg, border, text = _TAG_PILL_COLORS.get(tag_name, _TAG_PILL_DEFAULT)
    return (
        f'<span style="background:{bg};border:1px solid {border};color:{text};'
        f'border-radius:3px;padding:2px 9px;font-family:\'Barlow Condensed\',sans-serif;'
        f'font-size:10px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;'
        f'display:inline-block;margin:2px">{label}</span>'
    )


def render_tag_pills(tag_names: list[str]) -> str:
    """Return HTML string of styled pill spans for the given tag names."""
    return "".join(
        _render_tag_pill(t) for t in tag_names if t not in _INTERNAL_TAG_NAMES
    )


def _fmt_tags_text(tag_names_str: str) -> str:
    """Format pipe-delimited tag names as display text for dataframe cells."""
    if not tag_names_str:
        return ""
    tags = [t.strip() for t in tag_names_str.split("|") if t.strip()]
    tags = [t for t in tags if t not in _INTERNAL_TAG_NAMES]
    return "  ".join(_TAGS_DISPLAY_MAP.get(t, t) for t in tags)


def _parse_tags(tag_names_str: str) -> list[str]:
    """Parse pipe-delimited tag string into list."""
    if not tag_names_str:
        return []
    return [t.strip() for t in tag_names_str.split("|") if t.strip()]


def _fmt_tags(raw) -> str:
    """Format comma-delimited tag names for board display. Filters internal system tags."""
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    parts = [t.strip() for t in str(raw).split(",") if t.strip()]
    parts = [p for p in parts if p not in _INTERNAL_TAG_NAMES]
    return "  ".join(_TAGS_DISPLAY_MAP.get(p, p) for p in parts)


def _render_gap_label(gap_label: str | None, archetype_gap: float | None) -> str:
    if not gap_label:
        return ""
    return _GAP_LABEL_DISPLAY_MAP.get(gap_label.strip().upper(), gap_label.strip().title())


def _safe_float(v, fmt=".1f"):
    """Return formatted float string or '—'."""
    if v is None:
        return "—"
    try:
        f = float(v)
        if math.isnan(f):
            return "—"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "—"


def _v23_present(v) -> bool:
    """True when a v2.3 text field contains usable content."""
    if v is None:
        return False
    if isinstance(v, float):
        return not math.isnan(v)
    return bool(str(v).strip())


def _fm_is_present(v) -> bool:
    if v is None:
        return False
    if isinstance(v, float):
        return not math.isnan(v)
    return str(v).strip().upper() not in ("", "NONE", "N/A")


# ---------------------------------------------------------------------------
# Trait bar helpers (detail card)
# ---------------------------------------------------------------------------

def _bar_color(val: float) -> str:
    if val >= 9.0:
        return "#00e676"
    if val >= 7.0:
        return "#69f0ae"
    if val >= 5.0:
        return "#ffd740"
    return "#ff5252"


def _trait_bar_html(label: str, val: float | None) -> str:
    """
    DraftOS-branded trait bar with threshold color system.
    >= 8.5  -> green  (hi)
    7.0-8.4 -> cold blue (mid)
    5.0-6.9 -> amber (lo)
    < 5.0   -> red (red)
    """
    if val is None or (isinstance(val, float) and math.isnan(val)) or val == 0.0:
        return (
            f'<div class="dos-trait-row">'
            f'<span class="dos-trait-lbl">{label}</span>'
            f'<div class="dos-trait-track"></div>'
            f'<span class="dos-trait-val" style="color:rgba(255,255,255,0.22)">—</span>'
            f'</div>'
        )

    pct = min(max(val / 10.0 * 100, 0), 100)

    if val >= 8.5:
        color_cls = "dos-tf-hi"
        val_color = "#5ab87a"
    elif val >= 7.0:
        color_cls = "dos-tf-mid"
        val_color = "#7eb4e2"
    elif val >= 5.0:
        color_cls = "dos-tf-lo"
        val_color = "#e8a84a"
    else:
        color_cls = "dos-tf-red"
        val_color = "#e05c5c"

    return (
        f'<div class="dos-trait-row">'
        f'<span class="dos-trait-lbl">{label}</span>'
        f'<div class="dos-trait-track">'
        f'<div class="dos-trait-fill {color_cls}" style="width:{pct:.0f}%"></div>'
        f'</div>'
        f'<span class="dos-trait-val" style="color:{val_color}">{val:.1f}</span>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Detail card renderers
# ---------------------------------------------------------------------------

def _render_apex_detail(d: dict) -> None:
    """
    DraftOS Classified Dossier x Prizm visual rebuild.
    Full replacement for the original _render_apex_detail function.
    Signature unchanged. All DB calls and session_state wiring are upstream.
    """

    # ── Unpack core fields ──────────────────────────────────────────────────
    pos       = d.get("position_group") or "?"
    name      = d.get("display_name") or "Unknown"
    school    = d.get("school_canonical") or "—"
    tier      = (d.get("apex_tier") or "").strip().upper()
    crank     = d.get("consensus_rank")
    conf      = d.get("confidence_band") or "—"
    ras_raw   = d.get("ras_score") or d.get("ras_total")

    rank_str  = f"#{int(crank)}" if crank is not None and pd.notna(crank) else "—"
    ras_str   = _safe_float(ras_raw, ".2f") if ras_raw is not None and pd.notna(ras_raw) else "—"
    raw_str   = _safe_float(d.get("raw_score"))
    comp_str  = _safe_float(d.get("apex_composite"))
    pvc_str   = _safe_float(d.get("pvc"), ".2f")

    # Tier badge CSS class
    tier_css_map = {
        "ELITE": "dos-tier-ELITE",
        "DAY1":  "dos-tier-DAY1",
        "DAY2":  "dos-tier-DAY2",
        "DAY3":  "dos-tier-DAY3",
        "UDFA-P":"dos-tier-UDFAP",
        "UDFA":  "dos-tier-UDFA",
    }
    tier_css  = tier_css_map.get(tier, "dos-tier-UDFA")
    tier_lbl  = {"ELITE": "★ ELITE"}.get(tier, tier or "—")

    # ── HEADER ZONE ─────────────────────────────────────────────────────────
    header_l, header_r = st.columns([5, 3])

    with header_l:
        st.markdown(
            f'<div style="margin-bottom:4px">'
            f'<span class="dos-pos-chip">{pos}</span>'
            f'</div>'
            f'<div class="dos-name">{name}</div>'
            f'<div class="dos-meta" style="margin-top:8px">'
            f'<span>{school}</span>'
            f'&nbsp;·&nbsp;Consensus <span>{rank_str}</span>'
            f'&nbsp;·&nbsp;Confidence: <span>{conf}</span>'
            + (f'&nbsp;·&nbsp;RAS: <span>{ras_str}</span>' if ras_str != "—" else "")
            + f'</div>',
            unsafe_allow_html=True,
        )

    with header_r:
        st.markdown(
            f'<div class="dos-score-block">'
            f'<div style="display:flex;justify-content:flex-end;align-items:baseline;gap:28px;margin-bottom:4px">'

            f'<div style="text-align:center">'
            f'<div class="dos-score-num rpg">{raw_str}</div>'
            f'<div class="dos-score-lbl">Player Grade</div>'
            f'</div>'

            f'<div style="text-align:center">'
            f'<div class="dos-score-num apex">{comp_str}</div>'
            f'<div class="dos-score-lbl">Draft Value</div>'
            f'</div>'

            f'<div style="text-align:center;align-self:center">'
            f'<div class="dos-tier-badge {tier_css}">{tier_lbl}</div>'
            f'</div>'

            f'</div>'
            f'<div class="dos-formula">'
            f'RPG {raw_str} × {pvc_str} ({pos}) = APEX {comp_str}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── HEADER DIVIDER ───────────────────────────────────────────────────────
    st.markdown(
        '<div style="height:1px;background:linear-gradient(90deg,'
        '#4a90d4 0%,rgba(74,144,212,0.3) 40%,transparent 100%);margin:12px 0 16px 0"></div>',
        unsafe_allow_html=True,
    )

    # ── DIVERGENCE NARRATIVE ─────────────────────────────────────────────────
    _div_delta = d.get("auto_apex_delta")
    if _div_delta is not None:
        _narr_traits = {
            "v_processing":  d.get("v_processing"),
            "v_athleticism": d.get("v_athleticism"),
            "v_scheme_vers": d.get("v_scheme_vers"),
            "v_comp_tough":  d.get("v_comp_tough"),
            "v_character":   d.get("v_character"),
            "v_dev_traj":    d.get("v_dev_traj"),
            "v_production":  d.get("v_production"),
            "v_injury":      d.get("v_injury"),
        }
        _narrative = build_divergence_narrative(
            display_name=d.get("display_name", ""),
            position=d.get("position_group", ""),
            divergence_delta=int(_div_delta),
            trait_scores=_narr_traits,
            fm_primary=d.get("failure_mode_primary"),
        )
        if _narrative:
            st.markdown(
                f'<div class="dos-div-bar">📊 {_narrative}</div>',
                unsafe_allow_html=True,
            )

    # ── PLAYER PROFILE / TRAIT METERS ───────────────────────────────────────
    _traits_raw = {
        "v_processing":     d.get("v_processing"),
        "v_athleticism":    d.get("v_athleticism"),
        "v_scheme_vers":    d.get("v_scheme_vers"),
        "v_comp_tough":     d.get("v_comp_tough"),
        "v_character":      d.get("v_character"),
        "v_dev_traj":       d.get("v_dev_traj"),
        "v_production":     d.get("v_production"),
        "v_injury":         d.get("v_injury"),
        "c1_public_record": d.get("c1_public_record"),
        "c2_motivation":    d.get("c2_motivation"),
        "c3_psych_profile": d.get("c3_psych_profile"),
    }
    _traits = {
        k: (float(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else 0.0)
        for k, v in _traits_raw.items()
    }
    _has_apex_data = any(v > 0 for v in _traits.values())

    if _has_apex_data:
        st.markdown('<div class="dos-sec-lbl">Player Profile</div>', unsafe_allow_html=True)

        profile_dims = get_profile_dimensions(d.get("position_group", ""), _traits)
        has_profile = len(profile_dims) > 0 and any(s > 0 for _, s in profile_dims)

        prof_col1, prof_col2 = st.columns([4, 1])
        with prof_col2:
            if has_profile:
                profile_view = st.radio(
                    "View",
                    options=["Football", "System"],
                    index=0,
                    horizontal=True,
                    key=f"profile_view_{d['prospect_id']}",
                    label_visibility="collapsed",
                )
            else:
                profile_view = "System"

        if profile_view == "Football" and has_profile:
            display_bars = profile_dims
        else:
            display_bars = [
                ("Processing & Instincts",  _traits["v_processing"]),
                ("Athleticism",             _traits["v_athleticism"]),
                ("Scheme Versatility",      _traits["v_scheme_vers"]),
                ("Competitive Toughness",   _traits["v_comp_tough"]),
                ("Character & Intangibles", _traits["v_character"]),
                ("Dev. Trajectory",         _traits["v_dev_traj"]),
                ("Production",              _traits["v_production"]),
                ("Injury & Durability",     _traits["v_injury"]),
            ]

        mid = (len(display_bars) + 1) // 2
        bar_col1, bar_col2 = st.columns(2)
        with bar_col1:
            st.markdown(
                "".join(_trait_bar_html(lbl, val) for lbl, val in display_bars[:mid]),
                unsafe_allow_html=True,
            )
        with bar_col2:
            st.markdown(
                "".join(_trait_bar_html(lbl, val) for lbl, val in display_bars[mid:]),
                unsafe_allow_html=True,
            )

        # Character sub-scores
        c1, c2, c3 = d.get("c1_public_record"), d.get("c2_motivation"), d.get("c3_psych_profile")
        if any(v is not None for v in [c1, c2, c3]):
            sub = []
            if c1 is not None: sub.append(f"Off-field: <span style='color:rgba(255,255,255,0.65)'>{c1:.1f}</span>")
            if c2 is not None: sub.append(f"Motor & drive: <span style='color:rgba(255,255,255,0.65)'>{c2:.1f}</span>")
            if c3 is not None: sub.append(f"Mental makeup: <span style='color:rgba(255,255,255,0.65)'>{c3:.1f}</span>")
            st.markdown(
                f'<div class="dos-meta" style="margin-top:6px">{"  ·  ".join(sub)}</div>',
                unsafe_allow_html=True,
            )

        # Special rule badges
        badges = []
        if d.get("smith_rule"):
            badges.append(("⚠", "#e8a84a", "Character cap applied — draft capital reduced"))
        if d.get("schwesinger_full"):
            badges.append(("▲", "#5ab87a", "Elite character bonus — Dev Trajectory boosted (full)"))
        if d.get("schwesinger_half"):
            badges.append(("▲", "#5ab87a", "Character bonus — Dev Trajectory boosted"))
        if d.get("two_way_premium"):
            badges.append(("◈", "#7eb4e2", "Two-way prospect — scored at higher-value position"))
        for icon, color, text in badges:
            st.markdown(
                f'<div class="dos-meta" style="color:{color};margin-top:4px">{icon} {text}</div>',
                unsafe_allow_html=True,
            )

    # ── ARCHETYPE BLOCK ──────────────────────────────────────────────────────
    arch      = d.get("matched_archetype") or "—"
    gap_label = (d.get("gap_label") or "").strip().upper()
    fit_score = d.get("archetype_gap")
    fit_str   = f"{fit_score:.1f} pts" if fit_score is not None else "—"
    gap_display = _GAP_LABEL_DISPLAY_MAP.get(gap_label, gap_label.title() if gap_label else "—")

    arch_parts = arch.split(" ", 1) if arch != "—" else ["—", ""]
    arch_code  = arch_parts[0]
    arch_label = arch_parts[1] if len(arch_parts) > 1 else ""

    fit_css_map = {
        "CLEAN":       "dos-fit-CLEAN",
        "SOLID":       "dos-fit-SOLID",
        "TWEENER":     "dos-fit-TWEENER",
        "COMPRESSION": "dos-fit-COMPRESSION",
        "NO_FIT":      "dos-fit-NO_FIT",
    }
    fit_css = fit_css_map.get(gap_label, "dos-fit-SOLID")

    st.markdown(
        f'<div class="dos-panel" style="margin-top:18px">'
        f'<div class="dos-sec-lbl" style="border-bottom:none;margin-bottom:8px;padding-bottom:0">Archetype</div>'
        f'<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">'
        f'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:11px;'
        f'font-weight:700;letter-spacing:0.18em;color:#7eb4e2;text-transform:uppercase">{arch_code}</span>'
        f'<span class="dos-arch-name">{arch_label or arch}</span>'
        f'<span class="dos-fit-badge {fit_css}">{gap_display}</span>'
        f'<span style="font-family:\'Barlow\',sans-serif;font-size:11px;color:rgba(255,255,255,0.32);'
        f'margin-left:4px">Fit: {fit_str}</span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    gap_explanation = _GAP_LABEL_EXPLANATIONS.get(gap_label, "")
    if gap_explanation:
        st.markdown(
            f'<div class="dos-meta" style="margin:6px 0 0 2px">{gap_explanation}</div>',
            unsafe_allow_html=True,
        )

    if d.get("override_arch"):
        od = d.get("override_delta") or 0
        st.markdown(
            f'<div style="background:rgba(232,168,74,0.08);border:1px solid rgba(232,168,74,0.20);'
            f'border-left:3px solid #c98828;border-radius:0 4px 4px 0;padding:8px 14px;margin:8px 0">'
            f'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:9px;font-weight:700;'
            f'letter-spacing:0.16em;text-transform:uppercase;color:#e8a84a">Override</span>'
            f'<span style="font-family:\'Barlow\',sans-serif;font-size:12px;color:rgba(232,168,74,0.80);'
            f'margin-left:8px">{d["override_arch"]} (Δ{od:+.1f}) — '
            f'{d.get("override_rationale") or "No rationale recorded."}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── FAILURE MODE RISK ────────────────────────────────────────────────────
    fm_primary   = d.get("failure_mode_primary")
    fm_secondary = d.get("failure_mode_secondary")

    if _fm_is_present(fm_primary):
        fm_code     = str(fm_primary)[:4]
        fm_num      = fm_code.replace("FM-", "")
        fm_css      = f"dos-fm-{fm_num}" if fm_num in "123456" else "dos-fm-3"
        pip_css_map = {"1":"dos-pip-1","2":"dos-pip-2","3":"dos-pip-3",
                       "4":"dos-pip-4","5":"dos-pip-5","6":"dos-pip-6"}

        active_codes = set()
        if _fm_is_present(fm_primary):
            _m = re.search(r"FM-(\d+)", str(fm_primary))
            if _m: active_codes.add(_m.group(1))
        if _fm_is_present(fm_secondary):
            _m = re.search(r"FM-(\d+)", str(fm_secondary))
            if _m: active_codes.add(_m.group(1))

        pips_html = "".join(
            f'<div class="dos-fm-pip {pip_css_map.get(str(i), "")}">'
            f'</div>'
            if str(i) in active_codes
            else f'<div class="dos-fm-pip"></div>'
            for i in range(1, 7)
        )

        fm_tags_html = f'<span class="dos-fm-badge {fm_css}">{fm_primary}</span>'
        if _fm_is_present(fm_secondary):
            fm_sec_code = str(fm_secondary)[:4]
            fm_sec_num  = fm_sec_code.replace("FM-", "")
            fm_sec_css  = f"dos-fm-{fm_sec_num}" if fm_sec_num in "123456" else "dos-fm-6"
            fm_tags_html += f'<span class="dos-fm-badge {fm_sec_css}">{fm_secondary}</span>'

        bust_warning = d.get("bust_warning")
        fm_mechanism_text = (
            str(bust_warning).strip()
            if _fm_is_present(bust_warning)
            else _FM_DESCRIPTIONS.get(fm_code, str(fm_primary))
        )

        st.markdown(
            f'<div class="dos-panel" style="margin-top:12px">'
            f'<div class="dos-sec-lbl" style="border-bottom:none;margin-bottom:8px;padding-bottom:0">Failure Mode Risk</div>'
            f'<div class="dos-fm-pips">{pips_html}</div>'
            f'<div>{fm_tags_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="dos-meta" style="margin:4px 0 8px 2px">{fm_mechanism_text}</div>',
            unsafe_allow_html=True,
        )

    # ── DRAFT CAPITAL ────────────────────────────────────────────────────────
    cap_base = d.get("capital_base") or "—"
    cap_adj  = d.get("capital_adjusted") or "—"

    st.markdown(
        f'<div class="dos-panel" style="margin-top:12px">'
        f'<div class="dos-sec-lbl" style="border-bottom:none;margin-bottom:10px;padding-bottom:0">Draft Capital</div>'
        f'<div class="dos-cap-row">'
        f'<div><div class="dos-cap-lbl">Base</div><div class="dos-cap-val">{cap_base}</div></div>'
        f'<div><div class="dos-cap-lbl">Adjusted (PVC)</div><div class="dos-cap-val">{cap_adj}</div></div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── DIVIDER ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="height:1px;background:rgba(255,255,255,0.06);margin:20px 0 16px 0"></div>',
        unsafe_allow_html=True,
    )

    # ── SIGNATURE PLAY ───────────────────────────────────────────────────────
    sig_play = d.get("signature_play")
    if _v23_present(sig_play):
        st.markdown(
            f'<div class="dos-sig-play">'
            f'<div class="dos-sig-lbl">◆ Signature Play</div>'
            f'<div class="dos-sig-text">{sig_play}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── STRENGTHS + RED FLAGS ────────────────────────────────────────────────
    strengths  = d.get("strengths")
    red_flags  = d.get("red_flags")
    trans_risk = d.get("translation_risk")

    def _build_sf_items(text: str, dot_cls: str) -> str:
        if not _v23_present(text):
            return (
                '<div class="dos-sf-item"><span class="dos-dot ' + dot_cls + '"></span>'
                '<span style="color:rgba(255,255,255,0.22);font-style:italic">Not yet available</span></div>'
            )
        lines = [l.strip() for l in str(text).split("\n") if l.strip()]
        if not lines:
            lines = [str(text).strip()]
        items = []
        for line in lines[:3]:
            items.append(
                f'<div class="dos-sf-item">'
                f'<span class="dos-dot {dot_cls}"></span>'
                f'<span>{line}</span>'
                f'</div>'
            )
        return "".join(items)

    str_col, rf_col = st.columns(2)

    with str_col:
        st.markdown(
            f'<div class="dos-sf-panel">'
            f'<div class="dos-sf-hdr g">'
            f'<span class="dos-sf-ind g"></span>Strengths'
            f'</div>'
            f'{_build_sf_items(strengths, "g")}'
            f'</div>',
            unsafe_allow_html=True,
        )

    with rf_col:
        st.markdown(
            f'<div class="dos-sf-panel">'
            f'<div class="dos-sf-hdr r">'
            f'<span class="dos-sf-ind r"></span>Red Flags'
            f'</div>'
            f'{_build_sf_items(red_flags, "r")}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── TRANSLATION RISK BANNER ───────────────────────────────────────────────
    if _v23_present(trans_risk):
        st.markdown(
            f'<div class="dos-risk-banner">'
            f'<span class="dos-risk-icon">!</span>'
            f'<div class="dos-risk-text">{trans_risk}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── HISTORICAL COMPS ─────────────────────────────────────────────────────
    _arch_code = d.get("matched_archetype")
    if _arch_code:
        with connect() as _hconn:
            _comps = get_historical_comps(_hconn, _arch_code, limit=3)
            _rate  = get_archetype_translation_rate(_hconn, _arch_code)

        if _comps:
            st.markdown(
                '<div style="height:1px;background:rgba(255,255,255,0.06);margin:20px 0 16px 0"></div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="dos-sec-lbl">Historical Comps</div>', unsafe_allow_html=True)

            _hit_pct = _rate["hit_rate_pct"]
            _hit_cnt = _rate["hit_count"]
            _total   = _rate["total"]
            rate_color = (
                "#5ab87a" if _hit_pct >= 67
                else "#e8a84a" if _hit_pct >= 40
                else "#e05c5c"
            )
            st.markdown(
                f'<div class="dos-meta" style="margin-bottom:6px">'
                f'{_arch_code} translation rate: '
                f'<span style="color:{rate_color};font-weight:700">{_hit_pct}% HIT</span>'
                f' ({_hit_cnt} of {_total})</div>',
                unsafe_allow_html=True,
            )

            _comp_parts = []
            for _c in _comps:
                _icon = {"HIT": "✓", "PARTIAL": "~", "MISS": "✗"}.get(
                    _c["translation_outcome"], ""
                )
                _fm_note = f" · {_c['fm_code']}" if _c.get("fm_code") else ""
                _comp_parts.append(
                    f'<span style="color:rgba(255,255,255,0.52)">'
                    f'{_c["player_name"]}</span>'
                    f'<span style="color:rgba(255,255,255,0.28)">'
                    f' ({_icon}{_c["translation_outcome"]}{_fm_note})</span>'
                )
            st.markdown(
                '<div class="dos-meta" style="margin-bottom:12px">Mechanism comps: '
                + ' · '.join(_comp_parts)
                + '</div>',
                unsafe_allow_html=True,
            )

            prominent = _comps[:2]
            comp_cols = st.columns(len(prominent))

            _outcome_to_cls = {"HIT": "hit", "PARTIAL": "partial", "MISS": "miss"}

            for col, _c in zip(comp_cols, prominent):
                oc  = _c["translation_outcome"]
                cls = _outcome_to_cls.get(oc, "miss")
                with col:
                    st.markdown(
                        f'<div class="dos-comp-card {cls}">'
                        f'<div class="dos-comp-type {cls}">'
                        f'{"Archetype Ceiling" if oc == "HIT" else "FM Risk Comp" if oc == "PARTIAL" else "Miss Pattern"}'
                        f'</div>'
                        f'<div class="dos-comp-name">{_c["player_name"]}</div>'
                        f'<span class="dos-comp-badge {cls}">{oc}</span>'
                        f'<div class="dos-comp-desc">{_c.get("outcome_summary","")}</div>'
                        f'<div class="dos-comp-year">{_c.get("era_bracket","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            if len(_comps) > 2:
                with st.expander("All comp details"):
                    for _c in _comps:
                        oc = _c["translation_outcome"]
                        oc_color = {"HIT": "#5ab87a", "PARTIAL": "#e8a84a", "MISS": "#e05c5c"}.get(oc, "#888")
                        st.markdown(
                            f'<span style="color:{oc_color};font-weight:700">{_c["player_name"]}</span>'
                            f' ({_c["era_bracket"]}) — {_c.get("outcome_summary","")}',
                            unsafe_allow_html=True,
                        )

    # ── FM RISK REFERENCE ────────────────────────────────────────────────────
    _fm_primary_str  = d.get("failure_mode_primary") or ""
    _fm_primary_code = None
    if _fm_primary_str:
        _fm_m = re.search(r"FM-\d+", _fm_primary_str)
        if _fm_m:
            _fm_primary_code = _fm_m.group(0)

    if _fm_primary_code:
        with connect() as _fmconn:
            _fm_ref_comps = get_fm_reference_comps(
                _fmconn,
                _fm_primary_code,
                archetype_code=d.get("matched_archetype"),
                limit=2,
            )

        _frc_prospect_pos = (d.get("position_group") or "").upper()

        if _fm_ref_comps:
            st.markdown(
                '<div style="height:1px;background:rgba(255,255,255,0.06);margin:20px 0 16px 0"></div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="dos-sec-lbl">FM Risk Reference</div>', unsafe_allow_html=True)

            _OUTCOME_COLOR = {
                "MISS":    "#e05c5c",
                "PARTIAL": "#e8a84a",
                "HIT":     "#5ab87a",
            }

            for _frc in _fm_ref_comps:
                _frc_outcome = _frc.get("translation_outcome", "MISS")
                _frc_color   = _OUTCOME_COLOR.get(_frc_outcome, "#888888")
                _frc_player  = _frc.get("player_name", "")
                _frc_arch    = _frc.get("archetype_code", "")
                _frc_fm      = _frc.get("fm_code", "")
                _frc_era     = _frc.get("era_bracket") or ""
                _frc_summary = _frc.get("outcome_summary") or ""
                _frc_mech    = _frc.get("fm_mechanism") or ""
                _frc_pre     = _frc.get("pre_draft_signal") or ""

                _frc_comp_pos = _frc_arch.split("-")[0].strip() if _frc_arch and "-" in _frc_arch else ""
                _frc_is_cross = bool(_frc_comp_pos) and _frc_comp_pos != _frc_prospect_pos
                _cross_html = ""
                if _frc_is_cross:
                    _cross_html = (
                        f'<div style="font-family:\'Barlow\',sans-serif;font-size:11px;'
                        f'color:rgba(232,168,74,0.75);margin:4px 0 6px 0;line-height:1.5">'
                        f'Cross-position reference — {_frc_fm} mechanism is position-independent. '
                        f'{_frc_comp_pos} shown as highest-severity historical pattern.'
                        f'</div>'
                    )

                st.markdown(
                    f'<div class="dos-fm-ref-card" style="border-left:3px solid {_frc_color}">'
                    f'<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px">'
                    f'<span class="dos-fm-ref-outcome" style="color:{_frc_color}">■ {_frc_outcome}</span>'
                    f'<span class="dos-fm-ref-name">{_frc_player}</span>'
                    f'<span class="dos-fm-ref-meta">{_frc_arch} · {_frc_fm}</span>'
                    f'<span class="dos-fm-ref-era" style="margin-left:auto">{_frc_era}</span>'
                    f'</div>'
                    f'{_cross_html}'
                    + (f'<div style="font-family:\'Barlow\',sans-serif;font-size:13px;'
                       f'color:rgba(255,255,255,0.60);line-height:1.6;margin-bottom:4px">'
                       f'{_frc_summary}</div>' if _frc_summary else "")
                    + f'</div>',
                    unsafe_allow_html=True,
                )

                if _frc_pre:
                    with st.expander("Pre-draft signal", expanded=True):
                        st.markdown(
                            f'<div style="font-family:\'Barlow\',sans-serif;font-size:12px;'
                            f'line-height:1.6;color:rgba(255,255,255,0.55)">{_frc_pre}</div>',
                            unsafe_allow_html=True,
                        )

                if _frc_mech:
                    st.markdown(
                        f'<div class="dos-bust-mech">'
                        f'<span class="dos-bust-lbl">Bust mechanism:</span>{_frc_mech}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                st.markdown(
                    '<div style="height:1px;background:rgba(255,255,255,0.05);margin:8px 0"></div>',
                    unsafe_allow_html=True,
                )

    # ── EVAL CONFIDENCE FOOTER ───────────────────────────────────────────────
    conf_field = d.get("eval_confidence") or "—"
    scored_at  = d.get("scored_at") or ""
    conf_color_map = {"Tier A": "#5ab87a", "Tier B": "#e8a84a", "Tier C": "#e05c5c"}
    conf_color = conf_color_map.get(conf_field, "rgba(255,255,255,0.28)")

    st.markdown(
        f'<div style="height:1px;background:rgba(255,255,255,0.06);margin:16px 0 10px 0"></div>'
        f'<div class="dos-eval-footer">'
        f'Eval Confidence: <span style="color:{conf_color};font-weight:700">{conf_field}</span>'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'Scored: {scored_at[:10] if scored_at else "—"}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_consensus_card(row) -> None:
    """Minimal detail card for prospects not yet APEX-scored."""
    h1, h2, h3, h4 = st.columns([3, 1, 2, 2])
    h1.markdown(f"**{row['display_name']}**")
    h2.markdown(f"`{row['position_group']}`")
    h3.markdown(f"{row['school_canonical'] or '—'}")
    _crank = int(row["consensus_rank"]) if pd.notna(row.get("consensus_rank")) else "—"
    h4.markdown(f"Consensus #{_crank}")
    _ras = row.get("ras_score")
    _ras_str = f"{_ras:.2f}" if _ras is not None and pd.notna(_ras) else "—"
    st.caption(
        f"Tier: {row.get('consensus_tier', '—')}   |   "
        f"Confidence: {row.get('confidence_band', '—')}   |   "
        f"Sources: {row.get('coverage_count', '—')}   |   "
        f"RAS: {_ras_str}"
    )
    _dflag = row.get("divergence_flag")
    if _dflag is not None and pd.notna(_dflag) and _dflag == 1:
        _delta = row.get("divergence_delta")
        _direction = "higher" if _delta and _delta < 0 else "lower"
        _delta_abs = abs(_delta) if _delta else "?"
        st.info(
            f"⚡ Divergence flag: JFoster ranks this prospect "
            f"{_direction} than consensus ({_delta_abs} spots)."
        )
    st.caption("*Not yet APEX-scored. Run apex_scoring to generate full profile.*")


def _render_compare_panel(name_a: str, name_b: str, board_df: pd.DataFrame) -> None:
    """Render side-by-side prospect comparison panel."""
    row_a = board_df[board_df["display_name"] == name_a]
    row_b = board_df[board_df["display_name"] == name_b]
    if row_a.empty or row_b.empty:
        st.warning("One or both prospects not found in current board.")
        return

    pa = row_a.iloc[0]
    pb = row_b.iloc[0]
    pid_a = int(pa["prospect_id"])
    pid_b = int(pb["prospect_id"])

    # Load APEX detail for capital + FM fields (only for scored prospects)
    da: dict | None = None
    db: dict | None = None
    if pd.notna(pa.get("apex_composite")):
        with connect() as conn:
            da = get_apex_detail(conn, prospect_id=pid_a)
    if pd.notna(pb.get("apex_composite")):
        with connect() as conn:
            db = get_apex_detail(conn, prospect_id=pid_b)

    def _get(detail, row, key, board_key=None, fmt=None):
        """Pull value from detail dict (preferred) or board row, return formatted string."""
        v = None
        if detail and detail.get(key) is not None:
            _raw = detail[key]
            if not (isinstance(_raw, float) and pd.isna(_raw)):
                v = _raw
        if v is None and board_key is not None:
            _raw = row.get(board_key)
            if _raw is not None and not (isinstance(_raw, float) and pd.isna(_raw)):
                v = _raw
        if v is None:
            return "—"
        if fmt:
            try:
                return fmt(v)
            except Exception:
                return str(v)
        return str(v)

    def _num(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except Exception:
            return None

    apex_a = _num(pa.get("apex_composite"))
    apex_b = _num(pb.get("apex_composite"))
    rpg_a  = _num(pa.get("raw_score"))
    rpg_b  = _num(pb.get("raw_score"))
    rank_a = _num(pa.get("consensus_rank"))
    rank_b = _num(pb.get("consensus_rank"))

    fmt_score = lambda v: f"{float(v):.1f}"
    fmt_rank  = lambda v: f"#{int(v)}"

    # (label, val_a_str, val_b_str, direction, raw_a, raw_b)
    # direction: "high" = higher wins, "low" = lower wins, None = no highlight
    compare_rows = [
        ("Name",            name_a,                                                              name_b,                                                              None,   None,   None),
        ("Position",        str(pa.get("position_group") or "—"),                               str(pb.get("position_group") or "—"),                               None,   None,   None),
        ("School",          str(pa.get("school_canonical") or "—"),                             str(pb.get("school_canonical") or "—"),                             None,   None,   None),
        ("Archetype",       _get(da, pa, "matched_archetype", "apex_archetype"),                _get(db, pb, "matched_archetype", "apex_archetype"),                None,   None,   None),
        ("APEX Score",      _get(da, pa, "apex_composite", "apex_composite", fmt_score),        _get(db, pb, "apex_composite", "apex_composite", fmt_score),        "high", apex_a, apex_b),
        ("APEX Tier",       str(pa.get("apex_tier") or "—"),                                    str(pb.get("apex_tier") or "—"),                                    None,   None,   None),
        ("Consensus Rank",  _get(da, pa, "consensus_rank", "consensus_rank", fmt_rank),         _get(db, pb, "consensus_rank", "consensus_rank", fmt_rank),         "low",  rank_a, rank_b),
        ("RPG",             _get(da, pa, "raw_score", "raw_score", fmt_score),                  _get(db, pb, "raw_score", "raw_score", fmt_score),                  "high", rpg_a,  rpg_b),
        ("FM Primary",      _get(da, pa, "failure_mode_primary", "failure_mode_primary"),       _get(db, pb, "failure_mode_primary", "failure_mode_primary"),       None,   None,   None),
        ("Capital (Base)",  _get(da, pa, "capital_base"),                                       _get(db, pb, "capital_base"),                                       None,   None,   None),
        ("Capital (Adj.)",  _get(da, pa, "capital_adjusted"),                                   _get(db, pb, "capital_adjusted"),                                   None,   None,   None),
        ("Eval Confidence", _get(da, pa, "eval_confidence", "eval_confidence"),                 _get(db, pb, "eval_confidence", "eval_confidence"),                 None,   None,   None),
    ]

    st.subheader("⚖️ Comparison")
    hdr_lbl, hdr_a, hdr_b = st.columns([2, 3, 3])
    with hdr_lbl:
        st.markdown('<div style="font-size:11px;color:#ffffff;letter-spacing:1px">FIELD</div>', unsafe_allow_html=True)
    with hdr_a:
        st.markdown(f'<div style="font-size:14px;font-weight:700;color:#63B3ED">{name_a}</div>', unsafe_allow_html=True)
    with hdr_b:
        st.markdown(f'<div style="font-size:14px;font-weight:700;color:#68D391">{name_b}</div>', unsafe_allow_html=True)

    st.markdown("<hr style='border-color:#333;margin:4px 0 8px 0'>", unsafe_allow_html=True)

    for label, va, vb, direction, raw_a, raw_b in compare_rows:
        style_a = style_b = "color:#ffffff"
        if direction and raw_a is not None and raw_b is not None:
            try:
                fa, fb = float(raw_a), float(raw_b)
                if direction == "high":
                    if fa > fb:
                        style_a = "color:#69f0ae;font-weight:700"
                    elif fb > fa:
                        style_b = "color:#69f0ae;font-weight:700"
                elif direction == "low":
                    if fa < fb:
                        style_a = "color:#69f0ae;font-weight:700"
                    elif fb < fa:
                        style_b = "color:#69f0ae;font-weight:700"
            except Exception:
                pass

        col_lbl, col_a, col_b = st.columns([2, 3, 3])
        with col_lbl:
            st.markdown(f'<div style="font-size:13px;color:#ffffff;padding:3px 0">{label}</div>', unsafe_allow_html=True)
        with col_a:
            st.markdown(f'<div style="font-size:13px;{style_a};padding:3px 0">{va}</div>', unsafe_allow_html=True)
        with col_b:
            st.markdown(f'<div style="font-size:13px;{style_b};padding:3px 0">{vb}</div>', unsafe_allow_html=True)

    if da is None:
        st.caption(f"APEX score pending for {name_a}.")
    if db is None:
        st.caption(f"APEX score pending for {name_b}.")


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def _load_board() -> list[dict] | None:
    try:
        with connect() as conn:
            return get_big_board(conn)
    except Exception as e:
        st.session_state["_load_error"] = str(e)
        return None


@st.cache_data(ttl=30)
def _load_detail(prospect_id: int) -> dict | None:
    try:
        with connect() as conn:
            return get_prospect_detail(conn, prospect_id=prospect_id)
    except Exception:
        return None


@st.cache_data(ttl=300)
def _load_active_tag_defs() -> list[dict]:
    """
    Return tag definitions for all tags that have at least one active prospect_tag,
    ordered by display_order. Excludes internal tags (apex_rank_2026).
    """
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT DISTINCT td.tag_name, td.description, td.tag_category,
                                td.display_order
                FROM prospect_tags pt
                JOIN tag_definitions td ON td.tag_def_id = pt.tag_def_id
                WHERE pt.is_active = 1
                  AND td.is_active = 1
                  AND td.tag_name NOT IN ('apex_rank_2026')
                ORDER BY td.display_order, td.tag_name
            """).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


raw = _load_board()

if raw is None:
    err = st.session_state.get("_load_error", "Unknown error")
    st.error(f"DB not found or failed to load. Run pipeline first.\n\n{err}")
    st.stop()

if not raw:
    st.warning("No board data found. Run pipeline to generate snapshot.")
    st.stop()

df = pd.DataFrame(raw)

# Ensure tag_names column exists (defensive fallback)
if "tag_names" not in df.columns:
    df["tag_names"] = ""
else:
    df["tag_names"] = df["tag_names"].fillna("")

# Add APEX tier sort key (not displayed — used for correct column sort order)
df["_apex_tier_sort"] = df["apex_tier"].map(
    lambda x: _APEX_TIER_ORDER.get(str(x).strip(), 99) if x else 99
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
snapshot_date   = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else "unknown"
total_prospects = len(df)
apex_scored     = df["apex_composite"].notna().sum() if "apex_composite" in df.columns else 0

st.title("DraftOS — 2026 Big Board")
st.caption(
    f"Snapshot: {snapshot_date}   |   "
    f"Total prospects: {total_prospects}   |   "
    f"APEX v2.3 scored: {apex_scored}"
)

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")

    show_low = st.checkbox("Show Low confidence", value=False)

    show_divergence_only = st.checkbox("Show divergence flags only (⚡)", value=False)

    show_apex_only = st.checkbox("Show APEX scored only (auto-rank)", value=False)

    show_apex_scored_only = st.checkbox("Show APEX scored only", value=False)

    all_positions = sorted(df["position_group"].dropna().unique().tolist())
    selected_positions = st.multiselect(
        "Position group",
        options=all_positions,
        default=all_positions,
    )

    all_tiers = ["Elite", "Strong", "Playable", "Watch"]
    present_tiers = [t for t in all_tiers if t in df["consensus_tier"].unique()]
    selected_tiers = st.multiselect(
        "Consensus tier",
        options=present_tiers,
        default=present_tiers,
    )

    # APEX tier filter — draft-capital vocabulary, all 6 tiers
    if apex_scored > 0 and "apex_tier" in df.columns:
        apex_tier_options = ["(all)", "ELITE", "DAY1", "DAY2", "DAY3", "UDFA-P", "UDFA"]
        selected_apex_tier = st.selectbox("APEX tier", options=apex_tier_options, index=0)
    else:
        selected_apex_tier = "(all)"

    school_search = st.text_input("School (contains search)", value="")

    ras_values = df["ras_score"].dropna()
    if not ras_values.empty:
        ras_min = float(ras_values.min())
        ras_max = float(ras_values.max())
        ras_range = st.slider(
            "RAS score range",
            min_value=ras_min,
            max_value=ras_max,
            value=(ras_min, ras_max),
            step=0.1,
        )
    else:
        ras_range = None

    top_n = st.number_input(
        "Show top N by consensus rank",
        min_value=10,
        max_value=total_prospects,
        value=min(250, total_prospects),
        step=10,
    )

    # --- Tag filter — multiselect with AND logic (all selected tags must be present) ---
    st.markdown("### Tags")
    _active_tag_defs = _load_active_tag_defs()
    _tag_name_to_label = {
        d["tag_name"]: _TAGS_DISPLAY_MAP.get(d["tag_name"], d["tag_name"])
        for d in _active_tag_defs
    }
    _tag_label_to_name = {v: k for k, v in _tag_name_to_label.items()}
    _tag_display_opts = [_tag_name_to_label[d["tag_name"]] for d in _active_tag_defs]

    selected_tag_labels = st.multiselect(
        "Tags (all must match)",
        options=_tag_display_opts,
        default=[],
        key="tag_multiselect",
    )
    selected_tags: list[str] = [
        _tag_label_to_name[lbl]
        for lbl in selected_tag_labels
        if lbl in _tag_label_to_name
    ]

    # --- Tag legend — dynamic: mirrors active tag defs ---
    with st.expander("📖 Tag Legend", expanded=False):
        for _tdef in _active_tag_defs:
            _lbl  = _TAGS_DISPLAY_MAP.get(_tdef["tag_name"], _tdef["tag_name"])
            _desc = (_tdef.get("description") or "").strip()
            st.markdown(f"**{_lbl}** — {_desc}" if _desc else f"**{_lbl}**")

    with st.expander("📊 Positional Value (PVC)", expanded=False):
        st.markdown("""
**How position affects draft value:**

| Position | PVC | Impact |
|----------|-----|--------|
| QB, CB, EDGE | 1.00x | Premium — no discount |
| WR, OT, S, IDL | 0.90x | Tier 2 — slight discount |
| ILB, OLB | 0.85x | Tier 3 — moderate discount |
| OG, TE, C | 0.80x | Tier 4 — significant discount |
| RB | 0.70x | Tier 5 — maximum discount |

RPG × PVC = APEX Score

An elite RB (RPG 84) has a lower APEX Score (59) than
a good CB (RPG 74, APEX 74) because the NFL pays, drafts,
and replaces running backs differently than cornerbacks.
This reflects draft economics, not player talent.
""")

    # --- Prospect Detail selectbox — write to selected_pid ---
    st.markdown("---")
    st.markdown("### 🔍 Prospect Detail")
    _all_sorted_names = sorted(df["display_name"].dropna().unique().tolist())
    # Reset counter forces selectbox recreation (returns to index 0) on Clear
    if "detail_reset_n" not in st.session_state:
        st.session_state["detail_reset_n"] = 0
    _det_col_sel, _det_col_clr = st.columns([3, 1])
    with _det_col_sel:
        _detail_dropdown = st.selectbox(
            "Select prospect",
            options=["— select —"] + _all_sorted_names,
            key=f"detail_select_{st.session_state['detail_reset_n']}",
            label_visibility="collapsed",
        )
    with _det_col_clr:
        st.write("")  # vertical alignment spacer
        if st.button("Clear", key="detail_clear", use_container_width=True):
            st.session_state["selected_pid"] = None
            st.session_state["detail_reset_n"] += 1
            st.rerun()
    if _detail_dropdown == "— select —":
        st.session_state["selected_pid"] = None
    else:
        _pid_rows = df[df["display_name"] == _detail_dropdown]["prospect_id"]
        if not _pid_rows.empty:
            st.session_state["selected_pid"] = int(_pid_rows.iloc[0])

    # --- Compare Two Prospects expander ---
    with st.expander("⚖️ Compare Two Prospects"):
        _cmp_names = ["—"] + _all_sorted_names
        compare_a_input = st.selectbox("Prospect A", options=_cmp_names, key="cmp_a")
        compare_b_input = st.selectbox("Prospect B", options=_cmp_names, key="cmp_b")
        cmp_col1, cmp_col2 = st.columns(2)
        with cmp_col1:
            run_compare = st.button("Compare ⚖️", key="run_cmp", use_container_width=True)
        with cmp_col2:
            clear_compare = st.button("Clear", key="clear_cmp", use_container_width=True)
        if run_compare and compare_a_input != "—" and compare_b_input != "—":
            st.session_state["compare_a"] = compare_a_input
            st.session_state["compare_b"] = compare_b_input
        if clear_compare:
            st.session_state.pop("compare_a", None)
            st.session_state.pop("compare_b", None)

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
filtered = df.copy()

if not show_low:
    filtered = filtered[filtered["confidence_band"] != "Low"]

if show_divergence_only:
    filtered = filtered[filtered["divergence_flag"] == 1]

if show_apex_only:
    filtered = filtered[filtered["auto_apex_rank"].notna()]

if show_apex_scored_only and "apex_composite" in filtered.columns:
    filtered = filtered[filtered["apex_composite"].notna()]

if selected_positions:
    filtered = filtered[filtered["position_group"].isin(selected_positions)]

if selected_tiers:
    filtered = filtered[filtered["consensus_tier"].isin(selected_tiers)]

if selected_apex_tier != "(all)" and "apex_tier" in filtered.columns:
    filtered = filtered[filtered["apex_tier"] == selected_apex_tier]

if school_search.strip():
    mask = filtered["school_canonical"].str.contains(
        school_search.strip(), case=False, na=False
    )
    filtered = filtered[mask]

if ras_range is not None:
    ras_lo, ras_hi = ras_range
    has_ras  = filtered["ras_score"].notna()
    in_range = filtered["ras_score"].between(ras_lo, ras_hi)
    filtered = filtered[~has_ras | in_range]

# Tag filter — AND logic: all selected tags must be present on the prospect
if selected_tags:
    selected_set = set(selected_tags)

    def _has_all_tags(tag_str: str) -> bool:
        present = set(_parse_tags(tag_str))
        return selected_set.issubset(present)

    tag_mask = filtered["tag_names"].apply(_has_all_tags)
    filtered = filtered[tag_mask]

filtered = filtered.sort_values("consensus_rank", ascending=True)
filtered = filtered.head(int(top_n))

# Ordered prospect_id list — aligns with display DataFrame row positions
_bb_prospect_ids: list[int] = filtered["prospect_id"].tolist()

# ---------------------------------------------------------------------------
# Build display table
# ---------------------------------------------------------------------------

def _fmt_div(row) -> str:
    """Format divergence delta for display. Positive = jf ranks prospect higher."""
    if row["divergence_flag"] != 1 or row["divergence_delta"] is None:
        return ""
    display_val = -int(row["divergence_delta"])
    return f"{display_val:+d}"


def _fmt_apex_delta(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "\u2014"
    try:
        v = int(val)
    except (TypeError, ValueError):
        return "\u2014"
    return f"{v:+d}"


def _fmt_apex_composite(val) -> str:
    """Return formatted score string, or '-' when NULL."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    try:
        return f"{float(val):.1f}"
    except (TypeError, ValueError):
        return "-"


display = pd.DataFrame()
display["Rank"]       = filtered["consensus_rank"].astype("Int64")
display["Player"]     = filtered["display_name"]
display["School"]     = filtered["school_canonical"]
display["Pos"]        = filtered["position_group"]
display["Score"]      = filtered["consensus_score"].apply(
    lambda x: round(float(x), 1) if pd.notna(x) else None
)
display["Consensus"]  = filtered["consensus_tier"]
display["Confidence"] = filtered["confidence_band"]
display["Sources"]    = filtered["sources_present"].astype("Int64")
display["Coverage"]   = filtered["coverage_count"].astype("Int64")
display["RAS"]        = filtered["ras_score"].apply(
    lambda x: round(float(x), 1) if pd.notna(x) else None
)
display["⚡ Div"]    = filtered.apply(_fmt_div, axis=1)
display["APEX"]       = filtered["auto_apex_rank"].astype("Int64")
display["\u0394 APEX"] = filtered["auto_apex_delta"].apply(_fmt_apex_delta)

# RPG — raw score before PVC discount
if "raw_score" in filtered.columns:
    display["RPG"] = filtered["raw_score"].apply(_fmt_apex_composite)
else:
    display["RPG"] = "-"

# APEX engine columns — NULL-safe
if "apex_composite" in filtered.columns:
    display["APEX Score"] = filtered["apex_composite"].apply(
        lambda x: round(float(x), 1) if pd.notna(x) else None
    )
    display["APEX Tier"]  = filtered["apex_tier"].fillna("")
    display["Archetype"]  = filtered["apex_archetype"].fillna("-")
else:
    display["APEX Score"] = None
    display["APEX Tier"]  = ""
    display["Archetype"]  = "-"

display["Tags"] = filtered["tag_names"].apply(_fmt_tags_text)

display["Snapshot"] = (
    filtered["snapshot_date"].str[:10]
    if hasattr(filtered["snapshot_date"], "str")
    else filtered["snapshot_date"]
)

display = display.reset_index(drop=True)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
CONFIDENCE_COLORS = {
    "High":   "color: #5ab87a; font-weight: 600",   # green text — DraftOS --green
    "Medium": "color: #e8a84a; font-weight: 600",   # amber text — DraftOS --amber
    "Low":    "color: #e05c5c; font-weight: 500",   # red text   — DraftOS --red
}

# Draft-capital tier colors — visual hierarchy matches draft capital importance
APEX_TIER_COLORS = {
    "ELITE":  "background-color: #c89820; color: #000000; font-weight: 800; letter-spacing: 0.06em",
    "DAY1":   "background-color: #1a4a7a; color: #7eb4e2; font-weight: 700",
    "DAY2":   "background-color: #1a3d28; color: #5ab87a; font-weight: 700",
    "DAY3":   "background-color: #3d2800; color: #e8a84a; font-weight: 600",
    "UDFA-P": "background-color: #2a1a3d; color: #a57ee0; font-weight: 500",
    "UDFA":   "background-color: #1a1a22; color: rgba(255,255,255,0.35); font-weight: 400",
}

DIVERGENCE_COLOR = "color: #e8a84a; font-weight: 700"   # amber text, no background


def _style_confidence(val: str) -> str:
    return CONFIDENCE_COLORS.get(val, "")


# Consensus tier: text color only, aligned to DraftOS token system
_CONSENSUS_TIER_COLORS = {
    "Elite":    "color: #f0c040; font-weight: 600",   # --elite gold
    "Strong":   "color: #7eb4e2; font-weight: 600",   # --cold blue
    "Playable": "color: #e8a84a; font-weight: 500",   # --amber
    "Watch":    "color: #e05c5c; font-weight: 500",   # --red
}


def _style_consensus_tier(val: str) -> str:
    return _CONSENSUS_TIER_COLORS.get(val, "")


def _style_divergence(val: str) -> str:
    """Amber text on any non-empty divergence value."""
    return DIVERGENCE_COLOR if val not in ("", None) else ""


def _style_apex_delta(val: str) -> str:
    """
    Positive (APEX higher than market) -> cold blue — system sees premium not priced in.
    Negative (APEX lower than market)  -> red, muted.
    Zero / em-dash -> no style.
    """
    if val in ("", "—", "\u2014", None):
        return ""
    try:
        n = int(str(val).replace("+", ""))
    except (ValueError, AttributeError):
        return ""
    if n > 0:
        return "color: #7eb4e2; font-weight: 700"   # cold blue — APEX higher than market
    if n < 0:
        return "color: #e05c5c; font-weight: 500"   # red — APEX lower than market
    return "color: rgba(255,255,255,0.35)"           # aligned — dim neutral


def _style_apex_tier(val: str) -> str:
    return APEX_TIER_COLORS.get(val, "")


_NUM_COLS = ["Rank", "Score", "Sources", "Coverage", "RAS", "APEX Score"]
_STR_COLS = ["Player", "School", "Pos", "Consensus", "Confidence", "APEX Tier",
             "Archetype", "Tags", "Snapshot", "⚡ Div", "\u0394 APEX", "RPG"]

styled = (
    display.style
    # ── Alignment ──────────────────────────────────────────────────────────
    .set_properties(
        subset=[c for c in _NUM_COLS if c in display.columns],
        **{"text-align": "right"}
    )
    .set_properties(
        subset=[c for c in _STR_COLS if c in display.columns],
        **{"text-align": "left"}
    )
    # ── Color signals ───────────────────────────────────────────────────────
    .map(_style_confidence,     subset=["Confidence"])
    .map(_style_consensus_tier, subset=["Consensus"])
    .map(_style_divergence,     subset=["⚡ Div"])
    .map(_style_apex_delta,     subset=["\u0394 APEX"])
    .map(_style_apex_tier,      subset=["APEX Tier"])
    # ── Table-level properties ───────────────────────────────────────────────
    .set_table_styles([
        {
            "selector": "thead tr th",
            "props": [
                ("font-family", "'Barlow Condensed', sans-serif"),
                ("font-size",   "9px"),
                ("font-weight", "700"),
                ("letter-spacing", "0.12em"),
                ("text-transform", "uppercase"),
                ("color", "rgba(255,255,255,0.32)"),
                ("border-bottom", "1px solid rgba(255,255,255,0.08)"),
                ("padding-bottom", "6px"),
            ]
        },
        {
            "selector": "tbody tr td",
            "props": [
                ("font-family", "'Barlow', sans-serif"),
                ("font-size",   "13px"),
                ("color", "rgba(255,255,255,0.80)"),
            ]
        },
        {
            "selector": "tbody tr td:nth-child(2)",
            "props": [
                ("font-family", "'Barlow Condensed', sans-serif"),
                ("font-size",   "14px"),
                ("font-weight", "600"),
                ("color", "rgba(255,255,255,0.92)"),
            ]
        },
        {
            "selector": "tbody tr td:nth-child(1)",
            "props": [
                ("font-family", "'Barlow Condensed', sans-serif"),
                ("font-size",   "13px"),
                ("font-weight", "700"),
                ("color", "rgba(255,255,255,0.45)"),
            ]
        },
        {
            "selector": "tbody tr:hover td",
            "props": [
                ("background-color", "rgba(74,144,212,0.05)"),
            ]
        },
    ])
    # ── Hide Snapshot column (internal/noise) ────────────────────────────────
    .hide(axis="columns", subset=["Snapshot"] if "Snapshot" in display.columns else [])
)

# ---------------------------------------------------------------------------
# Column guide (above the board)
# ---------------------------------------------------------------------------
with st.expander("📋 Column Guide", expanded=False):
    st.markdown("""
| Column | Description |
|--------|-------------|
| Rank | Consensus rank across active sources (weighted by tier) |
| Score | Weighted consensus score (0–100 scale) |
| Consensus | Consensus tier: Elite / Strong / Playable / Watch |
| Confidence | Source coverage × agreement quality (High / Medium / Low) |
| Sources | Active sources that have ranked this prospect |
| Coverage | Sources covering this prospect out of active canonical set |
| RAS | Relative Athletic Score (scale 2.74–10.0) |
| ⚡ Div | Divergence flag — APEX vs consensus rank signal (premium positions only) |
| APEX | Auto-derived APEX rank from apex_composite sort order (manual override takes precedence) |
| Δ APEX | consensus_rank − APEX rank (positive = APEX values prospect higher than market) |
| RPG | Raw Player Grade — talent evaluation independent of position. How good is this player as a football player? |
| APEX Score | APEX composite — RPG adjusted by positional value (PVC). How valuable is this player as a draft asset? |
| APEX Tier | **ELITE** ≥85 · **DAY1** ≥70 · **DAY2** ≥55 · **DAY3** ≥40 · **UDFA-P** ≥28 · **UDFA** <28 |
| Archetype | How this prospect wins — matched from APEX positional library |
| Archetype Fit | **Clean Fit** >15 pts · **Solid Fit** 8–15 pts · **Tweener** <8 pts · **No Fit** = concern |
| Tags | System-generated signals. See Tag Legend in sidebar. |
""")
    st.markdown("---")
    st.markdown("""
**How RPG and APEX Score Work Together**

DraftOS uses two scores to separate player talent from draft value:

- **RPG (Raw Player Grade)** measures how good a player is at football — independent
  of what position they play. An elite running back and an elite cornerback with
  identical trait vectors will have identical RPGs.

- **APEX Score** measures how valuable a player is as a draft pick. It takes the RPG
  and adjusts it by a Positional Value Coefficient (PVC) that reflects how the NFL
  actually values each position in the draft economy.

**The PVC multipliers:**
QB, CB, EDGE = 1.00x (premium) · WR, OT, S, IDL = 0.90x · ILB, OLB = 0.85x · OG, TE, C = 0.80x · RB = 0.70x

**Example:** Jeremiyah Love has elite trait vectors → RPG ~84. But as a running back
(PVC = 0.70), his APEX Score = ~59. This doesn't mean DraftOS thinks Love is a bad
player. It means the NFL structurally devalues the RB position, and draft capital
should reflect that reality.

**When to use which score:**
- Sorting by **RPG** answers: *"Who are the best football players in this class?"*
- Sorting by **APEX Score** answers: *"Who are the best draft values in this class?"*
""")

# ---------------------------------------------------------------------------
# Tabbed boards
# ---------------------------------------------------------------------------
tab_bb, tab_apex = st.tabs([
    "📋  Big Board",
    f"⚡  APEX Board — {apex_scored} scored",
])

with tab_bb:
    bb_event = st.dataframe(
        styled,
        column_config={
            "Score":      st.column_config.NumberColumn("Score",      format="%.1f"),
            "RAS":        st.column_config.NumberColumn("RAS",        format="%.1f"),
            "APEX Score": st.column_config.NumberColumn("APEX Score", format="%.1f"),
            "APEX Tier":  st.column_config.TextColumn(
                              "APEX Tier",
                              disabled=True,
                              help="Draft capital tier — derived from APEX Score.",
                          ),
        },
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="big_board_table",
    )
    if bb_event and bb_event.selection and bb_event.selection.rows:
        _bb_row_idx = bb_event.selection.rows[0]
        st.session_state["selected_pid"] = int(_bb_prospect_ids[_bb_row_idx])

    st.caption(
        f"Showing **{len(display)}** of {total_prospects} prospects"
        + (f" · {len(selected_tags)} tag filter(s) active" if selected_tags else "")
    )
    st.caption("💡 Click any row to load the prospect detail panel below, or use **🔍 Prospect Detail** in the sidebar.")

    # Tagged prospects pill view
    tagged_filtered = filtered[filtered["tag_names"] != ""].copy()
    if not tagged_filtered.empty:
        with st.expander(f"Tagged prospects on this board ({len(tagged_filtered)})", expanded=False):
            # Legend: tags actually present on the current filtered board
            _board_tag_set: set[str] = set()
            for _ts in tagged_filtered["tag_names"]:
                for _t in _parse_tags(_ts):
                    if _t not in _INTERNAL_TAG_NAMES:
                        _board_tag_set.add(_t)
            # Order by display_order from active tag defs, then alphabetically
            _def_order = {d["tag_name"]: d["display_order"] for d in _active_tag_defs}
            active_legend_tags = sorted(
                _board_tag_set,
                key=lambda t: (_def_order.get(t, 999), t),
            )
            if active_legend_tags:
                st.markdown(
                    "Tags on this board: "
                    + "".join(_render_tag_pill(t) for t in active_legend_tags),
                    unsafe_allow_html=True,
                )
            st.markdown("---")
            for _, row in tagged_filtered.sort_values("consensus_rank").iterrows():
                tags = [
                    t for t in _parse_tags(row["tag_names"])
                    if t not in _INTERNAL_TAG_NAMES
                ]
                if not tags:
                    continue
                pill_html = render_tag_pills(tags)
                rank = int(row["consensus_rank"]) if pd.notna(row["consensus_rank"]) else "?"
                name = row["display_name"]
                pos  = row["position_group"]
                apex = _fmt_apex_composite(row.get("apex_composite"))
                tier = row.get("apex_tier") or ""
                st.markdown(
                    f"**#{rank} {name}** ({pos}) &nbsp; APEX {apex} {tier}"
                    f" &nbsp;&nbsp; {pill_html}",
                    unsafe_allow_html=True,
                )

with tab_apex:
    if apex_scored > 0 and "apex_composite" in df.columns:
        apex_df = df[df["apex_composite"].notna()].copy()

        apex_df = apex_df.sort_values(
            ["auto_apex_rank", "apex_composite"],
            ascending=[True, False],
            na_position="last",
        )

        ab = pd.DataFrame()
        ab["APEX Rank"]  = apex_df["auto_apex_rank"].astype("Int64")
        ab["Player"]     = apex_df["display_name"]
        ab["Pos"]        = apex_df["position_group"]
        ab["School"]     = apex_df["school_canonical"]
        ab["RPG"]        = apex_df["raw_score"].apply(_fmt_apex_composite) if "raw_score" in apex_df.columns else "-"
        ab["APEX Score"] = apex_df["apex_composite"].apply(_fmt_apex_composite)
        ab["APEX Tier"]  = apex_df["apex_tier"].fillna("")
        ab["Archetype"]  = apex_df["apex_archetype"].fillna("-")

        if "gap_label" in apex_df.columns:
            ab["Fit"] = apex_df["gap_label"].map(
                lambda v: _GAP_LABEL_DISPLAY_MAP.get(
                    str(v).strip().upper(), str(v)
                ) if pd.notna(v) else "-"
            )
        else:
            ab["Fit"] = "-"

        ab["Consensus"]   = apex_df["consensus_rank"].astype("Int64")
        ab["\u0394 APEX"] = apex_df["auto_apex_delta"].apply(_fmt_apex_delta)

        if "eval_confidence" in apex_df.columns:
            ab["Eval Conf"] = apex_df["eval_confidence"].fillna("-")
        else:
            ab["Eval Conf"] = "-"

        if "apex_tags" in apex_df.columns:
            ab["Tags"] = apex_df["apex_tags"].apply(_fmt_tags)
        else:
            ab["Tags"] = ""

        _apex_prospect_ids: list[int] = apex_df["prospect_id"].tolist()

        ab = ab.reset_index(drop=True)

        _right_cols_apex = ["APEX Rank", "APEX Score", "Consensus", "\u0394 APEX"]
        _left_cols_apex  = ["Player", "Pos", "School", "RPG", "APEX Tier", "Archetype",
                            "Fit", "Eval Conf", "Tags"]

        apex_styled = (
            ab.style
            .map(_style_apex_tier,  subset=["APEX Tier"])
            .map(_style_apex_delta, subset=["\u0394 APEX"])
            .set_properties(subset=_right_cols_apex, **{"text-align": "right"})
            .set_properties(subset=_left_cols_apex,  **{"text-align": "left"})
            .set_table_styles([
                {
                    "selector": "thead tr th",
                    "props": [
                        ("font-family", "'Barlow Condensed', sans-serif"),
                        ("font-size",   "9px"),
                        ("font-weight", "700"),
                        ("letter-spacing", "0.12em"),
                        ("text-transform", "uppercase"),
                        ("color", "rgba(255,255,255,0.32)"),
                        ("border-bottom", "1px solid rgba(255,255,255,0.08)"),
                    ]
                },
                {
                    "selector": "tbody tr td",
                    "props": [
                        ("font-family", "'Barlow', sans-serif"),
                        ("font-size",   "13px"),
                        ("color", "rgba(255,255,255,0.80)"),
                    ]
                },
                {
                    "selector": "tbody tr td:nth-child(2)",
                    "props": [
                        ("font-family", "'Barlow Condensed', sans-serif"),
                        ("font-size",   "14px"),
                        ("font-weight", "600"),
                        ("color", "rgba(255,255,255,0.92)"),
                    ]
                },
                {
                    "selector": "tbody tr:hover td",
                    "props": [("background-color", "rgba(74,144,212,0.05)")]
                },
            ])
        )

        ab_event = st.dataframe(
            apex_styled,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="apex_board_table",
        )
        if ab_event and ab_event.selection and ab_event.selection.rows:
            _ab_row_idx = ab_event.selection.rows[0]
            st.session_state["selected_pid"] = int(_apex_prospect_ids[_ab_row_idx])

        st.caption("💡 Click any row to load the prospect detail panel below.")
    else:
        st.info("No APEX-scored prospects yet. Run apex_scoring to populate this board.")

# ---------------------------------------------------------------------------
# APEX rank input panel (analyst overrides)
# ---------------------------------------------------------------------------
with st.expander("🔧 Set APEX Rank (Analyst Override — optional)", expanded=False):
    all_names = sorted(df["display_name"].dropna().unique().tolist())

    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
    with col1:
        selected_name = st.selectbox(
            "Prospect",
            options=all_names,
            key="apex_prospect_select",
        )
    with col2:
        apex_rank_input = st.number_input(
            "Rank",
            min_value=1,
            max_value=total_prospects,
            value=1,
            step=1,
            key="apex_rank_input",
        )
    with col3:
        save_clicked = st.button("Save APEX", type="primary")
    with col4:
        clear_clicked = st.button("Clear APEX")

    if save_clicked and selected_name:
        pid_rows = df[df["display_name"] == selected_name]["prospect_id"]
        if not pid_rows.empty:
            pid = int(pid_rows.iloc[0])
            with connect() as conn:
                save_apex_rank(conn, prospect_id=pid, apex_rank=int(apex_rank_input))
            st.success(f"Saved: {selected_name} → APEX #{apex_rank_input}")
            _load_board.clear()
            st.rerun()

    if clear_clicked and selected_name:
        pid_rows = df[df["display_name"] == selected_name]["prospect_id"]
        if not pid_rows.empty:
            pid = int(pid_rows.iloc[0])
            with connect() as conn:
                clear_apex_rank(conn, prospect_id=pid)
            st.success(f"Cleared APEX rank for {selected_name}")
            _load_board.clear()
            st.rerun()

# ---------------------------------------------------------------------------
# Compare Panel (renders when both A and B are set)
# ---------------------------------------------------------------------------
_cmp_a = st.session_state.get("compare_a")
_cmp_b = st.session_state.get("compare_b")

if _cmp_a and _cmp_b:
    st.divider()
    _render_compare_panel(_cmp_a, _cmp_b, df)

# ---------------------------------------------------------------------------
# Prospect Detail Panel (unified)
# Compare is active when both compare_a and compare_b are set in session_state.
# When compare is active, suppress the full detail card to avoid a confusing
# three-prospect view — show a brief info note instead.
# ---------------------------------------------------------------------------
_compare_active = bool(
    st.session_state.get("compare_a") and st.session_state.get("compare_b")
)

st.divider()
st.subheader("📋 Prospect Detail")

_selected_pid = st.session_state.get("selected_pid")

if _selected_pid is None:
    st.caption(
        "No prospect selected. Click a row in either board above, or use "
        "**🔍 Prospect Detail** in the sidebar to load a profile."
    )
elif _compare_active:
    st.caption(
        "ℹ️ Prospect detail hidden while Compare is active. "
        "Clear the comparison to view an individual profile."
    )
else:
    _prospect_row = df[df["prospect_id"] == _selected_pid]
    if _prospect_row.empty:
        st.warning("Prospect not found in current board.")
        st.session_state.pop("selected_pid", None)
    else:
        _pr = _prospect_row.iloc[0]
        _has_apex = pd.notna(_pr.get("apex_composite"))

        if _has_apex:
            with connect() as conn:
                _detail = get_apex_detail(conn, prospect_id=_selected_pid)
            if _detail:
                # Supplement with board row data for header and bullet generation
                if not _detail.get("consensus_rank"):
                    _detail["consensus_rank"] = _pr.get("consensus_rank")
                if not _detail.get("confidence_band"):
                    _detail["confidence_band"] = _pr.get("confidence_band")
                # Expose board-side RAS for detail card (ras_total from ras table)
                _detail["ras_score"] = _pr.get("ras_score")
                # Expose auto_apex_delta for divergence narrative
                _detail["auto_apex_delta"] = _pr.get("auto_apex_delta")
                _render_apex_detail(_detail)
            else:
                st.warning("APEX detail record not found despite apex_composite being set.")
        else:
            _render_consensus_card(_pr)

        # PDF export button — available for all prospects regardless of APEX coverage
        if st.button("📄 Generate Report", key=f"pdf_{_selected_pid}"):
            with st.spinner("Generating PDF..."):
                try:
                    pdf_path = generate_pdf(prospect_id=_selected_pid, season_id=1)
                    with open(pdf_path, "rb") as _f:
                        st.download_button(
                            label="⬇️ Download One-Pager",
                            data=_f.read(),
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            key=f"dl_{_selected_pid}",
                        )
                except Exception as _e:
                    st.error(f"PDF generation failed: {_e}")
