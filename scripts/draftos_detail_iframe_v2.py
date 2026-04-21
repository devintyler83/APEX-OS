"""
DraftOS — draftos_detail_iframe_v2.py
Full prospect detail drawer HTML builder.

Replaces _build_detail_html() in app.py with the reference design from
draftos_drawer_reference.html: two-column sticky rail + scrollable content.

Usage in app.py:
    from scripts.draftos_detail_iframe_v2 import build_detail_html, estimate_height
    ...
    html_content = build_detail_html(d, comps_list, rate_info)
    components.html(html_content, height=estimate_height(d, comps_list), scrolling=True)
"""

import html as _html_mod
import math
import re
import sys
import os as _os
from datetime import datetime

# Ensure the scripts directory is on sys.path so archetype_defs can be found
# regardless of which directory app.py is launched from.
_SCRIPTS_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from archetype_defs import ARCHETYPE_DEFS as _ARCHETYPE_DEFS


# ── Helpers ──────────────────────────────────────────────────────────────────

def _e(s) -> str:
    return _html_mod.escape(str(s)) if s is not None else ""


def _safe_float(v, fmt=".1f") -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
        if math.isnan(f):
            return "—"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "—"


def _split_score(val):
    s = _safe_float(val)
    if s == "—":
        return ("—", "")
    parts = s.split(".")
    return (parts[0], parts[1] if len(parts) > 1 else "0")


def _v23_present(v) -> bool:
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


def _smart_split_bullets(text, max_items: int = 3) -> list:
    if not text or not str(text).strip():
        return []
    raw = [line.strip() for line in str(text).split("\n") if line.strip()]
    if not raw:
        return []
    merged = []
    for line in raw:
        if merged and len(line) < 50 and not merged[-1].endswith((".", "!", "?", "…")):
            merged[-1] = merged[-1] + " " + line
        else:
            merged.append(line)
    return merged[:max_items]


def _trait_cls(v: float) -> str:
    if v >= 8.5:
        return "hi"
    if v >= 7.0:
        return "mid"
    if v >= 5.0:
        return "lo"
    return "red"


_FIT_VERDICT_COLORS: dict[str, str] = {
    "Strong fit":             "#5ab87a",   # --green
    "Strong conditional fit": "#8bc34a",
    "Mixed fit":              "#e8a84a",   # --amber
    "Fragile fit":            "#e07b1a",
    "Poor fit":               "#e05c5c",   # --red
}

_FM_DISPLAY_NAMES: dict[str, str] = {
    "FM-1": "Athleticism Mirage",
    "FM-2": "Zone Dependency",
    "FM-3": "Processing Wall",
    "FM-4": "Structural Fragility",
    "FM-5": "Motivation Cliff",
    "FM-6": "Role Mismatch",
}

