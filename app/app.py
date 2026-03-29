"""
DraftOS Big Board — Session 40
Read-only Streamlit UI with divergence flags, APEX rank input, APEX scores,
tag display, prospect detail drawer, stacking filters, and side-by-side comparison.
No DB writes except through save_apex_rank() and clear_apex_rank(). No business logic.
"""

import math
import re
import sys
from pathlib import Path

# Ensure repo root (C:\DraftOS) is on sys.path so `scripts.*` imports work
# regardless of which directory Streamlit is launched from.
_REPO_ROOT = str(Path(__file__).parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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


# ---------------------------------------------------------------------------
# FM Profile Data Layer
# ---------------------------------------------------------------------------

FM_PROFILES: dict[int, dict] = {
    1: {
        "name":               "FM-1: Athleticism Mirage",
        "definition":         "Physical tools produce college dominance that disappears when athletic advantage closes at the NFL level. The mechanism was the athleticism itself — not a skill, technique, or processing layer that the athleticism was enabling. When NFL athletes close the gap, there is nothing behind the speed, length, or burst that can sustain performance.",
        "primary_positions":  "CB-3 (highest severity), EDGE-2, WR-2, WR-3",
        "capital_loss":       "Highest at Round 1 capital. FM-1 at CB-3 with Pick 1–15 investment has >60% bust rate. The combine-premium market is the structural cause.",
        "color_token":        "fm1",
        "color_hex":          "#e05c5c",
        "color_dim":          "rgba(224,92,92,0.15)",
        "color_border":       "rgba(224,92,92,0.30)",
        "color_text":         "#f08080",
    },
    2: {
        "name":               "FM-2: Scheme Ghost",
        "definition":         "Production or coverage performance is scheme-dependent. The player's mechanism requires a specific structural context — a coverage family, an alignment concept, a manufactured advantage — and does not replicate when that context is unavailable. The player is not bad; they are specifically good, in a way that does not transfer.",
        "primary_positions":  "CB-2 zone-dominant (Type A), S-3 projection (Type A), WR spread-system (Type B), TE scheme-specific (Type B), EDGE-2 wide-9 amplification (Type B)",
        "capital_loss":       "Moderate standalone. Severe in FM-2/FM-6 compound (nomadic career pattern). FM-2 at EDGE-2: landing spot is the primary capital determinant — capital recommendation must reflect scheme-alignment probability, not the ceiling case alone.",
        "color_token":        "fm2",
        "color_hex":          "#e8a84a",
        "color_dim":          "rgba(232,168,74,0.15)",
        "color_border":       "rgba(232,168,74,0.30)",
        "color_text":         "#f0b866",
    },
    3: {
        "name":               "FM-3: Processing Wall",
        "definition":         "Processing speed or anticipatory recognition is insufficient to operate at NFL decision velocity. The physical tools execute correctly but the cognitive trigger arrives too late. Production in college was enabled by athletic advantages that compressed the processing requirement — those advantages compress at the NFL level.",
        "primary_positions":  "QB-1 (highest severity), QB-2, CB-3",
        "capital_loss":       "Catastrophic at QB with Round 1 capital. FM-3 at QB is the highest expected capital loss pattern in the system.",
        "color_token":        "fm3",
        "color_hex":          "#5b9cf0",
        "color_dim":          "rgba(91,156,240,0.15)",
        "color_border":       "rgba(91,156,240,0.30)",
        "color_text":         "#8ab8f5",
    },
    4: {
        "name":               "FM-4: Body Breakdown",
        "definition":         "Physical structure — joints, soft tissue, or availability — fails to sustain the mechanism that justified draft capital. The mechanism was real and confirmed. The body could not deliver it at NFL volume. FM-4 is the only failure mode that is fully mechanism-independent: even the best-built archetype can be destroyed by structural failure.",
        "primary_positions":  "RB-1 (highest severity), S-2, EDGE-2, EDGE-4, OT-1",
        "capital_loss":       "Highest at RB with Round 1 capital. FM-4 + PVC 0.70 is the worst capital efficiency bust in the system. FM-4 at QB is low frequency but maximum severity — the single catastrophic outcome case.",
        "color_token":        "fm4",
        "color_hex":          "#e05c5c",
        "color_dim":          "rgba(224,92,92,0.18)",
        "color_border":       "rgba(224,92,92,0.30)",
        "color_text":         "#f08080",
    },
    5: {
        "name":               "FM-5: Motivation Cliff",
        "definition":         "Competitive drive or coachability degrades after draft capital is secured. Production was real pre-draft. The internal engine that produced it was contingent on external pressure — combine preparation, draft positioning, proving-ground context. That context disappears post-signing.",
        "primary_positions":  "WR-1, RB-1, EDGE-3",
        "capital_loss":       "Severe when FM-5 activates in Year 2–3 on a second contract trajectory. Capital is already committed at that point with no exit mechanism.",
        "color_token":        "fm5",
        "color_hex":          "#c47ae0",
        "color_dim":          "rgba(196,122,224,0.18)",
        "color_border":       "rgba(196,122,224,0.30)",
        "color_text":         "#d4a0f0",
    },
    6: {
        "name":               "FM-6: Role Mismatch",
        "definition":         "The NFL deployment context does not match the mechanism that produced college value. The player is real. The production was real. The job they are being asked to do at the NFL level is not the job their mechanism can execute — scheme, alignment, or role requirements exceed the mechanism's range.",
        "primary_positions":  "WR-2, TE-2, LB-2",
        "capital_loss":       "Moderate. Recoverable if scheme fit is corrected in Year 2–3. Becomes severe when the mismatch persists across multiple contracts and the player is never deployed correctly.",
        "color_token":        "fm6",
        "color_hex":          "#a57ee0",
        "color_dim":          "rgba(165,126,224,0.15)",
        "color_border":       "rgba(165,126,224,0.30)",
        "color_text":         "#c4a5f5",
    },
}

COMPOUND_SEVERITY: dict[frozenset, str] = {
    frozenset([1, 3]): "Compound FM-1 + FM-3: athleticism mirage with processing deficit. Independent failure paths — either mechanism alone is a bust case. Athletic tools masked the processing limit in college; both compress simultaneously at NFL speed.",
    frozenset([1, 4]): "Compound FM-1 + FM-4: athleticism dependency with structural fragility. The physical tools are both the mechanism and the liability — burst-dependent mechanisms stress exactly the joints and soft tissue most prone to FM-4 activation.",
    frozenset([1, 6]): "Compound FM-1 + FM-6: athleticism mirage with role mismatch. Speed premium priced for a deployment that may not exist at NFL level. If the role narrows and the speed advantage closes, there is no secondary mechanism.",
    frozenset([3, 4]): "Compound FM-3 + FM-4: processing wall with body breakdown risk. Highest severity compound pattern at QB. Two independent paths to catastrophic capital loss — processing failure or structural failure either one ends the outcome.",
    frozenset([3, 5]): "Compound FM-3 + FM-5: processing deficit with motivation contingency. Development trajectory requires both cognitive improvement and sustained drive. Both are uncertain; neither compensates for the other.",
    frozenset([3, 6]): "Compound FM-3 + FM-6: processing wall with role mismatch. Scheme demands that mask processing limits in college may not exist at the NFL level. Mismatch removes the structural support the mechanism depended on.",
    frozenset([4, 5]): "Compound FM-4 + FM-5: structural fragility with motivation cliff. Pre-draft production environment generated both physical output and competitive drive. Injury risk in Year 1–2 is the activation trigger for FM-5.",
    frozenset([1, 5]): "Compound FM-1 + FM-5: athleticism mirage with motivation cliff. Elite combine tools drove both the draft grade and the competitive intensity. When the tools stop generating separation, the motivational engine that ran on proving-ground context has no remaining fuel.",
}


def get_compound_label(fm_codes: list[int]) -> str:
    """Returns compound severity string for a two-FM prospect. Empty string if not two codes."""
    if len(fm_codes) != 2:
        return ""
    key = frozenset(fm_codes)
    return COMPOUND_SEVERITY.get(
        key,
        f"Compound FM-{fm_codes[0]} + FM-{fm_codes[1]}: independent failure paths — "
        f"evaluate each mechanism separately. Either alone is a capital risk pattern."
    )


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
  --fm1-dim:   rgba(224,92,92,0.15);
  --fm2-dim:   rgba(232,168,74,0.15);
  --fm3-dim:   rgba(91,156,240,0.15);
  --fm4-dim:   rgba(224,92,92,0.18);
  --fm5-dim:   rgba(196,122,224,0.18);
  --fm6-dim:   rgba(165,126,224,0.15);
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

/* ── FM PROFILE BLOCKS ── */
.fm-compound-banner {
  background: rgba(232,168,74,0.13);
  border: 1px solid rgba(232,168,74,0.22);
  border-left: 3px solid #c98828;
  border-radius: 0 5px 5px 0;
  padding: 10px 14px;
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 12px;
}

.fm-compound-icon {
  font-size: 13px;
  color: #e8a84a;
  font-weight: 800;
  font-family: 'Barlow Condensed', sans-serif;
  flex-shrink: 0;
  margin-top: 1px;
  line-height: 1.4;
}

.fm-compound-text {
  font-size: 10px;
  line-height: 1.6;
  color: rgba(232,168,74,0.85);
}

.fm-profile-block {
  border-radius: 0 5px 5px 0;
  padding: 14px 16px;
  margin-bottom: 10px;
}

.fm-profile-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.fm-profile-def {
  font-size: 11px;
  line-height: 1.6;
  color: rgba(255,255,255,0.52);
  margin-bottom: 12px;
}

.fm-profile-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
}

