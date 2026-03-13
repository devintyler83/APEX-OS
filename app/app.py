"""
DraftOS Big Board — Session 37
Read-only Streamlit UI with divergence flags, APEX rank input, APEX v2.2 scores,
tag display, and prospect detail drawer.
No DB writes except through save_apex_rank() and clear_apex_rank(). No business logic.
"""

import pandas as pd
import streamlit as st

from draftos.db.connect import connect
from draftos.queries.apex import save_apex_rank, clear_apex_rank, get_apex_detail
from draftos.queries.model_outputs import get_big_board, get_prospect_detail

# Streamlit ≥ 1.35 supports on_select / selection_mode on st.dataframe
_ON_SELECT_AVAILABLE = tuple(
    int(x) for x in st.__version__.split(".")[:2]
) >= (1, 35)

st.set_page_config(layout="wide", page_title="DraftOS Big Board")

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
    "Scheme Dependent":   "🔒 Scheme Lock",
    "Development Bet":    "📈 Dev Bet",
    "Floor Play":         "🛡️ Safe Floor",
    "Riser":              "📈 Riser",
    "Faller":             "📉 Faller",
    "Scheme Fit":         "🎯 Scheme Fit",
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
    "CRUSH":              "💎 Priority",
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
    "Walk-On Flag":       ("#1a1a1a", "#333333", "#aaaaaa"),
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