# ─────────────────────────────────────────────────────────────────────────────
# Interpretation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _si(v: object, fallback: int | None = None) -> int | None:
    """Safe int conversion. Returns fallback on None/failure."""
    if v is None:
        return fallback
    try:
        return int(round(float(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


# deployment_fit and pick_fit: 0-100 graded scores (baselines 60/65). Higher = better. Not probabilities.
def _interp_grade(score: object) -> tuple[str, str]:
    v = _si(score)
    if v is None:                return ("—",            "rgba(255,255,255,0.32)")
    if v >= 85: return ("Excellent",   "#5ab87a")
    if v >= 70: return ("Strong",      "#8bc34a")
    if v >= 55: return ("Conditional", "#e8a84a")
    if v >= 40: return ("Fragile",     "#e07b1a")
    return              ("Poor",       "#e05c5c")


# fm_risk_score: 0-100 severity grade (baseline 50). Higher = more risk. NOT a probability.
def _interp_fm_risk(score: object) -> tuple[str, str]:
    v = _si(score)
    if v is None:                return ("—",          "rgba(255,255,255,0.32)")
    if v < 25: return ("Low",        "#5ab87a")
    if v < 45: return ("Manageable", "#8bc34a")
    if v < 60: return ("Moderate",   "#e8a84a")
    if v < 75: return ("Elevated",   "#e07b1a")
    return              ("Severe",   "#e05c5c")


# confidence: APEX eval tier (A→0.85, B→0.70, C→0.55). Eval depth, not fit probability.
def _interp_confidence(conf: object) -> tuple[str, str]:
    if conf is None:
        return ("—", "rgba(255,255,255,0.32)")
    try:
        v = float(conf)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ("—", "rgba(255,255,255,0.32)")
    if v >= 0.80: return ("High",   "#5ab87a")
    if v >= 0.65: return ("Medium", "#e8a84a")
    return              ("Low",     "#e05c5c")


def _decision_banner(
    verdict: str,
    pick_number: object,
    vr_start: object,
    vr_end: object,
    fm_activated: list[str],
    raw_fm_risk: object,
) -> tuple[str, str]:
    """
    Top-level decision label (6 states) + color.
    Derived from verdict, pick-vs-band alignment, and FM risk.
    Logic:
      - 'Draftable for this team'    → Strong fit, pick not overpriced
      - 'Draftable only at value'    → Strong fit but pick is before value band (overpriced)
      - 'Role-dependent fit'         → Conditional/Mixed with active FMs or scheme dependency
      - 'Risky fit'                  → Fragile fit or Elevated/Severe FM risk
      - 'Avoid at current price'     → Any fit where pick is overpriced relative to value band
      - 'Not a fit for this team'    → Poor fit
    """
    pn = _si(pick_number)
    lo = _si(vr_start)
    hi = _si(vr_end)
    fm_v = _si(raw_fm_risk, 50)

    # Pick overpriced = pick is BEFORE the value band start (team spending too early)
    is_overpriced = (pn is not None and lo is not None and pn < lo)

    if verdict == "Poor fit":
        return ("Not a fit for this team", "#e05c5c")

    if verdict == "Fragile fit":
        if is_overpriced:
            return ("Avoid at current price", "#e07b1a")
        return ("Risky fit", "#e07b1a")

    if verdict == "Mixed fit":
        if is_overpriced:
            return ("Avoid at current price", "#e8a84a")
        if fm_activated:
            return ("Role-dependent fit", "#e8a84a")
        return ("Conditional fit", "#e8a84a")

    if verdict == "Strong conditional fit":
        if is_overpriced:
            return ("Avoid at current price", "#8bc34a")
        if fm_activated:
            return ("Role-dependent fit", "#8bc34a")
        return ("Draftable — conditional", "#8bc34a")

    if verdict == "Strong fit":
        if is_overpriced:
            return ("Draftable only at value", "#8bc34a")
        return ("Draftable for this team", "#5ab87a")

    return ("Fit not evaluated", "rgba(255,255,255,0.32)")


def _fo_summary(
    team_name: str,
    verdict: str,
    role: str,
    vr_start: object,
    vr_end: object,
    pick_number: object,
    fm_activated: list[str],
    fm_suppressed: list[str],
) -> str:
    """
    One-sentence front office summary covering role, value alignment, and primary failure path.
    Derived entirely from available fit fields. Never invents analytics.
    """
    role_lower = (role or "").lower()
    if "day 1 starter" in role_lower:
        role_clause = "offers a clear Day 1 starter path"
    elif "sub-package" in role_lower or "year 2" in role_lower:
        role_clause = "provides a sub-package entry role with a full-time path by Year 2"
    elif "redshirt" in role_lower:
        role_clause = "requires a redshirt runway before meaningful deployment"
    else:
        role_clause = "has a role path contingent on scheme alignment"

    pn = _si(pick_number)
    lo = _si(vr_start)
    hi = _si(vr_end)

    if pn is not None and lo is not None and hi is not None:
        if lo <= pn <= hi:
            value_clause = f"value aligns at Pick {pn}"
        elif pn < lo:
            value_clause = f"Pick {pn} is ahead of the established value window (Picks {lo}-{hi})"
        else:
            value_clause = f"Pick {pn} is a value opportunity below the standard window"
    elif lo is not None and hi is not None:
        value_clause = f"optimal value window is Picks {lo}-{hi}"
    else:
        value_clause = "value window is not yet calibrated"

    if fm_activated:
        fm = fm_activated[0]
        fm_name = _FM_DISPLAY_NAMES.get(fm, fm)
        risk_clause = f"{fm} ({fm_name}) is the primary failure path in this context"
    elif fm_suppressed:
        fm = fm_suppressed[0]
        fm_name = _FM_DISPLAY_NAMES.get(fm, fm)
        risk_clause = f"team context suppresses {fm} ({fm_name}), supporting the outcome floor"
    else:
        risk_clause = "no active failure modes flagged for this pairing"

    return f"{team_name} {role_clause}; {value_clause}; {risk_clause}."


def _fmt_value_range_football(lo: object, hi: object) -> str:
    """
    Convert pick-number range to football-native round language.
    Examples: "Round 1", "Late Round 1 / Round 2", "Round 2", "Round 3"
    Never returns 'None', 'None - None', or empty strings.
    """
    lo_v = _si(lo)
    hi_v = _si(hi)
    if lo_v is None or hi_v is None:
        return "Not calibrated"

    def _r(p: int) -> int:
        if p <= 32:  return 1
        if p <= 64:  return 2
        if p <= 105: return 3
        if p <= 143: return 4
        if p <= 178: return 5
        if p <= 215: return 6
        return 7

    lo_r = _r(lo_v)
    hi_r = _r(hi_v)

    if lo_r == hi_r:
        r = lo_r
        if r == 1:
            if hi_v <= 10:                  return "Top 10"
            if lo_v <= 10:                  return "Round 1"
            if lo_v <= 22:                  return "Round 1 mid-late"
            return "Round 1 late"
        if r == 2:
            if hi_v <= 48:                  return "Round 2 early"
            if lo_v >= 49:                  return "Round 2 late"
            return "Round 2"
        return f"Round {r}"

    if lo_r == 1 and hi_r == 2:
        if lo_v >= 22:                      return "Late Round 1 / Round 2"
        return "Round 1-2"
    if lo_r == 2 and hi_r == 3:
        if lo_v <= 48:                      return "Round 2-3"
        return "Round 2 late / Round 3"
    if lo_r >= 4:
        return f"Day 3 (Round {lo_r}+)"
    return f"Round {lo_r}-{hi_r}"


def _short_role(role: str) -> str:
    """Compact version of role_outcome for chip display."""
    rl = (role or "").lower()
    if "day 1 starter"  in rl: return "Day 1 starter"
    if "sub-package"    in rl: return "Sub-pkg / Year 2"
    if "redshirt"       in rl: return "Redshirt runway"
    if not role:               return "Role not set"
    return role[:20] + ("..." if len(role) > 20 else "")


def _main_risk_chip(fm_activated: list[str], fm_suppressed: list[str]) -> tuple[str, str]:
    """
    Primary risk chip text + color for the decision strip.
    Returns (text, color). Never returns blank or null artifacts.
    """
    if fm_activated:
        fm = fm_activated[0]
        name = _FM_DISPLAY_NAMES.get(fm, fm)
        return (f"{fm} - {name}", "#e05c5c")
    if fm_suppressed:
        fm = fm_suppressed[0]
        name = _FM_DISPLAY_NAMES.get(fm, fm)
        return (f"Mitigated - {name}", "#5ab87a")
    return ("None flagged", "#5ab87a")


def _action_tag(
    verdict: str,
    pick_number: object,
    vr_start: object,
    vr_end: object,
    fm_activated: list[str],
) -> tuple[str, str]:
    """
    Draft recommendation label + color for the Decision strip and Draft Decision block.
    Recommendation set: Target confidently / Target at value / Target only in protected role /
                        Proceed cautiously / Avoid at current price / Do not target for this team
    Derived deterministically from verdict, pick alignment, and activated FMs.
    """
    pn = _si(pick_number)
    lo = _si(vr_start)
    hi = _si(vr_end)
    is_overpriced = (pn is not None and lo is not None and pn < lo)

    if verdict == "Poor fit":
        return ("Do not target for this team", "#e05c5c")

    if verdict == "Fragile fit":
        if is_overpriced:
            return ("Avoid at current price", "#e07b1a")
        return ("Proceed cautiously", "#e07b1a")

    if verdict == "Mixed fit":
        if is_overpriced:
            return ("Avoid at current price", "#e8a84a")
        return ("Proceed cautiously", "#e8a84a")

    if verdict == "Strong conditional fit":
        if is_overpriced:
            return ("Avoid at current price", "#8bc34a")
        if fm_activated:
            return ("Target only in protected role", "#8bc34a")
        return ("Target at value", "#8bc34a")

    if verdict == "Strong fit":
        if is_overpriced:
            return ("Target at value", "#8bc34a")
        if pn is not None and lo is not None and hi is not None and lo <= pn <= hi:
            return ("Target confidently", "#5ab87a")
        return ("Target at value", "#5ab87a")

    return ("Evaluating", "rgba(255,255,255,0.32)")


def _fmt_score(v: object) -> str:
    """Format an integer score 0-100. Returns em-dash only when value is genuinely absent."""
    if v is None:
        return "—"
    try:
        return str(int(round(float(v))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"


def _fmt_confidence(v: object) -> str:
    """Format confidence float as percentage string. Never returns None/nan."""
    if v is None:
        return "—"
    try:
        return f"{int(round(float(v) * 100))}%"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"


def _fmt_pick(v: object) -> str:
    """Format a pick number. Returns 'TBD' instead of null artifacts."""
    if v is None:
        return "TBD"
    try:
        n = int(v)  # type: ignore[arg-type]
        return f"Pick {n}"
    except (TypeError, ValueError):
        return "TBD"


def _fmt_value_range(vr: dict | None) -> str:
    """
    Null-safe best value range formatter.
    Never returns 'None - None', 'None', or empty strings.
    """
    if not vr:
        return "Best value range not set."
    lo = vr.get("start")
    hi = vr.get("end")
    if lo is not None and hi is not None:
        try:
            return f"Picks {int(lo)}–{int(hi)}"
        except (TypeError, ValueError):
            pass
    if lo is not None:
        try:
            return f"Pick {int(lo)} and later"
        except (TypeError, ValueError):
            pass
    if hi is not None:
        try:
            return f"Up to Pick {int(hi)}"
        except (TypeError, ValueError):
            pass
    return "Best value range not set."


def _draft_decision_text(
    verdict: str,
    pick_number: object,
    vr_start: object,
    vr_end: object,
    fm_activated: list[str],
    fm_suppressed: list[str],
) -> str:
    """
    Derive a deterministic, mechanism-grade draft decision sentence.
    Never returns empty string or null artifacts.
    """
    pn = None
    try:
        pn = int(pick_number)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    lo = None
    hi = None
    try:
        lo = int(vr_start)  # type: ignore[arg-type]
        hi = int(vr_end)    # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass

    fm_act_str = ", ".join(fm_activated) if fm_activated else ""
    fm_sup_str = ", ".join(fm_suppressed) if fm_suppressed else ""

    if verdict == "Strong fit":
        if pn is not None and lo is not None and hi is not None and lo <= pn <= hi:
            return f"Draft at {_fmt_pick(pn)}. Value band, deployment path, and positional need are aligned."
        if pn is not None and lo is not None and pn < lo:
            return f"Draft at {_fmt_pick(pn)} if value is justified. Pick is ahead of the standard value window."
        return "Draft. Strong deployment, need, and mechanism alignment across all dimensions."

    if verdict == "Strong conditional fit":
        if fm_act_str:
            return f"Draft conditionally. Scheme fit is valid — monitor {fm_act_str} activation under NFL-speed reads."
        if fm_sup_str:
            return f"Draft conditionally. {fm_sup_str} is suppressed by this context, supporting the floor."
        return "Draft conditionally. Scheme execution is the governing variable — deployment path is real but not guaranteed."

    if verdict == "Mixed fit":
        if pn is not None and hi is not None and pn > hi:
            return f"Wait or pass. {_fmt_pick(pn)} is above the value ceiling. Revisit if available in a later round."
        if fm_act_str:
            return f"Proceed with caution. {fm_act_str} may be activated in this scheme context — downside is real."
        return "Proceed with caution. Fit has structural merit but gaps in deployment or value alignment remain."

    if verdict == "Fragile fit":
        if fm_act_str:
            return f"Avoid unless positional desperation. {fm_act_str} is activated in this context and creates high bust exposure."
        return "Avoid unless no better option exists at the position. Fit is fragile and dependent on favorable conditions."

    # Poor fit
    if fm_act_str:
        return f"Do not draft for this team. {fm_act_str} is active in this context. Deployment, value, or FM exposure disqualifies this pairing."
    return "Do not draft for this team. Deployment mismatch or value misalignment makes this pairing non-viable."


def buildteamfithtml(fit: dict | None) -> str:
    """
    Render the decision-grade Team Fit panel for the detail iframe.

    Field semantics (from team_fitevaluator.py):
      deployment_fit   — 0-100 graded score (baseline 60). How well the team's scheme
                         activates the player's winning mechanism. Higher is better.
      pick_fit         — 0-100 graded score (baseline 65). How well the team's actual
                         pick aligns with the player's APEX value band. Higher is better.
      fm_risk_score    — 0-100 severity score (baseline 50). Whether team context
                         activates or suppresses the player's failure modes. NOT a
                         probability. NOT a trigger percentage. Higher = more risk.
      confidence       — 0.35-0.95, derived from APEX eval tier (A→0.85, B→0.70, C→0.55).
                         Reflects depth/reliability of the APEX model evaluation of this
                         player. NOT probability the fit works.

    Null-safety contract:
      fit=None            → prompt state. Never blank.
      fit._no_context     → team name + 'not yet evaluated'. Never blank.
      All numeric fields  → typed formatters. No Python None/nan/null in HTML.

    Panel hierarchy (decision-grade):
      ① Decision Banner — large label + team/pick + one-sentence FO summary
      ② Decision Strip  — 4 chips: Action / Best Role / Best Value / Main Risk
      ③ Fit Conditions  — Works if / Breaks if (from why_for[0] / why_against[0])
      ④ Why It Works    — full bullet list
      ⑤ Why It Could Fail — full bullet list
      ⑥ FM Risk Detail  — activated/suppressed FM breakdown
      ⑦ Draft Decision  — action tag + decision sentence
      ⑧ Support metrics — deployment/pick_fit/fm_risk/confidence (secondary)
      ⑨ Score guide     — interpretation key
    """
    if not fit:
        return """
        <div class="notes-placeholder">
          <div class="notes-lbl">TEAM FIT</div>
          <div class="notes-body">Select a team from the dropdown to evaluate fit.</div>
        </div>
        """

    # ── No-context state (team selected but not seeded in DB) ──────────────────
    if fit.get("_no_context"):
        team_name = fit.get("team_name") or fit.get("team_id") or "Unknown team"
        team_id   = fit.get("team_id") or ""
        return f"""
        <div class="report-block">
          <div class="report-lbl">TEAM FIT — {team_id}</div>
          <div class="report-val">{team_name}</div>
          <div class="report-sub" style="margin-top:10px; color:var(--amber);">
            Team fit not yet evaluated for this club.
          </div>
          <div class="report-sub" style="margin-top:4px; color:var(--dim);">
            Seed team context via <code>seed_team_draft_context_2026.py</code> to enable
            deterministic fit evaluation across all 32 clubs.
          </div>
        </div>
        """

    # ── Raw fields ──────────────────────────────────────────────────────────────
    team_id     = fit.get("team_id") or ""
    team_name   = fit.get("team_name") or team_id or "Unknown team"
    pick_number = fit.get("pick_number")
    pick_display = _fmt_pick(pick_number)

    raw_deployment = fit.get("deployment_fit")
    raw_pick_fit   = fit.get("pick_fit")
    raw_fm_risk    = fit.get("fm_risk_score")
    raw_confidence = fit.get("confidence")

    # ── Interpretation labels ───────────────────────────────────────────────────
    dep_label, dep_color   = _interp_grade(raw_deployment)
    pf_label,  pf_color    = _interp_grade(raw_pick_fit)
    fm_label,  fm_color    = _interp_fm_risk(raw_fm_risk)
    conf_label, conf_color = _interp_confidence(raw_confidence)

    dep_num  = _fmt_score(raw_deployment)
    pf_num   = _fmt_score(raw_pick_fit)
    fm_num   = _fmt_score(raw_fm_risk)
    conf_pct = _fmt_confidence(raw_confidence)

    # ── Text fields ─────────────────────────────────────────────────────────────
    verdict     = fit.get("verdict") or "Fit not evaluated"
    role        = fit.get("role_outcome") or "No deterministic deployment note available yet."
    vr          = fit.get("best_value_range") or {}
    vr_start    = vr.get("start")
    vr_end      = vr.get("end")
    why_for     = [x for x in (fit.get("why_for")     or []) if x and str(x).strip()]
    why_against = [x for x in (fit.get("why_against") or []) if x and str(x).strip()]
    fm_activated  = [x for x in (fit.get("fm_activated")  or []) if x and str(x).strip()]
    fm_suppressed = [x for x in (fit.get("fm_suppressed") or []) if x and str(x).strip()]

    # ── Decision-grade derived fields ───────────────────────────────────────────
    banner_label, banner_color = _decision_banner(
        verdict, pick_number, vr_start, vr_end, fm_activated, raw_fm_risk
    )
    fo_summary = _fo_summary(
        team_name, verdict, role, vr_start, vr_end, pick_number, fm_activated, fm_suppressed
    )
    action, action_color = _action_tag(
        verdict, pick_number, vr_start, vr_end, fm_activated
    )
    short_role_text              = _short_role(role)
    best_value_football          = _fmt_value_range_football(vr_start, vr_end)
    risk_chip_text, risk_chip_color = _main_risk_chip(fm_activated, fm_suppressed)

    # ── Fit Conditions (first item from why_for / why_against) ─────────────────
    works_if  = why_for[0]  if why_for  else "Deployment path and need alignment hold."
    breaks_if = why_against[0] if why_against else "Scheme execution gaps or FM activation occur."

    # ── Draft Decision sentence ─────────────────────────────────────────────────
    decision_text = _draft_decision_text(
        verdict, pick_number, vr_start, vr_end, fm_activated, fm_suppressed,
    )

    def bullets(items: list[str], empty_msg: str) -> str:
        if not items:
            return f"<div class='report-sub' style='color:var(--dim);font-size:13px;'>{empty_msg}</div>"
        return "".join(f"<div class='report-sub' style='font-size:13px;'>• {x}</div>" for x in items)

    # ── FM Risk Detail block inner HTML ────────────────────────────────────────
    if fm_activated or fm_suppressed:
        fm_lines: list[str] = []
        for fm in fm_activated:
            name = _FM_DISPLAY_NAMES.get(fm, fm)
            fm_lines.append(
                f"<div class='report-sub' style='margin-bottom:3px;'>"
                f"<span style='color:#e05c5c; font-weight:700;'>&#9650; {fm} — {name}</span>"
                f" — activated in this scheme context."
                f"</div>"
            )
        for fm in fm_suppressed:
            name = _FM_DISPLAY_NAMES.get(fm, fm)
            fm_lines.append(
                f"<div class='report-sub' style='margin-bottom:3px;'>"
                f"<span style='color:#5ab87a; font-weight:700;'>&#9660; {fm} — {name}</span>"
                f" — suppressed by this team's deployment structure."
                f"</div>"
            )
        fm_detail_inner = "".join(fm_lines)
    else:
        fm_detail_inner = (
            "<div class='report-sub' style='color:var(--dim);'>"
            "No failure modes activated or suppressed by this team context.</div>"
        )

    return f"""
    <!-- ① DECISION BANNER -->
    <div style="padding:14px 16px 12px; background:var(--ink3);
                border:1px solid {banner_color}40; border-radius:6px; margin-bottom:10px;">
      <div style="font-size:7px; font-weight:700; letter-spacing:0.14em;
                  text-transform:uppercase; color:var(--dim); margin-bottom:6px;">
        Team fit — {team_id} &nbsp;·&nbsp; {pick_display}
      </div>
      <div style="font-size:18px; font-weight:700; color:{banner_color};
                  letter-spacing:-0.01em; line-height:1.2; margin-bottom:8px;">
        {banner_label}
      </div>
      <div style="font-size:13px; color:var(--mid); line-height:1.5;">
        {fo_summary}
      </div>
    </div>

    <!-- ② DECISION STRIP -->
    <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:10px;">
      <!-- Action -->
      <div style="padding:8px 10px; background:var(--ink4); border-radius:4px;
                  border-top:2px solid {action_color};">
        <div style="font-size:7px; font-weight:700; letter-spacing:0.12em;
                    text-transform:uppercase; color:var(--dim); margin-bottom:3px;">
          Decision
        </div>
        <div style="font-size:9px; font-weight:700; color:{action_color}; line-height:1.3;">
          {action}
        </div>
      </div>
      <!-- Best Role -->
      <div style="padding:8px 10px; background:var(--ink4); border-radius:4px;
                  border-top:2px solid var(--cold);">
        <div style="font-size:7px; font-weight:700; letter-spacing:0.12em;
                    text-transform:uppercase; color:var(--dim); margin-bottom:3px;">
          Best role
        </div>
        <div style="font-size:9px; font-weight:700; color:var(--text); line-height:1.3;">
          {short_role_text}
        </div>
      </div>
      <!-- Best Value -->
      <div style="padding:8px 10px; background:var(--ink4); border-radius:4px;
                  border-top:2px solid var(--amber);">
        <div style="font-size:7px; font-weight:700; letter-spacing:0.12em;
                    text-transform:uppercase; color:var(--dim); margin-bottom:3px;">
          Best value
        </div>
        <div style="font-size:9px; font-weight:700; color:var(--amber); line-height:1.3;">
          {best_value_football}
        </div>
      </div>
      <!-- Main Risk -->
      <div style="padding:8px 10px; background:var(--ink4); border-radius:4px;
                  border-top:2px solid {risk_chip_color};">
        <div style="font-size:7px; font-weight:700; letter-spacing:0.12em;
                    text-transform:uppercase; color:var(--dim); margin-bottom:3px;">
          Main risk
        </div>
        <div style="font-size:9px; font-weight:700; color:{risk_chip_color}; line-height:1.3;">
          {risk_chip_text}
        </div>
      </div>
    </div>

    <!-- ③ FIT CONDITIONS -->
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:10px;">
      <div style="padding:8px 10px; background:rgba(90,184,122,0.07);
                  border:1px solid rgba(90,184,122,0.18); border-radius:4px;">
        <div style="font-size:7px; font-weight:700; letter-spacing:0.12em;
                    text-transform:uppercase; color:#5ab87a; margin-bottom:4px;">
          Works if
        </div>
        <div style="font-size:13px; color:var(--mid); line-height:1.4;">{works_if}</div>
      </div>
      <div style="padding:8px 10px; background:rgba(224,92,92,0.07);
                  border:1px solid rgba(224,92,92,0.18); border-radius:4px;">
        <div style="font-size:7px; font-weight:700; letter-spacing:0.12em;
                    text-transform:uppercase; color:#e05c5c; margin-bottom:4px;">
          Breaks if
        </div>
        <div style="font-size:13px; color:var(--mid); line-height:1.4;">{breaks_if}</div>
      </div>
    </div>

    <!-- ④ WHY IT WORKS -->
    <div class="report-block" style="margin-top:10px;">
      <div class="report-lbl">Why it works</div>
      {bullets(why_for, "No affirmative fit factors identified.")}
    </div>

    <!-- ⑤ WHY IT COULD FAIL -->
    <div class="report-block" style="margin-top:10px;">
      <div class="report-lbl">Why it could fail</div>
      {bullets(why_against, "No structural failure risks identified for this pairing.")}
    </div>

    <!-- ⑥ FM RISK DETAIL -->
    <div class="report-block" style="margin-top:10px;">
      <div class="report-lbl">FM risk detail</div>
      {fm_detail_inner}
    </div>

    <!-- ⑦ DRAFT DECISION -->
    <div class="report-block" style="margin-top:10px; border-left:3px solid {action_color};">
      <div class="report-lbl">Draft decision</div>
      <div class="report-val" style="font-size:13px; color:{action_color};">{action}</div>
      <div class="report-sub" style="margin-top:6px;">{decision_text}</div>
    </div>

    <!-- ⑧ SUPPORT METRICS (secondary) -->
    <div style="margin-top:12px; padding:10px 12px; background:var(--ink3);
                border:1px solid var(--wire); border-radius:4px;">
      <div style="font-size:7px; font-weight:700; letter-spacing:0.14em;
                  text-transform:uppercase; color:var(--dim); margin-bottom:7px;">
        Support metrics
      </div>
      <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:6px;">
        <div>
          <div style="font-size:7px; color:var(--dim); margin-bottom:2px;">Deployment</div>
          <div style="font-size:11px; font-weight:700; color:{dep_color};">
            {dep_label}
            <span style="font-size:8px; font-weight:400; color:var(--dim);"> {dep_num}</span>
          </div>
        </div>
        <div>
          <div style="font-size:7px; color:var(--dim); margin-bottom:2px;">Pick fit</div>
          <div style="font-size:11px; font-weight:700; color:{pf_color};">
            {pf_label}
            <span style="font-size:8px; font-weight:400; color:var(--dim);"> {pf_num}</span>
          </div>
        </div>
        <div>
          <div style="font-size:7px; color:var(--dim); margin-bottom:2px;">FM severity</div>
          <div style="font-size:11px; font-weight:700; color:{fm_color};">
            {fm_label}
            <span style="font-size:8px; font-weight:400; color:var(--dim);"> {fm_num}</span>
          </div>
          <div style="font-size:7px; color:var(--dim); font-style:italic; margin-top:1px;">
            not a probability
          </div>
        </div>
        <div>
          <div style="font-size:7px; color:var(--dim); margin-bottom:2px;">Eval confidence</div>
          <div style="font-size:11px; font-weight:700; color:{conf_color};">
            {conf_label}
            <span style="font-size:8px; font-weight:400; color:var(--dim);"> {conf_pct}</span>
          </div>
          <div style="font-size:7px; color:var(--dim); font-style:italic; margin-top:1px;">
            eval depth, not fit %
          </div>
        </div>
      </div>
    </div>

    <!-- ⑨ SCORE GUIDE -->
    <div style="margin-top:8px; padding:8px 12px; background:var(--ink3);
                border:1px solid var(--wire); border-radius:4px;">
      <div style="font-size:7px; font-weight:700; letter-spacing:0.14em;
                  text-transform:uppercase; color:var(--dim); margin-bottom:5px;">
        Score guide
      </div>
      <div style="font-size:8px; color:var(--dim); line-height:1.7;">
        <span style="color:var(--dim); font-weight:600;">Deployment &middot; Pick fit</span>
        &nbsp;&mdash;&nbsp;
        <span style="color:#5ab87a;">Excellent 85+</span>&nbsp;
        <span style="color:#8bc34a;">Strong 70&ndash;84</span>&nbsp;
        <span style="color:#e8a84a;">Conditional 55&ndash;69</span>&nbsp;
        <span style="color:#e07b1a;">Fragile 40&ndash;54</span>&nbsp;
        <span style="color:#e05c5c;">Poor &lt;40</span>
        <br>
        <span style="color:var(--dim); font-weight:600;">FM Risk severity</span>
        &nbsp;&mdash;&nbsp;
        <span style="color:#5ab87a;">Low &lt;25</span>&nbsp;
        <span style="color:#8bc34a;">Manageable 25&ndash;44</span>&nbsp;
        <span style="color:#e8a84a;">Moderate 45&ndash;59</span>&nbsp;
        <span style="color:#e07b1a;">Elevated 60&ndash;74</span>&nbsp;
        <span style="color:#e05c5c;">Severe 75+</span>
        <br>
        <span style="color:var(--dim); font-weight:600;">Eval confidence</span>
        &nbsp;&mdash;&nbsp;
        <span style="color:#5ab87a;">High</span> (&ge;80%)&nbsp;
        <span style="color:#e8a84a;">Medium</span> (65&ndash;79%)&nbsp;
        <span style="color:#e05c5c;">Low</span> (&lt;65%)
        &nbsp;&middot; reflects APEX evaluation depth, not fit probability.
      </div>
    </div>
    """

# ── Compound severity lookup ──────────────────────────────────────────────────

_COMPOUND_SEVERITY: dict[frozenset, str] = {
    frozenset([1, 3]): "Compound FM-1 + FM-3: athleticism mirage with processing deficit. Independent failure paths — either mechanism alone is a bust case. Athletic tools masked the processing limit in college; both compress simultaneously at NFL speed.",
    frozenset([1, 4]): "Compound FM-1 + FM-4: athleticism dependency with structural fragility. The physical tools are both the mechanism and the liability — burst-dependent mechanisms stress exactly the joints and soft tissue most prone to FM-4 activation.",
    frozenset([1, 6]): "Compound FM-1 + FM-6: athleticism mirage with role mismatch. Speed premium priced for a deployment that may not exist at NFL level. If the role narrows and the speed advantage closes, there is no secondary mechanism.",
    frozenset([3, 4]): "Compound FM-3 + FM-4: processing wall with body breakdown risk. Highest severity compound pattern at QB. Two independent paths to catastrophic capital loss — processing failure or structural failure either one ends the outcome.",
    frozenset([3, 5]): "Compound FM-3 + FM-5: processing deficit with motivation contingency. Development trajectory requires both cognitive improvement and sustained drive. Both are uncertain; neither compensates for the other.",
    frozenset([3, 6]): "Compound FM-3 + FM-6: processing wall with role mismatch. Scheme demands that mask processing limits in college may not exist at the NFL level. Mismatch removes the structural support the mechanism depended on.",
    frozenset([4, 5]): "Compound FM-4 + FM-5: structural fragility with motivation cliff. Pre-draft production environment generated both physical output and competitive drive. Injury risk in Year 1–2 is the activation trigger for FM-5.",
    frozenset([1, 5]): "Compound FM-1 + FM-5: athleticism mirage with motivation cliff. Elite combine tools drove both the draft grade and the competitive intensity. When the tools stop generating separation, the motivational engine that ran on proving-ground context has no remaining fuel.",
}


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
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
  --mid:       rgba(255,255,255,0.55);
  --text:      rgba(255,255,255,0.90);
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
  --fm1: #e05c5c; --fm1-dim: rgba(224,92,92,0.15);
  --fm2: #e8a84a; --fm2-dim: rgba(232,168,74,0.15);
  --fm3: #5b9cf0; --fm3-dim: rgba(91,156,240,0.15);
  --fm4: #e05c5c; --fm4-dim: rgba(224,92,92,0.18);
  --fm5: #c47ae0; --fm5-dim: rgba(196,122,224,0.18);
  --fm6: #a57ee0; --fm6-dim: rgba(165,126,224,0.15);
  --prism-1: #7eb4e2;
  --prism-2: #a57ee0;
  --prism-3: #e8a84a;
  --prism-4: #5ab87a;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  height: 100%;
  overflow: hidden;
}

body {
  background: var(--ink);
  font-family: 'Barlow', sans-serif;
  color: var(--text);
  margin: 0;
  padding: 0;
}

/* ── DRAWER SHELL ── */
.drawer {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100vh;
  overflow: hidden;
  border-left: 4px solid transparent;
  border-image: linear-gradient(180deg, var(--prism-1), var(--prism-2), var(--prism-3), var(--prism-4)) 1;
}

/* ── LEFT RAIL ── */
.rail {
  background: var(--ink2);
  border-right: 1px solid var(--wire2);
  padding: 24px 18px 20px 22px;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow-y: auto;
  position: relative;
}

.rail::before {
  content: '';
  position: absolute;
  top: -40px; right: -60px;
  width: 180px; height: 180px;
  background: radial-gradient(ellipse at center, rgba(126,180,226,0.05) 0%, transparent 70%);
  pointer-events: none;
}

/* Position chip */
.pos-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--cold-dim2);
  border: 1px solid rgba(74,144,212,0.5);
  border-radius: 3px;
  padding: 3px 10px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.10em;
  color: var(--cold);
  text-transform: uppercase;
  margin-bottom: 10px;
  width: fit-content;
}
.pos-dot { width: 4px; height: 4px; border-radius: 50%; background: var(--cold); opacity: 0.7; }

/* Player name */
.player-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 48px;
  font-weight: 900;
  line-height: 0.87;
  letter-spacing: -0.02em;
  text-transform: uppercase;
  color: var(--text);
  margin-bottom: 8px;
}

.name-slash {
  width: 32px; height: 2px;
  background: linear-gradient(90deg, var(--cold2), transparent);
  margin-bottom: 10px;
}

/* Meta chips */
.meta-row { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 16px; }
.meta-chip {
  font-size: 9px; font-weight: 600; color: var(--mid);
  background: var(--wire); border: 1px solid var(--wire2);
  border-radius: 3px; padding: 2px 7px; letter-spacing: 0.04em;
}
.meta-chip.hi { color: var(--cold); border-color: rgba(126,180,226,0.28); background: var(--cold-dim); }

/* APEX score window */
.apex-window {
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-radius: 5px;
  padding: 13px 13px 11px;
  margin-bottom: 13px;
  position: relative;
  overflow: hidden;
}
.apex-window::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(126,180,226,0.04) 0%, transparent 40%, rgba(240,192,64,0.04) 100%);
  pointer-events: none;
}