.fm-profile-row:last-child { margin-bottom: 0; }

.fm-profile-lbl {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.32);
}

.fm-profile-val {
  font-size: 10px;
  font-weight: 600;
  line-height: 1.5;
}

/* ── v3 card CSS additions ── */

/* CSS variables needed for v3 classes */
:root {
  --fm1: #e05c5c; --fm1-dim: rgba(224,92,92,0.15);
  --fm2: #e8a84a; --fm2-dim: rgba(232,168,74,0.15);
  --fm3: #5b9cf0; --fm3-dim: rgba(91,156,240,0.15);
  --fm4: #e05c5c; --fm4-dim: rgba(224,92,92,0.18);
  --fm5: #c47ae0; --fm5-dim: rgba(196,122,224,0.18);
  --fm6: #a57ee0; --fm6-dim: rgba(165,126,224,0.15);
  --elite2: #c89820;
}

/* pos-chip (v3 inline card style) */
.pos-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(126,180,226,0.20);
  border: 1px solid rgba(74,144,212,0.5);
  border-radius: 3px;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #7eb4e2;
  text-transform: uppercase;
  width: fit-content;
}

.pos-chip-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: #7eb4e2;
  opacity: 0.7;
}

/* meta-chip (rank chip in pos row) */
.meta-chip {
  font-size: 10px;
  font-weight: 600;
  color: rgba(255,255,255,0.52);
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 3px;
  padding: 2px 8px;
  letter-spacing: 0.04em;
}

.meta-chip.hi {
  color: #7eb4e2;
  border-color: rgba(126,180,226,0.28);
  background: rgba(126,180,226,0.10);
}

/* apex-window score grid (v3) */
.apex-window {
  background: #161b22;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 6px;
  padding: 18px 18px 14px;
  margin-bottom: 18px;
  position: relative;
  overflow: hidden;
}

.score-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}

.score-grid.unified {
  grid-template-columns: 1fr;
}

.score-grid.unified .score-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 4px 0 8px;
}

.score-grid.unified .score-val {
  font-size: 56px;
  color: #e8a84a;
}

.score-grid.unified .score-decimal {
  font-size: 28px;
}

.score-grid.unified .score-lbl {
  letter-spacing: 0.12em;
  margin-bottom: 6px;
}

.score-lbl {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.32);
  margin-bottom: 3px;
}

.score-val {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 44px;
  font-weight: 800;
  line-height: 0.95;
  color: #7eb4e2;
  letter-spacing: -0.01em;
}

.score-val.apex { color: #e8a84a; }

.score-decimal {
  font-size: 22px;
  font-weight: 600;
  opacity: 0.7;
}

/* Tier badges (v3 spec) */
.tier-badge-elite {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(240,192,64,0.12);
  border: 1px solid rgba(240,192,64,0.35);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}

.tier-badge-day1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(126,180,226,0.10);
  border: 1px solid rgba(126,180,226,0.32);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}

.tier-badge-day1 .tier-badge-text { color: #7eb4e2; }
.tier-badge-day1 .tier-badge-sub  { color: rgba(126,180,226,0.5); }

.tier-badge-day2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(90,184,122,0.10);
  border: 1px solid rgba(90,184,122,0.28);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}

.tier-badge-day2 .tier-badge-text { color: #5ab87a; }
.tier-badge-day2 .tier-badge-sub  { color: rgba(90,184,122,0.45); }

.tier-badge-day3 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}

.tier-badge-day3 .tier-badge-text { color: rgba(255,255,255,0.52); }
.tier-badge-day3 .tier-badge-sub  { color: rgba(255,255,255,0.32); }

.tier-badge-udfa {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 4px;
  padding: 7px 14px;
  margin-bottom: 8px;
}

.tier-badge-udfa .tier-badge-text { color: rgba(255,255,255,0.32); }
.tier-badge-udfa .tier-badge-sub  { color: rgba(255,255,255,0.18); }

.tier-badge-text {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 0.12em;
  color: #f0c040;
  text-transform: uppercase;
}

.tier-badge-sub {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: rgba(240,192,64,0.55);
  text-transform: uppercase;
}

/* Traits section — system variant gets top border */
.traits-section { margin-bottom: 14px; }

.traits-section.system {
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.06);
}

/* FM pip bar (v3) */
.fm-pip-bar { display: flex; gap: 3px; margin-bottom: 9px; }

.fm-pip {
  flex: 1;
  height: 5px;
  border-radius: 1.5px;
  background: rgba(255,255,255,0.06);
}

