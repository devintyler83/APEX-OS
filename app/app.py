"""
DraftOS Big Board — Session 31
Read-only Streamlit UI with divergence flags, APEX rank input, APEX v2.2 scores,
tag display, and prospect detail drawer.
No DB writes except through save_apex_rank() and clear_apex_rank(). No business logic.
"""

import pandas as pd
import streamlit as st

from draftos.db.connect import connect
from draftos.queries.apex import save_apex_rank, clear_apex_rank
from draftos.queries.model_outputs import get_big_board, get_prospect_detail

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
# ---------------------------------------------------------------------------
_TAGS_DISPLAY_MAP: dict[str, str] = {
    "Smith Rule"       : "⚠️ Character Cap Active",
    "CRUSH"            : "💎 Priority Target",
    "Walk-On Flag"     : "🏃 Walk-On Origin",
    "Two-Way Premium"  : "🔄 Two-Way Athlete",
    "Schwesinger Rule" : "🚀 Elite Character Bonus",
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
    """Format pipe-delimited tag names as compact emoji text for dataframe cells."""
    if not tag_names_str:
        return ""
    tags = [t.strip() for t in tag_names_str.split("|") if t.strip()]
    return " ".join(_TAG_LABEL_MAP.get(t, t[:3].upper()) for t in tags)


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
    """Format prospect_tags for board display. Filters internal system tags."""
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    parts = [t.strip() for t in str(raw).split(",") if t.strip()]
    parts = [p for p in parts if p not in _INTERNAL_TAG_NAMES]
    mapped = [_TAGS_DISPLAY_MAP.get(p, p) for p in parts]
    return ", ".join(mapped)


display = pd.DataFrame()
display["Rank"]       = filtered["consensus_rank"].astype("Int64")
display["Player"]     = filtered["display_name"]
display["School"]     = filtered["school_canonical"]
display["Pos"]        = filtered["position_group"]
display["Score"]      = filtered["consensus_score"].apply(
    lambda x: round(float(x), 1) if pd.notna(x) else None
)
display["Tier"]       = filtered["consensus_tier"]
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
_STR_COLS = ["Player", "School", "Pos", "Tier", "Confidence", "APEX Tier", "Archetype", "Tags", "Snapshot", "⚡ Div", "\u0394 APEX"]

styled = (
    display.style
    .set_properties(subset=[c for c in _NUM_COLS if c in display.columns],
                    **{"text-align": "right"})
    .set_properties(subset=[c for c in _STR_COLS if c in display.columns],
                    **{"text-align": "left"})
    .map(_style_confidence, subset=["Confidence"])
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
| Tier | Consensus tier: Elite / Strong / Playable / Watch |
| Confidence | Source coverage × agreement quality |
| Sources | Active sources that have ranked this prospect |
| Coverage | Sources covering this prospect out of 14 active |
| RAS | Relative Athletic Score (scale 2.74–10.0) |
| ⚡ Div | Divergence flag — APEX vs consensus rank signal |
| APEX | Auto-derived APEX rank from apex_composite sort order (manual override takes precedence) |
| Δ APEX | consensus_rank − APEX rank (positive = APEX values prospect higher than market) |
| APEX Score | APEX v2.2 composite score (0–100) |
| APEX Tier | ELITE ≥85 / DAY1 ≥70 / DAY2 ≥55 / DAY3 ≥40 / UDFA |
| Archetype | How this prospect wins — from APEX v2.2 positional library |
| Tags | System-generated signals. See Tag Legend in sidebar. |
""")

# ---------------------------------------------------------------------------
# Render table
# ---------------------------------------------------------------------------
st.dataframe(
    styled,
    column_config={
        "Score":      st.column_config.NumberColumn("Score",      format="%.1f"),
        "RAS":        st.column_config.NumberColumn("RAS",        format="%.1f"),
        "APEX Score": st.column_config.NumberColumn("APEX Score", format="%.1f"),
        "APEX Tier":  st.column_config.TextColumn(
                          "APEX Tier",
                          disabled=True,
                          help="Draft capital tier — derived from APEX Score. Sort by APEX Score column.",
                      ),
    },
    use_container_width=True,
    hide_index=True,
)
st.caption(f"Showing {len(display)} of {total_prospects} prospects")

# ---------------------------------------------------------------------------
# APEX v2.2 tier legend
# ---------------------------------------------------------------------------
st.caption(
    "**APEX v2.2 Tiers:** "
    "ELITE (≥85) | DAY1 (≥70) | DAY2 (≥55) | DAY3 (≥40) | UDFA-P (≥28) | UDFA (<28)   "
    "**Sort tip:** click APEX Tier to group by tier (DAY tiers cluster, UDFA sorts last)."
)

# ---------------------------------------------------------------------------
# Tagged prospects pill view (HTML rendering for color)
# ---------------------------------------------------------------------------
tagged_filtered = filtered[filtered["tag_names"] != ""].copy()
if not tagged_filtered.empty:
    with st.expander(f"Tagged prospects on this board ({len(tagged_filtered)})", expanded=False):
        st.markdown(
            "Tag pills: "
            + " ".join(
                f'<span style="background:{_TAG_COLOR_MAP.get(t, "#6B7280")};color:white;'
                f'padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;'
                f'margin-right:3px">{_TAG_LABEL_MAP.get(t, t)}</span>'
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

# ---------------------------------------------------------------------------
# APEX Board — v2.2
# ---------------------------------------------------------------------------
if apex_scored > 0 and "apex_composite" in df.columns:
    st.divider()
    st.subheader(f"APEX Board — v2.2 ({apex_scored} prospects scored)")

    apex_df = df[df["apex_composite"].notna()].copy()

    # Primary sort: auto_apex_rank ascending (rank 1 at top)
    # Fallback: apex_composite descending for any rows where auto_apex_rank
    # is somehow None (should not occur post-Session 32, but defensive)
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

    # Gap column — reuse existing _GAP_LABEL_DISPLAY_MAP
    if "gap_label" in apex_df.columns:
        ab["Gap"] = apex_df["gap_label"].map(
            lambda v: _GAP_LABEL_DISPLAY_MAP.get(str(v).strip().upper(), str(v)) if pd.notna(v) else "-"
        )
    else:
        ab["Gap"] = "-"

    ab["Consensus"]  = apex_df["consensus_rank"].astype("Int64")
    ab["\u0394 APEX"] = apex_df["auto_apex_delta"].apply(_fmt_apex_delta)

    # Eval Confidence
    if "eval_confidence" in apex_df.columns:
        ab["Eval Conf"] = apex_df["eval_confidence"].fillna("-")
    else:
        ab["Eval Conf"] = "-"

    # Tags column — module-level _fmt_tags filters internal system tags
    if "apex_tags" in apex_df.columns:
        ab["Tags"] = apex_df["apex_tags"].apply(_fmt_tags)
    else:
        ab["Tags"] = ""

    ab = ab.reset_index(drop=True)

    _right_cols_apex = ["APEX Rank", "APEX Score", "Consensus", "\u0394 APEX"]
    _left_cols_apex  = ["Player", "Pos", "School", "APEX Tier", "Archetype",
                        "Gap", "Eval Conf", "Tags"]

    apex_styled = (
        ab.style
        .map(_style_apex_tier, subset=["APEX Tier"])
        .map(_style_apex_delta, subset=["\u0394 APEX"])
        .set_properties(subset=_right_cols_apex, **{"text-align": "right"})
        .set_properties(subset=_left_cols_apex,  **{"text-align": "left"})
    )

    st.dataframe(apex_styled, use_container_width=True, hide_index=True)

    st.caption(
        "**APEX v2.2 Tiers:** "
        "ELITE (\u226585) | DAY1 (\u226570) | DAY2 (\u226555) | DAY3 (\u226540) | UDFA-P (\u226528) | UDFA (<28)  "
        "\u00b7 **Gap:** \u2705 Clean Fit (>15) | \U0001f7e2 Solid Fit (8\u201315) | \u26a0\ufe0f Tweener (<8)"
    )

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
# Prospect Detail Drawer
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Prospect Detail")

# Build sorted option list from filtered board (prospects with consensus_rank only)
_sorted_filtered = filtered.dropna(subset=["consensus_rank"]).sort_values("consensus_rank")
_prospect_options = ["— select a prospect —"]
_pid_for_label: dict[str, int] = {}
for _, _row in _sorted_filtered.iterrows():
    _rank = int(_row["consensus_rank"])
    _name = _row["display_name"]
    _pos  = _row["position_group"]
    _label = f"{_rank}. {_name} ({_pos})"
    _prospect_options.append(_label)
    _pid_for_label[_label] = int(_row["prospect_id"])

selected_label = st.selectbox(
    "Select prospect to view full APEX profile",
    options=_prospect_options,
    index=0,
    key="detail_select",
)

if selected_label != "— select a prospect —":
    _pid = _pid_for_label.get(selected_label)
    if _pid is not None:
        detail = _load_detail(_pid)

        if detail is None:
            st.error("Could not load prospect detail. Check DB connection.")
        else:
            # ── PANEL 1: IDENTITY + CONSENSUS ──────────────────────────────
            st.markdown("---")
            p1c1, p1c2, p1c3, p1c4 = st.columns([2, 1, 1, 1])
            with p1c1:
                st.markdown(f"### {detail['display_name']}")
                _school = detail.get("school_canonical") or "Unknown"
                _pos_label = detail.get("position_group") or "—"
                st.caption(f"{_pos_label}  |  {_school}")
            with p1c2:
                _crank = detail.get("consensus_rank")
                st.metric("Consensus Rank", f"#{_crank}" if _crank is not None else "—")
            with p1c3:
                _ctier = detail.get("consensus_tier") or "—"
                st.metric("Consensus Tier", _ctier)
            with p1c4:
                _cband = detail.get("confidence_band") or "—"
                _cov   = detail.get("coverage_count")
                _cov_str = f"{int(_cov)} sources" if _cov is not None else "—"
                st.metric("Confidence", _cband)
                st.caption(f"Coverage: {_cov_str}")

            # ── PANEL 2: APEX PROFILE ───────────────────────────────────────
            st.markdown("---")
            st.markdown("**APEX v2.2 Profile**")
            _apex = detail.get("apex_composite")

            if _apex is None:
                st.info("APEX v2.2: Not yet scored")
            else:
                # Row 1 — 4 key metrics
                _r1c1, _r1c2, _r1c3, _r1c4 = st.columns(4)
                with _r1c1:
                    st.metric("APEX Score", f"{_apex:.1f}")
                with _r1c2:
                    st.metric("Tier", detail.get("apex_tier") or "—")
                with _r1c3:
                    _cap = detail.get("capital_adjusted") or detail.get("capital_base") or "—"
                    st.metric("Capital", _cap)
                with _r1c4:
                    st.metric("Eval Confidence", detail.get("eval_confidence") or "—")

                # Row 2 — Archetype line with human-readable gap label
                _arch        = detail.get("apex_archetype") or "—"
                _gap_display = _render_gap_label(
                    detail.get("gap_label"),
                    detail.get("archetype_gap"),
                )
                if _gap_display:
                    st.markdown(f"**Archetype:** {_arch}  &nbsp;|&nbsp;  {_gap_display}")
                else:
                    st.markdown(f"**Archetype:** {_arch}")

                # Row 3 — Modifier flags (human-readable labels from _TAGS_DISPLAY_MAP)
                if detail.get("schwesinger_full") or detail.get("schwesinger_half"):
                    st.success(_TAGS_DISPLAY_MAP["Schwesinger Rule"])
                if detail.get("smith_rule"):
                    st.error(_TAGS_DISPLAY_MAP["Smith Rule"])

                # Row 4 — Trait vector table (2-column layout)
                st.markdown("**Trait Vectors**")
                _TRAITS = [
                    ("Processing & Instincts", "v_processing"),
                    ("Athleticism",             "v_athleticism"),
                    ("Scheme Versatility",      "v_scheme_vers"),
                    ("Competitive Toughness",   "v_comp_tough"),
                    ("Character",               "v_character"),
                    ("Dev. Trajectory",         "v_dev_traj"),
                    ("Production",              "v_production"),
                    ("Injury & Durability",     "v_injury"),
                ]
                _tc1, _tc2 = st.columns(2)
                for _idx, (_tlabel, _tkey) in enumerate(_TRAITS):
                    _tval = detail.get(_tkey)
                    _tstr = f"{_tval:.1f}" if _tval is not None else "—"
                    # Color based on score
                    if _tval is not None and _tval >= 8.0:
                        _style = "color: #10B981; font-weight: 600"
                    elif _tval is not None and _tval <= 4.0:
                        _style = "color: #EF4444; font-weight: 600"
                    else:
                        _style = ""
                    _html = (
                        f'<span style="{_style}">{_tstr}</span>'
                        if _style else _tstr
                    )
                    _col = _tc1 if _idx % 2 == 0 else _tc2
                    with _col:
                        st.markdown(
                            f"**{_tlabel}:** {_html}",
                            unsafe_allow_html=True,
                        )
                        # Character sub-components
                        if _tkey == "v_character":
                            _c1 = detail.get("c1_public_record")
                            _c2 = detail.get("c2_motivation")
                            _c3 = detail.get("c3_psych_profile")
                            _c1s = f"{_c1:.1f}" if _c1 is not None else "—"
                            _c2s = f"{_c2:.1f}" if _c2 is not None else "—"
                            _c3s = f"{_c3:.1f}" if _c3 is not None else "—"
                            st.caption(f"  C1: {_c1s}  C2: {_c2s}  C3: {_c3s}")

                # Row 5 — Strengths / Red Flags
                _sc1, _sc2 = st.columns(2)
                with _sc1:
                    st.caption("Strengths")
                    st.write(detail.get("strengths") or "—")
                with _sc2:
                    st.caption("Red Flags")
                    st.write(detail.get("red_flags") or "—")

                # Row 6 — Engine tags (rendered with frontend display aliases)
                _etag_list = _render_tags(detail.get("apex_tags") or "")
                if _etag_list:
                    st.caption("Modifier Flags")
                    for _etag in _etag_list:
                        st.markdown(f"`{_etag}`")

                # Row 7 — Override log
                _ov_arch  = detail.get("override_arch")
                _ov_delta = detail.get("override_delta")
                _ov_rat   = detail.get("override_rationale")
                if _ov_arch or _ov_delta or _ov_rat:
                    _ov_d_str = f"{_ov_delta:+.1f}" if _ov_delta is not None else "0"
                    st.warning(
                        f"Override: arch={_ov_arch or '—'}  "
                        f"Δ={_ov_d_str}  "
                        f"Rationale: {_ov_rat or '—'}"
                    )
                    st.caption(f"Scored: {detail.get('scored_at') or '—'}")

            # ── PANEL 3: DIVERGENCE ─────────────────────────────────────────
            st.markdown("---")
            st.markdown("**Divergence Signal**")
            _dflag = detail.get("divergence_flag")
            if _dflag is None:
                st.caption("Divergence: Not computed")
            else:
                _ddelta = detail.get("divergence_rank_delta")
                _dmag   = detail.get("divergence_mag") or ""
                _ddelta_str = f"{_ddelta:+d}" if _ddelta is not None else "—"
                _div_content = f"{_dflag}  |  Rank delta: {_ddelta_str}  |  {_dmag}"
                if _dflag == "APEX_HIGH":
                    st.success(_div_content)
                    st.caption("APEX values this prospect higher than market consensus.")
                elif _dflag == "APEX_LOW_PVC_STRUCTURAL":
                    st.info(_div_content)
                    st.caption("Structural — PVC discount, not actionable.")
                elif _dflag == "APEX_LOW":
                    st.error(_div_content)
                    st.caption("APEX values this prospect lower — monitor.")
                else:
                    st.info(_div_content)

            # ── PANEL 4: RAS ────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("**RAS Measurables**")
            _ras = detail.get("ras_total")
            if _ras is None:
                st.caption("RAS: Not yet measured")
            else:
                st.metric("RAS Total", f"{_ras:.2f}")
                _rc1, _rc2, _rc3, _rc4 = st.columns(4)
                _ras_ath  = detail.get("ras_ath")
                _ras_size = detail.get("ras_size")
                _ras_spd  = detail.get("ras_speed")
                _ras_agi  = detail.get("ras_agility")
                with _rc1:
                    st.metric("Athleticism", f"{_ras_ath:.2f}" if _ras_ath is not None else "—")
                with _rc2:
                    st.metric("Size",        f"{_ras_size:.2f}" if _ras_size is not None else "—")
                with _rc3:
                    st.metric("Speed",       f"{_ras_spd:.2f}"  if _ras_spd  is not None else "—")
                with _rc4:
                    st.metric("Agility",     f"{_ras_agi:.2f}"  if _ras_agi  is not None else "—")
                # Measurables row
                _meas_parts = []
                _hs = detail.get("hand_size")
                _al = detail.get("arm_length")
                _ws = detail.get("wingspan")
                if _hs is not None:
                    _meas_parts.append(f'Hand: {_hs}"')
                if _al is not None:
                    _meas_parts.append(f'Arm: {_al}"')
                if _ws is not None:
                    _meas_parts.append(f'Wingspan: {_ws}"')
                if _meas_parts:
                    st.caption("  ".join(_meas_parts))

            # ── PANEL 5: SOURCE RANKS ───────────────────────────────────────
            st.markdown("---")
            st.markdown("**Source Rankings**")
            _sranks = detail.get("source_ranks", [])
            if not _sranks:
                st.caption("No source rankings found for this prospect.")
            else:
                _sr_df = pd.DataFrame(_sranks)[["source_name", "source_tier", "weight", "overall_rank"]]
                _sr_df.columns = ["Source", "Tier", "Weight", "Rank"]
                st.dataframe(_sr_df, use_container_width=True, hide_index=True)
                st.caption(f"Ranked by {len(_sranks)} of 14 active sources")

            # ── PANEL 6: ACTIVE TAGS ────────────────────────────────────────
            st.markdown("---")
            st.markdown("**Active Tags**")
            _atags = detail.get("active_tags", [])
            if not _atags:
                st.caption("No active tags.")
            else:
                for _tag in _atags:
                    _tcolor = (_tag.get("tag_color") or "").lower()
                    _emoji  = _TAG_EMOJI_MAP.get(_tcolor, "⚪")
                    _tname  = _tag.get("tag_name") or "—"
                    _tnote  = _tag.get("note")
                    if _tnote:
                        st.markdown(f"{_emoji} **{_tname}** — {_tnote}")
                    else:
                        st.markdown(f"{_emoji} **{_tname}**")
