"""
DraftOS Big Board — Session 31
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
# Tag helpers
# ---------------------------------------------------------------------------

# Actual tag_name values as stored in tag_definitions
_TAG_COLOR_MAP: dict[str, str] = {
    "Divergence Alert":  "#F59E0B",
    "Development Bet":   "#3B82F6",
    "Compression Flag":  "#8B5CF6",
    "Elite RAS":         "#10B981",
    "Great RAS":         "#14B8A6",
    "Poor RAS":          "#EF4444",
    "Injury Flag":       "#F97316",
}

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

# Tag color emoji for drawer panels
_TAG_EMOJI_MAP: dict[str, str] = {
    "green": "🟢",
    "red":   "🔴",
    "blue":  "🔵",
    "gold":  "🟡",
}

# ---------------------------------------------------------------------------
# Frontend display aliases — backend strings NEVER shown to users
# Keys are the exact tag_name values from tag_definitions.
# ---------------------------------------------------------------------------
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
    # Legacy engine tags (from apex_scores.tags comma field)
    "Smith Rule":         "⚠️ Char. Cap",
    "CRUSH":              "💎 Priority",
    "Walk-On Flag":       "🏃 Walk-On",
    "Two-Way Premium":    "🔄 Two-Way",
    "Schwesinger Rule":   "🚀 Elite Char.",
}

_GAP_LABEL_DISPLAY_MAP: dict[str, str] = {
    "CLEAN"       : "✅ Clean Fit",
    "SOLID"       : "🟢 Solid Fit",
    "TWEENER"     : "⚠️ Tweener",
    "COMPRESSION" : "🔵 Elite Tweener",
    "NO_FIT"      : "🔴 No Dominant Fit",
}

# Tag names that exist in prospect_tags for system purposes but should
# never appear in board display columns.
_INTERNAL_TAG_NAMES: frozenset[str] = frozenset({
    "apex_rank_2026",
})


def _render_tags(raw_tags_string: str) -> list[str]:
    """
    Split apex_scores.tags comma string, map each to frontend display label.
    Returns list of display strings. Unknown tags pass through title-cased.
    """
    if not raw_tags_string:
        return []
    return [
        _TAGS_DISPLAY_MAP.get(t.strip(), t.strip().title())
        for t in raw_tags_string.split(",")
        if t.strip()
    ]


def _render_gap_label(gap_label: str | None, archetype_gap: float | None) -> str:
    """
    Return a clean badge string for archetype fit quality.
    Raw gap number is suppressed from display — shown only via this badge.
    """
    if not gap_label:
        return ""
    display_label = _GAP_LABEL_DISPLAY_MAP.get(
        gap_label.strip().upper(),
        gap_label.strip().title()
    )
    return display_label  # gap float intentionally NOT shown


def render_tag_pills(tag_names: list[str]) -> str:
    """Return HTML string of colored pill spans for the given tag names."""
    pills = []
    for tag in tag_names:
        color = _TAG_COLOR_MAP.get(tag, "#6B7280")
        label = _TAG_LABEL_MAP.get(tag, tag[:4].upper())
        pill = (
            f'<span style="background:{color};color:white;padding:2px 6px;'
            f'border-radius:4px;font-size:11px;font-weight:600;'
            f'margin-right:3px;white-space:nowrap">{label}</span>'
        )
        pills.append(pill)
    return "".join(pills)


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
snapshot_date    = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else "unknown"
total_prospects  = len(df)
apex_scored      = df["apex_composite"].notna().sum() if "apex_composite" in df.columns else 0

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


def _fmt_tags(raw) -> str:
    """Format comma-delimited tag names for board display. Filters internal system tags."""
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    parts = [t.strip() for t in str(raw).split(",") if t.strip()]
    parts = [p for p in parts if p not in _INTERNAL_TAG_NAMES]
    return "  ".join(_TAGS_DISPLAY_MAP.get(p, p) for p in parts)


def _render_apex_detail(d: dict) -> None:
    """Render full APEX evaluation breakdown inside an expander."""

    # ── Header ────────────────────────────────────────────────────────────────
    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([3, 1, 2, 2, 2])
    col_h1.markdown(f"**{d['display_name']}**")
    col_h2.markdown(f"`{d['position_group']}`")
    col_h3.markdown(f"{d['school_canonical'] or '—'}")
    score_str = f"**{d['apex_composite']:.1f}**" if d.get('apex_composite') is not None else "—"
    col_h4.markdown(f"APEX {score_str}")
    tier = d.get('apex_tier') or "—"
    tier_color = {
        "ELITE":  "🟢", "DAY1": "🔵", "DAY2": "🟡",
        "DAY3":   "🟠", "UDFA-P": "🔴", "UDFA": "⚫",
    }.get(tier, "⚪")
    col_h5.markdown(f"{tier_color} {tier}")

    st.divider()

    # ── Trait Vectors ─────────────────────────────────────────────────────────
    st.markdown("**Trait Vectors** *(1–10)*")
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
    t_cols = st.columns(4)
    for i, (label, val) in enumerate(traits):
        col = t_cols[i % 4]
        val_str = f"{val:.1f}" if val is not None else "—"
        col.metric(label=label, value=val_str)

    # Character sub-scores — plain English labels
    c1 = d.get("c1_public_record")
    c2 = d.get("c2_motivation")
    c3 = d.get("c3_psych_profile")
    if any(v is not None for v in [c1, c2, c3]):
        sub = []
        if c1 is not None: sub.append(f"Off-field record: **{c1:.1f}**")
        if c2 is not None: sub.append(f"Motor & drive: **{c2:.1f}**")
        if c3 is not None: sub.append(f"Mental makeup: **{c3:.1f}**")
        st.caption("  ·  ".join(sub))

    # Special rule badges — plain English
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
    arch_col1, arch_col2, arch_col3 = st.columns([3, 2, 2])
    arch_col1.markdown(f"**Archetype:** {d.get('matched_archetype') or '—'}")
    _agap = d.get("archetype_gap")
    if _agap is not None:
        if _agap > 15:
            _gap_ctx = "Clean fit — clear archetype match"
        elif _agap >= 8:
            _gap_ctx = "Solid fit — good match with some overlap"
        else:
            _gap_ctx = "Tweener — no dominant archetype"
        arch_col2.markdown(f"**Archetype fit:** {_agap:.1f} pts  \n*{_gap_ctx}*")
    else:
        arch_col2.markdown("**Archetype fit:** —")
    gap_label = (d.get("gap_label") or "—").strip().upper()
    gap_colors = {
        "CLEAN": "🟢", "SOLID": "🟡", "TWEENER": "🟠",
        "COMPRESSION": "🔴", "NO_FIT": "⚫",
    }
    arch_col3.markdown(f"**Fit label:** {gap_colors.get(gap_label, '⚪')} {gap_label}")

    if d.get("override_arch"):
        _od = d.get("override_delta") or 0
        st.warning(
            f"🔧 **OVERRIDE:** {d['override_arch']} "
            f"(Δ{_od:+.1f}) — "
            f"{d.get('override_rationale') or 'No rationale recorded.'}"
        )

    st.divider()

    # ── Capital Block ─────────────────────────────────────────────────────────
    cap_col1, cap_col2 = st.columns(2)
    cap_col1.markdown(f"**Draft capital (base):** {d.get('capital_base') or '—'}")
    cap_col2.markdown(f"**Draft capital (adjusted):** {d.get('capital_adjusted') or '—'}")

    st.divider()

    # ── Strengths / Red Flags — toggle bullets vs prose ───────────────────────
    import re as _re

    def _to_bullets(text: str | None) -> list[str]:
        if not text:
            return []
        sentences = _re.split(r'(?<=[.!?])\s+', text.strip())
        return [s.strip() for s in sentences if len(s.strip()) > 10]

    _view_mode = st.radio(
        "View mode",
        options=["Summary", "Bullet Points"],
        index=0,
        horizontal=True,
        key=f"detail_view_mode_{d.get('prospect_id', 0)}",
    )

    s_col, r_col = st.columns(2)
    with s_col:
        st.markdown("**✅ Strengths**")
        _strengths = d.get("strengths") or ""
        if _view_mode == "Bullet Points":
            _bullets = _to_bullets(_strengths)
            if _bullets:
                for _b in _bullets:
                    st.markdown(f"• {_b}")
            else:
                st.markdown("*No strengths recorded.*")
        else:
            st.markdown(_strengths or "*No strengths recorded.*")
    with r_col:
        st.markdown("**🚨 Red Flags**")
        _redflags = d.get("red_flags") or ""
        if _view_mode == "Bullet Points":
            _bullets = _to_bullets(_redflags)
            if _bullets:
                for _b in _bullets:
                    st.markdown(f"• {_b}")
            else:
                st.markdown("*No red flags recorded.*")
        else:
            st.markdown(_redflags or "*No red flags recorded.*")

    # ── Eval Confidence ───────────────────────────────────────────────────────
    st.divider()
    conf = d.get("eval_confidence") or "—"
    conf_color = {"Tier A": "🟢", "Tier B": "🟡", "Tier C": "🔴"}.get(conf, "⚪")
    scored_at = d.get("scored_at") or ""
    st.caption(
        f"**Eval Confidence:** {conf_color} {conf}   |   "
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
    # T# — visible sort key: 1=ELITE 2=DAY1 3=DAY2 4=DAY3 5=UDFA-P 6=UDFA
    # Click T# column header for correct draft-capital tier sort order
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


# Consensus tier: text color only (no background fill) — distinguishes from APEX Tier
_CONSENSUS_TIER_COLORS = {
    "Elite":    "color: #4ade80; font-weight: 600",   # green text
    "Strong":   "color: #60a5fa; font-weight: 600",   # blue text
    "Playable": "color: #facc15; font-weight: 600",   # yellow text
    "Watch":    "color: #f97316; font-weight: 600",   # orange text
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
        return "background-color: #1a5a1a; color: white"   # green — you rank higher
    if n < 0:
        return "background-color: #6a1a1a; color: white"   # red — you rank lower
    return ""


def _style_apex_tier(val: str) -> str:
    return APEX_TIER_COLORS.get(val, "")


_NUM_COLS = ["Rank", "Score", "Sources", "Coverage", "RAS", "APEX Score"]
_STR_COLS = ["Player", "School", "Pos", "Consensus", "Confidence", "APEX Tier", "Archetype", "Tags", "Snapshot", "⚡ Div", "\u0394 APEX"]

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
| Rank | Consensus rank across 14 active sources (weighted by tier) |
| Score | Weighted consensus score (0–100 scale) |
| Consensus | Consensus tier: Elite / Strong / Playable / Watch |
| Confidence | Source coverage × agreement quality (High / Medium / Low) |
| Sources | Active sources that have ranked this prospect |
| Coverage | Sources covering this prospect out of 14 active |
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
            st.markdown(
                "Tag pills: "
                + " ".join(
                    f'<span style="background:{_TAG_COLOR_MAP.get(t, "#6B7280")};color:white;'
                    f'padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;'
                    f'margin-right:3px">{_TAGS_DISPLAY_MAP.get(t, t)}</span>'
                    for t in _SIDEBAR_TAGS
                    if any(t in _parse_tags(row) for row in tagged_filtered["tag_names"])
                ),
                unsafe_allow_html=True,
            )
            st.markdown("---")
            for _, row in tagged_filtered.sort_values("consensus_rank").iterrows():
                tags = _parse_tags(row["tag_names"])
                pill_html = render_tag_pills(tags)
                rank = int(row["consensus_rank"]) if pd.notna(row["consensus_rank"]) else "?"
                name = row["display_name"]
                pos  = row["position_group"]
                apex = _fmt_apex_composite(row.get("apex_composite"))
                tier = row.get("apex_tier") or ""
                st.markdown(
                    f"**#{rank} {name}** ({pos}) &nbsp; APEX {apex} {tier} &nbsp;&nbsp; {pill_html}",
                    unsafe_allow_html=True,
                )

with tab_apex:
    if apex_scored > 0 and "apex_composite" in df.columns:
        apex_df = df[df["apex_composite"].notna()].copy()

        # Primary sort: auto_apex_rank ascending (rank 1 at top)
        apex_df = apex_df.sort_values(
            ["auto_apex_rank", "apex_composite"],
            ascending=[True, False],
            na_position="last",
        )

        # Build display frame — column order is the board contract
        ab = pd.DataFrame()
        ab["APEX Rank"]  = apex_df["auto_apex_rank"].astype("Int64")
        ab["Player"]     = apex_df["display_name"]
        ab["Pos"]        = apex_df["position_group"]
        ab["School"]     = apex_df["school_canonical"]
        ab["APEX Score"] = apex_df["apex_composite"].apply(_fmt_apex_composite)
        ab["APEX Tier"]  = apex_df["apex_tier"].fillna("")
        ab["Archetype"]  = apex_df["apex_archetype"].fillna("-")

        # Gap column
        if "gap_label" in apex_df.columns:
            ab["Fit"] = apex_df["gap_label"].map(
                lambda v: _GAP_LABEL_DISPLAY_MAP.get(str(v).strip().upper(), str(v)) if pd.notna(v) else "-"
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

        # Ordered prospect_id list — aligns with ab row positions
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
                _render_apex_detail(_detail)
            else:
                st.warning("APEX detail record not found despite apex_composite being set.")
        else:
            _render_consensus_card(_pr)
