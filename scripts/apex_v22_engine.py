"""
APEX v2.2 — Production Engine
All four v2.2 changes implemented:
  1. Archetype differentiation widened to ±8-10pp (primary vector)
  2. ILB-1 Green Dot vs ILB-3 Run-First sharply differentiated
  3. QB C2 base weight 8% → 11%
  4. Two-Way Premium flag + Safety SOS gate documented
  5. Gap flag logic corrected: "Complete Player Compression" added

Gap Flag Logic (v2.2):
  > 15 pts:  CLEAN — unambiguous archetype match
  8–15 pts:  SOLID — strong match
  3–7 pts:   TWEENER — FM-6 risk, -1 round capital
  1–2.9 pts: COMPRESSION — complete player, no one-dimensional weakness; 
             confirm archetype by mechanism (PAA/tape), not by gap alone
  < 1 pt:    NO FIT — re-evaluate archetype set OR apply Override
"""

def normalize(w):
    t = sum(w)
    return [round(x/t, 6) for x in w]

def make_arch(base, overrides):
    w = list(base)
    for idx, val in overrides.items():
        w[idx] = val
    return normalize(w)

BASE = {
    "QB":   [0.22, 0.10, 0.15, 0.08, 0.11, 0.12, 0.14, 0.08],
    "CB":   [0.22, 0.20, 0.16, 0.12, 0.08, 0.10, 0.08, 0.04],
    "ILB":  [0.22, 0.18, 0.16, 0.14, 0.08, 0.10, 0.08, 0.04],
    "OT":   [0.20, 0.25, 0.14, 0.18, 0.03, 0.08, 0.05, 0.12],
    "OG":   [0.20, 0.15, 0.14, 0.22, 0.03, 0.09, 0.05, 0.12],
    "TE":   [0.22, 0.18, 0.16, 0.13, 0.07, 0.09, 0.11, 0.04],
    "RB":   [0.20, 0.20, 0.15, 0.10, 0.08, 0.05, 0.15, 0.12],
    "S":    [0.25, 0.18, 0.15, 0.13, 0.10, 0.09, 0.06, 0.04],
    "EDGE": [0.20, 0.18, 0.13, 0.14, 0.05, 0.12, 0.11, 0.07],
    "IDL_A":[0.20, 0.22, 0.12, 0.16, 0.03, 0.08, 0.14, 0.05],
    "IDL_B":[0.16, 0.18, 0.15, 0.24, 0.02, 0.04, 0.13, 0.08],
    "OLB":  [0.20, 0.22, 0.18, 0.13, 0.08, 0.05, 0.12, 0.05],
    "C":    [0.28, 0.18, 0.14, 0.12, 0.10, 0.08, 0.06, 0.04],
}