.score-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.score-grid.unified { grid-template-columns: 1fr; }
.score-grid.unified .score-item { text-align: center; }
.score-grid.unified .score-val { font-size: 52px; color: var(--amber); }
.score-grid.unified .score-decimal { font-size: 26px; }
.score-item {}
.score-lbl { font-size: 7px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--dim); margin-bottom: 2px; }
.score-val {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 40px; font-weight: 800; line-height: 0.92;
  color: var(--cold); letter-spacing: -0.01em;
}
.score-val.apex { color: var(--amber); }
.score-decimal { font-size: 20px; font-weight: 600; opacity: 0.65; }

/* Tier badges */
.tier-badge { display: flex; align-items: center; justify-content: space-between; border-radius: 4px; padding: 6px 12px; margin-bottom: 6px; }
.tier-badge.elite  { background: var(--elite-dim); border: 1px solid rgba(240,192,64,0.38); }
.tier-badge.day1   { background: var(--cold-dim);  border: 1px solid rgba(126,180,226,0.32); }
.tier-badge.day2   { background: var(--green-dim); border: 1px solid rgba(90,184,122,0.28); }
.tier-badge.day3   { background: var(--wire);      border: 1px solid var(--wire2); }
.tier-badge.udfa   { background: transparent;      border: 1px solid var(--wire); }

.tier-text { font-family: 'Barlow Condensed', sans-serif; font-size: 15px; font-weight: 900; letter-spacing: 0.12em; text-transform: uppercase; }
.tier-text.elite { color: var(--elite); }
.tier-text.day1  { color: var(--cold); }
.tier-text.day2  { color: var(--green); }
.tier-text.day3  { color: var(--mid); }
.tier-text.udfa  { color: var(--dim); }

.tier-sub { font-size: 7px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.tier-sub.elite { color: rgba(240,192,64,0.50); }
.tier-sub.day1  { color: rgba(126,180,226,0.45); }
.tier-sub.day2  { color: rgba(90,184,122,0.45); }
.tier-sub.day3  { color: var(--dim); }
.tier-sub.udfa  { color: rgba(255,255,255,0.20); }

.formula-line { font-size: 8px; color: var(--dim); font-family: 'Barlow Condensed', sans-serif; letter-spacing: 0.04em; opacity: 0.65; margin-top: 4px; }

/* Trait meters */
.traits-section { margin-bottom: 12px; }
.section-header {
  font-size: 7px; font-weight: 700; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--dim); margin-bottom: 7px;
  display: flex; align-items: center; gap: 6px;
}
.section-header::after { content: ''; flex: 1; height: 1px; background: var(--wire); }

.trait-row { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
.trait-lbl { font-size: 11px; font-weight: 500; color: var(--mid); width: 64px; flex-shrink: 0; }
.trait-track { flex: 1; height: 3px; background: var(--wire); border-radius: 1.5px; overflow: hidden; }
.trait-fill { height: 100%; border-radius: 1.5px; }
.trait-fill.hi  { background: var(--green); }
.trait-fill.mid { background: var(--cold); }
.trait-fill.lo  { background: var(--amber); }
.trait-fill.red { background: var(--red); }
.trait-val { font-family: 'Barlow Condensed', sans-serif; font-size: 13px; font-weight: 700; color: var(--text); width: 22px; text-align: right; }

/* Confidence + Divergence */
.conf-row { display: flex; gap: 6px; margin-bottom: 12px; }
.conf-item { flex: 1; background: var(--ink3); border: 1px solid var(--wire); border-radius: 4px; padding: 7px 9px; }
.conf-lbl { font-size: 7px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--dim); margin-bottom: 2px; font-weight: 700; }
.conf-val { font-family: 'Barlow Condensed', sans-serif; font-size: 12px; font-weight: 700; color: var(--text); }
.conf-val.green { color: var(--green); }
.conf-val.amber { color: var(--amber); }
.conf-val.blue  { color: var(--cold); }
.conf-val.red   { color: var(--red); }
.conf-val.dim   { color: var(--dim); }

/* Capital */
.capital-block { background: var(--ink3); border: 1px solid var(--wire); border-radius: 4px; padding: 9px 11px; margin-bottom: 12px; }
.capital-lbl { font-size: 7px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--dim); margin-bottom: 3px; }
.capital-val { font-family: 'Barlow Condensed', sans-serif; font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 2px; }
.capital-note { font-size: 9px; color: var(--dim); line-height: 1.5; }

/* Archetype fit badge */
.fit-badge-row { margin-bottom: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fit-badge {
  display: inline-flex; align-items: center;
  padding: 2px 8px; border-radius: 3px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
}

/* Watermark */
.watermark { margin-top: auto; padding-top: 10px; border-top: 1px solid var(--wire); display: flex; align-items: flex-end; justify-content: space-between; }
.brand-logo { font-family: 'Barlow Condensed', sans-serif; font-size: 11px; font-weight: 900; letter-spacing: 0.20em; text-transform: uppercase; color: rgba(255,255,255,0.13); }
.watermark-meta { font-size: 7px; color: var(--dim); text-align: right; letter-spacing: 0.04em; line-height: 1.7; }

/* ── RIGHT CONTENT ── */
.content {
  padding: 24px 28px 36px 24px;
  height: 100vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
}

.content::before {
  content: '';
  position: absolute; top: 0; right: 0;
  width: 260px; height: 260px;
  background: conic-gradient(from 200deg at 100% 0%, rgba(232,168,74,0.04) 0deg, rgba(126,180,226,0.04) 60deg, transparent 120deg);
  pointer-events: none;
}

/* Section divider */
.sec-divider {
  font-size: 8px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--dim);
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 12px; margin-top: 4px;
}
.sec-divider::after { content: ''; flex: 1; height: 1px; background: var(--wire); }
.sec-divider.cold  { color: var(--cold); }
.sec-divider.amber { color: var(--amber); }
.sec-divider.green { color: var(--green); }
.sec-divider.red   { color: var(--red); }

.section-gap { height: 20px; }

/* Archetype */
.arch-section { margin-bottom: 18px; }
.arch-header-row {
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 16px; margin-bottom: 12px;
}
.archetype-code { font-family: 'Barlow Condensed', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cold); margin-bottom: 4px; }
.archetype-name { font-family: 'Barlow Condensed', sans-serif; font-size: 32px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.02em; color: var(--amber); line-height: 0.95; }

.rank-ghost {
  position: absolute; right: 28px; top: 0;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 100px; font-weight: 900;
  color: rgba(255,255,255,0.022);
  letter-spacing: -0.04em; line-height: 1;
  pointer-events: none; user-select: none; z-index: 0;
}

.ras-block-right { text-align: right; flex-shrink: 0; }
.ras-lbl { font-size: 7px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--dim); margin-bottom: 2px; }
.ras-val { font-family: 'Barlow Condensed', sans-serif; font-size: 28px; font-weight: 800; color: var(--green); line-height: 1; }

/* Archetype fit row */
.fit-row {
  background: var(--ink3); border: 1px solid var(--wire);
  border-radius: 5px; padding: 10px 12px; margin-bottom: 10px;
}
.fit-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; }
.fit-lbl { font-size: 8px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--dim); }
.fit-score { font-family: 'Barlow Condensed', sans-serif; font-size: 18px; font-weight: 800; }
.fit-score.clean  { color: var(--green); }
.fit-score.solid  { color: var(--cold); }
.fit-score.tweak  { color: var(--amber); }
.fit-score.nofit  { color: var(--red); }
.fit-track { height: 4px; background: var(--wire); border-radius: 2px; overflow: hidden; margin-bottom: 5px; }
.fit-fill { height: 100%; border-radius: 2px; }
.fit-fill.clean { background: var(--green); }
.fit-fill.solid { background: var(--cold); }
.fit-fill.tweak { background: var(--amber); }
.fit-fill.nofit { background: var(--red); }
.fit-breakdown { font-size: 9px; color: var(--dim); letter-spacing: 0.02em; }
.fit-breakdown span { color: var(--mid); }

