"""
DraftOS Big Board — Session 3
Read-only Streamlit UI with divergence flags, APEX rank input, APEX v2.2 scores, and tag display.
No DB writes except through save_apex_rank(). No business logic.

TODO Session 3: Prospect detail expander — click row, show explain_json breakdown,
  source-by-source rank table, confidence reasons, APEX notes field
TODO Session 3: Movers panel — delta_rank from snapshot comparison, top risers/fallers
"""

import pandas as pd
import streamlit as st

from draftos.db.connect import connect
from draftos.queries.apex import save_apex_rank, clear_apex_rank
from draftos.queries.model_outputs import get_big_board

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

    show_apex_only = st.checkbox("Show APEX ranked only (analyst)", value=False)

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
    filtered = filtered[filtered["apex_rank"].notna()]

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


def _fmt_apex_rank(val) -> str:
    """Return rank string or em dash when NULL."""
    try:
        i = int(val)
        return str(i)
    except (TypeError, ValueError):
        return "\u2014"


display = pd.DataFrame()
display["Rank"]       = filtered["consensus_rank"].astype("Int64")
display["Player"]     = filtered["display_name"]
display["School"]     = filtered["school_canonical"]
display["Pos"]        = filtered["position_group"]
display["Score"]      = filtered["consensus_score"].round(1)
display["Tier"]       = filtered["consensus_tier"]
display["Confidence"] = filtered["confidence_band"]
display["Sources"]    = filtered["sources_present"].astype("Int64")
display["Coverage"]   = filtered["coverage_count"].astype("Int64")
display["RAS"]        = filtered["ras_score"].round(1)
display["⚡ Div"]    = filtered.apply(_fmt_div, axis=1)
display["APEX"]       = filtered["apex_rank"].apply(_fmt_apex_rank)
display["\u0394 APEX"] = filtered["apex_delta"].apply(_fmt_apex_delta)

# APEX v2.2 engine columns — NULL-safe: '-' for missing score, '' for missing tier/archetype
if "apex_composite" in filtered.columns:
    display["APEX Score"] = filtered["apex_composite"].apply(_fmt_apex_composite)
    display["APEX Tier"]  = filtered["apex_tier"].fillna("")
    display["Archetype"]  = filtered["apex_archetype"].fillna("-")
    # Sort key — integer, hidden from display
    display["_apex_tier_sort"] = filtered["_apex_tier_sort"]
else:
    display["APEX Score"] = "-"
    display["APEX Tier"]  = ""
    display["Archetype"]  = "-"
    display["_apex_tier_sort"] = 99

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


# Columns to show (exclude hidden sort key)
_display_cols = [c for c in display.columns if c != "_apex_tier_sort"]

styled = (
    display[_display_cols].style
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
| APEX | Analyst-assigned APEX rank override |
| Δ APEX | Rank delta between analyst APEX rank and consensus |
| APEX Score | APEX v2.2 composite score (0–100) |
| APEX Tier | ELITE ≥85 / DAY1 ≥70 / DAY2 ≥55 / DAY3 ≥40 / UDFA |
| Archetype | How this prospect wins — from APEX v2.2 positional library |
| Tags | System-generated signals. See Tag Legend in sidebar. |
""")

# ---------------------------------------------------------------------------
# Render table
# ---------------------------------------------------------------------------
st.dataframe(styled, use_container_width=True, hide_index=True)
st.caption(f"Showing {len(display)} of {total_prospects} prospects")

# ---------------------------------------------------------------------------
# APEX v2.2 tier legend
# ---------------------------------------------------------------------------
st.caption(
    "**APEX v2.2 Tiers:** "
    "ELITE (≥85) | DAY1 (≥70) | DAY2 (≥55) | DAY3 (≥40) | UDFA-P (≥28) | UDFA (<28)   "
    "**Sort tip:** click APEX Tier column header — rows sort ELITE → DAY1 → DAY2 → DAY3 → UDFA "
    "because the hidden _apex_tier_sort key drives correct order."
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
# APEX v2.2 scores panel (if any prospects scored)
# ---------------------------------------------------------------------------
if apex_scored > 0 and "apex_composite" in df.columns:
    st.divider()
    st.subheader(f"APEX v2.2 Engine — {apex_scored} Prospects Scored")

    apex_df = df[df["apex_composite"].notna()].copy()
    apex_df = apex_df.sort_values(["_apex_tier_sort", "apex_composite"], ascending=[True, False])

    apex_display = pd.DataFrame()
    apex_display["Player"]     = apex_df["display_name"]
    apex_display["Pos"]        = apex_df["position_group"]
    apex_display["School"]     = apex_df["school_canonical"]
    apex_display["Archetype"]  = apex_df["apex_archetype"].fillna("-")
    apex_display["APEX Score"] = apex_df["apex_composite"].apply(_fmt_apex_composite)
    apex_display["APEX Tier"]  = apex_df["apex_tier"].fillna("")
    apex_display["Consensus"]  = apex_df["consensus_rank"].astype("Int64")

    apex_styled = (
        apex_display.style
        .map(_style_apex_tier, subset=["APEX Tier"])
    )

    st.dataframe(apex_styled, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# APEX rank input panel (analyst overrides)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Set APEX Rank (Analyst Override)")

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