.fm-pip.p1 { background: #e05c5c; }
.fm-pip.p2 { background: #e8a84a; }
.fm-pip.p3 { background: #5b9cf0; }
.fm-pip.p4 { background: #e05c5c; }
.fm-pip.p5 { background: #c47ae0; }
.fm-pip.p6 { background: #a57ee0; }

/* fm-tag (v3 spec) */
.fm-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.fm-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.fm-tag.t1 { background: var(--fm1-dim); border: 1px solid rgba(224,92,92,0.3);   color: #f08080; }
.fm-tag.t2 { background: var(--fm2-dim); border: 1px solid rgba(232,168,74,0.3);  color: #f0b866; }
.fm-tag.t3 { background: var(--fm3-dim); border: 1px solid rgba(91,156,240,0.3);  color: #8ab8f5; }
.fm-tag.t4 { background: var(--fm4-dim); border: 1px solid rgba(224,92,92,0.3);   color: #f08080; }
.fm-tag.t5 { background: var(--fm5-dim); border: 1px solid rgba(196,122,224,0.3); color: #d4a0f0; }
.fm-tag.t6 { background: var(--fm6-dim); border: 1px solid rgba(165,126,224,0.3); color: #c4a5f5; }
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


def _e(s) -> str:
    import html as _html_mod
    return _html_mod.escape(str(s)) if s is not None else ""


def _split_score(val):
    s = _safe_float(val)
    if s == "—":
        return ("—", "")
    parts = s.split(".")
    return (parts[0], parts[1] if len(parts) > 1 else "0")


def _smart_split_bullets(text, max_items: int = 3) -> list:
    if not text or not str(text).strip():
        return []
    raw = [l.strip() for l in str(text).split("\n") if l.strip()]
    if not raw:
        return []
    merged = []
    for line in raw:
        if merged and len(line) < 50 and not merged[-1].endswith((".", "!", "?", "…")):
            merged[-1] = merged[-1] + " " + line
        else:
            merged.append(line)
    return merged[:max_items]


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


def render_fm_profile_block(fm_codes: list[int]) -> str:
    """
    Renders the FM Profile section as an HTML string for use in the
    Streamlit detail drawer via st.markdown(..., unsafe_allow_html=True).

    Args:
        fm_codes: List of active FM code integers for this prospect.
                  e.g. [1, 4] for Mendoza, [3, 6] for Rueben Bain.

    Returns:
        HTML string. Empty string if fm_codes is empty.
    """
    import html as _html_mod

    if not fm_codes:
        return ""

    def _e(s: object) -> str:
        return _html_mod.escape(str(s)) if s is not None else ""

    parts: list[str] = []

    # Compound severity banner — only when exactly 2 FM codes present
    if len(fm_codes) == 2:
        compound_text = get_compound_label(fm_codes)
        if compound_text:
            parts.append(f"""
<div class="fm-compound-banner">
  <span class="fm-compound-icon">!</span>
  <div class="fm-compound-text">{_e(compound_text)}</div>
</div>""")

    # Individual FM profile blocks
    for code in fm_codes:
        profile = FM_PROFILES.get(code)
        if not profile:
            continue

        color_hex    = profile["color_hex"]
        color_dim    = profile["color_dim"]
        color_border = profile["color_border"]
        color_text   = profile["color_text"]

        block_style = (
            f"background:{color_dim};"
            f"border:1px solid {color_border};"
            f"border-left:3px solid {color_hex};"
        )

        parts.append(f"""
<div class="fm-profile-block" style="{block_style}">
  <div class="fm-profile-name" style="color:{color_text};">{_e(profile['name'])}</div>
  <div class="fm-profile-def">{_e(profile['definition'])}</div>
  <div class="fm-profile-row">
    <span class="fm-profile-lbl">Primary Risk Positions</span>
    <span class="fm-profile-val" style="color:{color_text};">{_e(profile['primary_positions'])}</span>
  </div>
  <div class="fm-profile-row">
    <span class="fm-profile-lbl">Capital Loss Profile</span>
    <span class="fm-profile-val" style="color:rgba(255,255,255,0.52);">{_e(profile['capital_loss'])}</span>
  </div>
</div>""")

    return "\n".join(parts)


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
    """DraftOS Prospect Detail — iframe-isolated, full Prizm card treatment."""

    archetype_raw = d.get("matched_archetype") or d.get("apex_archetype") or ""

    comps_list = []
    rate_info = None
    if archetype_raw:
        try:
            with connect() as _hconn:
                comps_list = get_historical_comps(_hconn, archetype_raw, limit=3)
                rate_info = get_archetype_translation_rate(_hconn, archetype_raw)
        except Exception:
            comps_list = []
            rate_info = None

    html_content = _build_detail_html(d, comps_list, rate_info)

    # Height estimate
    h = 850
    if _v23_present(d.get("signature_play")):
        h += 100
    if _v23_present(d.get("strengths")) or _v23_present(d.get("red_flags")):
        h += 280
    if _v23_present(d.get("translation_risk")):
        h += 80
    if comps_list:
        h += 200

    components.html(html_content, height=h, scrolling=True)


def _build_detail_html(d: dict, comps: list, rate) -> str:  # rate: dict | None

    # Unpack
    pos       = d.get("position_group") or "?"
    name      = d.get("display_name") or "Unknown"
    school    = d.get("school_canonical") or "—"
    tier      = (d.get("apex_tier") or "").strip().upper()
    crank     = d.get("consensus_rank")
    conf      = d.get("confidence_band") or d.get("eval_confidence") or "—"
    ras_raw   = d.get("ras_score") or d.get("ras_total")
    raw_score = d.get("raw_score")
    apex_comp = d.get("apex_composite")
    pvc       = d.get("pvc")
    pos_rank  = d.get("position_rank")

    archetype_raw = d.get("matched_archetype") or d.get("apex_archetype") or ""
    gap_label = (d.get("gap_label") or "").strip().upper()
    fit_score = d.get("archetype_gap")
    gap_display = _GAP_LABEL_DISPLAY_MAP.get(gap_label, gap_label.title() if gap_label else "")

    fm_primary        = d.get("failure_mode_primary")
    fm_secondary      = d.get("failure_mode_secondary")
    signature_play    = d.get("signature_play")
    strengths_raw     = d.get("strengths")
    red_flags_raw     = d.get("red_flags")
    translation_risk  = d.get("translation_risk")
    capital_base      = d.get("capital_base") or d.get("capital_adjusted") or "—"
    capital_note      = d.get("capital_note") or ""
    snapshot_date     = d.get("scored_at") or d.get("snapshot_date") or ""

    # Derived
    rank_str = f"#{int(crank)}" if crank is not None and pd.notna(crank) else "NR"
    rank_num = int(crank) if crank is not None and pd.notna(crank) else 0
    ras_str  = _safe_float(ras_raw, ".2f") if ras_raw is not None and pd.notna(ras_raw) else None

    raw_int,  raw_dec  = _split_score(raw_score)
    apex_int, apex_dec = _split_score(apex_comp)

    is_unified = False
    if pvc is not None:
        try:
            is_unified = abs(float(pvc) - 1.0) < 0.005
        except Exception:
            pass

    pvc_str = _safe_float(pvc, ".2f") if pvc else "—"

    name_parts = name.split(" ", 1)
    name_html  = _e(name_parts[0])
    if len(name_parts) > 1:
        name_html += "<br>" + _e(name_parts[1])

    if archetype_raw and " " in archetype_raw:
        arch_code, arch_label = archetype_raw.split(" ", 1)
    else:
        arch_code, arch_label = archetype_raw or "—", ""

    ghost_rank = f"#{rank_num}" if rank_num > 0 else ""

    TIER_MAP = {
        "ELITE":  ("elite", "★ Elite", "Top Tier"),
        "DAY1":   ("day1",  "Day 1",   "Round 1"),
        "DAY2":   ("day2",  "Day 2",   "Rounds 2\u20133"),
        "DAY3":   ("day3",  "Day 3",   "Rounds 4\u20137"),
        "UDFA-P": ("udfa",  "UDFA",    "Priority Free Agent"),
        "UDFA":   ("udfa",  "UDFA",    "Priority Free Agent"),
    }
    tier_cls, tier_text, tier_sub = TIER_MAP.get(tier, ("udfa", tier or "—", ""))

    conf_color = {
        "Tier A": "#5ab87a", "Tier B": "#e8a84a", "Tier C": "#e05c5c",
        "High": "#5ab87a",   "Medium": "#e8a84a", "Low":    "#e05c5c",
        "A": "#5ab87a",      "B": "#e8a84a",      "C":      "#e05c5c",
    }.get(conf, "rgba(255,255,255,0.35)")

    # Divergence
    div_delta = d.get("divergence_delta") or d.get("auto_apex_delta")
    if div_delta is None:
        div_text, div_color = "N/A", "var(--dim)"
    else:
        try:
            dd = int(float(div_delta))
            if abs(dd) < 3:
                div_text  = f"Aligned ({dd:+d})" if dd != 0 else "Aligned (0)"
                div_color = "var(--dim)"
            elif dd > 0:
                div_text, div_color = f"APEX High +{dd}", "var(--amber)"
            else:
                div_text, div_color = f"APEX Low {dd}", "var(--red)"
        except Exception:
            div_text, div_color = "N/A", "var(--dim)"

    # Position rank chip
    pos_rank_chip = ""
    if pos_rank and pos_rank != crank:
        pos_rank_chip = (
            f'<span class="meta-chip hi" style="font-size:10px;padding:4px 10px">'
            f'#{int(pos_rank)} at {_e(pos)}</span>'
        )

    # FM codes
    fm_codes  = set()
    fm_labels = []
    if _fm_is_present(fm_primary):
        m = re.search(r"FM-(\d+)", str(fm_primary))
        if m:
            fm_codes.add(int(m.group(1)))
        fm_labels.append(str(fm_primary).strip())
    if _fm_is_present(fm_secondary):
        m = re.search(r"FM-(\d+)", str(fm_secondary))
        if m:
            fm_codes.add(int(m.group(1)))
        fm_labels.append(str(fm_secondary).strip())

    # RAS block
    ras_html = ""
    if ras_str:
        ras_html = (
            '<div class="ras-block">'
            f'<div class="ras-lbl">RAS Score</div>'
            f'<div class="ras-val">{ras_str}</div>'
            '</div>'
        )

    # Watermark date
    try:
        from datetime import datetime as _dt
        wm_date = _dt.strptime(str(snapshot_date)[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except Exception:
        from datetime import datetime as _dt
        wm_date = _dt.now().strftime("%b %d, %Y")

    # Trait rows
    def _trait(label, key):
        val = d.get(key)
        if val is None or (isinstance(val, float) and math.isnan(val)) or val == 0.0:
            return (
                f'<div class="trait-row">'
                f'<span class="trait-lbl">{_e(label)}</span>'
                '<div class="trait-track"></div>'
                '<span class="trait-val" style="color:var(--dim)">—</span>'
                '</div>'
            )
        try:
            v = float(val)
        except Exception:
            v = 0.0
        pct = min(max(v / 10.0 * 100, 0), 100)
        cls = "hi" if v >= 8.5 else "mid" if v >= 7.0 else "lo" if v >= 5.0 else "red"
        return (
            f'<div class="trait-row">'
            f'<span class="trait-lbl">{_e(label)}</span>'
            f'<div class="trait-track"><div class="trait-fill {cls}" style="width:{pct:.0f}%"></div></div>'
            f'<span class="trait-val">{v:.1f}</span>'
            '</div>'
        )

    football_html = "".join([
        _trait("Processing",  "v_processing"),
        _trait("Athleticism", "v_athleticism"),
        _trait("Comp. Tough", "v_comp_tough"),
        _trait("Durability",  "v_injury"),
    ])
    system_html = "".join([
        _trait("Scheme Vers.", "v_scheme_vers"),
        _trait("Production",   "v_production"),
        _trait("Dev. Traj.",   "v_dev_traj"),
        _trait("Character",    "v_character"),
    ])

    # Score block
    if is_unified:
        score_block = (
            '<div class="score-grid unified">'
            '<div class="score-item">'
            '<div class="score-lbl">Player Grade \u00b7 Draft Value</div>'
            f'<div class="score-val apex">{raw_int}<span class="score-decimal">.{raw_dec}</span></div>'
            '</div></div>'
        )
    else:
        score_block = (
            '<div class="score-grid">'
            '<div class="score-item">'
            '<div class="score-lbl">Player Grade</div>'
            f'<div class="score-val">{raw_int}<span class="score-decimal">.{raw_dec}</span></div>'
            '</div>'
            '<div class="score-item">'
            '<div class="score-lbl">Draft Value</div>'
            f'<div class="score-val apex">{apex_int}<span class="score-decimal">.{apex_dec}</span></div>'
            '</div></div>'
        )

    # FM section
    fm_section = ""
    if fm_codes:
        pips = "".join(
            f'<div class="fm-pip{" p" + str(i) if i in fm_codes else ""}"></div>'
            for i in range(1, 7)
        )
        tags = " ".join(
            '<span class="fm-tag t{n}">{label}</span>'.format(
                n=re.search(r"FM-(\d+)", lbl).group(1) if re.search(r"FM-(\d+)", lbl) else "1",
                label=_e(lbl),
            )
            for lbl in fm_labels
        )
        fm_section = (
            '<div class="fm-section">'
            '<div class="sec-lbl">Failure Mode Risk</div>'
            f'<div class="fm-pip-bar">{pips}</div>'
            f'<div class="fm-tags">{tags}</div>'
            '</div>'
        )

    # Signature play
    sig_html = ""
    if _v23_present(signature_play):
        sig_html = (
            '<div class="sig-play">'
            '<div class="sig-lbl"><span class="sig-lbl-dot"></span>Signature Play</div>'
            f'<div class="sig-text">{_e(signature_play)}</div>'
            '</div>'
        )

    # Strengths + Red Flags
    str_items = _smart_split_bullets(strengths_raw)
    rf_items  = _smart_split_bullets(red_flags_raw)

    def _pitems(items, dc):
        return "".join(
            f'<div class="panel-item"><span class="pi-dot {dc}"></span>{_e(it)}</div>'
            for it in items
        )

    two_col = ""
    if str_items or rf_items:
        sp = (
            '<div class="panel">'
            '<div class="panel-hdr g"><span class="ph-ind g"></span>Strengths</div>'
            f'{_pitems(str_items, "g")}</div>'
        ) if str_items else ""
        rp = (
            '<div class="panel">'
            '<div class="panel-hdr r"><span class="ph-ind r"></span>Red Flags</div>'
            f'{_pitems(rf_items, "r")}</div>'
        ) if rf_items else ""
        two_col = f'<div class="two-col">{sp}{rp}</div>'

    # Translation risk
    risk_html = ""
    if _v23_present(translation_risk):
        risk_html = (
            '<div class="risk-banner">'
            '<span class="risk-icon">!</span>'
            f'<div class="risk-text">{_e(translation_risk)}</div>'
            '</div>'
        )

    # Archetype fit badge (strip leading emoji from module-level display map if present)
    fit_badge = ""
    if gap_display:
        FC = {
            "CLEAN": "#5ab87a", "SOLID": "#7eb4e2",
            "TWEENER": "#e8a84a", "COMPRESSION": "#c47ae0", "NO_FIT": "#e05c5c",
        }
        clean_gap = gap_display
        if clean_gap and clean_gap[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            clean_gap = clean_gap.split(" ", 1)[-1] if " " in clean_gap else clean_gap
        fc = FC.get(gap_label, "#7eb4e2")
        fit_badge = (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:3px;'
            f'background:{fc}1a;border:1px solid {fc}44;color:{fc};'
            f'font-size:9px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase">'
            f'{_e(clean_gap)}</span>'
        )

    # Comps
    comps_html = ""
    if comps:
        rate_html = ""
        if rate:
            hp = rate.get("hit_rate_pct", 0)
            rc = "#5ab87a" if hp >= 67 else "#e8a84a" if hp >= 40 else "#e05c5c"
            rate_html = (
                f'<div style="font-size:11px;color:var(--mid);margin-bottom:10px">'
                f'{_e(archetype_raw)} translation rate: '
                f'<span style="color:{rc};font-weight:700">{hp}% HIT</span>'
                f' ({rate.get("hit_count", 0)} of {rate.get("total", 0)})</div>'
            )

        OC = {"HIT": "hit", "PARTIAL": "partial", "MISS": "miss"}
        IC = {"HIT": "\u2713", "PARTIAL": "\u2691", "MISS": "\u2717"}
        LB = {"HIT": "Archetype Ceiling", "PARTIAL": "FM Risk Comp", "MISS": "Miss Pattern"}

        cards = ""
        for c in comps[:2]:
            oc   = c.get("translation_outcome", "MISS")
            cls  = OC.get(oc, "miss")
            icon = IC.get(oc, "")
            lbl  = LB.get(oc, "")
            fm_badge = ""
            fmc = c.get("fm_code", "")
            if fmc and oc in ("PARTIAL", "MISS"):
                for code in re.findall(r"FM-\d+", fmc):
                    fn = code.replace("FM-", "")
                    fm_badge += (
                        f' <span class="fm-tag t{fn}" style="font-size:8px;padding:2px 7px">{code}</span>'
                    )
            cards += (
                f'<div class="comp-card {cls}">'
                f'<div class="comp-type-lbl {cls}">{icon} {_e(lbl)}</div>'
                f'<div class="comp-name-row">'
                f'<div class="comp-name">{_e(c.get("player_name", ""))}</div>'
                f'<span class="comp-badge {cls}">{oc}</span>{fm_badge}'
                '</div>'
                f'<div class="comp-desc">{_e(c.get("outcome_summary", ""))}</div>'
                f'<div class="comp-year">{_e(c.get("era_bracket", ""))}</div>'
                '</div>'
            )

        all_det = ""
        if len(comps) > 2:
            items = ""
            for c in comps:
                oc   = c.get("translation_outcome", "MISS")
                oc_c = {"HIT": "#5ab87a", "PARTIAL": "#e8a84a", "MISS": "#e05c5c"}.get(oc, "#888")
                items += (
                    f'<div style="padding:6px 0;border-bottom:1px solid var(--wire)">'
                    f'<span style="color:{oc_c};font-weight:700;'
                    f"font-family:'Barlow Condensed',sans-serif;"
                    f'font-size:14px;text-transform:uppercase">'
                    f'{_e(c.get("player_name", ""))}</span> '
                    f'<span style="color:var(--dim);font-size:11px">'
                    f'({_e(c.get("era_bracket", ""))})</span>'
                    f' \u2014 <span style="color:var(--mid);font-size:11px">'
                    f'{_e(c.get("outcome_summary", ""))}</span>'
                    '</div>'
                )
            all_det = (
                '<details style="margin-top:12px">'
                '<summary style="cursor:pointer;font-size:11px;font-weight:700;color:var(--cold);'
                'letter-spacing:0.06em;padding:8px 12px;background:var(--ink3);'
                'border:1px solid var(--wire);border-radius:5px;text-transform:uppercase">'
                'All comp details</summary>'
                f'<div style="padding:8px 12px;background:var(--ink3);border:1px solid var(--wire);'
                f'border-top:none;border-radius:0 0 5px 5px">{items}</div>'
                '</details>'
            )

        comps_html = (
            '<div class="comps-section">'
            '<div class="sec-lbl">Historical Comps</div>'
            f'{rate_html}'
            f'<div class="comps-row">{cards}</div>'
            f'{all_det}'
            '</div>'
        )

    # ── CSS ──────────────────────────────────────────────────────────────────
    css = (
        ":root{"
        "--ink:#0a0c0f;--ink2:#0f1318;--ink3:#161b22;--ink4:#1c2330;--ink5:#222b38;"
        "--wire:rgba(255,255,255,0.06);--wire2:rgba(255,255,255,0.11);--wire3:rgba(255,255,255,0.20);"
        "--dim:rgba(255,255,255,0.32);--mid:rgba(255,255,255,0.52);--text:rgba(255,255,255,0.88);"
        "--cold:#7eb4e2;--cold2:#4a90d4;--cold-dim:rgba(126,180,226,0.10);--cold-dim2:rgba(126,180,226,0.20);"
        "--amber:#e8a84a;--amber2:#c98828;--amber-dim:rgba(232,168,74,0.13);"
        "--red:#e05c5c;--red-dim:rgba(224,92,92,0.12);"
        "--green:#5ab87a;--green-dim:rgba(90,184,122,0.12);"
        "--elite:#f0c040;--elite-dim:rgba(240,192,64,0.12);"
        "--fm1:#e05c5c;--fm1-dim:rgba(224,92,92,0.15);--fm2:#e8a84a;--fm2-dim:rgba(232,168,74,0.15);"
        "--fm3:#5b9cf0;--fm3-dim:rgba(91,156,240,0.15);--fm4:#e05c5c;--fm4-dim:rgba(224,92,92,0.18);"
        "--fm5:#c47ae0;--fm5-dim:rgba(196,122,224,0.18);--fm6:#a57ee0;--fm6-dim:rgba(165,126,224,0.15);"
        "--prism-1:#7eb4e2;--prism-2:#a57ee0;--prism-3:#e8a84a;--prism-4:#5ab87a;"
        "}"
        "*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}"
        "body{background:#0a0c0f;margin:0;padding:0;font-family:'Barlow',sans-serif}"
        ".card{background:var(--ink);position:relative;overflow:hidden;border:1px solid var(--wire2)}"
        ".prism-strip{position:absolute;left:0;top:0;bottom:0;width:4px;"
        "background:linear-gradient(180deg,var(--prism-1) 0%,var(--prism-2) 30%,var(--prism-3) 60%,var(--prism-4) 100%);z-index:10}"
        ".top-bar{height:2px;background:linear-gradient(90deg,var(--cold2) 0%,var(--cold) 35%,"
        "rgba(126,180,226,0.3) 70%,transparent 100%);position:relative;z-index:5}"
        ".card::after{content:'';position:absolute;inset:0;"
        "background-image:repeating-linear-gradient(0deg,rgba(255,255,255,0.012) 0px,"
        "rgba(255,255,255,0.012) 1px,transparent 1px,transparent 3px);pointer-events:none;z-index:2}"
        ".card::before{content:'';position:absolute;inset:0;"
        "background-image:linear-gradient(rgba(255,255,255,0.018) 1px,transparent 1px),"
        "linear-gradient(90deg,rgba(255,255,255,0.018) 1px,transparent 1px);"
        "background-size:32px 32px;pointer-events:none;z-index:1}"
        ".layout{display:grid;grid-template-columns:280px 1fr;align-items:stretch;min-height:700px;position:relative;z-index:3}"
        ".left{background:var(--ink2);border-right:1px solid var(--wire2);padding:28px 22px 24px 26px;"
        "display:flex;flex-direction:column;position:relative;overflow:visible}"
        ".left::before{content:'';position:absolute;top:-60px;right:-80px;width:220px;height:220px;"
        "background:radial-gradient(ellipse at center,rgba(126,180,226,0.06) 0%,transparent 70%);pointer-events:none}"
        ".identity-row{display:flex;align-items:center;gap:6px;margin-bottom:12px;flex-wrap:wrap}"
        ".pos-chip{display:inline-flex;align-items:center;gap:6px;background:var(--cold-dim2);"
        "border:1px solid rgba(74,144,212,0.5);border-radius:3px;padding:4px 10px;"
        "font-size:10px;font-weight:700;letter-spacing:0.1em;color:var(--cold);text-transform:uppercase}"
        ".pos-chip-dot{width:5px;height:5px;border-radius:50%;background:var(--cold);opacity:0.7}"
        ".player-name{font-family:'Barlow Condensed',sans-serif;font-size:48px;font-weight:900;"
        "line-height:0.88;letter-spacing:-0.02em;text-transform:uppercase;color:var(--text);margin-bottom:14px}"
        ".name-slash{width:40px;height:2px;background:linear-gradient(90deg,var(--cold2),transparent);"
        "margin-bottom:14px;margin-top:-6px}"
        ".meta-row{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:20px}"
        ".meta-chip{font-size:10px;font-weight:600;color:var(--mid);background:var(--wire);"
        "border:1px solid var(--wire2);border-radius:3px;padding:2px 8px;letter-spacing:0.04em;display:inline-block}"
        ".meta-chip.hi{color:var(--cold);border-color:rgba(126,180,226,0.28);background:var(--cold-dim)}"
        ".apex-window{background:var(--ink3);border:1px solid var(--wire2);border-radius:6px;"
        "padding:16px 16px 12px;margin-bottom:16px;position:relative;overflow:hidden}"
        ".apex-window::before{content:'';position:absolute;inset:0;"
        "background:linear-gradient(135deg,rgba(126,180,226,0.04) 0%,transparent 40%,"
        "rgba(240,192,64,0.04) 100%);pointer-events:none}"
        ".score-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}"
        ".score-grid.unified{grid-template-columns:1fr}"
        ".score-grid.unified .score-item{text-align:center}"
        ".score-grid.unified .score-val{font-size:52px;color:var(--amber)}"
        ".score-grid.unified .score-decimal{font-size:26px}"
        ".score-item{text-align:center;padding:2px 0}"
        ".score-lbl{font-size:8px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:6px}"
        ".score-val{font-family:'Barlow Condensed',sans-serif;font-size:42px;font-weight:800;line-height:1;color:var(--cold)}"
        ".score-val.apex{color:var(--amber)}"
        ".score-decimal{font-size:21px;font-weight:700;opacity:0.7}"
        ".tier-badge{display:flex;align-items:center;justify-content:space-between;border-radius:4px;padding:7px 14px;margin-bottom:6px}"
        ".tier-badge-text{font-family:'Barlow Condensed',sans-serif;font-size:16px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase}"
        ".tier-badge-sub{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase}"
        ".tier-badge.elite{background:var(--elite-dim);border:1px solid rgba(240,192,64,0.40)}"
        ".tier-badge.elite .tier-badge-text{color:var(--elite)}"
        ".tier-badge.elite .tier-badge-sub{color:rgba(240,192,64,0.50)}"
        ".tier-badge.day1{background:var(--cold-dim);border:1px solid rgba(126,180,226,0.32)}"
        ".tier-badge.day1 .tier-badge-text{color:var(--cold)}"
        ".tier-badge.day1 .tier-badge-sub{color:rgba(126,180,226,0.50)}"
        ".tier-badge.day2{background:var(--green-dim);border:1px solid rgba(90,184,122,0.28)}"
        ".tier-badge.day2 .tier-badge-text{color:var(--green)}"
        ".tier-badge.day2 .tier-badge-sub{color:rgba(90,184,122,0.50)}"
        ".tier-badge.day3{background:var(--wire);border:1px solid var(--wire2)}"
        ".tier-badge.day3 .tier-badge-text{color:var(--mid)}"
        ".tier-badge.day3 .tier-badge-sub{color:var(--dim)}"
        ".tier-badge.udfa{background:transparent;border:1px solid var(--wire)}"
        ".tier-badge.udfa .tier-badge-text{color:var(--dim)}"
        ".tier-badge.udfa .tier-badge-sub{color:rgba(255,255,255,0.18)}"
        ".formula-line{font-family:'Barlow Condensed',sans-serif;font-size:10px;"
        "color:rgba(255,255,255,0.28);letter-spacing:0.04em;text-align:center}"
        ".traits-section{margin-bottom:14px}"
        ".section-header{font-family:'Barlow Condensed',sans-serif;font-size:8px;font-weight:700;"
        "letter-spacing:0.16em;text-transform:uppercase;color:var(--dim);margin-bottom:8px;"
        "padding-bottom:4px;border-bottom:1px solid var(--wire)}"
        ".trait-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}"
        ".trait-lbl{font-size:10px;font-weight:500;color:var(--mid);width:70px;flex-shrink:0}"
        ".trait-track{flex:1;height:3px;background:var(--wire);border-radius:2px;overflow:hidden}"
        ".trait-fill{height:100%;border-radius:2px}"
        ".trait-fill.hi{background:var(--green)}"
        ".trait-fill.mid{background:var(--cold)}"
        ".trait-fill.lo{background:var(--amber)}"
        ".trait-fill.red{background:var(--red)}"
        ".trait-val{font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;width:26px;text-align:right;color:var(--text)}"
        ".left-footer{margin-top:auto}"
        ".conf-box{display:flex;gap:18px;margin-bottom:12px;padding:10px 12px;"
        "background:var(--ink3);border:1px solid var(--wire);border-radius:5px}"
        ".conf-lbl{font-size:8px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:2px}"
        ".conf-val{font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700}"
        ".capital-box{padding:10px 12px;background:var(--ink3);border:1px solid var(--wire);border-radius:5px;margin-bottom:16px}"
        ".capital-lbl{font-size:8px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;color:var(--dim);margin-bottom:4px}"
        ".capital-val{font-family:'Barlow Condensed',sans-serif;font-size:22px;font-weight:800;color:var(--text);line-height:1;margin-bottom:6px}"
        ".capital-note{font-size:10px;line-height:1.5;color:var(--dim)}"
        ".eval-box{padding:8px 12px;background:var(--ink3);border:1px solid var(--wire);border-radius:5px;margin-bottom:16px;font-size:11px;color:var(--dim)}"
        ".watermark{padding-top:12px;border-top:1px solid var(--wire);display:flex;align-items:flex-end;justify-content:space-between}"
        ".brand-logo{font-family:'Barlow Condensed',sans-serif;font-size:15px;font-weight:900;"
        "letter-spacing:0.2em;text-transform:uppercase;color:rgba(255,255,255,0.15);line-height:1}"
        ".brand-version{font-size:8px;color:rgba(255,255,255,0.12);letter-spacing:0.1em}"
        ".watermark-meta{font-size:8px;color:var(--dim);text-align:right;letter-spacing:0.04em;line-height:1.7}"
        ".right{padding:24px 28px 28px 26px;display:flex;flex-direction:column;position:relative}"
        ".right::before{content:'';position:absolute;top:0;right:0;width:280px;height:280px;"
        "background:conic-gradient(from 200deg at 100% 0%,rgba(232,168,74,0.04) 0deg,"
        "rgba(126,180,226,0.04) 60deg,transparent 120deg);pointer-events:none}"
        ".header-zone{border-bottom:1px solid var(--wire);padding-bottom:18px;margin-bottom:18px;position:relative}"
        ".rank-ghost{position:absolute;right:0;top:-8px;font-family:'Barlow Condensed',sans-serif;"
        "font-size:100px;font-weight:900;color:rgba(255,255,255,0.025);letter-spacing:-0.04em;"
        "line-height:1;pointer-events:none;user-select:none}"
        ".header-row{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:6px}"
        ".archetype-code{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700;"
        "letter-spacing:0.18em;text-transform:uppercase;color:var(--cold);margin-bottom:4px}"
        ".archetype-name{font-family:'Barlow Condensed',sans-serif;font-size:32px;font-weight:800;"
        "text-transform:uppercase;letter-spacing:0.02em;color:var(--amber);line-height:0.95}"
        ".ras-block{text-align:right;flex-shrink:0}"
        ".ras-lbl{font-size:8px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:2px}"
        ".ras-val{font-family:'Barlow Condensed',sans-serif;font-size:28px;font-weight:800;color:var(--green);line-height:1}"
        ".fm-section{margin-bottom:16px}"
        ".sec-lbl{font-size:8px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;"
        "color:var(--dim);margin-bottom:9px;display:flex;align-items:center;gap:8px}"
        ".sec-lbl::after{content:'';flex:1;height:1px;background:var(--wire)}"
        ".fm-pip-bar{display:flex;gap:3px;margin-bottom:9px}"
        ".fm-pip{flex:1;height:5px;border-radius:1.5px;background:var(--wire)}"
        ".fm-pip.p1{background:var(--fm1)}.fm-pip.p2{background:var(--fm2)}.fm-pip.p3{background:var(--fm3)}"
        ".fm-pip.p4{background:var(--fm4)}.fm-pip.p5{background:var(--fm5)}.fm-pip.p6{background:var(--fm6)}"
        ".fm-tags{display:flex;gap:6px;flex-wrap:wrap}"
        ".fm-tag{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:3px;"
        "font-size:10px;font-weight:700;letter-spacing:0.04em}"
        ".fm-tag.t1{background:var(--fm1-dim);border:1px solid rgba(224,92,92,0.3);color:#f08080}"
        ".fm-tag.t2{background:var(--fm2-dim);border:1px solid rgba(232,168,74,0.3);color:#f0b868}"
        ".fm-tag.t3{background:var(--fm3-dim);border:1px solid rgba(91,156,240,0.3);color:#8ab8f5}"
        ".fm-tag.t4{background:var(--fm4-dim);border:1px solid rgba(224,92,92,0.35);color:#f08080}"
        ".fm-tag.t5{background:var(--fm5-dim);border:1px solid rgba(196,122,224,0.35);color:#d8a5f0}"
        ".fm-tag.t6{background:var(--fm6-dim);border:1px solid rgba(165,126,224,0.3);color:#c4a5f5}"
        ".sig-play{background:var(--ink3);border:1px solid var(--wire);border-left:3px solid var(--cold2);"
        "border-radius:0 5px 5px 0;padding:12px 16px;margin-bottom:16px}"
        ".sig-lbl{font-size:8px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;"
        "color:var(--cold);margin-bottom:6px;display:flex;align-items:center;gap:6px}"
        ".sig-lbl-dot{width:5px;height:5px;border-radius:50%;background:var(--cold2)}"
        ".sig-text{font-size:11px;line-height:1.6;color:var(--mid);font-style:italic}"
        ".two-col{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}"
        ".panel{background:var(--ink3);border:1px solid var(--wire);border-radius:5px;padding:12px 13px}"
        ".panel-hdr{font-size:9px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;"
        "margin-bottom:9px;display:flex;align-items:center;gap:6px}"
        ".panel-hdr.g{color:var(--green)}.panel-hdr.r{color:var(--red)}"
        ".ph-ind{width:6px;height:6px;border-radius:1px;flex-shrink:0}"
        ".ph-ind.g{background:var(--green)}.ph-ind.r{background:var(--red)}"
        ".panel-item{font-size:10px;line-height:1.55;color:var(--mid);padding:5px 0;"
        "border-top:1px solid var(--wire);display:flex;gap:7px;align-items:flex-start}"
        ".panel-item:first-of-type{border-top:none}"
        ".pi-dot{width:3px;height:3px;border-radius:50%;margin-top:5px;flex-shrink:0}"
        ".pi-dot.g{background:var(--green)}.pi-dot.r{background:rgba(224,92,92,0.55)}"
        ".risk-banner{background:var(--amber-dim);border:1px solid rgba(232,168,74,0.22);"
        "border-left:3px solid var(--amber2);border-radius:0 5px 5px 0;padding:10px 14px;"
        "display:flex;align-items:flex-start;gap:9px;margin-bottom:16px}"
        ".risk-icon{font-size:12px;line-height:1.4;flex-shrink:0;color:var(--amber);"
        "font-weight:800;font-family:'Barlow Condensed',sans-serif}"
        ".risk-text{font-size:10px;line-height:1.6;color:rgba(232,168,74,0.80)}"
        ".comps-section{margin-top:auto;padding-top:10px}"
        ".comps-row{display:flex;gap:10px}"
        ".comp-card{flex:1;background:var(--ink3);border:1px solid var(--wire2);border-radius:5px;"
        "padding:14px;position:relative;overflow:hidden}"
        ".comp-card::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px}"
        ".comp-card.hit::before{background:linear-gradient(180deg,var(--green),rgba(90,184,122,0.4))}"
        ".comp-card.partial::before{background:linear-gradient(180deg,var(--amber),rgba(232,168,74,0.4))}"
        ".comp-card.miss::before{background:linear-gradient(180deg,var(--red),rgba(224,92,92,0.4))}"
        ".comp-card::after{content:'';position:absolute;inset:0;"
        "background:linear-gradient(135deg,rgba(255,255,255,0.025) 0%,transparent 50%);pointer-events:none}"
        ".comp-type-lbl{font-size:8px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:4px}"
        ".comp-type-lbl.hit{color:var(--green)}.comp-type-lbl.partial{color:var(--amber)}.comp-type-lbl.miss{color:var(--red)}"
        ".comp-name-row{display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap}"
        ".comp-name{font-family:'Barlow Condensed',sans-serif;font-size:22px;font-weight:900;"
        "letter-spacing:0.01em;text-transform:uppercase;color:var(--text);line-height:1}"
        ".comp-badge{display:inline-flex;align-items:center;gap:4px;font-size:8px;font-weight:700;"
        "letter-spacing:0.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px}"
        ".comp-badge.hit{background:var(--green-dim);color:var(--green);border:1px solid rgba(90,184,122,0.25)}"
        ".comp-badge.partial{background:var(--amber-dim);color:var(--amber);border:1px solid rgba(232,168,74,0.25)}"
        ".comp-badge.miss{background:var(--red-dim);color:var(--red);border:1px solid rgba(224,92,92,0.25)}"
        ".comp-badge::before{content:'';width:4px;height:4px;border-radius:50%;background:currentColor;opacity:0.8}"
        ".comp-desc{font-size:9px;line-height:1.6;color:var(--dim);margin-bottom:6px}"
        ".comp-year{font-size:8px;color:rgba(255,255,255,0.18);"
        "font-family:'Barlow Condensed',sans-serif;letter-spacing:0.06em}"
        ".card-stamp{position:absolute;bottom:10px;right:24px;font-family:'Barlow Condensed',sans-serif;"
        "font-size:9px;font-weight:700;letter-spacing:0.16em;color:rgba(255,255,255,0.10);"
        "text-transform:uppercase;z-index:4}"
    )

    cap_note_html = f'<div class="capital-note">{_e(capital_note)}</div>' if capital_note else ""
    scored_html   = (
        f"&nbsp;&nbsp;\u00b7&nbsp;&nbsp;Scored: {_e(str(snapshot_date)[:10])}"
        if snapshot_date else ""
    )
    fit_row = ""
    if fit_badge:
        fit_score_span = (
            f"&nbsp;<span style='font-size:11px;color:var(--dim)'>Fit: {_e(f'{fit_score:.1f}')} pts</span>"
            if fit_score else ""
        )
        fit_row = (
            f"<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:4px'>"
            f"{fit_badge}{fit_score_span}</div>"
        )
    stamp_id = d.get("prospect_id") or d.get("consensus_rank") or "000"

    gf_url = (
        "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;500;600;700;800;900"
        "&family=Barlow:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&display=swap"
    )

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        f'<link href="{gf_url}" rel="stylesheet">\n'
        f'<style>\n{css}\n</style>\n'
        '</head>\n<body>\n'
        '<div class="card">\n'
        '  <div class="prism-strip"></div>\n'
        '  <div class="top-bar"></div>\n'
        '  <div class="layout">\n'
        '    <div class="left">\n'
        f'      <div class="identity-row">'
        f'<div class="pos-chip"><span class="pos-chip-dot"></span>{_e(pos)}</div>'
        f'{pos_rank_chip}</div>\n'
        f'      <div class="player-name">{name_html}</div>\n'
        '      <div class="name-slash"></div>\n'
        f'      <div class="meta-row">'
        f'<span class="meta-chip">{_e(school)}</span>'
        f'<span class="meta-chip">Consensus {rank_str}</span></div>\n'
        f'      <div class="apex-window">{score_block}'
        f'<div class="tier-badge {tier_cls}">'
        f'<span class="tier-badge-text">{_e(tier_text)}</span>'
        f'<span class="tier-badge-sub">{_e(tier_sub)}</span></div>'
        f'<div class="formula-line">RPG {_safe_float(raw_score)} \u00d7 PVC {pvc_str}'
        f' ({_e(pos)}) = APEX {_safe_float(apex_comp)}</div></div>\n'
        f'      <div class="traits-section">'
        f'<div class="section-header">Football Traits</div>{football_html}</div>\n'
        f'      <div class="traits-section">'
        f'<div class="section-header">System Traits</div>{system_html}</div>\n'
        f'      <div class="left-footer">'
        f'<div class="conf-box">'
        f'<div><div class="conf-lbl">Confidence</div>'
        f'<div class="conf-val" style="color:{conf_color}">{_e(conf)}</div></div>'
        f'<div><div class="conf-lbl">Divergence</div>'
        f'<div class="conf-val" style="color:{div_color}">{div_text}</div></div></div>'
        f'<div class="capital-box">'
        f'<div class="capital-lbl">Draft Capital</div>'
        f'<div class="capital-val">{_e(capital_base)}</div>{cap_note_html}</div>'
        f'<div class="eval-box">Eval Confidence: '
        f'<span style="color:{conf_color};font-weight:700">{_e(conf)}</span>'
        f'{scored_html}</div>'
        f'<div class="watermark">'
        f'<div><span class="brand-logo">DraftOS</span><br>'
        f'<span class="brand-version">v2.3 \u00b7 2026</span></div>'
        f'<div class="watermark-meta">{rank_str} \u00b7 {_e(pos)} \u00b7 {_e(school)}<br>'
        f'Generated {wm_date}</div></div></div>\n'
        '    </div>\n'
        '    <div class="right">\n'
        f'      <div class="header-zone">'
        f'<div class="rank-ghost">{ghost_rank}</div>'
        f'<div class="header-row">'
        f'<div><div class="archetype-code">{_e(arch_code)}</div>'
        f'<div class="archetype-name">{_e(arch_label or archetype_raw)}</div></div>'
        f'{ras_html}</div>{fit_row}</div>\n'
        f'      {fm_section}\n'
        f'      {sig_html}\n'
        f'      {two_col}\n'
        f'      {risk_html}\n'
        f'      {comps_html}\n'
        '    </div>\n'
        '  </div>\n'
        f'  <div class="card-stamp">DRAFTOS \u00b7 2026 DRAFT CLASS \u00b7 #{stamp_id}</div>\n'
        '</div>\n'
        '</body>\n</html>'
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