/* Tags */
.tags-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 4px; }
.htag { display: inline-flex; align-items: center; padding: 3px 9px; border-radius: 3px; font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.htag.crush   { background: rgba(90,184,122,0.12); border: 1px solid rgba(90,184,122,0.30); color: var(--green); }
.htag.tw      { background: rgba(126,180,226,0.10); border: 1px solid rgba(126,180,226,0.28); color: var(--cold); }
.htag.walkOn  { background: rgba(232,168,74,0.10); border: 1px solid rgba(232,168,74,0.28); color: var(--amber); }
.htag.schwes  { background: rgba(126,180,226,0.10); border: 1px solid rgba(126,180,226,0.28); color: var(--cold); }
.htag.neutral { background: var(--wire); border: 1px solid var(--wire2); color: var(--mid); }

/* FM Risk */
.fm-section { margin-bottom: 18px; }
.fm-pip-bar { display: flex; gap: 3px; margin-bottom: 8px; }
.fm-pip { flex: 1; height: 6px; border-radius: 2px; background: var(--wire); }
.fm-pip.p1 { background: var(--fm1); }
.fm-pip.p2 { background: var(--fm2); }
.fm-pip.p3 { background: var(--fm3); }
.fm-pip.p4 { background: var(--fm4); }
.fm-pip.p5 { background: var(--fm5); }
.fm-pip.p6 { background: var(--fm6); }
.fm-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.fm-tag { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 3px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }
.fm-tag.t1 { background: var(--fm1-dim); border: 1px solid rgba(224,92,92,0.30);   color: #f08080; }
.fm-tag.t2 { background: var(--fm2-dim); border: 1px solid rgba(232,168,74,0.30);  color: #f0b85a; }
.fm-tag.t3 { background: var(--fm3-dim); border: 1px solid rgba(91,156,240,0.30);  color: #8ab8f5; }
.fm-tag.t4 { background: var(--fm4-dim); border: 1px solid rgba(224,92,92,0.30);   color: #f08080; }
.fm-tag.t5 { background: var(--fm5-dim); border: 1px solid rgba(196,122,224,0.30); color: #d4a5f5; }
.fm-tag.t6 { background: var(--fm6-dim); border: 1px solid rgba(165,126,224,0.30); color: #c4a5f5; }

/* FM severity note */
.fm-severity {
  background: var(--red-dim);
  border: 1px solid rgba(224,92,92,0.22);
  border-left: 3px solid var(--red);
  border-radius: 0 4px 4px 0;
  padding: 8px 12px;
  font-size: 10px;
  color: rgba(224,92,92,0.85);
  line-height: 1.5;
  margin-bottom: 6px;
}

/* FM definition blocks with prospect-specific failure projection */
.fm-def-block {
  border-radius: 0 5px 5px 0;
  padding: 10px 14px;
  margin-bottom: 8px;
}
.fm-def-name {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 10px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
  margin-bottom: 5px;
}
.fm-def-text {
  font-size: 13px; line-height: 1.6; color: var(--mid);
  margin-bottom: 4px;
}
.fm-def-note {
  font-size: 13px; line-height: 1.55;
  color: var(--text); opacity: 0.75;
  padding-top: 5px;
  border-top: 1px solid rgba(255,255,255,0.06);
  margin-top: 5px;
  font-style: italic;
}

/* Divergence panel */
.divergence-panel {
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-radius: 5px;
  padding: 14px 16px;
  margin-bottom: 18px;
  position: relative; overflow: hidden;
}
.divergence-panel.high    { border-left: 3px solid var(--fm3); }
.divergence-panel.low     { border-left: 3px solid var(--red); }
.divergence-panel.aligned { border-left: 3px solid var(--wire3); }

.div-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.div-delta { font-family: 'Barlow Condensed', sans-serif; font-size: 28px; font-weight: 800; line-height: 1; }
.div-delta.high    { color: var(--fm3); }
.div-delta.low     { color: var(--red); }
.div-delta.aligned { color: var(--mid); }
.div-lbl { font-size: 8px; color: var(--dim); font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 2px; }
.div-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 9px; border-radius: 3px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
}
.div-chip.high    { background: rgba(91,156,240,0.15); border: 1px solid rgba(91,156,240,0.30); color: #8ab8f5; }
.div-chip.low     { background: var(--red-dim); border: 1px solid rgba(224,92,92,0.30); color: #f08080; }
.div-chip.aligned { background: var(--wire); border: 1px solid var(--wire2); color: var(--mid); }
.div-rationale {
  font-size: 13px; line-height: 1.65; color: var(--mid);
  border-top: 1px solid var(--wire); padding-top: 10px;
}
.div-rationale strong { color: var(--text); font-weight: 600; }

/* Signature play */
.sig-play {
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-left: 3px solid var(--cold2);
  border-radius: 0 5px 5px 0;
  padding: 12px 16px;
  margin-bottom: 18px;
}
.sig-lbl { font-size: 8px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--cold); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.sig-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--cold2); }
.sig-text { font-size: 13px; line-height: 1.65; color: var(--mid); font-style: italic; }

/* Strengths + Red Flags */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 18px; }
.panel { background: var(--ink3); border: 1px solid var(--wire); border-radius: 5px; padding: 13px 13px; }
.panel-hdr { font-size: 9px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
.panel-hdr.g { color: var(--green); }
.panel-hdr.r { color: var(--red); }
.ph-ind { width: 6px; height: 6px; border-radius: 1px; flex-shrink: 0; }
.ph-ind.g { background: var(--green); }
.ph-ind.r { background: var(--red); }
.panel-item { font-size: 13px; line-height: 1.55; color: var(--mid); padding: 6px 0; border-top: 1px solid var(--wire); display: flex; gap: 8px; align-items: flex-start; }
.panel-item:first-of-type { border-top: none; }
.pi-dot { width: 3px; height: 3px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.pi-dot.g { background: var(--green); }
.pi-dot.r { background: rgba(224,92,92,0.55); }

/* Translation risk */
.risk-banner {
  background: var(--amber-dim);
  border: 1px solid rgba(232,168,74,0.22);
  border-left: 3px solid var(--amber2);
  border-radius: 0 5px 5px 0;
  padding: 12px 16px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 18px;
}
.risk-icon { font-size: 13px; line-height: 1.4; flex-shrink: 0; color: var(--amber); font-weight: 800; font-family: 'Barlow Condensed', sans-serif; margin-top: 1px; }
.risk-text { font-size: 13px; line-height: 1.65; color: rgba(232,168,74,0.82); }

/* Historical comps */
.comps-section { margin-bottom: 20px; }
.comp-card-full {
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-radius: 5px;
  padding: 15px 16px;
  margin-bottom: 10px;
  position: relative; overflow: hidden;
  display: grid;
  grid-template-columns: 3px 1fr;
  gap: 0 14px;
}
.comp-card-full::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.018) 0%, transparent 50%);
  pointer-events: none;
}
.comp-accent { width: 3px; border-radius: 1.5px; align-self: stretch; }
.comp-accent.hit     { background: linear-gradient(180deg, var(--green), rgba(90,184,122,0.3)); }
.comp-accent.partial { background: linear-gradient(180deg, var(--amber), rgba(232,168,74,0.3)); }
.comp-accent.miss    { background: linear-gradient(180deg, var(--red), rgba(224,92,92,0.3)); }
.comp-type-lbl { font-size: 8px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 3px; }
.comp-type-lbl.hit     { color: var(--green); }
.comp-type-lbl.partial { color: var(--amber); }
.comp-type-lbl.miss    { color: var(--red); }
.comp-name-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.comp-name { font-family: 'Barlow Condensed', sans-serif; font-size: 24px; font-weight: 900; letter-spacing: 0.01em; text-transform: uppercase; color: var(--text); line-height: 1; }
.comp-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 8px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 2px;
}
.comp-badge.hit     { background: var(--green-dim); color: var(--green); border: 1px solid rgba(90,184,122,0.25); }
.comp-badge.partial { background: var(--amber-dim); color: var(--amber); border: 1px solid rgba(232,168,74,0.25); }
.comp-badge.miss    { background: var(--red-dim);   color: var(--red);   border: 1px solid rgba(224,92,92,0.25); }
.comp-badge::before { content: ''; width: 4px; height: 4px; border-radius: 50%; background: currentColor; opacity: 0.8; }
.comp-fm-note { font-size: 9px; color: var(--dim); margin-bottom: 8px; font-style: italic; }
.comp-fm-note span { color: #c4a5f5; font-style: normal; font-weight: 600; }
.comp-desc { font-size: 13px; line-height: 1.65; color: var(--mid); margin-bottom: 8px; }
.comp-year { font-size: 8px; color: rgba(255,255,255,0.20); font-family: 'Barlow Condensed', sans-serif; letter-spacing: 0.06em; }

/* FM Risk Reference Records */
.fm-ref-section { margin-bottom: 20px; }
.fm-ref-card {
  border: 1px solid var(--wire);
  border-left: 3px solid var(--wire3);
  border-radius: 0 5px 5px 0;
  padding: 10px 14px;
  margin-bottom: 8px;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  background: var(--ink3);
}
.fm-ref-card.miss    { border-left-color: var(--red); }
.fm-ref-card.partial { border-left-color: var(--amber); }
.fm-ref-card.hit     { border-left-color: var(--green); }
.fm-ref-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.fm-ref-outcome { font-size: 7px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase; }
.fm-ref-outcome.miss    { color: var(--red); }
.fm-ref-outcome.partial { color: var(--amber); }
.fm-ref-outcome.hit     { color: var(--green); }
.fm-ref-name { font-family: 'Barlow Condensed', sans-serif; font-size: 18px; font-weight: 800; text-transform: uppercase; color: var(--text); line-height: 1; }
.fm-ref-pos-fm { font-size: 9px; color: var(--dim); margin-bottom: 4px; }
.fm-ref-pos-fm span { color: #c4a5f5; }
.fm-ref-pattern { font-size: 12px; color: var(--mid); font-style: italic; line-height: 1.5; margin-bottom: 4px; }
.fm-ref-excerpt { font-size: 12px; color: var(--dim); line-height: 1.5; }
.fm-ref-meta { text-align: right; }
.fm-ref-years { font-size: 8px; color: rgba(255,255,255,0.20); font-family: 'Barlow Condensed', sans-serif; letter-spacing: 0.06em; white-space: nowrap; }
.fm-ref-gen { font-size: 7px; color: var(--dim); white-space: nowrap; margin-top: 2px; }

/* No same-position FM ref data */
.fm-ref-no-data {
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-left: 3px solid var(--wire3);
  border-radius: 0 5px 5px 0;
  padding: 12px 16px;
}
.fm-ref-no-data-lbl {
  font-size: 9px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--dim); margin-bottom: 5px;
}
.fm-ref-no-data-text { font-size: 10px; line-height: 1.6; color: var(--dim); }

/* Card stamp */
.card-stamp {
  position: fixed; bottom: 10px; right: 20px;
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 8px; font-weight: 700; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.08); text-transform: uppercase;
  pointer-events: none; z-index: 100;
}

/* ── Decision Card ─────────────────────────────────────────────────────── */
.decision-card {
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-left: 4px solid var(--cold);
  border-radius: 0 6px 6px 0;
  padding: 16px 18px 12px;
  margin-bottom: 20px;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
}
.dc-zones {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
  margin-bottom: 10px;
}
.dc-call-lbl {
  font-size: 7px; font-weight: 700; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--cold); margin-bottom: 3px;
}
.dc-call-text {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 16px; font-weight: 800; line-height: 1.2;
  color: var(--text); letter-spacing: 0.01em;
  margin-bottom: 8px;
}
.dc-field-lbl {
  font-size: 7px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--dim); margin-bottom: 2px;
}
.dc-field-val {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 8px;
}
.dc-risk-hdr {
  font-size: 7px; font-weight: 700; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--red); margin-bottom: 8px;
}
.dc-risk-note {
  font-size: 13px; line-height: 1.55; color: var(--mid); margin-top: 8px;
}
.dc-strip {
  border-top: 1px solid var(--wire);
  padding-top: 8px;
  display: flex; gap: 16px; align-items: center;
  font-size: 9px; color: var(--dim);
}
.dc-strip-lbl {
  font-size: 7px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--dim); margin-right: 4px;
}
.dc-strip-val { font-family: 'Barlow Condensed', sans-serif; font-size: 13px; font-weight: 700; }
.dc-sep { color: var(--wire3); font-size: 10px; }

/* ── Tab navigation ─────────────────────────────────────────────────────── */
.tab-nav {
  display: flex; gap: 2px; margin-bottom: 16px;
  border-bottom: 1px solid var(--wire2); padding-bottom: 0;
}
.tab-btn {
  font-family: 'Barlow Condensed', sans-serif; font-size: 10px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--dim);
  background: none; border: none; padding: 8px 14px 9px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  transition: color 120ms ease, border-color 120ms ease;
}
.tab-btn:hover { color: var(--mid); }
.tab-btn.active { color: var(--cold); border-bottom-color: var(--cold); }
.tab-pane { display: none; }
.tab-pane.active { display: block; }

/* ── Notes placeholder ──────────────────────────────────────────────────── */
.notes-placeholder {
  background: var(--ink3); border: 1px solid var(--wire);
  border-radius: 5px; padding: 16px;
}
.notes-lbl {
  font-family: 'Barlow Condensed', sans-serif; font-size: 9px; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--dim);
  margin-bottom: 8px;
}
.notes-body { font-size: 11px; line-height: 1.6; color: var(--mid); }

/* ── Report tab ─────────────────────────────────────────────────────────── */
.report-block {
  background: var(--ink3); border: 1px solid var(--wire2);
  border-radius: 5px; padding: 16px 18px; margin-bottom: 12px;
}
.report-lbl {
  font-family: 'Barlow Condensed', sans-serif; font-size: 8px; font-weight: 700;
  letter-spacing: 0.16em; text-transform: uppercase; color: var(--dim);
  margin-bottom: 4px;
}
.report-val {
  font-family: 'Barlow Condensed', sans-serif; font-size: 16px; font-weight: 800;
  color: var(--text); margin-bottom: 2px;
}
.report-sub { font-size: 13px; color: var(--mid); line-height: 1.5; }

/* ── Traits tab ─────────────────────────────────────────────────────────── */
.traits-note {
  font-size: 13px; color: var(--dim); margin-top: 12px;
  padding: 8px 10px; background: var(--ink3);
  border-left: 2px solid var(--wire2); border-radius: 0 3px 3px 0;
}

/* ── Comps empty state ──────────────────────────────────────────────────── */
.comps-empty {
  font-size: 11px; color: var(--dim); padding: 20px 0; text-align: center;
}

/* ── Scout Pad (Notes tab) ──────────────────────────────────────────────── */
.sp-block {
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-radius: 4px;
  padding: 10px 12px;
  margin-bottom: 14px;
}
.sp-kv {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 0;
  border-bottom: 1px solid var(--wire);
}
.sp-kv:last-child { border-bottom: none; }
.sp-k {
  font-size: 7px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dim);
  flex-shrink: 0;
}
.sp-v {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  text-align: right;
  line-height: 1.3;
}
.sp-market-line {
  font-size: 13px;
  line-height: 1.55;
  color: var(--mid);
  font-style: italic;
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px solid var(--wire);
}
.sp-take-block {
  background: rgba(232,168,74,0.06);
  border: 1px solid rgba(232,168,74,0.18);
  border-left: 3px solid var(--amber2);
  border-radius: 0 5px 5px 0;
  padding: 11px 14px;
  margin-bottom: 14px;
}
.sp-take-text {
  font-family: 'Barlow', sans-serif;
  font-size: 13px;
  line-height: 1.65;
  color: rgba(255,255,255,0.78);
  font-style: italic;
}

/* ── Detail Hero Card ── */
.detail-hero-card {
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-radius: 6px;
  padding: 16px 18px;
  margin-bottom: 14px;
}

/* ── Detail Section ── */
.detail-section {
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-radius: 5px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.detail-section-header {
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--wire);
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ── Stat Chips (Summary tab 3-chip row) ── */
.stat-chip-row { display: flex; gap: 8px; margin-bottom: 14px; }
.detail-stat-chip {
  flex: 1;
  padding: 10px 12px;
  background: var(--ink4);
  border: 1px solid var(--wire2);
  border-radius: 5px;
}
.detail-stat-chip-lbl {
  font-size: 7px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--dim); margin-bottom: 4px;
}
.detail-stat-chip-val {
  font-family: 'Barlow Condensed', sans-serif;
  font-size: 15px; font-weight: 800; line-height: 1.2;
}

/* ── Insight Card ── */
.insight-card {
  background: var(--ink3);
  border: 1px solid var(--wire2);
  border-left: 3px solid var(--cold2);
  border-radius: 0 5px 5px 0;
  padding: 12px 16px;
  margin-bottom: 10px;
}
.insight-card.amber { border-left-color: var(--amber2); }
.insight-card.green { border-left-color: var(--green); }
.insight-card.red   { border-left-color: var(--red); }
.insight-hdr {
  font-size: 8px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--dim); margin-bottom: 6px;
}
.insight-body {
  font-size: 13px; line-height: 1.65; color: var(--mid);
}