_INTERNAL_TAG_NAMES: frozenset[str] = frozenset({
    "apex_rank_2026",
})

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
    "UDFA":   ("#37474f", "#cccccc"),
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
        f'border-radius:999px;padding:2px 10px;font-size:11px;font-weight:600;'
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
    if val is None:
        return (
            f'<div style="display:flex;align-items:center;margin-bottom:6px">'
            f'<div style="width:175px;font-size:12px;color:#777">{label}</div>'
            f'<div style="flex:1;background:#222;border-radius:3px;height:8px;margin:0 10px"></div>'
            f'<div style="width:28px;text-align:right;font-size:12px;color:#555">—</div>'
            f'</div>'
        )
    pct   = min(max(val / 10.0 * 100, 0), 100)
    color = _bar_color(val)
    return (
        f'<div style="display:flex;align-items:center;margin-bottom:6px">'
        f'<div style="width:175px;font-size:12px;color:#bbb">{label}</div>'
        f'<div style="flex:1;background:#222;border-radius:3px;height:8px;margin:0 10px">'
        f'<div style="width:{pct:.0f}%;background:{color};height:100%;border-radius:3px"></div></div>'
        f'<div style="width:28px;text-align:right;font-size:12px;color:{color};font-weight:700">{val:.1f}</div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Dynamic bullet generator
# ---------------------------------------------------------------------------

def _generate_bullets(d: dict) -> tuple[list[str], list[str]]:
    """
    Generate strength and flag bullets from trait scores.
    Returns (strengths, flags) — each a list of bullet strings.
    """
    strengths: list[str] = []
    flags:     list[str] = []

    v_ath  = d.get("v_athleticism")
    v_proc = d.get("v_processing")
    v_prod = d.get("v_production")
    v_dev  = d.get("v_dev_traj")
    v_comp = d.get("v_comp_tough")
    v_vers = d.get("v_scheme_vers")
    v_inj  = d.get("v_injury")
    c2     = d.get("c2_motivation")
    c3     = d.get("c3_psych_profile")
    ras    = d.get("ras_score") or d.get("ras_total")
    gap    = (d.get("gap_label") or "").strip().upper()
    fit_sc = d.get("archetype_gap")
    e_conf = d.get("eval_confidence") or ""
    schwes = bool(d.get("schwesinger_full")) or bool(d.get("schwesinger_half"))

    # ── Strengths ──────────────────────────────────────────────────────────
    if v_ath is not None:
        ras_str = f"{float(ras):.2f}" if ras is not None else "N/A"
        if v_ath >= 9.5:
            strengths.append(
                f"Elite athletic profile — {v_ath:.1f}/10 athleticism with {ras_str} RAS"
            )
        elif v_ath >= 8.5:
            strengths.append(
                f"Above-average athlete — {v_ath:.1f}/10, moves well for the position"
            )

    if v_proc is not None:
        if v_proc >= 9.0:
            strengths.append(
                f"Elite pre-snap processor — {v_proc:.1f}/10, anticipates before the snap"
            )
        elif v_proc >= 8.0:
            strengths.append(
                f"Advanced diagnostic ability — {v_proc:.1f}/10, quick read-to-react"
            )

    if v_prod is not None and v_prod >= 9.0:
        strengths.append(f"Elite production baseline — {v_prod:.1f}/10 in a proven role")

    if v_dev is not None and v_dev >= 9.0:
        strengths.append(
            f"Exceptional development trajectory — {v_dev:.1f}/10, improving fast"
        )

    if c2 is not None and c2 >= 8.0:
        strengths.append(
            f"Motor and drive rated {c2:.1f}/10 — coaches consistently note elite work ethic"
        )

    if v_comp is not None and v_comp >= 9.0:
        strengths.append(f"Rises in big games — {v_comp:.1f}/10 competitive toughness")

    if v_vers is not None and v_vers >= 9.0:
        strengths.append(
            f"Scheme-transcendent — {v_vers:.1f}/10, deploys across multiple systems"
        )

    if v_inj is not None and v_inj >= 9.0:
        strengths.append(
            f"Elite durability profile — {v_inj:.1f}/10, consistently available"
        )

    if schwes:
        strengths.append(
            "Character multiplier active — C2+C3 combo boosts Dev Trajectory"
        )

    if gap == "CLEAN" and fit_sc is not None:
        strengths.append(
            f"Clean archetype match — {fit_sc:.1f} fit score, clear translation path"
        )

    # ── Flags ──────────────────────────────────────────────────────────────
    if v_ath is not None and v_ath < 6.0:
        flags.append(
            f"Athleticism concern — {v_ath:.1f}/10 raises FM-1 risk at NFL speed"
        )

    if v_proc is not None and v_proc < 6.0:
        flags.append(
            f"Processing ceiling flagged — {v_proc:.1f}/10, FM-3 risk in NFL complexity"
        )

    if v_vers is not None and v_vers < 5.0:
        flags.append(
            f"Scheme-dependent — {v_vers:.1f}/10, FM-2/FM-6 risk without right fit"
        )

    if v_inj is not None and v_inj < 6.0:
        flags.append(
            f"Injury/durability concern — {v_inj:.1f}/10, FM-4 risk over full season"
        )

    if c2 is not None and c2 < 5.0:
        flags.append(f"Motor/drive below threshold — {c2:.1f}/10, FM-5 watch list")

    if c3 is not None and c3 < 3.0:
        flags.append("Smith Rule active — C3 score caps character ceiling")

    if v_dev is not None and v_dev < 5.0:
        flags.append(
            f"Limited development runway — {v_dev:.1f}/10, near finished product"
        )

    if v_prod is not None and v_prod < 6.0:
        flags.append(
            f"Production questions — {v_prod:.1f}/10, limited sample or scheme-aided"
        )

    if gap == "TWEENER":
        flags.append("Tweener archetype fit — falls between profiles, deployment TBD")
    elif gap == "NO_FIT" and fit_sc is not None:
        flags.append(
            f"Archetype miss — {fit_sc:.1f} fit score, translation confidence low"
        )

    if ras is None:
        flags.append("Combine data not yet available")

    if "C" in e_conf:
        flags.append(
            "Eval Confidence Tier C — heavy projection required, Tier C discount applied"
        )

    # Defaults
    if not strengths:
        strengths = [
            "Sufficient tape evidence exists; no standout strength vectors above threshold."
        ]
    if not flags:
        flags = [
            "No significant flags identified at current eval confidence level."
        ]

    return strengths, flags


# ---------------------------------------------------------------------------
# Detail card renderers
# ---------------------------------------------------------------------------

def _render_apex_detail(d: dict) -> None:
    """Render full APEX evaluation card with styled HTML sections and dynamic bullets."""

    # ── Header ────────────────────────────────────────────────────────────────
    pos    = d.get("position_group") or "?"
    name   = d.get("display_name") or "Unknown"
    school = d.get("school_canonical") or "—"
    score  = d.get("apex_composite")
    tier   = (d.get("apex_tier") or "").strip().upper()
    crank  = d.get("consensus_rank")
    conf   = d.get("confidence_band") or "—"
    ras    = d.get("ras_score") or d.get("ras_total")

    pos_color   = _POS_BADGE_COLORS.get(pos, "#555555")
    tier_bg, tier_text = _APEX_TIER_BADGE.get(tier, ("#555555", "#ffffff"))
    score_color = _APEX_SCORE_COLORS.get(tier, "#e0e0e0")
    score_str   = f"{score:.1f}" if score is not None else "—"
    rank_str    = f"#{int(crank)}" if crank is not None and pd.notna(crank) else "—"
    ras_str     = f"{float(ras):.2f}" if ras is not None and pd.notna(ras) else "—"

    header_html = f"""
<div style="display:flex;align-items:center;gap:10px;padding:14px 0 10px 0;flex-wrap:wrap;
            border-bottom:1px solid #333">
  <span style="background:{pos_color};color:white;padding:5px 12px;border-radius:6px;
               font-size:13px;font-weight:800;letter-spacing:0.5px">{pos}</span>
  <span style="font-size:22px;font-weight:800;color:#f0f0f0">{name}</span>
  <div style="flex:1"></div>
  <span style="font-size:30px;font-weight:900;color:{score_color}">{score_str}</span>
  <span style="background:{tier_bg};color:{tier_text};padding:5px 14px;border-radius:6px;
               font-size:15px;font-weight:800">{tier or "—"}</span>
</div>
<div style="font-size:13px;color:#888;padding:8px 0 12px 0">
  {school} &nbsp;·&nbsp; Consensus {rank_str} &nbsp;·&nbsp; Confidence: {conf}
  &nbsp;·&nbsp; RAS: {ras_str}
</div>
"""
    st.markdown(header_html, unsafe_allow_html=True)

    # ── Trait Vector Bars ─────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:12px;font-weight:700;color:#999;letter-spacing:1px;'
        'margin-bottom:8px">TRAIT VECTORS</div>',
        unsafe_allow_html=True,
    )

    traits = [
        ("Processing & Instincts", d.get("v_processing")),
        ("Athleticism",            d.get("v_athleticism")),
        ("Scheme Versatility",     d.get("v_scheme_vers")),
        ("Competitive Toughness",  d.get("v_comp_tough")),
        ("Character & Intangibles",d.get("v_character")),
        ("Dev. Trajectory",        d.get("v_dev_traj")),
        ("Production",             d.get("v_production")),
        ("Injury & Durability",    d.get("v_injury")),
    ]

    bar_col1, bar_col2 = st.columns(2)
    with bar_col1:
        st.markdown(
            "".join(_trait_bar_html(lbl, val) for lbl, val in traits[:4]),
            unsafe_allow_html=True,
        )
    with bar_col2:
        st.markdown(
            "".join(_trait_bar_html(lbl, val) for lbl, val in traits[4:]),
            unsafe_allow_html=True,
        )

    # Character sub-scores
    c1 = d.get("c1_public_record")
    c2 = d.get("c2_motivation")
    c3 = d.get("c3_psych_profile")
    if any(v is not None for v in [c1, c2, c3]):
        sub = []
        if c1 is not None: sub.append(f"Off-field record: **{c1:.1f}**")
        if c2 is not None: sub.append(f"Motor & drive: **{c2:.1f}**")
        if c3 is not None: sub.append(f"Mental makeup: **{c3:.1f}**")
        st.caption("  ·  ".join(sub))

    # Special rule badges
    badges = []
    if d.get("smith_rule"):
        badges.append("⚠️ Character cap applied — reduces draft capital")
    if d.get("schwesinger_full"):
        badges.append("🚀 Elite character bonus — Dev Trajectory boosted (full)")
    if d.get("schwesinger_half"):
        badges.append("📈 Character bonus — Dev Trajectory boosted")
    if d.get("two_way_premium"):
        badges.append("⭐ Two-way prospect — scored at higher-value position")
    for b in badges:
        st.caption(b)

    st.divider()

    # ── Archetype Block ───────────────────────────────────────────────────────
    arch      = d.get("matched_archetype") or "—"
    gap_label = (d.get("gap_label") or "").strip().upper()
    fit_score = d.get("archetype_gap")
    gap_bg, gap_text = _GAP_BADGE_COLORS.get(gap_label, ("#555555", "#ffffff"))
    fit_str      = f"{fit_score:.1f} pts" if fit_score is not None else "—"
    gap_display  = _GAP_LABEL_DISPLAY_MAP.get(gap_label, gap_label)

    arch_html = f"""
<div style="background:#1a1a2a;border:1px solid #2a2a40;border-radius:8px;
            padding:12px 16px;margin:6px 0">
  <div style="font-size:11px;color:#666;letter-spacing:1px;margin-bottom:6px">ARCHETYPE</div>
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <span style="font-size:16px;font-weight:700;color:#e0e0e0">{arch}</span>
    <span style="font-size:13px;color:#888">Fit: {fit_str}</span>
    <span style="background:{gap_bg};color:{gap_text};padding:3px 10px;border-radius:999px;
                 font-size:11px;font-weight:700">{gap_display}</span>
  </div>
</div>
"""
    st.markdown(arch_html, unsafe_allow_html=True)

    if d.get("override_arch"):
        od = d.get("override_delta") or 0
        st.warning(
            f"🔧 **OVERRIDE:** {d['override_arch']} "
            f"(Δ{od:+.1f}) — "
            f"{d.get('override_rationale') or 'No rationale recorded.'}"
        )

    # ── Draft Capital ─────────────────────────────────────────────────────────
    cap_base = d.get("capital_base") or "—"
    cap_adj  = d.get("capital_adjusted") or "—"

    capital_html = f"""
<div style="background:#1a1a2a;border:1px solid #2a2a40;border-radius:8px;
            padding:12px 16px;margin:6px 0 14px 0">
  <div style="font-size:11px;color:#666;letter-spacing:1px;margin-bottom:8px">DRAFT CAPITAL</div>
  <div style="display:flex;gap:40px;flex-wrap:wrap">
    <div>
      <div style="font-size:11px;color:#666;margin-bottom:2px">Base</div>
      <div style="font-size:16px;font-weight:700;color:#e0e0e0">{cap_base}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#666;margin-bottom:2px">Adjusted (PVC)</div>
      <div style="font-size:16px;font-weight:700;color:#e0e0e0">{cap_adj}</div>
    </div>
  </div>
</div>
"""
    st.markdown(capital_html, unsafe_allow_html=True)

    st.divider()

    # ── Strengths / Red Flags — Summary vs Bullet Points ─────────────────────
    _view_mode = st.radio(
        "View mode",
        options=["Summary", "Bullet Points"],
        index=0,
        horizontal=True,
        key=f"detail_view_mode_{d.get('prospect_id', 0)}",
    )

    s_col, r_col = st.columns(2)

    if _view_mode == "Bullet Points":
        str_bullets, flg_bullets = _generate_bullets(d)
        with s_col:
            st.markdown("**✅ Strengths**")
            for b in str_bullets:
                st.markdown(f"• {b}")
        with r_col:
            st.markdown("**🚨 Red Flags**")
            for b in flg_bullets:
                st.markdown(f"• {b}")
    else:
        with s_col:
            st.markdown("**✅ Strengths**")
            st.markdown(d.get("strengths") or "*No strengths recorded.*")
        with r_col:
            st.markdown("**🚨 Red Flags**")
            st.markdown(d.get("red_flags") or "*No red flags recorded.*")

    # ── Eval Confidence ───────────────────────────────────────────────────────
    st.divider()
    conf_field = d.get("eval_confidence") or "—"
    conf_color = {"Tier A": "🟢", "Tier B": "🟡", "Tier C": "🔴"}.get(conf_field, "⚪")
    scored_at  = d.get("scored_at") or ""
    st.caption(
        f"**Eval Confidence:** {conf_color} {conf_field}   |   "
        f"Scored: {scored_at[:10] if scored_at else '—'}"
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
    f"APEX v2.2 scored: {apex_scored}"
)

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")

    show_low = st.checkbox("Show Low confidence", value=False)

    show_divergence_only = st.checkbox("Show divergence flags only (⚡)", value=False)

    show_apex_only = st.checkbox("Show APEX scored only (auto-rank)", value=False)

    show_apex_scored_only = st.checkbox("Show APEX v2.2 scored only", value=False)

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

    # APEX v2.2 tier filter — draft-capital vocabulary, all 6 tiers
    if apex_scored > 0 and "apex_tier" in df.columns:
        apex_tier_options = ["(all)", "ELITE", "DAY1", "DAY2", "DAY3", "UDFA-P", "UDFA"]
        selected_apex_tier = st.selectbox("APEX v2.2 tier", options=apex_tier_options, index=0)
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

    # --- Tag filter ---
    st.markdown("### Tags")
    selected_tags: list[str] = []
    for tag_name in _SIDEBAR_TAGS:
        if st.checkbox(_TAG_LABEL_MAP.get(tag_name, tag_name), key=f"tag_{tag_name}"):
            selected_tags.append(tag_name)

    # --- Tag legend ---
    with st.expander("📖 Tag Legend", expanded=False):
        st.markdown("""
**⚡ Divergence Alert** — APEX score diverges significantly from consensus
rank. Premium positions only (QB/CB/EDGE/OT/S). Review recommended.

**📈 Dev Bet** — Consensus rank exceeds APEX projection. Market may be
underrating developmental upside. Usually round 3+.

**⚖ Compression** — Multiple archetypes score within range. True positional
identity unclear. Scheme-fit dependent.

**🔥 Elite RAS** — Relative Athletic Score ≥ 9.5. Top-tier measurables.

**✓ Great RAS** — RAS 8.0–9.4. Above-average athletic profile.

**⚠ Poor RAS** — RAS < 5.0. Athletic concern for position demands.

**🩹 Injury** — Significant injury history. Durability risk flagged.
""")

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