ARCHETYPES = {
    "QB-1_EliteField":       make_arch(BASE["QB"],  {0:0.30, 5:0.14}),
    "QB-2_GameManager":      make_arch(BASE["QB"],  {2:0.22, 0:0.18}),
    "QB-3_AthArmed":         make_arch(BASE["QB"],  {1:0.20, 0:0.16}),
    "QB-4_SystemSpec":       make_arch(BASE["QB"],  {2:0.24, 6:0.18}),
    "QB-5_RawProj":          make_arch(BASE["QB"],  {5:0.22, 4:0.15}),
    "CB-1_PressManShutdown": make_arch(BASE["CB"],  {0:0.30, 2:0.08}),
    "CB-2_OffCoverage":      make_arch(BASE["CB"],  {0:0.26, 1:0.14}),
    "CB-3_ManAthletic":      make_arch(BASE["CB"],  {1:0.28, 0:0.14}),
    "CB-4_Zone":             make_arch(BASE["CB"],  {2:0.26, 0:0.18}),
    "CB-5_RawProj":          make_arch(BASE["CB"],  {5:0.20, 1:0.26}),
    "ILB-1_GreenDot":        make_arch(BASE["ILB"], {0:0.32, 3:0.08}),  # v2.2 SHARP
    "ILB-2_PassRushHybrid":  make_arch(BASE["ILB"], {1:0.26, 0:0.16}),
    "ILB-3_RunFirst":        make_arch(BASE["ILB"], {3:0.24, 0:0.14}),  # v2.2 SHARP
    "ILB-4_CoverageSpec":    make_arch(BASE["ILB"], {2:0.26, 0:0.24}),
    "ILB-5_RawProj":         make_arch(BASE["ILB"], {5:0.22, 4:0.16}),
    "OT-1_EliteAnchor":      make_arch(BASE["OT"],  {0:0.28, 1:0.22}),
    "OT-2_Technician":       make_arch(BASE["OT"],  {0:0.30, 1:0.17}),
    "OT-3_PowerMauler":      make_arch(BASE["OT"],  {1:0.20, 3:0.26}),
    "OT-4_ZoneSpec":         make_arch(BASE["OT"],  {2:0.22, 0:0.24}),
    "OT-5_RawProj":          make_arch(BASE["OT"],  {4:0.15, 5:0.18}),
    "OG-1_CompleteAnchor":   make_arch(BASE["OG"],  {0:0.28, 3:0.18}),
    "OG-2_Mauler":           make_arch(BASE["OG"],  {3:0.30, 0:0.14}),
    "OG-3_AthZoneMauler":    make_arch(BASE["OG"],  {1:0.24, 2:0.20}),
    "OG-4_TechFinisher":     make_arch(BASE["OG"],  {0:0.25, 5:0.14}),
    "OG-5_RawProj":          make_arch(BASE["OG"],  {4:0.15, 5:0.18}),
    "TE-1_SeamAnticipator":  make_arch(BASE["TE"],  {0:0.30, 3:0.07}),
    "TE-2_MismatchCreator":  make_arch(BASE["TE"],  {1:0.28, 0:0.14}),
    "TE-3_DualThreat":       make_arch(BASE["TE"],  {3:0.22, 6:0.15}),
    "TE-4_AfterContact":     make_arch(BASE["TE"],  {3:0.24, 1:0.12}),
    "TE-5_RawProj":          make_arch(BASE["TE"],  {5:0.22, 4:0.14}),
    "RB-1_Workhorse":        make_arch(BASE["RB"],  {1:0.28, 2:0.08, 5:0.02}),
    "RB-2_Receiving":        make_arch(BASE["RB"],  {2:0.24, 0:0.25}),
    "RB-3_Explosive":        make_arch(BASE["RB"],  {1:0.30, 6:0.18}),
    "RB-4_ChessPiece":       make_arch(BASE["RB"],  {0:0.28, 2:0.22}),
    "RB-5_RawProj":          make_arch(BASE["RB"],  {4:0.18, 5:0.15}),
    "S-1_Centerfielder":     make_arch(BASE["S"],   {0:0.34, 1:0.12}),
    "S-2_BoxEnforcer":       make_arch(BASE["S"],   {1:0.28, 0:0.16}),
    "S-3_Multiplier":        make_arch(BASE["S"],   {0:0.30, 2:0.24}),
    "S-4_CoverageSafety":    make_arch(BASE["S"],   {0:0.30, 1:0.22}),
    "S-5_RawProj":           make_arch(BASE["S"],   {4:0.22, 5:0.18}),
    "EDGE-1_EveryDay":       make_arch(BASE["EDGE"],{3:0.22, 0:0.24}),
    "EDGE-2_SpeedBend":      make_arch(BASE["EDGE"],{1:0.28, 5:0.16}),
    "EDGE-3_PowerCounter":   make_arch(BASE["EDGE"],{5:0.22, 0:0.24}),
    "EDGE-4_AthDominator":   make_arch(BASE["EDGE"],{1:0.28, 0:0.12}),
    "EDGE-5_Tweener":        make_arch(BASE["EDGE"],{2:0.24, 7:0.12}),
    "IDL-1_Wrecker":         make_arch(BASE["IDL_A"],{1:0.30, 6:0.18}),
    "IDL-2_VersatileDisrupt":make_arch(BASE["IDL_A"],{2:0.22, 0:0.26}),
    "IDL-3_TwoGapAnchor":    make_arch(BASE["IDL_B"],{3:0.32, 5:0.02}),
    "IDL-4_HybridPenAnchor": make_arch(BASE["IDL_A"],{3:0.24, 1:0.26}),
    "IDL-5_PassRushSpec":    make_arch(BASE["IDL_A"],{1:0.28, 2:0.08}),
    "OLB-1_SpeedBend":       make_arch(BASE["OLB"], {1:0.32, 0:0.14}),
    "OLB-2_HandFighter":     make_arch(BASE["OLB"], {0:0.28, 1:0.14}),
    "OLB-3_Hybrid":          make_arch(BASE["OLB"], {2:0.28, 1:0.16}),
    "OLB-4_PowerBull":       make_arch(BASE["OLB"], {3:0.24, 1:0.16}),
    "OLB-5_RawProj":         make_arch(BASE["OLB"], {4:0.20, 5:0.16}),
    "OC-1_Cerebral":         make_arch(BASE["C"],   {0:0.36, 4:0.14}),
    "OC-2_Complete":         make_arch(BASE["C"],   {1:0.26, 0:0.30}),
    "OC-3_PowerAnchor":      make_arch(BASE["C"],   {3:0.22, 2:0.22, 0:0.18}),
    "OC-4_ZoneTech":         make_arch(BASE["C"],   {1:0.28, 2:0.24, 0:0.18}),
    "OC-5_ProjAthlete":      make_arch(BASE["C"],   {1:0.28, 5:0.16, 4:0.16}),
    "OC-6_GuardConvert":     make_arch(BASE["C"],   {0:0.36, 2:0.18, 4:0.14}),
}

