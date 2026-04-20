from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


PREMIUM_POSITIONS = {"QB", "CB", "EDGE", "OT", "S"}


@dataclass
class TeamFitResult:
    team_id: str
    team_name: str
    pick_number: int | None
    deployment_fit: int
    pick_fit: int
    fm_risk_score: int
    fm_activated: list[str]
    fm_suppressed: list[str]
    role_outcome: str
    best_value_range: dict[str, int | None]
    verdict: str
    why_for: list[str]
    why_against: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(v: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(v))))


def _verdict(score: int) -> str:
    if score >= 85:
        return "Strong fit"
    if score >= 75:
        return "Strong conditional fit"
    if score >= 65:
        return "Mixed fit"
    if score >= 55:
        return "Fragile fit"
    return "Poor fit"


def _safe_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _safe_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    return {}


def _pick_band_from_text(capital_range: str | None) -> tuple[int | None, int | None]:
    if not capital_range:
        return (None, None)

    mapping = {
        "R1 Top 5": (1, 5),
        "R1 Top 10": (1, 10),
        "R1": (1, 32),
        "R1 Picks 11-32": (11, 32),
        "R1 Late": (22, 32),
        "R2 Early": (33, 48),
        "R2 Mid": (49, 56),
        "R2 Late": (57, 64),
        "R2 Mid-R3 Top": (49, 80),
        "R3 Top": (65, 80),
        "R3": (65, 100),
        "DAY1": (1, 32),
        "DAY2": (33, 100),
        "DAY3": (101, 257),
    }

    for k, rng in mapping.items():
        if k in capital_range:
            return rng
    return (None, None)


