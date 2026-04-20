# scripts/divergence_triage_helper.py

from typing import Dict, List, Tuple


def classify_position_group(position_group: str) -> str:
    """Return 'premium' or 'non_premium'."""
    pg = (position_group or "").upper()
    if pg in {"QB", "CB", "EDGE", "OT", "S"}:
        return "premium"
    return "non_premium"


def is_structural_cluster(prospect_name: str, position_group: str) -> bool:
    """
    Hard-coded structural clusters for 2026 board.
    Extend as needed (or replace with DB lookup later).
    """
    name = (prospect_name or "").lower()
    pg = (position_group or "").upper()

    # S APEX_LOW structural cluster
    if pg == "S" and name in {
        "genesis smith",
        "caleb downs",
        "kamari ramsey",
    }:
        return True

    # Reese ILB-3 structural disagreement example (kept for pattern)
    if pg in {"ILB", "LB"} and "reese" in name:
        return True

    return False


def suggest_analyst_tags(
    position_group: str,
    archetype_code: str,
    fm_codes: List[str],
    delta: float,
) -> List[str]:
    """
    Given basic prospect context, return a list of suggested analyst tag strings.
    This does NOT write to the DB; caller is responsible for applying tags.
    """
    tags: List[str] = []
    pg = (position_group or "").upper()
    arch = (archetype_code or "").upper()
    fm = {code.upper() for code in (fm_codes or [])}
    abs_delta = abs(delta)

    # Bust risk patterns
    if {"FM-3", "FM-5"} <= fm:
        tags.append("Possible Bust (FM-3/FM-5)")
    elif "FM-1" in fm:
        tags.append("Possible Bust (FM-1)")

    # Scheme dependent patterns
    if arch in {"S-3", "S-4"} or (pg == "S" and ("FM-2" in fm or "FM-6" in fm)):
        tags.append("Scheme Dependent (Safety)")
    if arch == "ILB-3":
        tags.append("Scheme Dependent (ILB-3)")
    if arch == "DT-3":
        tags.append("Scheme Dependent (DT-3)")
    if arch == "WR-5":
        tags.append("Scheme Dependent (WR-5)")
    if arch == "EDGE-5":
        tags.append("Scheme Dependent (EDGE-5)")

    # Development bet patterns
    if arch in {"EDGE-4", "OT-5", "QB-5"} and "FM-3" not in fm and "FM-5" not in fm:
        # Tools-heavy but without confirmed projection bust stack -> Development Bet
        tags.append(f"Development Bet ({pg or 'UNKNOWN'})")

    # Ceiling capped patterns (example: role-player EDGE disagreement)
    if pg == "EDGE" and abs_delta <= 25 and "FM-4" in fm:
        tags.append("Ceiling Capped EDGE")

    # Premium big signals get at least one tag
    if not tags:
        if classify_position_group(pg) == "premium" and abs_delta >= 20:
            tags.append("Divergence Priority")

    return tags


def build_divergence_note(
    prospect_name: str,
    position_group: str,
    archetype_code: str,
    fm_codes: List[str],
    delta: float,
) -> str:
    """
    Return a one-line rationale string for the Divergence Alert.
    Caller should store this into the rec / tag note field.
    """
    name = prospect_name or "This prospect"
    pg = (position_group or "").upper()
    arch = (archetype_code or "").upper()
    fm = {code.upper() for code in (fm_codes or [])}
    abs_delta = abs(delta)

    # Special-cased structural cluster examples (hard-coded 2026)
    lname = name.lower()
    if pg == "S" and lname == "genesis smith":
        return (
            "APEX is pricing FM-5 motivation risk and S-3 deployment sensitivity; "
            "consensus is treating Genesis Smith as a clean, scheme-agnostic Day 1 safety."
        )
    if pg == "S" and lname == "caleb downs":
        return (
            "APEX is paying only for S-4 zone-dominant value under Mode B deployment, "
            "while consensus is pricing Caleb Downs as a universal safety with scheme-proof coverage."
        )
    if pg == "S" and lname == "kamari ramsey":
        return (
            "APEX sees Kamari Ramsey as part of the S APEX_LOW structural cluster, with "
            "coverage/deployment constraints the market is ignoring in a generic 'starting safety' price."
        )
    if pg == "EDGE" and lname == "nadame tucker":
        return (
            "APEX is ahead of the market on Nadame Tucker as a technique-led EDGE profile whose "
            "pass-rush translation odds are stronger than his current consensus rank implies."
        )
    if pg == "EDGE" and lname == "akheem mesidor":
        return (
            "APEX is fading Akheem Mesidor relative to consensus because EDGE archetype, counter package, "
            "and durability flags cap his ceiling below the tools-driven market narrative."
        )

    # Generic patterns based on archetype / FM / delta

    direction = "discounting" if delta < 0 else "elevating"
    base = f"APEX is {direction} {name} relative to consensus"

    if pg == "QB":
        if {"FM-3", "FM-5"} <= fm:
            return (
                f"{base} for QB archetype-driven processing and motivation risk that "
                "consensus boards are not fully pricing into early-round capital."
            )
        if "FM-3" in fm:
            return f"{base} based on concerns about processing ceiling under NFL disguise and pressure."
        return f"{base} based on QB archetype, processing, and translation odds rather than raw production."

    if pg == "EDGE":
        if "FM-1" in fm:
            return (
                f"{base} because tools and measurables outstrip confirmed EDGE pass-rush mechanism; "
                "APEX is fading an athleticism-mirage profile."
            )
        if arch in {"EDGE-3"}:
            return (
                f"{base} as a technique-led EDGE whose counter package and motor project better than "
                "consensus rank implies."
            )
        return f"{base} based on EDGE archetype and FM stack, not just sack totals."

    if pg == "S":
        if arch in {"S-3", "S-4"} or "FM-2" in fm or "FM-6" in fm:
            return (
                f"{base} for safety deployment and scheme fit; value is system-tied, "
                "while consensus is pricing a scheme-agnostic starter."
            )
        return f"{base} based on safety archetype and coverage role rather than generic DB upside."

    # Fallback generic line
    return (
        f"{base} because APEX is pricing archetype, FM stack, and translation odds differently "
        "than consensus surface grades."
    )


def triage_divergence(
    prospect_name: str,
    position_group: str,
    archetype_code: str,
    fm_codes: List[str],
    delta: float,
) -> Dict[str, object]:
    """
    High-level helper: given basic context, return a triage suggestion:
      - action: 'accept' or 'dismiss_soft'
      - note: one-line string
      - tags: list of analyst tag strings
      - structural_cluster: bool
      - priority: 'high' | 'normal'
    """
    pg_type = classify_position_group(position_group)
    abs_delta = abs(delta)
    structural = is_structural_cluster(prospect_name, position_group)
    tags = suggest_analyst_tags(position_group, archetype_code, fm_codes, delta)
    note = build_divergence_note(
        prospect_name, position_group, archetype_code, fm_codes, delta
    )

    # Default action logic
    if structural:
        action = "accept"
        priority = "high"
    elif pg_type == "premium" and abs_delta >= 20:
        action = "accept"
        priority = "high"
    else:
        # Non-premium or small delta: leave as softer suggestion
        action = "accept"
        priority = "normal"

    return {
        "action": action,
        "note": note,
        "tags": tags,
        "structural_cluster": structural,
        "priority": priority,
    }