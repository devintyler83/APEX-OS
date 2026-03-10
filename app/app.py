"""
DraftOS Big Board — Session 3
Read-only Streamlit UI with divergence flags, APEX rank input, and APEX v2.2 scores.
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

    # APEX tier filter (only show if there are scored prospects)
    if apex_scored > 0 and "apex_tier" in df.columns:
        apex_tier_options = ["(all)", "ELITE", "APEX", "SOLID", "DEVELOPMENTAL", "ARCHETYPE MISS"]
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
        return ""
    try:
        v = int(val)
    except (TypeError, ValueError):
        return ""
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
display["Score"]      = filtered["consensus_score"].round(1)
display["Tier"]       = filtered["consensus_tier"]
display["Confidence"] = filtered["confidence_band"]
display["Sources"]    = filtered["sources_present"].astype("Int64")
display["Coverage"]   = filtered["coverage_count"].astype("Int64")
display["RAS"]        = filtered["ras_score"].round(1)
display["⚡ Div"]    = filtered.apply(_fmt_div, axis=1)
display["APEX"]       = filtered["apex_rank"].astype("Int64")
display["Δ APEX"]    = filtered["apex_delta"].apply(_fmt_apex_delta)

# APEX v2.2 engine columns — NULL-safe: '-' for missing score, '' for missing tier/archetype
if "apex_composite" in filtered.columns:
    display["APEX Score"] = filtered["apex_composite"].apply(_fmt_apex_composite)
    display["APEX Tier"]  = filtered["apex_tier"].fillna("")
    display["Archetype"]  = filtered["apex_archetype"].fillna("-")
else:
    display["APEX Score"] = "-"
    display["APEX Tier"]  = ""
    display["Archetype"]  = "-"

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

APEX_TIER_COLORS = {
    "ELITE":          "background-color: #b8860b; color: white",   # dark gold
    "APEX":           "background-color: #1a7a1a; color: white",   # green
    "SOLID":          "background-color: #005090; color: white",   # blue
    "DEVELOPMENTAL":  "background-color: #555555; color: white",   # grey
    "ARCHETYPE MISS": "background-color: #7a1a1a; color: white",   # red
}

DIVERGENCE_COLOR = "background-color: #8a5700; color: white"   # amber


def _style_confidence(val: str) -> str:
    return CONFIDENCE_COLORS.get(val, "")


def _style_divergence(val: str) -> str:
    return DIVERGENCE_COLOR if val != "" else ""


def _style_apex_delta(val: str) -> str:
    if val == "":
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


styled = (
    display.style
    .map(_style_confidence, subset=["Confidence"])
    .map(_style_divergence, subset=["⚡ Div"])
    .map(_style_apex_delta, subset=["Δ APEX"])
    .map(_style_apex_tier, subset=["APEX Tier"])
)

# ---------------------------------------------------------------------------
# Render table
# ---------------------------------------------------------------------------
st.dataframe(styled, use_container_width=True, hide_index=True)
st.caption(f"Showing {len(display)} of {total_prospects} prospects")

# ---------------------------------------------------------------------------
# APEX v2.2 scores panel (if any prospects scored)
# ---------------------------------------------------------------------------
if apex_scored > 0 and "apex_composite" in df.columns:
    st.divider()
    st.subheader(f"APEX v2.2 Engine — {apex_scored} Prospects Scored")

    apex_df = df[df["apex_composite"].notna()].copy()
    apex_df = apex_df.sort_values("apex_composite", ascending=False)

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