PVC = {
    "QB":1.00,"CB":1.00,"EDGE":1.00,"ILB":0.85,
    "OT":0.90,"S":0.90,"IDL":0.90,"OLB":0.85,
    "OG":0.80,"TE":0.80,"C":0.80,"RB":0.70
}

def evaluate(traits, prefix, pos, char, paa_mods=None, override_arch=None, override_delta=0, override_rationale=""):
    """Full APEX v2.2 evaluation. Returns dict with all outputs."""
    t = list(traits)
    c1,c2,c3 = char
    char_comp = round(sum(char)/3, 1)

    # PAA modifications
    paa_flags = paa_mods or []
    if paa_mods:
        for mod in paa_mods:
            idx, cap = mod
            t[idx] = min(t[idx], cap)

    # Schwesinger Rule
    schwesinger_full = c2 >= 9 and c3 >= 8
    schwesinger_half = (not schwesinger_full) and c2 >= 8 and c3 >= 7
    smith = char_comp < 5.0 or c2 < 5
    if schwesinger_full: t[5] = min(10, t[5] + 2)
    elif schwesinger_half: t[5] = min(10, round(t[5] + 1.5, 1))

    # Score all archetypes
    scores = {}
    for name, w in ARCHETYPES.items():
        if name.startswith(prefix):
            scores[name] = round(sum(wi*(ti/10) for wi,ti in zip(w,t))*100, 2)

    sv = sorted(scores.items(), key=lambda x: -x[1])
    best_name, best_raw = sv[0]
    gap = round(sv[0][1] - sv[1][1], 1) if len(sv) > 1 else 99

    # v2.2 gap flag with Complete Player Compression exception
    min_trait = min(t[:8])
    if gap > 15:    gap_label = "CLEAN"
    elif gap >= 8:  gap_label = "SOLID"
    elif gap >= 3:  gap_label = "TWEENER"
    elif gap >= 1 and min_trait >= 7:
                    gap_label = "COMPRESSION"  # v2.2 NEW: complete player
    else:           gap_label = "NO_FIT"

    # Override
    if override_arch and override_arch in scores:
        best_name = override_arch
        best_raw = scores[override_arch]

    # Composite
    pvc = PVC.get(pos, 1.0)
    raw = best_raw + override_delta
    composite = round(raw * pvc, 1)

    # Tier
    def tier(s):
        if s >= 85: return "ELITE"
        if s >= 70: return "APEX"
        if s >= 55: return "SOLID"
        if s >= 40: return "DEVELOPMENTAL"
        return "ARCHETYPE_MISS"
    t_label = tier(composite)

    # Capital
    cap_base = {"ELITE":"Top 5–10","APEX":"R1 Picks 11–32","SOLID":"R1 Late/Early R2",
                "DEVELOPMENTAL":"R2–R3","ARCHETYPE_MISS":"R3+"}
    capital = cap_base[t_label]
    upgrades = []
    if schwesinger_full: upgrades.append("+1 full round (Schwesinger Full)")
    elif schwesinger_half: upgrades.append("+0.5 round (Schwesinger Half)")
    if smith: upgrades.append("-1 round (Smith Rule)")
    if gap_label == "TWEENER": upgrades.append("-1 round (Tweener FM-6 discount)")
    if override_delta != 0: upgrades.append(f"Override Δ{override_delta:+.1f}: {override_rationale}")

    return {
        "archetype": best_name,
        "raw": raw,
        "pvc": pvc,
        "composite": composite,
        "tier": t_label,
        "capital": capital,
        "capital_adjustments": upgrades,
        "gap": gap,
        "gap_label": gap_label,
        "all_scores": sv,
        "schwesinger_full": schwesinger_full,
        "schwesinger_half": schwesinger_half,
        "smith_rule": smith,
        "char_composite": char_comp,
        "adjusted_traits": t,
    }

# Export for use
if __name__ == "__main__":
    # Quick test
    r = evaluate(
        traits=[9,7,8,8,9,7,8,8],
        prefix="OC-", pos="C",
        char=[9,9,9]
    )
    print("Jared Wilson test:")
    print(f"  Archetype: {r['archetype']}  Gap: {r['gap']} [{r['gap_label']}]")
    print(f"  Composite: {r['composite']}  Tier: {r['tier']}  Capital: {r['capital']}")
    for adj in r['capital_adjustments']: print(f"    + {adj}")

    r2 = evaluate(
        traits=[9,7,8,7,10,8,8,7],
        prefix="ILB-", pos="ILB",
        char=[10,10,9]
    )
    print("\nSchwesinger test:")
    print(f"  Archetype: {r2['archetype']}  Gap: {r2['gap']} [{r2['gap_label']}]")
    print(f"  Composite: {r2['composite']}  Tier: {r2['tier']}  Capital: {r2['capital']}")
    for adj in r2['capital_adjustments']: print(f"    + {adj}")