/* ── Insight Split (works-if / breaks-if) ── */
.insight-split { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
.insight-split-cell { padding: 10px 12px; border-radius: 5px; }
.insight-split-cell.green {
  background: rgba(90,184,122,0.07);
  border: 1px solid rgba(90,184,122,0.20);
}
.insight-split-cell.red {
  background: rgba(224,92,92,0.07);
  border: 1px solid rgba(224,92,92,0.20);
}
.insight-split-lbl {
  font-size: 7px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; margin-bottom: 5px;
}
.insight-split-lbl.green { color: var(--green); }
.insight-split-lbl.red   { color: var(--red); }
.insight-split-body { font-size: 13px; color: var(--mid); line-height: 1.5; }

/* ── Support Info ── */
.support-info {
  background: var(--ink3);
  border: 1px solid var(--wire);
  border-radius: 4px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.support-info-lbl {
  font-size: 7px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--dim); margin-bottom: 6px;
}
.support-info-body { font-size: 13px; color: var(--mid); line-height: 1.55; }
"""


# ── HTML fragment builders ────────────────────────────────────────────────────

def _build_trait(label: str, val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)) or val == 0.0:
        return (
            f'<div class="trait-row">'
            f'<span class="trait-lbl">{label}</span>'
            f'<div class="trait-track"></div>'
            f'<span class="trait-val" style="color:var(--dim)">—</span>'
            f'</div>'
        )
    try:
        v = float(val)
    except (TypeError, ValueError):
        v = 0.0
    pct = min(max(v / 10.0 * 100, 0), 100)
    cls = _trait_cls(v)
    return (
        f'<div class="trait-row">'
        f'<span class="trait-lbl">{label}</span>'
        f'<div class="trait-track"><div class="trait-fill {cls}" style="width:{pct:.0f}%"></div></div>'
        f'<span class="trait-val">{v:.1f}</span>'
        f'</div>'
    )


_FM_DEFINITIONS = {
    1: ("FM-1: Athleticism Mirage",
        "Physical tools produce college dominance that disappears when the athletic advantage closes at NFL speed. "
        "The mechanism was the athleticism itself — not skill, technique, or processing. "
        "When NFL athletes close the gap, there is nothing behind the burst or length to sustain production."),
    2: ("FM-2: Scheme Ghost",
        "Production is scheme-dependent. The player requires a specific structural context — "
        "a coverage family, alignment concept, or manufactured advantage — that may not exist at the NFL level. "
        "The player is not bad; they are specifically good in a way that may not transfer."),
    3: ("FM-3: Processing Wall",
        "Processing speed or anticipatory recognition is insufficient to operate at NFL decision velocity. "
        "Physical tools execute correctly but the cognitive trigger arrives too late. "
        "College production was enabled by athletic advantages that compressed the processing requirement — "
        "those advantages close at NFL speed."),
    4: ("FM-4: Body Breakdown",
        "Physical structure — joints, soft tissue, or availability — fails to sustain the mechanism that justified capital. "
        "The mechanism was real. The body could not deliver it at NFL volume. "
        "FM-4 is mechanism-independent: even the best-built archetype can be destroyed by structural failure."),
    5: ("FM-5: Motivation Cliff",
        "Competitive drive degrades after draft capital is secured. Production was real pre-draft. "
        "The engine that produced it was contingent on proving-ground context — "
        "combine preparation, draft positioning, external pressure. That context disappears post-signing."),
    6: ("FM-6: Role Mismatch",
        "The NFL deployment context does not match the mechanism that produced college value. "
        "The player is real. The production was real. The job they are asked to do at the NFL level "
        "is not the job their mechanism can execute — scheme, alignment, or role requirements exceed the mechanism range."),
}


def _build_fm_section(fm_codes: set, fm_labels: list, prospect: dict | None = None) -> str:
    if not fm_codes:
        return ""

    pips = "".join(
        f'<div class="fm-pip{" p" + str(i) if i in fm_codes else ""}"></div>'
        for i in range(1, 7)
    )

    tags = ""
    for lbl in fm_labels:
        m = re.search(r"FM-(\d+)", str(lbl))
        n = m.group(1) if m else "1"
        tags += f'<span class="fm-tag t{n}">{_e(lbl)}</span>'

    # Compound severity
    severity_html = ""
    if len(fm_codes) == 2:
        key = frozenset(fm_codes)
        compound = _COMPOUND_SEVERITY.get(
            key,
            f"Compound FM-{min(fm_codes)} + FM-{max(fm_codes)}: independent failure paths — "
            f"evaluate each mechanism separately. Either alone is a capital risk pattern."
        )
        severity_html = f'<div class="fm-severity">{_e(compound)}</div>'

    # Per-FM definition blocks with prospect-specific failure projection
    _FC = {1:"fm1",2:"fm2",3:"fm3",4:"fm4",5:"fm5",6:"fm6"}
    def_blocks = ""
    for code in sorted(fm_codes):
        fm_name, fm_def = _FM_DEFINITIONS.get(code, (f"FM-{code}", ""))
        fc = _FC.get(code, "fm1")
        failure_note = ""
        if prospect:
            try:
                pos      = (prospect.get("position_group") or "").upper()
                proc     = prospect.get("v_processing")
                ath      = prospect.get("v_athleticism")
                char     = prospect.get("v_character")
                inj      = prospect.get("v_injury")
                sch      = prospect.get("v_scheme_vers")
                arch_raw = prospect.get("matched_archetype") or prospect.get("apex_archetype") or ""
                name_p   = prospect.get("display_name") or "This prospect"
                if code == 1 and ath is not None:
                    av = float(ath)
                    if av >= 8.5:
                        failure_note = (f"Athletic grade {av:.1f} is elite. The risk: if NFL athletes neutralize "
                                        f"the physical gap, there is no confirmed secondary win mechanism to fall back on.")
                    else:
                        failure_note = (f"Athletic grade {av:.1f} is above average but not dominant. "
                                        f"At NFL speed the advantage compresses — production depends on technique holding.")
                elif code == 2 and sch is not None:
                    sv = float(sch)
                    if sv < 6.0:
                        failure_note = (f"Scheme Versatility grades {sv:.1f} — below viable threshold. "
                                        f"Landing spot is the entire evaluation. A mismatched scheme deployment ends this profile.")
                    else:
                        failure_note = (f"Scheme Versatility grades {sv:.1f}. Acceptable range, but FM-2 risk is structural: "
                                        f"if the deployment context narrows post-draft, production disappears with it.")
                elif code == 3 and proc is not None:
                    pv = float(proc)
                    if pv < 6.5:
                        failure_note = (f"Processing grades {pv:.1f} — this is a hard FM-3 signal. "
                                        f"Cognitive trigger speed is below NFL threshold at {pos}. "
                                        f"Physical tools will not compensate when decision windows compress.")
                    else:
                        failure_note = (f"Processing grades {pv:.1f}. Below elite threshold for {pos}. "
                                        f"NFL pre-snap complexity will pressure this ceiling in Year 1–2.")
                elif code == 4 and inj is not None:
                    iv = float(inj)
                    if iv < 6.0:
                        failure_note = (f"Durability grades {iv:.1f} — structural flag present. "
                                        f"Medical scrutiny required before capital commitment. FM-4 at this level has a high activation rate.")
                    else:
                        failure_note = (f"Durability grades {iv:.1f}. No hard structural flag in trait data, "
                                        f"but FM-4 activates independent of pre-draft indicators — availability history must be reviewed.")
                elif code == 5 and char is not None:
                    cv = float(char)
                    if cv < 6.0:
                        failure_note = (f"Character grades {cv:.1f} — below threshold. "
                                        f"Competitive drive contingency is a live risk at this level. "
                                        f"FM-5 probability is elevated; Year 2–3 production is the real evaluation.")
                    else:
                        failure_note = (f"Character grades {cv:.1f}. Acceptable pre-draft signal, "
                                        f"but FM-5 is behavioral and does not fully surface in scouting data. "
                                        f"Track closely through rookie year.")
                elif code == 6:
                    failure_note = (f"FM-6 at {pos} is a scheme-alignment risk. "
                                    f"The mechanism in {arch_raw} may not survive deployment into a mismatched role. "
                                    f"Confirm scheme fit before committing capital.")
            except (TypeError, ValueError):
                pass

        def_blocks += (
            f'<div class="fm-def-block" style="border-left:3px solid var(--{fc});background:var(--{fc}-dim);">'
            f'<div class="fm-def-name" style="color:var(--{fc});">{_e(fm_name)}</div>'
            f'<div class="fm-def-text">{_e(fm_def)}</div>'
            + (f'<div class="fm-def-note">{_e(failure_note)}</div>' if failure_note else "")
            + '</div>'
        )

    return (
        f'<div class="fm-section">'
        f'<div class="sec-divider red">Failure Mode Risk</div>'
        f'<div class="fm-pip-bar">{pips}</div>'
        f'<div class="fm-tags">{tags}</div>'
        f'{severity_html}'
        f'<div style="height:10px"></div>'
        f'{def_blocks}'
        f'</div>'
    )


def _build_divergence_panel(div_delta, narrative: str | None) -> str:
    if div_delta is None:
        return ""
    try:
        dd = int(float(div_delta))
    except (TypeError, ValueError):
        return ""

    if abs(dd) < 3:
        panel_cls  = "aligned"
        delta_cls  = "aligned"
        delta_str  = f"{dd:+d}" if dd != 0 else "0"
        chip_cls   = "aligned"
        chip_label = "Aligned"
    elif dd > 0:
        panel_cls  = "high"
        delta_cls  = "high"
        delta_str  = f"+{dd}"
        chip_cls   = "high"
        chip_label = "▲ Above Consensus"
    else:
        panel_cls  = "low"
        delta_cls  = "low"
        delta_str  = str(dd)
        chip_cls   = "low"
        chip_label = "▼ Below Consensus"

    rationale_html = ""
    if narrative:
        rationale_html = f'<div class="div-rationale">{_e(narrative)}</div>'
    elif abs(dd) >= 3:
        # Synthesize rationale from direction and magnitude when DB field is null
        if dd > 0:
            if dd >= 15:
                synth = (f"APEX rates this prospect {dd} ranks above consensus — a major divergence. "
                         f"APEX is weighting positional value and mechanism strength more heavily than the market. "
                         f"Consensus may be undervaluing the archetype or over-discounting a correctable weakness. "
                         f"The divergence is worth investigating before the board locks.")
            else:
                synth = (f"APEX rates this prospect {dd} ranks above consensus. "
                         f"The gap reflects APEX weighting positional scarcity and mechanism quality "
                         f"above the market's current read. Monitor for late consensus movement toward this range.")
        else:
            adelta = abs(dd)
            if adelta >= 15:
                synth = (f"APEX rates this prospect {adelta} ranks below consensus — a major caution signal. "
                         f"APEX has identified a mechanism risk, scheme dependency, or FM profile "
                         f"that the market has not priced in. This divergence warrants direct scrutiny before draft weekend.")
            else:
                synth = (f"APEX rates this prospect {adelta} ranks below consensus. "
                         f"The gap reflects APEX discounting a component of the market grade — "
                         f"likely a FM risk, scheme fit concern, or positional value adjustment. "
                         f"Review the FM section above for the specific mechanism.")
        rationale_html = f'<div class="div-rationale">{_e(synth)}</div>'

    return (
        f'<div class="divergence-panel {panel_cls}">'
        f'<div class="div-header">'
        f'<div><div class="div-delta {delta_cls}">{delta_str}</div>'
        f'<div class="div-lbl">APEX rank vs consensus rank</div></div>'
        f'<div style="margin-left:auto"><span class="div-chip {chip_cls}">{chip_label}</span></div>'
        f'</div>'
        f'{rationale_html}'
        f'</div>'
    )


def _build_comps_html(comps: list, archetype_raw: str, rate) -> str:
    if not comps:
        return ""

    OC = {"HIT": "hit", "PARTIAL": "partial", "MISS": "miss"}
    IC = {"HIT": "✓", "PARTIAL": "⚠", "MISS": "✗"}
    LB = {"HIT": "Archetype Ceiling", "PARTIAL": "FM Risk Comp", "MISS": "Miss Pattern"}

    # Translation rate % intentionally suppressed — small sample sizes (N of M)
    # make the percentage statistically invalid and misleading to evaluators.

    hit_count = 0
    cards = ""
    for c in comps[:2]:
        oc      = c.get("translation_outcome", "MISS")
        cls     = OC.get(oc, "miss")
        icon    = IC.get(oc, "")
        # First HIT = Archetype Ceiling (the definitive ceiling case)
        # Subsequent HITs = Archetype Comp (additional positive evidence)
        if oc == "HIT":
            lbl = "Archetype Ceiling" if hit_count == 0 else "Archetype Comp"
            hit_count += 1
        else:
            lbl = LB.get(oc, "")
        fm_note = ""
        fmc     = c.get("fm_code", "")
        if fmc and oc in ("PARTIAL", "MISS"):
            codes = re.findall(r"FM-\d+", str(fmc))
            if codes:
                fm_note = (
                    f'<div class="comp-fm-note">FM pattern: '
                    f'<span>{_e(", ".join(codes))}</span></div>'
                )
        cards += (
            f'<div class="comp-card-full">'
            f'<div class="comp-accent {cls}"></div>'
            f'<div class="comp-body">'
            f'<div class="comp-type-lbl {cls}">{icon} {_e(lbl)}</div>'
            f'<div class="comp-name-row">'
            f'<span class="comp-name">{_e(c.get("player_name", ""))}</span>'
            f'<span class="comp-badge {cls}">{_e(oc.title())}</span>'
            f'</div>'
            f'{fm_note}'
            f'<div class="comp-desc">{_e(c.get("outcome_summary", ""))}</div>'
            f'<div class="comp-year">{_e(c.get("era_bracket", ""))}</div>'
            f'</div>'
            f'</div>'
        )

    return (
        f'<div class="comps-section">'
        f'<div class="sec-divider">Historical Comps</div>'
        f'{cards}'
        f'</div>'
    )


def _build_fm_ref_html(fm_ref_comps: list, fm_labels: list | None = None, pos: str = "") -> str:
    if not fm_ref_comps:
        # No same-position historical bust comps in DB — explain rather than show wrong-position data
        fm_str = ", ".join(fm_labels) if fm_labels else "this failure mode"
        pos_str = f" at {pos}" if pos else ""
        return (
            f'<div class="fm-ref-section">'
            f'<div class="sec-divider red">FM Risk Reference</div>'
            f'<div class="fm-ref-no-data">'
            f'<div class="fm-ref-no-data-lbl">No same-position reference records</div>'
            f'<div class="fm-ref-no-data-text">'
            f'Historical bust comps for {_e(fm_str)}{_e(pos_str)} are not yet available in the '
            f'reference database. Evaluate the failure mechanism directly using the FM definition above.'
            f'</div>'
            f'</div>'
            f'</div>'
        )

    OC = {"HIT": "hit", "PARTIAL": "partial", "MISS": "miss"}
    cards = ""
    for c in fm_ref_comps[:4]:
        oc  = str(c.get("translation_outcome", "MISS")).upper()
        cls = OC.get(oc, "miss")
        fm_str = c.get("fm_code", "")
        pos_str = c.get("position_group", "")
        pos_fm = f"{_e(pos_str)} · <span>{_e(fm_str)}</span>" if fm_str else _e(pos_str)
        cards += (
            f'<div class="fm-ref-card {cls}">'
            f'<div>'
            f'<div class="fm-ref-header"><span class="fm-ref-outcome {cls}">{_e(oc)}</span></div>'
            f'<div class="fm-ref-name">{_e(c.get("player_name", ""))}</div>'
            f'<div class="fm-ref-pos-fm">{pos_fm}</div>'
            f'<div class="fm-ref-pattern">{_e(c.get("fm_mechanism", ""))}</div>'
            f'<div class="fm-ref-excerpt">{_e(c.get("outcome_summary", ""))}</div>'
            f'</div>'
            f'<div class="fm-ref-meta">'
            f'<div class="fm-ref-years">{_e(c.get("era_bracket", ""))}</div>'
            f'</div>'
            f'</div>'
        )

    return (
        f'<div class="fm-ref-section">'
        f'<div class="sec-divider red">FM Risk Reference</div>'
        f'{cards}'
        f'</div>'
    )


def _build_draft_day_take(
    pos: str,
    tier: str,
    arch_label: str,
    conf_raw,
    fm_codes: set,
    div_delta,
) -> str | None:
    """
    Produce a deterministic one-sentence draft-room take.
    Returns None if essential data is missing.
    """
    if not tier or tier == "—":
        return None

    _TIER_WORD = {
        "ELITE": "Elite", "DAY1": "Day 1", "DAY2": "Day 2",
        "DAY3": "Day 3", "UDFA-P": "Priority UDFA", "UDFA": "UDFA",
    }
    tier_word = _TIER_WORD.get(tier, tier)

    pos_upper = (pos or "").upper()

    # Divergence phrase
    div_phrase = ""
    try:
        if div_delta is not None:
            dd = int(float(div_delta))
            if dd >= 10:
                div_phrase = " with real APEX surplus"
            elif dd >= 5:
                div_phrase = " with positive APEX signal"
            elif dd <= -10:
                div_phrase = " — market ranks him higher than APEX"
            elif dd <= -5:
                div_phrase = " — mild APEX discount"
    except (TypeError, ValueError):
        pass

    # Confidence phrase
    _CONF_PHRASE = {
        "A": "Tier A confidence", "Tier A": "Tier A confidence",
        "B": "Tier B confidence", "Tier B": "Tier B confidence",
        "C": "Tier C confidence", "Tier C": "Tier C confidence",
    }
    conf_phrase = _CONF_PHRASE.get(str(conf_raw).strip(), "")

    # FM phrase
    fm_phrase = ""
    if fm_codes:
        sorted_fms = sorted(fm_codes)
        fm_phrase = ", ".join(f"FM-{c} watch" for c in sorted_fms[:2])

    # Arch role (first 3 words max to stay terse)
    arch_short = ""
    if arch_label:
        words = arch_label.strip().split()
        arch_short = " ".join(words[:4]) if len(words) > 4 else arch_label.strip()

    # Assemble: "[tier_word] [pos][div_phrase]; [arch_short], [conf_phrase][, fm_phrase]."
    mid_parts = [p for p in [arch_short, conf_phrase, fm_phrase] if p]
    mid = ", ".join(mid_parts)
    sentence = f"{tier_word} {pos_upper}{div_phrase}"
    if mid:
        sentence += f"; {mid}"
    sentence += "."
    return sentence


def resolve_draft_day_take(
    pid: int,
    archetype_overrides: dict | None,
    conn,
) -> str:
    """
    Canonical read for Draft Day Take.

    Priority:
      1) ARCHETYPE_OVERRIDES[pid]['draft_day_take']
      2) notes table, latest note_type='draft_day_take'
      3) _build_draft_day_take(...) generator from APEX fields

    Returns a plain string (may be empty but never None).
    """
    # 1) in-memory override
    if archetype_overrides is not None:
        ov = archetype_overrides.get(pid)
        if ov:
            val = ov.get("draft_day_take")
            if isinstance(val, str) and val.strip():
                return val.strip()

    # 2) notes table lookup — direct SQL (no external module dependency)
    try:
        cur = conn.cursor()
        note_row = cur.execute(
            """
            SELECT note FROM notes
            WHERE prospect_id = ? AND note_type = 'draft_day_take'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (pid,),
        ).fetchone()
        if note_row:
            note_text = (note_row[0] or "").strip()
            if note_text:
                return note_text
    except Exception:
        pass

    # 3) generator fallback — join prospects + divergence_flags for required fields
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT
            p.position_group,
            a.apex_tier,
            a.matched_archetype,
            a.eval_confidence,
            a.failure_mode_primary,
            a.failure_mode_secondary,
            df.divergence_rank_delta,
            df.divergence_rank_delta
        FROM apex_scores a
        JOIN prospects p ON p.prospect_id = a.prospect_id
        LEFT JOIN divergence_flags df
               ON df.prospect_id = a.prospect_id AND df.season_id = a.season_id
        WHERE a.prospect_id = ? AND a.season_id = 1
        """,
        (pid,),
    ).fetchone()

    if not row:
        return ""

    (
        pos,
        tier,
        arch_label,
        conf_raw,
        fm_primary,
        fm_secondary,
        div_delta,
        auto_delta,
    ) = row

    fm_codes: set[int] = set()
    for fm in (fm_primary, fm_secondary):
        if not fm:
            continue
        m = re.search(r"FM-(\d+)", str(fm))
        if m:
            try:
                fm_codes.add(int(m.group(1)))
            except ValueError:
                pass

    # use whichever divergence field is populated, same as _build_scout_pad
    div_val = div_delta if div_delta is not None else auto_delta

    sentence = _build_draft_day_take(
        pos=pos or "",
        tier=(tier or "").strip().upper(),
        arch_label=arch_label or "",
        conf_raw=conf_raw,
        fm_codes=fm_codes,
        div_delta=div_val,
    )
    if isinstance(sentence, str) and sentence.strip():
        return sentence.strip()
    return ""


def _build_scout_pad(d: dict, fm_codes: set, fm_labels: list, tag_list: list) -> str:
    """
    Build the Scout Pad HTML for the Notes tab.
    5 blocks: Draft Call, Market View, Risk Snapshot, Flags, Draft Day Take.
    Returns a fallback message if no APEX data is available.
    """
    apex_comp   = d.get("apex_composite")
    tier        = (d.get("apex_tier") or "").strip().upper()
    capital     = d.get("capital_base") or d.get("capital_adjusted") or "—"
    conf_raw    = d.get("eval_confidence") or d.get("eval_confidence_tier") or ""
    archetype   = d.get("matched_archetype") or ""
    crank       = d.get("consensus_rank")
    div_delta   = d.get("divergence_delta") or d.get("auto_apex_delta")
    fm_primary  = d.get("failure_mode_primary") or ""
    fm_secondary= d.get("failure_mode_secondary") or ""
    trans_risk  = d.get("translation_risk") or ""
    pos         = (d.get("position_group") or "").strip().upper()

    if not apex_comp and apex_comp != 0:
        return (
            '<div class="sp-block" style="text-align:center;padding:28px 16px">'
            '<div class="sp-k" style="margin-bottom:8px">Scout Pad</div>'
            '<div style="font-size:11px;color:var(--dim)">No APEX evaluation data available for this prospect.</div>'
            '</div>'
        )

    # ── Derived ────────────────────────────────────────────────────────────────
    if archetype and " " in archetype:
        arch_code_sp, arch_label_sp = archetype.split(" ", 1)
    else:
        arch_code_sp, arch_label_sp = archetype or "—", ""

    _TIER_WORD = {
        "ELITE": "Elite", "DAY1": "Day 1", "DAY2": "Day 2",
        "DAY3": "Day 3", "UDFA-P": "Priority UDFA", "UDFA": "UDFA",
    }
    _TIER_COLOR = {
        "ELITE": "#f0c040", "DAY1": "#7eb4e2", "DAY2": "#5ab87a",
        "DAY3": "#e8a84a", "UDFA-P": "#a57ee0", "UDFA": "rgba(255,255,255,0.35)",
    }
    tier_word  = _TIER_WORD.get(tier, tier or "—")
    tier_color = _TIER_COLOR.get(tier, "var(--text)")

    _CONF_DISPLAY = {"A": "Tier A", "B": "Tier B", "C": "Tier C"}
    conf_display = _CONF_DISPLAY.get(str(conf_raw).strip(), str(conf_raw).strip() or "—")
    _CONF_COLOR  = {
        "A": "var(--green)", "Tier A": "var(--green)",
        "B": "var(--amber)", "Tier B": "var(--amber)",
        "C": "var(--red)",   "Tier C": "var(--red)",
    }
    conf_color = _CONF_COLOR.get(str(conf_raw).strip(), "var(--dim)")

    # Consensus + derived APEX rank
    try:
        con_rank_int = int(float(crank)) if crank is not None else None
    except (TypeError, ValueError):
        con_rank_int = None
    con_rank_str = f"#{con_rank_int}" if con_rank_int else "NR"

    try:
        dd = int(float(div_delta)) if div_delta is not None else None
    except (TypeError, ValueError):
        dd = None

    apex_rank_str = "—"
    dd_color      = "var(--dim)"
    dd_str        = "—"
    if con_rank_int is not None and dd is not None:
        apex_rank_val = con_rank_int - dd
        apex_rank_str = f"#{apex_rank_val}"
        if dd > 0:
            dd_color = "var(--green)"
            dd_str   = f"+{dd}"
        elif dd < 0:
            dd_color = "var(--red)"
            dd_str   = str(dd)
        else:
            dd_str = "0"

    # Market framing line
    market_line = ""
    if dd is not None and abs(dd) >= 5:
        if dd >= 15:
            market_line = f"Scout consensus is significantly behind APEX on this prospect ({dd_str})."
        elif dd >= 5:
            market_line = f"APEX sees more upside here than current market consensus suggests ({dd_str})."
        elif dd <= -15:
            market_line = f"Market is pricing this player well above APEX valuation ({dd_str})."
        else:
            market_line = f"Mild APEX discount relative to scout consensus ({dd_str})."

    # FM rows
    def _fm_color(code: int) -> str:
        return {1: "var(--amber)", 2: "var(--red)", 3: "var(--amber)",
                4: "var(--amber)", 5: "var(--red)", 6: "var(--amber)"}.get(code, "var(--dim)")

    fm_rows = ""
    fm_pairs = [("Primary FM", fm_primary), ("Secondary FM", fm_secondary)]
    for lbl, fv in fm_pairs:
        if _fm_is_present(fv):
            m = re.search(r"FM-(\d+)", str(fv))
            code = int(m.group(1)) if m else None
            color = _fm_color(code) if code else "var(--dim)"
            # Show just code + first clause
            fv_display = str(fv).strip()
            if " — " in fv_display:
                fv_display = fv_display.split(" — ")[0].strip()
            fm_rows += (
                f'<div class="sp-kv">'
                f'<span class="sp-k">{_e(lbl)}</span>'
                f'<span class="sp-v" style="color:{color}">{_e(fv_display)}</span>'
                f'</div>'
            )
    if not fm_rows:
        fm_rows = (
            '<div class="sp-kv">'
            '<span class="sp-k">FM Risk</span>'
            '<span class="sp-v" style="color:var(--dim)">—</span>'
            '</div>'
        )

    # Translation risk (first sentence only)
    trans_display = "—"
    if _v23_present(trans_risk):
        first_sent = str(trans_risk).split(".")[0].strip()
        trans_display = first_sent[:120] + ("…" if len(first_sent) > 120 else "")

    # Tag pills (reuse .htag classes from existing CSS)
    pills_html = ""
    if tag_list:
        _TAG_CLS = {
            "CRUSH": "crush", "Two-Way Premium": "tw",
            "Walk-On Flag": "walkOn", "Schwesinger Rule": "schwes",
        }
        pills = "".join(
            f'<span class="htag {_TAG_CLS.get(t, "")}">{_e(t)}</span>'
            for t in tag_list
        )
        pills_html = f'<div class="htags-row" style="margin-top:4px">{pills}</div>'

    # Draft Day Take — prefer pre-resolved value (set by caller via d["draft_day_take_resolved"])
    take_sentence = (
        d.get("draft_day_take_resolved")
        or _build_draft_day_take(pos, tier, arch_label_sp, conf_raw, fm_codes, div_delta)
    )
    # take_sentence rendered below as insight-card (take_insight_html)

    # ── Assemble blocks ────────────────────────────────────────────────────────

    # Block 1: Draft Call
    arch_role_display = arch_label_sp or arch_code_sp or "—"
    block_call = (
        '<div class="detail-section">'
        '<div class="detail-section-header">Draft Call</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Tier</span>'
        f'<span class="sp-v" style="color:{tier_color}">{_e(tier_word)}</span>'
        f'</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Capital</span>'
        f'<span class="sp-v">{_e(capital)}</span>'
        f'</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Confidence</span>'
        f'<span class="sp-v" style="color:{conf_color}">{_e(conf_display)}</span>'
        f'</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Archetype / Role</span>'
        f'<span class="sp-v">{_e(arch_role_display)}</span>'
        f'</div>'
        '</div>'
    )

    # Block 2: Market View
    market_line_html = (
        f'<div class="sp-market-line">{_e(market_line)}</div>'
        if market_line else ""
    )
    block_market = (
        '<div class="detail-section">'
        '<div class="detail-section-header">Market View</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Consensus Rank</span>'
        f'<span class="sp-v">{_e(con_rank_str)}</span>'
        f'</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">APEX Rank</span>'
        f'<span class="sp-v">{_e(apex_rank_str)}</span>'
        f'</div>'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Δ APEX</span>'
        f'<span class="sp-v" style="color:{dd_color}">{_e(dd_str)}</span>'
        f'</div>'
        f'{market_line_html}'
        '</div>'
    )

    # Block 3: Risk Snapshot
    block_risk = (
        '<div class="detail-section">'
        '<div class="detail-section-header">Risk Snapshot</div>'
        f'{fm_rows}'
        f'<div class="sp-kv">'
        f'<span class="sp-k">Translation Risk</span>'
        f'<span class="sp-v" style="font-size:13px;text-align:right;color:var(--mid)">{_e(trans_display)}</span>'
        f'</div>'
        '</div>'
    )

    # Block 4: Flags
    block_flags = ""
    if tag_list:
        block_flags = (
            '<div class="detail-section">'
            '<div class="detail-section-header">Tags / Flags</div>'
            f'{pills_html}'
            '</div>'
        )

    # Draft Day Take — use insight-card
    take_insight_html = ""
    if take_sentence:
        take_insight_html = (
            '<div class="insight-card amber">'
            '<div class="insight-hdr">Draft Day Take</div>'
            f'<div class="insight-body" style="font-style:italic;">{_e(take_sentence)}</div>'
            '</div>'
        )

    return block_call + block_market + block_risk + block_flags + take_insight_html


# ── New Phase-5/7 helper functions ───────────────────────────────────────────

def _build_risk_hero(fm_codes: set, fm_labels: list, translation_risk, name: str, pos: str) -> str:
    """Risk tab hero card: FM severity headline + translation risk first sentence."""
    if not fm_codes:
        if not _v23_present(translation_risk):
            return (
                '<div class="detail-hero-card">'
                '<div class="insight-hdr">Risk Profile</div>'
                '<div class="insight-body" style="color:var(--dim)">No active failure modes flagged for this prospect.</div>'
                '</div>'
            )
        return (
            '<div class="detail-hero-card">'
            '<div class="insight-hdr">Risk Profile</div>'
            f'<div class="insight-body">{_e(str(translation_risk).split(".")[0].strip())}.</div>'
            '</div>'
        )

    fm_count = len(fm_codes)
    if fm_count >= 2:
        severity_word = "Compound FM Risk"
        severity_color = "var(--red)"
    else:
        fc = next(iter(fm_codes))
        severity_word = "Active FM Risk"
        severity_color = f"var(--fm{fc})"

    fm_labels_str = " · ".join(fm_labels[:2])
    trans_first = ""
    if _v23_present(translation_risk):
        trans_first = str(translation_risk).split(".")[0].strip()

    return (
        f'<div class="detail-hero-card">'
        f'<div style="font-size:8px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);margin-bottom:6px;">Risk Profile — {_e(name)} · {_e(pos)}</div>'
        f'<div style="font-size:20px;font-weight:800;color:{severity_color};line-height:1.2;margin-bottom:6px;">{severity_word}</div>'
        f'<div style="font-size:13px;color:var(--mid);margin-bottom:{"8px" if trans_first else "0"};">{_e(fm_labels_str)}</div>'
        + (f'<div style="font-size:13px;line-height:1.65;color:var(--mid);border-top:1px solid var(--wire);padding-top:8px;">{_e(trans_first)}.</div>' if trans_first else '')
        + '</div>'
    )


def _build_top_traits_card(d: dict, pos: str, pos_note: str) -> str:
    """Traits tab: highlight the 1–2 top-weighted traits for the position."""
    _POS_TOP: dict[str, list[str]] = {
        "QB":   ["v_processing", "v_scheme_vers"],
        "CB":   ["v_athleticism", "v_comp_tough"],
        "EDGE": ["v_athleticism", "v_comp_tough"],
        "OT":   ["v_comp_tough", "v_injury"],
        "S":    ["v_processing", "v_athleticism"],
        "IDL":  ["v_comp_tough", "v_injury"],
        "ILB":  ["v_processing", "v_athleticism"],
        "OLB":  ["v_athleticism", "v_comp_tough"],
        "WR":   ["v_athleticism", "v_production"],
        "TE":   ["v_comp_tough", "v_scheme_vers"],
        "OG":   ["v_comp_tough", "v_injury"],
        "C":    ["v_processing", "v_comp_tough"],
        "RB":   ["v_production", "v_injury"],
    }
    _TRAIT_LABELS: dict[str, str] = {
        "v_processing":   "Processing",
        "v_athleticism":  "Athleticism",
        "v_comp_tough":   "Comp. Toughness",
        "v_injury":       "Durability",
        "v_scheme_vers":  "Scheme Versatility",
        "v_production":   "Production",
        "v_dev_traj":     "Dev. Trajectory",
        "v_character":    "Character",
    }
    top_keys = _POS_TOP.get(pos.upper(), [])
    if not top_keys:
        return ""

    _COLOR_MAP = {"hi": "var(--green)", "mid": "var(--cold)", "lo": "var(--amber)", "red": "var(--red)"}
    chips = ""
    for k in top_keys:
        v = d.get(k)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        cls = _trait_cls(fv)
        color = _COLOR_MAP.get(cls, "var(--text)")
        label = _TRAIT_LABELS.get(k, k)
        chips += (
            f'<div style="flex:1;padding:10px 12px;background:var(--ink4);border-radius:5px;border-top:2px solid {color};">'
            f'<div style="font-size:7px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:var(--dim);margin-bottom:4px;">{_e(label)}</div>'
            f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:26px;font-weight:800;color:{color};line-height:1;">{fv:.1f}</div>'
            f'<div style="font-size:11px;color:var(--dim);margin-top:2px;">Key trait for {_e(pos)}</div>'
            f'</div>'
        )

    if not chips:
        return ""

    note_html = (
        f'<div style="font-size:13px;color:var(--dim);margin-top:10px;padding-top:8px;border-top:1px solid var(--wire);">{_e(pos_note)}</div>'
        if pos_note else ""
    )
    return (
        f'<div class="detail-section" style="margin-bottom:16px;">'
        f'<div class="detail-section-header">Key Position Traits</div>'
        f'<div style="display:flex;gap:8px;">{chips}</div>'
        f'{note_html}'
        f'</div>'
    )


# ── Public API ────────────────────────────────────────────────────────────────

def build_decision_card(d: dict, fm_codes: set) -> str:
    """
    Build the sticky decision summary card rendered at the top of the right content pane.
    Returns empty string for unscored prospects (apex_composite absent or null).
    """
    apex_comp = d.get("apex_composite")
    if not _v23_present(apex_comp):
        return ""

    tier         = (d.get("apex_tier") or "").strip().upper()
    name         = d.get("display_name") or d.get("name") or "—"
    pos          = d.get("position_group") or d.get("position") or ""
    capital_base = d.get("capital_base") or d.get("capital_adjusted") or "—"
    conf_raw     = d.get("eval_confidence") or d.get("confidence_band") or "—"
    gap_label    = (d.get("gap_label") or "").strip().upper()
    translation_risk = d.get("translation_risk")

    div_delta    = d.get("divergence_delta") or d.get("auto_apex_delta")
    try:
        dd = int(float(div_delta)) if div_delta is not None else None
    except (TypeError, ValueError):
        dd = None

    # ── Zone 1: Call logic ────────────────────────────────────────────────────
    if tier == "ELITE":
        call_text = "Priority target — commit capital above consensus"
    elif tier == "DAY1" and dd is not None and dd > 5:
        call_text = "Strong buy — APEX above market, investigate the gap"
    elif tier == "DAY1":
        call_text = "Day 1 value — execute at consensus range"
    elif tier == "DAY2" and dd is not None and dd < -5:
        call_text = "Monitor — APEX below market, confirm mechanism holds"
    elif tier == "DAY2":
        call_text = "Solid Day 2 target"
    elif tier == "DAY3":
        call_text = "Day 3 value — draft capital efficient at this range"
    elif tier in ("UDFA-P", "UDFA"):
        call_text = "Priority free agent — do not spend picks"
    else:
        call_text = "Evaluate — insufficient APEX data"

    # Market edge sentence (only when abs(dd) > 5)
    market_edge_html = ""
    if dd is not None and abs(dd) > 5:
        if dd > 5:
            edge_sentence = f"APEX rates {abs(dd)} spots above consensus — model sees premium the market has not priced in."
        else:
            edge_sentence = f"APEX rates {abs(dd)} spots below consensus — model has flagged a risk not reflected in market grade."
        market_edge_html = (
            f'<div class="dc-field-lbl">MARKET EDGE</div>'
            f'<div class="dc-field-val">{_e(edge_sentence)}</div>'
        )

    # ── Zone 2: FM risk block ─────────────────────────────────────────────────
    _FC = {1: "t1", 2: "t2", 3: "t3", 4: "t4", 5: "t5", 6: "t6"}
    fm_tags_html = ""
    if fm_codes:
        tags = ""
        for code in sorted(fm_codes)[:2]:
            label = f"FM-{code}"
            cls   = _FC.get(code, "t1")
            tags += f'<span class="fm-tag {cls}">{_e(label)}</span>'
        fm_tags_html = f'<div class="fm-tags">{tags}</div>'
    else:
        fm_tags_html = '<div style="font-size:10px;color:var(--dim);margin-bottom:8px;">No FM flags</div>'

    risk_note_html = ""
    if _v23_present(translation_risk):
        # Use the full first sentence. Only truncate on a word boundary if it
        # is exceptionally long (>280 chars) to prevent mid-word cutoffs.
        _tr_text = str(translation_risk).strip()
        _first_sent = _tr_text.split(".")[0].strip()
        if len(_first_sent) > 280:
            _trunc = _first_sent[:280]
            # Retreat to last word boundary
            _last_space = _trunc.rfind(" ")
            if _last_space > 180:
                _trunc = _trunc[:_last_space]
            _first_sent = _trunc + "…"
        risk_note_html = f'<div class="dc-risk-note">{_e(_first_sent)}</div>'

    # ── Zone 3: Confidence strip ──────────────────────────────────────────────
    _CONF_COLOR = {
        "HIGH": "var(--green)", "A": "var(--green)",
        "MEDIUM": "var(--amber)", "B": "var(--amber)",
        "LOW": "var(--red)", "C": "var(--red)",
    }
    conf_key  = str(conf_raw).strip().upper()
    conf_color = _CONF_COLOR.get(conf_key, "var(--dim)")
    conf_disp  = _e(conf_raw) if _v23_present(conf_raw) else "—"

    _GAP_COLOR = {
        "CLEAN": "var(--green)", "SOLID": "var(--cold)",
        "TWEENER": "var(--amber)", "COMPRESSION": "var(--amber)", "NO_FIT": "var(--red)",
    }
    _GAP_DISP = {
        "CLEAN": "Clean Fit", "SOLID": "Solid Fit",
        "TWEENER": "Tweener", "COMPRESSION": "Elite Tweener", "NO_FIT": "No Dominant Fit",
    }
    gap_color = _GAP_COLOR.get(gap_label, "var(--dim)")
    gap_disp  = _GAP_DISP.get(gap_label, gap_label.title() if gap_label else "—")

    score_disp = _safe_float(apex_comp)

    pos_chip = f'<span style="font-size:9px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase;color:var(--dim);margin-left:6px;">{_e(pos)}</span>' if pos else ""

    return (
        '<div class="decision-card">'
        '<div class="dc-zones">'
        # Zone 1 — Call block
        '<div>'
        f'<div style="margin-bottom:10px;">'
        f'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:13px;font-weight:700;color:var(--text);">{_e(name)}</span>'
        f'{pos_chip}'
        f'</div>'
        '<div class="dc-call-lbl">CALL</div>'
        f'<div class="dc-call-text">{_e(call_text)}</div>'
        '<div class="dc-field-lbl">CAPITAL</div>'
        f'<div class="dc-field-val">{_e(capital_base)}</div>'
        f'{market_edge_html}'
        '</div>'
        # Zone 2 — Risk block
        '<div>'
        '<div class="dc-risk-hdr">INVALIDATION</div>'
        f'{fm_tags_html}'
        f'{risk_note_html}'
        '</div>'
        '</div>'
        # Zone 3 — Confidence strip
        '<div class="dc-strip">'
        f'<span><span class="dc-strip-lbl">EVAL CONFIDENCE</span>'
        f'<span class="dc-strip-val" style="color:{conf_color}">{conf_disp}</span></span>'
        '<span class="dc-sep">·</span>'
        f'<span><span class="dc-strip-lbl">ARCHETYPE FIT</span>'
        f'<span class="dc-strip-val" style="color:{gap_color}">{_e(gap_disp)}</span></span>'
        '<span class="dc-sep">·</span>'
        f'<span><span class="dc-strip-lbl">APEX SCORE</span>'
        f'<span class="dc-strip-val" style="color:var(--amber)">{_e(score_disp)}</span></span>'
        '</div>'
        '</div>'
    )


def build_detail_html(d: dict, comps: list, rate, fm_ref_comps: list | None = None, team_fit_result: dict | None = None) -> str:
    """
        Build a complete self-contained HTML string for the DraftOS prospect detail drawer.
        Renders as a two-column layout: sticky left rail + scrollable right content.

        Args:
            d:             Prospect detail dict (same shape as _build_detail_html in app.py).
            comps:         List of historical comp dicts from get_historical_comps().
            rate:          Archetype translation rate dict from get_archetype_translation_rate(), or None.
            fm_ref_comps:  Optional list of FM reference comp dicts from get_fm_reference_comps().

        Returns:
            Complete <!DOCTYPE html> string ready to pass to components.html().
        """
        # ── Unpack fields ────────────────────────────────────────────────────────
    pos              = d.get("position_group") or "?"
    name             = d.get("display_name") or "Unknown"
    school           = d.get("school_canonical") or "—"
    tier             = (d.get("apex_tier") or "").strip().upper()
    crank            = d.get("consensus_rank")
    conf_raw         = d.get("confidence_band") or d.get("eval_confidence") or "—"
    ras_raw          = d.get("ras_score") or d.get("ras_total")
    raw_score        = d.get("raw_score")
    apex_comp        = d.get("apex_composite")
    pvc              = d.get("pvc")
    pos_rank         = d.get("position_rank")
    pos_rank_label   = d.get("position_rank_label")  # NEW: from get_apex_detail
    archetype_raw    = d.get("matched_archetype") or d.get("apex_archetype") or ""
    gap_label        = (d.get("gap_label") or "").strip().upper()
    fit_score_val    = d.get("archetype_gap")
    fm_primary       = d.get("failure_mode_primary")
    fm_secondary     = d.get("failure_mode_secondary")
    signature_play   = d.get("signature_play")
    strengths_raw    = d.get("strengths")
    red_flags_raw    = d.get("red_flags")
    translation_risk = d.get("translation_risk")
    capital_base     = d.get("capital_base") or d.get("capital_adjusted") or "—"
    capital_note     = d.get("capital_note") or ""
    snapshot_date    = d.get("scored_at") or d.get("snapshot_date") or ""
    div_delta        = d.get("divergence_delta") or d.get("auto_apex_delta")
    div_narrative    = d.get("divergence_narrative")
    prospect_id      = d.get("prospect_id") or d.get("consensus_rank") or "—"
    tags_raw         = d.get("tags") or d.get("tag_names") or ""

        # ── Header fields ────────────────────────────────────────────────────────
    if pos_rank_label:
        pos_chip_text = pos_rank_label          # e.g. "LB #1"
    else:
        pos_chip_text = pos                      # fall back to just "LB"

    meta_chips = []
    if crank:
        meta_chips.append(
            f'<span class="meta-chip hi">Consensus #{_e(crank)}</span>'
        )
    if pos_rank_label:
        meta_chips.append(
            f'<span class="meta-chip">({_e(pos_rank_label)})</span>'
        )
    
        # ── Derived values ───────────────────────────────────────────────────────
        import pandas as pd

        rank_str = f"#{int(crank)}" if crank is not None and _safe_float(str(crank)) != "—" else "NR"
        try:
            rank_num = int(float(crank)) if crank is not None else 0
        except (TypeError, ValueError):
            rank_num = 0

        ras_str = _safe_float(ras_raw, ".2f") if ras_raw is not None else None
        raw_int,  raw_dec  = _split_score(raw_score)
        apex_int, apex_dec = _split_score(apex_comp)

        is_unified = False
        if pvc is not None:
            try:
                is_unified = abs(float(pvc) - 1.0) < 0.005
            except (TypeError, ValueError):
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

        # Auto-lookup archetype definition from library (caller can override via apex_archetype_def)
        apex_archetype_def = d.get("apex_archetype_def") or _ARCHETYPE_DEFS.get(arch_code)
        arch_def_html = (
            f'<div class="archetype-def">{_e(apex_archetype_def)}</div>'
            if apex_archetype_def else ""
        )

        ghost_rank = f"#{rank_num}" if rank_num > 0 else ""

        TIER_MAP = {
            "ELITE":  ("elite", "★ Elite",  "Top Tier"),
            "DAY1":   ("day1",  "Day 1",    "Round 1"),
            "DAY2":   ("day2",  "Day 2",    "Rounds 2–3"),
            "DAY3":   ("day3",  "Day 3",    "Rounds 4–7"),
            "UDFA-P": ("udfa",  "UDFA",     "Priority Free Agent"),
            "UDFA":   ("udfa",  "UDFA",     "Free Agent"),
        }
        tier_cls, tier_text, tier_sub = TIER_MAP.get(tier, ("udfa", tier or "—", ""))

        conf_color_cls = {
            "Tier A": "green", "A": "green", "High": "green",
            "Tier B": "amber", "B": "amber", "Medium": "amber",
            "Tier C": "red",   "C": "red",   "Low": "red",
        }.get(conf_raw, "dim")

        conf_display = {
            "A": "Tier A", "B": "Tier B", "C": "Tier C",
        }.get(conf_raw, conf_raw)

        # Divergence display
        div_text  = "N/A"
        div_cls   = "dim"
        chip_cls  = "aligned"
        try:
            if div_delta is not None:
                dd = int(float(div_delta))
                if abs(dd) < 3:
                    div_text, div_cls = f"Aligned ({dd:+d})" if dd != 0 else "Aligned (0)", "dim"
                elif dd > 0:
                    div_text, div_cls = f"APEX +{dd}", "blue"
                else:
                    div_text, div_cls = f"APEX {dd}", "red"
        except (TypeError, ValueError):
            pass

        # Position rank chip
        pos_rank_chip = ""
        if pos_rank:
            try:
                if int(float(pos_rank)) != int(float(crank)):
                    pos_rank_chip = (
                        f'<span class="meta-chip hi">#{int(float(pos_rank))} at {_e(pos)}</span>'
                    )
            except (TypeError, ValueError):
                pass

        # FM codes
        fm_codes: set[int] = set()
        fm_labels: list[str] = []
        for fv in [fm_primary, fm_secondary]:
            if _fm_is_present(fv):
                m = re.search(r"FM-(\d+)", str(fv))
                if m:
                    fm_codes.add(int(m.group(1)))
                fm_labels.append(str(fv).strip())

        # Watermark date
        try:
            wm_date = datetime.strptime(str(snapshot_date)[:10], "%Y-%m-%d").strftime("%b %d, %Y")
        except (ValueError, TypeError):
            wm_date = datetime.now().strftime("%b %d, %Y")

        # Tags
        _TAG_CLASSES = {
            "CRUSH":           "crush",
            "Two-Way Premium": "tw",
            "Walk-On Flag":    "walkOn",
            "Schwesinger Rule": "schwes",
            "Schwesinger Full": "schwes",
        }
        _INTERNAL = frozenset({"apex_rank_2026"})
        if tags_raw:
            sep = "," if "," in str(tags_raw) else "|"
            tag_list = [t.strip() for t in str(tags_raw).split(sep) if t.strip() and t.strip() not in _INTERNAL]
        else:
            tag_list = []

        # ── Build HTML fragments ─────────────────────────────────────────────────

        # Score block
        if is_unified:
            score_block = (
                '<div class="score-grid unified">'
                '<div class="score-item">'
                '<div class="score-lbl">Player Grade · Draft Value</div>'
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
                '<div class="score-lbl">APEX Score</div>'
                f'<div class="score-val apex">{apex_int}<span class="score-decimal">.{apex_dec}</span></div>'
                '</div></div>'
            )

        # RAS block
        ras_html = ""
        if ras_str and ras_str != "—":
            ras_html = (
                f'<div class="ras-block-right">'
                f'<div class="ras-lbl">RAS Score</div>'
                f'<div class="ras-val">{_e(ras_str)}</div>'
                f'</div>'
            )

        # Trait bars
        football_html = "".join([
            _build_trait("Processing",  d.get("v_processing")),
            _build_trait("Athleticism", d.get("v_athleticism")),
            _build_trait("Comp. Tough", d.get("v_comp_tough")),
            _build_trait("Durability",  d.get("v_injury")),
        ])
        system_html = "".join([
            _build_trait("Scheme Vers.", d.get("v_scheme_vers")),
            _build_trait("Production",   d.get("v_production")),
            _build_trait("Dev. Traj.",   d.get("v_dev_traj")),
            _build_trait("Character",    d.get("v_character")),
        ])

        # Archetype fit row
        fit_row_html = ""
        if gap_label and fit_score_val is not None:
            GAP_CLS = {
                "CLEAN": "clean", "SOLID": "solid",
                "TWEENER": "tweak", "COMPRESSION": "solid", "NO_FIT": "nofit"
            }
            GAP_DISPLAY = {
                "CLEAN": "Clean Fit", "SOLID": "Solid Fit",
                "TWEENER": "Tweener", "COMPRESSION": "Elite Tweener", "NO_FIT": "No Dominant Fit"
            }
            gap_cls  = GAP_CLS.get(gap_label, "solid")
            gap_disp = GAP_DISPLAY.get(gap_label, gap_label.title())
            try:
                fs = float(fit_score_val)
                fit_pct = min(max(fs / 20.0 * 100, 0), 100)
            except (TypeError, ValueError):
                fs = 0.0
                fit_pct = 0.0
            fit_row_html = (
                f'<div class="fit-row">'
                f'<div class="fit-header">'
                f'<span class="fit-lbl">Archetype Fit</span>'
                f'<span class="fit-score {gap_cls}">{_e(gap_disp)} · {_safe_float(fit_score_val, ".1f")} pts</span>'
                f'</div>'
                f'<div class="fit-track"><div class="fit-fill {gap_cls}" style="width:{fit_pct:.1f}%"></div></div>'
                f'<div class="fit-breakdown">Clean Fit &gt;15 pts · <span>Solid Fit 8–15 pts</span> · Tweener &lt;8 pts</div>'
                f'</div>'
            )

        # Tags
        tags_html = ""
        if tag_list:
            pills = ""
            for t in tag_list:
                cls = _TAG_CLASSES.get(t, "neutral")
                pills += f'<span class="htag {cls}">{_e(t)}</span>'
            tags_html = f'<div class="tags-row">{pills}</div>'

        # Decision card — top of right content pane (APEX-scored prospects only)
        decision_card_html = build_decision_card(d, fm_codes)

        # Summary tab 3-chip stat row: Capital / Archetype Fit / Eval Confidence
        _GAP_CHIP_COLOR = {
            "CLEAN": "var(--green)", "SOLID": "var(--cold)",
            "TWEENER": "var(--amber)", "COMPRESSION": "var(--amber)", "NO_FIT": "var(--red)",
        }
        _GAP_CHIP_DISP = {
            "CLEAN": "Clean Fit", "SOLID": "Solid Fit",
            "TWEENER": "Tweener", "COMPRESSION": "Elite Tweener", "NO_FIT": "No Dominant Fit",
        }
        _CONF_CHIP_COLOR = {
            "A": "var(--green)", "Tier A": "var(--green)", "High": "var(--green)",
            "B": "var(--amber)", "Tier B": "var(--amber)", "Medium": "var(--amber)",
            "C": "var(--red)",   "Tier C": "var(--red)",   "Low": "var(--red)",
        }
        _cap_chip_val  = _e(capital_base) if capital_base and capital_base != "—" else "—"
        _gap_chip_color = _GAP_CHIP_COLOR.get(gap_label, "var(--dim)")
        _gap_chip_disp  = _GAP_CHIP_DISP.get(gap_label, gap_label.title() if gap_label else "—")
        _conf_chip_color = _CONF_CHIP_COLOR.get(str(conf_raw).strip(), "var(--dim)")
        _conf_chip_disp  = conf_display if conf_display else "—"
        stat_chip_row_html = (
            '<div class="stat-chip-row">'
            f'<div class="detail-stat-chip">'
            f'<div class="detail-stat-chip-lbl">Draft Capital</div>'
            f'<div class="detail-stat-chip-val" style="color:var(--text);">{_cap_chip_val}</div>'
            f'</div>'
            f'<div class="detail-stat-chip">'
            f'<div class="detail-stat-chip-lbl">Archetype Fit</div>'
            f'<div class="detail-stat-chip-val" style="color:{_gap_chip_color};">{_gap_chip_disp}</div>'
            f'</div>'
            f'<div class="detail-stat-chip">'
            f'<div class="detail-stat-chip-lbl">Eval Confidence</div>'
            f'<div class="detail-stat-chip-val" style="color:{_conf_chip_color};">{_conf_chip_disp}</div>'
            f'</div>'
            '</div>'
        ) if _v23_present(apex_comp) else ""

        # FM section
        fm_html = _build_fm_section(fm_codes, fm_labels, prospect=d)

        # Divergence panel (only when abs(delta) >= 3) — wrapped in insight-card
        divergence_panel_html = ""
        try:
            if div_delta is not None and abs(int(float(div_delta))) >= 3:
                _div_raw = _build_divergence_panel(div_delta, div_narrative)
                divergence_panel_html = (
                    '<div class="section-gap"></div>'
                    '<div class="sec-divider cold">APEX Divergence</div>'
                    + _div_raw
                )
        except (TypeError, ValueError):
            pass

        # Signature play — insight-card
        sig_html = ""
        if _v23_present(signature_play):
            sig_html = (
                '<div class="section-gap"></div>'
                '<div class="sec-divider">Signature Play</div>'
                '<div class="insight-card amber">'
                '<div class="insight-hdr">Signature Play</div>'
                f'<div class="insight-body" style="font-style:italic;">{_e(signature_play)}</div>'
                '</div>'
            )

        # Strengths + Red Flags — insight-split layout
        str_items = _smart_split_bullets(strengths_raw)
        rf_items  = _smart_split_bullets(red_flags_raw)

        def _pitems(items, dc):
            return "".join(
                f'<div class="panel-item"><span class="pi-dot {dc}"></span>{_e(it)}</div>'
                for it in items
            )

        two_col_html = ""
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
            two_col_html = (
                '<div class="section-gap"></div>'
                '<div class="sec-divider">Strengths &amp; Red Flags</div>'
                f'<div class="two-col">{sp}{rp}</div>'
            )

        # Translation risk
        risk_html = ""
        if _v23_present(translation_risk):
            risk_html = (
                '<div class="risk-banner">'
                '<span class="risk-icon">!</span>'
                f'<div class="risk-text">{_e(translation_risk)}</div>'
                '</div>'
            )

        # Comps
        comps_html = ""
        if comps:
            comps_html = (
                '<div class="section-gap"></div>'
                + _build_comps_html(comps, archetype_raw, rate)
            )

        # FM reference records — always render section when FM codes present
        # (shows explanatory block if no same-position data rather than nothing)
        fm_ref_html = ""
        if fm_codes:
            fm_ref_html = (
                '<div class="section-gap"></div>'
                + _build_fm_ref_html(fm_ref_comps or [], fm_labels, pos)
            )

        # Capital note
        cap_note_html = f'<div class="capital-note">{_e(capital_note)}</div>' if capital_note else ""

        # ── Tab-specific fragments ────────────────────────────────────────────────

        # TRAITS tab — positional baseline note
        _POS_TRAIT_NOTES: dict[str, str] = {
            "QB":   "Top weighted traits: Processing, Scheme Versatility.",
            "CB":   "Top weighted traits: Athleticism, Competitive Toughness.",
            "EDGE": "Top weighted traits: Athleticism, Competitive Toughness.",
            "OT":   "Top weighted traits: Competitive Toughness, Durability.",
            "S":    "Top weighted traits: Processing, Athleticism.",
            "IDL":  "Top weighted traits: Competitive Toughness, Durability.",
            "ILB":  "Top weighted traits: Processing, Athleticism.",
            "OLB":  "Top weighted traits: Athleticism, Competitive Toughness.",
            "WR":   "Top weighted traits: Athleticism, Production.",
            "TE":   "Top weighted traits: Competitive Toughness, Scheme Versatility.",
            "OG":   "Top weighted traits: Competitive Toughness, Durability.",
            "C":    "Top weighted traits: Processing, Competitive Toughness.",
            "RB":   "Top weighted traits: Production, Durability.",
        }
        _trait_note = _POS_TRAIT_NOTES.get(pos.upper(), "")
        pos_traits_note_html = (
            f'<div class="traits-note">{_e(_trait_note)}</div>'
            if _trait_note else ""
        )

        # COMPS tab — merge comps + FM refs, or empty state
        if comps_html or fm_ref_html:
            comps_tab_html = comps_html + fm_ref_html
        else:
            comps_tab_html = '<div class="comps-empty">No historical comp data available for this archetype yet.</div>'

        # NOTES tab — Scout Pad utility panel
        notes_tab_html = _build_scout_pad(d, fm_codes, fm_labels, tag_list)

        # FIT tab — Team Fit result panel
        fit_tab_html = buildteamfithtml(team_fit_result)

        # REPORT tab — capital + confidence + pos rank + snapshot
        _CONF_REPORT_COLOR = {
            "A": "var(--green)", "High": "var(--green)",
            "B": "var(--amber)", "Medium": "var(--amber)",
            "C": "var(--red)",   "Low": "var(--red)",
        }
        _report_conf_color = _CONF_REPORT_COLOR.get(str(conf_raw).strip(), "var(--dim)")
        _pos_rank_label = f"#{int(float(pos_rank))} at {pos}" if pos_rank and _v23_present(pos_rank) else "—"
        report_tab_html = (
            f'<div class="sec-divider" style="margin-bottom:16px;">Report Contents</div>'
            f'<div class="report-block">'
            f'<div class="report-lbl">Draft Capital</div>'
            f'<div class="report-val">{_e(capital_base)}</div>'
            f'{"<div class=\'report-sub\'>" + _e(capital_note) + "</div>" if capital_note else ""}'
            f'</div>'
            f'<div class="report-block">'
            f'<div class="report-lbl">Eval Confidence</div>'
            f'<div class="report-val" style="color:{_report_conf_color}">{_e(conf_display)}</div>'
            f'</div>'
            f'<div class="report-block">'
            f'<div class="report-lbl">Position Rank</div>'
            f'<div class="report-val">{_e(_pos_rank_label)}</div>'
            f'</div>'
            f'<div class="report-block">'
            f'<div class="report-lbl">Snapshot Date</div>'
            f'<div class="report-val">{_e(wm_date)}</div>'
            f'</div>'
        )

        # ── Font URL ─────────────────────────────────────────────────────────────
        gf_url = (
            "https://fonts.googleapis.com/css2?family=Barlow+Condensed"
            ":wght@300;400;500;600;700;800;900"
            "&family=Barlow:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&display=swap"
        )

        # ── Assemble ─────────────────────────────────────────────────────────────
        return f"""<!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="{gf_url}" rel="stylesheet">
    <style>
    {_CSS}
    </style>
    </head>
    <body>

    <div class="drawer">

      <!-- ═══ LEFT RAIL ═══ -->
      <div class="rail">

        <div class="pos-chip"><span class="pos-dot"></span>{_e(pos)}</div>

        <div class="player-name">{name_html}</div>
        <div class="name-slash"></div>

        <div class="meta-row">
          <span class="meta-chip">{_e(school)}</span>
          <span class="meta-chip">Consensus {rank_str}</span>
          {pos_rank_chip}
        </div>

        <div class="apex-window">
          {score_block}
          <div class="tier-badge {tier_cls}">
            <span class="tier-text {tier_cls}">{_e(tier_text)}</span>
            <span class="tier-sub {tier_cls}">{_e(tier_sub)}</span>
          </div>
          <div class="formula-line">RPG {_safe_float(raw_score)} × PVC {pvc_str} ({_e(pos)}) = APEX {_safe_float(apex_comp)}</div>
        </div>

        <div class="traits-section">
          <div class="section-header">Football Traits</div>
          {football_html}
        </div>

        <div class="traits-section">
          <div class="section-header">System Traits</div>
          {system_html}
        </div>

        <div class="conf-row">
          <div class="conf-item">
            <div class="conf-lbl">Confidence</div>
            <div class="conf-val {conf_color_cls}">{_e(conf_display)}</div>
          </div>
          <div class="conf-item">
            <div class="conf-lbl">Divergence</div>
            <div class="conf-val {div_cls}">{_e(div_text)}</div>
          </div>
        </div>

        <div class="capital-block">
          <div class="capital-lbl">Draft Capital</div>
          <div class="capital-val">{_e(capital_base)}</div>
          {cap_note_html}
        </div>

        <div class="watermark">
          <span class="brand-logo">APEX OS</span>
          <div class="watermark-meta">
            {rank_str} · {_e(pos)} · {_e(school)}<br>
            {_e(wm_date)}
          </div>
        </div>

      </div>
      <!-- end rail -->

      <!-- ═══ RIGHT CONTENT ═══ -->
      <div class="content">

        <div class="rank-ghost">{ghost_rank}</div>

        <!-- Tab Navigation -->
        <nav class="tab-nav">
          <button class="tab-btn active" data-tab="tab-summary">Summary</button>
          <button class="tab-btn" data-tab="tab-traits">Traits</button>
          <button class="tab-btn" data-tab="tab-risk">Risk</button>
          <button class="tab-btn" data-tab="tab-comps">Comps</button>
          <button class="tab-btn" data-tab="tab-fit">Fit</button>
          <button class="tab-btn" data-tab="tab-notes">Notes</button>
          <button class="tab-btn" data-tab="tab-report">Report</button>
        </nav>

        <!-- TAB: SUMMARY -->
        <div id="tab-summary" class="tab-pane active">

          {decision_card_html}

          {stat_chip_row_html}

          <div class="sec-divider">Archetype</div>
          <div class="arch-section">
            <div class="arch-header-row">
              <div>
                <div class="archetype-code">{_e(arch_code)}</div>
                <div class="archetype-name">{_e(arch_label or archetype_raw)}</div>
                {arch_def_html}
              </div>
              {ras_html}
            </div>
            {fit_row_html}
            {tags_html}
          </div>

          {divergence_panel_html}

          {sig_html}

          {two_col_html}

        </div>

        <!-- TAB: TRAITS -->
        <div id="tab-traits" class="tab-pane">

          {_build_top_traits_card(d, pos, _trait_note)}

          <div class="traits-section">
            <div class="section-header">Football Traits</div>
            {football_html}
          </div>

          <div class="traits-section">
            <div class="section-header">System Traits</div>
            {system_html}
          </div>

          {pos_traits_note_html}

        </div>

        <!-- TAB: RISK -->
        <div id="tab-risk" class="tab-pane">
          {_build_risk_hero(fm_codes, fm_labels, translation_risk, name, pos)}
          {fm_html}
          {risk_html}
        </div>

        <!-- TAB: COMPS -->
        <div id="tab-comps" class="tab-pane">
          {comps_tab_html}
        </div>

        <!-- TAB: FIT -->
        <div id="tab-fit" class="tab-pane">
          {fit_tab_html}
        </div>

        <!-- TAB: NOTES -->
        <div id="tab-notes" class="tab-pane">
          {notes_tab_html}
        </div>

        <!-- TAB: REPORT -->
        <div id="tab-report" class="tab-pane">
          {report_tab_html}
        </div>

      </div>
      <!-- end content -->

    </div>

    <div class="card-stamp">APEX OS · 2026 · #{prospect_id}</div>

    <script>
    document.querySelectorAll('.tab-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const target = btn.dataset.tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(target).classList.add('active');
      }});
    }});
    </script>

    </body>
    </html>"""


def estimate_height(d: dict, comps: list, fm_ref_comps: list | None = None, team_fit_result: dict | None = None) -> int:
    """
    Estimate iframe height in pixels for components.html() call.
    Tabs make height predictable — only FM and comps count adds to base.
    Sections in hidden tabs do not contribute to visible scroll height.
    """
    h = 980

    # FM pip bar + tags in RISK tab can push visible height on first open
    fm_primary   = d.get("failure_mode_primary")
    fm_secondary = d.get("failure_mode_secondary")
    if _fm_is_present(fm_primary) or _fm_is_present(fm_secondary):
        h += 80
    if _fm_is_present(fm_primary) and _fm_is_present(fm_secondary):
        h += 70

    # Comps in COMPS tab — each comp card is tall
    if comps:
        h += 180 * min(len(comps), 2)
    if fm_ref_comps:
        h += 90 * min(len(fm_ref_comps), 4)

    # FIT tab — full panel: overall + decision strip + role/range + why_for + why_against
    # + fm_risk_detail + draft_decision blocks ≈ 480px when result is present
    if team_fit_result:
        if team_fit_result.get("_no_context"):
            h += 120
        else:
            h += 700

    return max(980, h)
