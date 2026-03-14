# DraftOS Implementation Spec: RPG Score + PVC Bridge Display
## Session Target: Add Raw Player Grade to Board + Detail Card + Explanatory Copy

**Status:** Ready for Claude Code execution
**Files to modify:** `draftos/queries/model_outputs.py`, `app/app.py`
**Files NOT modified:** No schema changes. No migration needed. `raw_score` already exists in `apex_scores`.
**Prerequisite:** v2.3 migration must be applied first (for FM fields), but RPG display is independent.

---

## PART 1: DATA LAYER — `draftos/queries/model_outputs.py`

### Change: Add `raw_score` to `get_big_board()` query

In the `get_big_board()` function, the SELECT statement that joins `apex_scores` already
pulls `apex_composite`, `apex_tier`, and `matched_archetype`. Add `raw_score` to the
same SELECT:

```sql
-- In the apex_scores LEFT JOIN, add this column:
a.raw_score AS apex_raw_score,
```

Also add `pvc` if it exists (it's in the apex_scores schema):
```sql
a.pvc AS apex_pvc,
```

The returned dict should now include:
- `apex_raw_score` — the pre-PVC raw score (float or None)
- `apex_pvc` — the positional value coefficient applied (float or None)

### Change: Add new v2.3 fields to `get_big_board()` query

While touching this query, also pull the 4 new v2.3 mechanism fields:
```sql
a.failure_mode_primary,
a.failure_mode_secondary,
a.signature_play,
a.translation_risk,
```

Update the function docstring to document these new return keys.

---

## PART 2: BIG BOARD TABLE — `app/app.py`

### Change: Add RPG column to the display DataFrame

After the existing line:
```python
display["APEX Score"] = filtered["apex_composite"].apply(_fmt_apex_composite)
```

Add:
```python
display["RPG"] = filtered["apex_raw_score"].apply(_fmt_apex_composite)  # reuse same formatter
```

**Column position:** Place RPG immediately BEFORE "APEX Score" in the display DataFrame.
The column order should be:
```
... | RAS | ⚡ Div | APEX | Δ APEX | RPG | APEX Score | APEX Tier | Archetype | Tags | ...
```

### Change: Update Column Guide

In the Column Guide expander (`with st.expander("📋 Column Guide", expanded=False):`),
add these two rows to the markdown table. INSERT them in the correct position
(after Δ APEX, before APEX Score):

```
| RPG | Raw Player Grade — talent evaluation independent of position. How good is this player as a football player? |
| APEX Score | APEX composite — RPG adjusted by positional value (PVC). How valuable is this player as a draft asset? |
```

**Replace** the existing APEX Score row description. The old description was:
```
| APEX Score | APEX v2.2 composite score (0–100) |
```

### Change: Add "How Scoring Works" section to Column Guide

After the existing Column Guide markdown table, add this explanatory block
(still inside the same expander):

```python
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
```

---

## PART 3: PROSPECT DETAIL CARD — `app/app.py`

### Change: Redesign the score header block

The current detail card header (visible in screenshots) shows:

```
[POS badge]  Player Name                    APEX_SCORE  [TIER badge]
School · Consensus #N · Confidence: X · RAS: —
```

**Replace** the score display area with a two-score layout. The exact Streamlit code:

```python
# --- Score Header ---
# Left side: player info. Right side: dual score display.
header_left, header_right = st.columns([3, 2])

with header_left:
    # Position badge + name (existing code, keep as-is)
    pos = row["position_group"]
    name = row["display_name"]
    st.markdown(
        f'<span style="background:#2B6CB0;color:white;padding:4px 10px;'
        f'border-radius:6px;font-size:14px;font-weight:700;'
        f'margin-right:8px">{pos}</span>'
        f'<span style="font-size:24px;font-weight:700;color:#E2E8F0">{name}</span>',
        unsafe_allow_html=True,
    )
    # Subheader line
    school = row["school_canonical"]
    cons_rank = row["consensus_rank"]
    conf = row.get("confidence_band", "")
    ras_val = row.get("ras_score")
    ras_str = f"{ras_val:.1f}" if ras_val and not pd.isna(ras_val) else "—"
    st.caption(f"{school} · Consensus #{cons_rank} · Confidence: {conf} · RAS: {ras_str}")

with header_right:
    # Dual score display with PVC bridge
    raw = row.get("apex_raw_score")
    composite = row.get("apex_composite")
    pvc = row.get("apex_pvc")
    tier = row.get("apex_tier", "")

    raw_str = f"{float(raw):.1f}" if raw and not pd.isna(raw) else "—"
    comp_str = f"{float(composite):.1f}" if composite and not pd.isna(composite) else "—"
    pvc_str = f"{float(pvc):.2f}" if pvc and not pd.isna(pvc) else "—"
    pos_label = row["position_group"]

    # Tier badge color
    tier_colors = {
        "ELITE": "#48BB78", "DAY1": "#4299E1", "DAY2": "#ECC94B",
        "DAY3": "#ED8936", "UDFA-P": "#FC8181", "UDFA": "#FC8181",
    }
    tier_bg = tier_colors.get(tier, "#718096")

    st.markdown(
        f"""
        <div style="text-align:right">
            <div style="display:flex;justify-content:flex-end;align-items:baseline;gap:24px">
                <div style="text-align:center">
                    <div style="font-size:36px;font-weight:800;color:#63B3ED">{raw_str}</div>
                    <div style="font-size:11px;color:#A0AEC0;text-transform:uppercase;letter-spacing:1px">Player Grade</div>
                </div>
                <div style="text-align:center">
                    <div style="font-size:36px;font-weight:800;color:#48BB78">{comp_str}</div>
                    <div style="font-size:11px;color:#A0AEC0;text-transform:uppercase;letter-spacing:1px">Draft Value</div>
                </div>
                <div style="text-align:center">
                    <span style="background:{tier_bg};color:white;padding:6px 14px;
                    border-radius:6px;font-size:14px;font-weight:700">{tier}</span>
                </div>
            </div>
            <div style="font-size:12px;color:#718096;margin-top:6px;text-align:right">
                RPG {raw_str} × {pvc_str} ({pos_label}) = APEX {comp_str}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
```

**Visual result:**
```
[EDGE]  David Bailey                     84.3        88.4    [ELITE]
Texas Tech · Consensus #5 ...          Player Grade  Draft Value
                                        RPG 84.3 × 1.00 (EDGE) = APEX 88.4
```

For Jeremiyah Love (RB):
```
[RB]  Jeremiyah Love                     84.3        59.0    [DAY2]
Notre Dame · Consensus #4 ...          Player Grade  Draft Value
                                        RPG 84.3 × 0.70 (RB) = APEX 59.0
```

The PVC bridge line is the key teaching moment. It shows up on every card, and
for premium positions (QB/CB/EDGE) the multiplier is 1.00 — which reinforces
the lesson: "Oh, those positions aren't discounted."

---

## PART 4: FAILURE MODE SECTION ON DETAIL CARD — `app/app.py`

### Change: Add FM section between Archetype card and Draft Capital card

After the Archetype card and BEFORE the Draft Capital card, insert:

```python
# --- Failure Mode Section ---
fm_primary = row.get("failure_mode_primary", "")
fm_secondary = row.get("failure_mode_secondary", "")

if fm_primary and fm_primary != "NONE" and not pd.isna(fm_primary) if isinstance(fm_primary, float) else fm_primary:
    # FM color map
    _FM_COLORS = {
        "FM-1": "#F56565",  # red — Athleticism Mirage
        "FM-2": "#ED8936",  # orange — Scheme Ghost
        "FM-3": "#ECC94B",  # yellow — Processing Wall
        "FM-4": "#F6AD55",  # amber — Body Breakdown
        "FM-5": "#FC8181",  # light red — Motivation Cliff
        "FM-6": "#9F7AEA",  # purple — Role Mismatch
    }
    fm_code = fm_primary[:4] if len(fm_primary) >= 4 else ""
    fm_color = _FM_COLORS.get(fm_code, "#718096")

    fm_secondary_html = ""
    if fm_secondary and fm_secondary != "NONE":
        fm_sec_code = fm_secondary[:4] if len(fm_secondary) >= 4 else ""
        fm_sec_color = _FM_COLORS.get(fm_sec_code, "#718096")
        fm_secondary_html = (
            f'<span style="background:{fm_sec_color};color:white;padding:4px 10px;'
            f'border-radius:6px;font-size:12px;font-weight:600;margin-left:8px">'
            f'{fm_secondary}</span>'
        )

    st.markdown(
        f"""
        <div style="background:#1A202C;border:1px solid #2D3748;border-radius:12px;padding:16px;margin:8px 0">
            <div style="font-size:11px;color:#718096;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
                Failure Mode Risk
            </div>
            <span style="background:{fm_color};color:white;padding:6px 14px;
            border-radius:6px;font-size:13px;font-weight:700">{fm_primary}</span>
            {fm_secondary_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
```

---

## PART 5: MECHANISM SECTION — REPLACES SUMMARY/BULLET POINTS

### Change: Replace the current View Mode toggle with a single mechanism-grade section

**Remove** the current radio button toggle between "Summary" and "Bullet Points".
**Remove** the `_generate_bullets()` function if it exists.

**Replace** with:

```python
# --- Mechanism Section ---
sig_play = row.get("signature_play", "")
strengths = row.get("strengths", "")
red_flags = row.get("red_flags", "")
trans_risk = row.get("translation_risk", "")

# Signature Play (if available from v2.3)
if sig_play and not (isinstance(sig_play, float) and pd.isna(sig_play)):
    st.markdown(
        f"""
        <div style="background:#1A202C;border-left:3px solid #4299E1;padding:12px 16px;
        border-radius:0 8px 8px 0;margin:12px 0">
            <div style="font-size:11px;color:#4299E1;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:4px">Signature Play</div>
            <div style="color:#E2E8F0;font-size:14px">{sig_play}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Strengths + Red Flags side by side
str_col, rf_col = st.columns(2)
with str_col:
    st.markdown("✅ **Strengths**")
    if strengths and not (isinstance(strengths, float) and pd.isna(strengths)):
        st.markdown(f'<div style="color:#E2E8F0;font-size:13px;line-height:1.6">{strengths}</div>',
                    unsafe_allow_html=True)
    else:
        st.caption("Not yet scored with v2.3 prompt.")

with rf_col:
    st.markdown("🚩 **Red Flags**")
    if red_flags and not (isinstance(red_flags, float) and pd.isna(red_flags)):
        st.markdown(f'<div style="color:#E2E8F0;font-size:13px;line-height:1.6">{red_flags}</div>',
                    unsafe_allow_html=True)
    else:
        st.caption("Not yet scored with v2.3 prompt.")

# Translation Risk (if available from v2.3)
if trans_risk and not (isinstance(trans_risk, float) and pd.isna(trans_risk)):
    st.markdown(
        f"""
        <div style="background:#1A202C;border-left:3px solid #F6AD55;padding:12px 16px;
        border-radius:0 8px 8px 0;margin:12px 0">
            <div style="font-size:11px;color:#F6AD55;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:4px">Translation Risk</div>
            <div style="color:#E2E8F0;font-size:14px">{trans_risk}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
```

---

## PART 6: TRANSLATION CONFIDENCE TOOLTIPS

### Change: Update the Archetype card to include gap_label explanation

The current archetype card shows: `EDGE-1 Every-Down Disruptor  Fit: 18.3 pts  ✅ Clean Fit`

After the gap_label badge, add a subtitle line with the explanation:

```python
# Translation confidence explanations (add as constant near top of file)
_GAP_LABEL_EXPLANATIONS = {
    "CLEAN": "Dominant single-archetype match. High translation confidence — this player's NFL role is clear.",
    "SOLID": "Clear primary archetype fit. Good translation confidence with a defined NFL projection.",
    "TWEENER": "Split identity between archetypes. Landing spot determines which version you get.",
    "COMPRESSION": "Elite traits compress multiple archetypes. Positive signal — versatile deployment ceiling.",
    "NO_FIT": "No dominant archetype. Significant role clarity risk — deployment context unclear.",
}
```

In the archetype card rendering, after the gap_label badge, add:
```python
gap_label = row.get("gap_label", "")
gap_explanation = _GAP_LABEL_EXPLANATIONS.get(gap_label, "")
if gap_explanation:
    st.caption(gap_explanation)
```

---

## PART 7: PVC REFERENCE TABLE IN SIDEBAR

### Change: Add PVC reference to the Tag Legend area in sidebar

After the existing Tag Legend expander in the sidebar, add:

```python
with st.sidebar.expander("📊 Positional Value (PVC)", expanded=False):
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
```

---

## VERIFICATION CHECKLIST

After implementation, verify:

- [ ] `get_big_board()` returns `apex_raw_score` and `apex_pvc` for scored prospects
- [ ] Big Board table shows RPG column between Δ APEX and APEX Score
- [ ] Column Guide includes RPG description and updated APEX Score description
- [ ] "How RPG and APEX Score Work Together" section appears in Column Guide
- [ ] Detail card header shows dual scores (Player Grade + Draft Value) with PVC bridge line
- [ ] PVC bridge line shows correct math (e.g., "RPG 84.3 × 0.70 (RB) = APEX 59.0")
- [ ] For premium positions (QB/CB/EDGE), PVC shows 1.00 and both scores are identical
- [ ] Failure Mode section appears on detail card between Archetype and Draft Capital
- [ ] FM chips are color-coded by FM code
- [ ] Signature Play renders with blue left border accent
- [ ] Translation Risk renders with amber left border accent
- [ ] Summary/Bullet Points toggle is REMOVED — replaced by single mechanism section
- [ ] Gap label explanation appears below archetype badge
- [ ] PVC reference table appears in sidebar
- [ ] `python -m scripts.doctor` passes
- [ ] Unscored prospects show "—" for both RPG and APEX Score (no errors on NULL data)