def evaluate_team_fit(player_ctx: dict[str, Any], team_ctx: dict[str, Any], pick_number: int | None = None) -> dict[str, Any]:
    pos = (player_ctx.get("position_group") or "").upper()
    archetype = player_ctx.get("matched_archetype") or ""
    divergence = player_ctx.get("divergence_rank_delta")
    capital_range = player_ctx.get("capital_range")
    active_fm = _safe_list(player_ctx.get("active_fm_codes"))
    apex_tier = player_ctx.get("apex_tier")
    _eval_conf_raw = player_ctx.get("eval_confidence") or 0.0
    _EVAL_CONF_MAP = {"Tier A": 8.0, "Tier B": 5.0, "Tier C": 2.0}
    eval_conf = _EVAL_CONF_MAP.get(str(_eval_conf_raw), None)
    if eval_conf is None:
        try:
            eval_conf = float(_eval_conf_raw)
        except (ValueError, TypeError):
            eval_conf = 0.0

    team_id = team_ctx.get("team_id") or ""
    team_name = team_ctx.get("team_name") or team_id
    needs = _safe_list(team_ctx.get("premium_needs"))
    depth = _safe_dict(team_ctx.get("depth_chart_pressure"))
    defense_family = team_ctx.get("primary_defense_family") or ""
    coverage_bias = team_ctx.get("coverage_bias") or ""
    man_tol = team_ctx.get("man_rate_tolerance") or ""
    draft_capital = _safe_dict(team_ctx.get("draft_capital"))

    if pick_number is None:
        pick_number = draft_capital.get("pick_1")

    deployment = 60
    if pos in needs:
        deployment += 8
    if depth.get(pos) == "high":
        deployment += 10
    elif depth.get(pos) == "medium":
        deployment += 5

    if pos == "S":
        if "quarters" in coverage_bias or "robber" in coverage_bias:
            if archetype.startswith("S-1") or archetype.startswith("S-2") or archetype.startswith("S-3"):
                deployment += 12
        if man_tol == "high" and archetype.startswith("S-1"):
            deployment -= 6

    if pos == "CB":
        if "man" in coverage_bias and archetype.startswith("CB-3"):
            deployment += 10
        if "zone" in coverage_bias and archetype.startswith("CB-2"):
            deployment += 10
        if man_tol == "high" and archetype.startswith("CB-5"):
            deployment -= 10

    if pos == "EDGE":
        if "pressure" in defense_family and (archetype.startswith("EDGE-3") or archetype.startswith("EDGE-4")):
            deployment += 10
        if archetype.startswith("EDGE-5"):
            deployment -= 10

    if pos not in PREMIUM_POSITIONS:
        deployment -= 4

    band_lo, band_hi = _pick_band_from_text(capital_range)
    pick_fit = 65
    if pick_number is not None and band_lo is not None and band_hi is not None:
        if band_lo <= pick_number <= band_hi:
            pick_fit = 85
        elif pick_number < band_lo:
            pick_fit = 58
        else:
            pick_fit = 72

    if divergence is not None:
        if divergence >= 20:
            pick_fit += 6
        elif divergence <= -20:
            pick_fit -= 8

    fm_risk = 50
    fm_activated: list[str] = []
    fm_suppressed: list[str] = []

    for fm in active_fm:
        if fm == "FM-6":
            if depth.get(pos) == "high":
                fm_suppressed.append(fm)
                fm_risk -= 8
            else:
                fm_activated.append(fm)
                fm_risk += 10
        elif fm == "FM-3":
            if "disguise" in coverage_bias or "multiple" in defense_family:
                fm_activated.append(fm)
                fm_risk += 10
            else:
                fm_suppressed.append(fm)
                fm_risk -= 4
        elif fm == "FM-2":
            if pos == "CB" and "zone" in coverage_bias and archetype.startswith("CB-2"):
                fm_suppressed.append(fm)
                fm_risk -= 8
            else:
                fm_activated.append(fm)
                fm_risk += 6
        elif fm == "FM-4":
            fm_activated.append(fm)
            fm_risk += 6
        else:
            fm_activated.append(fm)
            fm_risk += 3

    if depth.get(pos) == "high":
        role = "Day 1 starter"
        role_score = 85
    elif depth.get(pos) == "medium":
        role = "Sub-package role early, full-time by Year 2"
        role_score = 74
    else:
        role = "Needs redshirt runway"
        role_score = 58

    composite = _clamp(
        0.35 * deployment +
        0.25 * pick_fit +
        0.20 * (100 - fm_risk) +
        0.15 * role_score +
        0.05 * 65
    )

    verdict = _verdict(composite)

    why_for: list[str] = []
    why_against: list[str] = []

    if pos in needs:
        why_for.append(f"{pos} is a declared premium need for this team.")
    if depth.get(pos) == "high":
        why_for.append("Depth chart creates a clean early role path.")
    if deployment >= 80:
        why_for.append("Archetype deployment aligns with the team’s preferred usage.")

    if fm_suppressed:
        why_for.append(f"Team context helps suppress {', '.join(fm_suppressed)}.")

    if pick_fit < 65:
        why_against.append("Current pick is rich relative to the player’s value band.")
    if fm_activated:
        why_against.append(f"Team context may activate {', '.join(fm_activated)}.")
    if role_score < 65:
        why_against.append("There is no clean rookie role path.")

    if not why_for:
        why_for.append("Baseline fit is supported by roster need and deployable role logic.")
    if not why_against:
        why_against.append("The fit works, but the margin for misuse still exists.")

    conf = max(0.35, min(0.95, round(0.45 + (float(eval_conf) * 0.05), 2)))

    result = TeamFitResult(
        team_id=team_id,
        team_name=team_name,
        pick_number=pick_number,
        deployment_fit=_clamp(deployment),
        pick_fit=_clamp(pick_fit),
        fm_risk_score=_clamp(fm_risk),
        fm_activated=fm_activated,
        fm_suppressed=fm_suppressed,
        role_outcome=role,
        best_value_range={"start": band_lo, "end": band_hi},
        verdict=verdict,
        why_for=why_for[:3],
        why_against=why_against[:2],
        confidence=conf,
    )
    return result.to_dict()