# Tag filter — OR logic: show prospects matching ANY selected tag
if selected_tags:
    selected_set = set(selected_tags)

    def _has_any_tag(tag_str: str) -> bool:
        return bool(selected_set.intersection(_parse_tags(tag_str)))

    tag_mask = filtered["tag_names"].apply(_has_any_tag)
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

# APEX v2.2 engine columns — NULL-safe
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
    "High":   "background-color: #1a7a1a; color: white",
    "Medium": "background-color: #7a6a00; color: white",
    "Low":    "background-color: #7a1a1a; color: white",
}

# Draft-capital tier colors
APEX_TIER_COLORS = {
    "ELITE":  "background-color: #b8860b; color: white",   # dark gold
    "DAY1":   "background-color: #1a7a1a; color: white",   # green
    "DAY2":   "background-color: #005090; color: white",   # blue
    "DAY3":   "background-color: #cc5500; color: white",   # orange
    "UDFA-P": "background-color: #6a1a8a; color: white",   # purple
    "UDFA":   "background-color: #455a64; color: white",   # grey-blue
}

DIVERGENCE_COLOR = "background-color: #8a5700; color: white"   # amber


def _style_confidence(val: str) -> str:
    return CONFIDENCE_COLORS.get(val, "")


# Consensus tier: text color only (no background fill)
_CONSENSUS_TIER_COLORS = {
    "Elite":    "color: #4ade80; font-weight: 600",
    "Strong":   "color: #60a5fa; font-weight: 600",
    "Playable": "color: #facc15; font-weight: 600",
    "Watch":    "color: #f97316; font-weight: 600",
}


def _style_consensus_tier(val: str) -> str:
    return _CONSENSUS_TIER_COLORS.get(val, "")


def _style_divergence(val: str) -> str:
    return DIVERGENCE_COLOR if val != "" else ""


def _style_apex_delta(val: str) -> str:
    if val in ("", "\u2014"):
        return ""
    try:
        n = int(val.replace("+", ""))
    except (ValueError, AttributeError):
        return ""
    if n > 0:
        return "background-color: #1a5a1a; color: white"
    if n < 0:
        return "background-color: #6a1a1a; color: white"
    return ""


def _style_apex_tier(val: str) -> str:
    return APEX_TIER_COLORS.get(val, "")


_NUM_COLS = ["Rank", "Score", "Sources", "Coverage", "RAS", "APEX Score"]
_STR_COLS = ["Player", "School", "Pos", "Consensus", "Confidence", "APEX Tier",
             "Archetype", "Tags", "Snapshot", "⚡ Div", "\u0394 APEX"]

styled = (
    display.style
    .set_properties(subset=[c for c in _NUM_COLS if c in display.columns],
                    **{"text-align": "right"})
    .set_properties(subset=[c for c in _STR_COLS if c in display.columns],
                    **{"text-align": "left"})
    .map(_style_confidence, subset=["Confidence"])
    .map(_style_consensus_tier, subset=["Consensus"])
    .map(_style_divergence, subset=["⚡ Div"])
    .map(_style_apex_delta, subset=["\u0394 APEX"])
    .map(_style_apex_tier, subset=["APEX Tier"])
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
| APEX Score | APEX v2.2 composite score (0–100) |
| APEX Tier | **ELITE** ≥85 · **DAY1** ≥70 · **DAY2** ≥55 · **DAY3** ≥40 · **UDFA-P** ≥28 · **UDFA** <28 |
| Archetype | How this prospect wins — matched from APEX v2.2 positional library |
| Archetype Fit | **Clean Fit** >15 pts · **Solid Fit** 8–15 pts · **Tweener** <8 pts · **No Fit** = concern |
| Tags | System-generated signals. See Tag Legend in sidebar. |
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

    st.caption(f"Showing {len(display)} of {total_prospects} prospects")
    st.caption("💡 Click any row to load the prospect detail panel below.")

    # Tagged prospects pill view
    tagged_filtered = filtered[filtered["tag_names"] != ""].copy()
    if not tagged_filtered.empty:
        with st.expander(f"Tagged prospects on this board ({len(tagged_filtered)})", expanded=False):
            # Legend: tags present on current filtered board
            active_legend_tags = [
                t for t in _SIDEBAR_TAGS
                if any(t in _parse_tags(row) for row in tagged_filtered["tag_names"])
            ]
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
        _left_cols_apex  = ["Player", "Pos", "School", "APEX Tier", "Archetype",
                            "Fit", "Eval Conf", "Tags"]

        apex_styled = (
            ab.style
            .map(_style_apex_tier, subset=["APEX Tier"])
            .map(_style_apex_delta, subset=["\u0394 APEX"])
            .set_properties(subset=_right_cols_apex, **{"text-align": "right"})
            .set_properties(subset=_left_cols_apex,  **{"text-align": "left"})
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
# Prospect Detail Panel (unified)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📋 Prospect Detail")

_selected_pid = st.session_state.get("selected_pid")

if _selected_pid is None:
    _hint = (
        "Click a row in either board above to load their profile."
        if _ON_SELECT_AVAILABLE
        else "Use the selector above to choose a prospect."
    )
    st.caption(f"No prospect selected. {_hint}")
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
                # Expose board-side RAS for _generate_bullets (ras_total from ras table)
                _detail["ras_score"] = _pr.get("ras_score")
                _render_apex_detail(_detail)
            else:
                st.warning("APEX detail record not found despite apex_composite being set.")
        else:
            _render_consensus_card(_pr)
