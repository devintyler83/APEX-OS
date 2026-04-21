"""
Seed record: Jacob Rodriguez | ILB-1 Green Dot Anchor | Texas Tech | 2026
Session 89 -- Sports Almanac Mode 1 archetype correction
ILB-2 Coverage Eraser -> ILB-1 Green Dot Anchor

Usage:
    python -m scripts.seed_rodriguez_s89 --apply 0   # dry run
    python -m scripts.seed_rodriguez_s89 --apply 1   # write
"""
import argparse
import sqlite3
from datetime import datetime, timezone
from draftos.config import PATHS

PROSPECT_ID = 19
SEASON_ID   = 1
MODEL       = "apex_v2.3"
APEX_ID     = 283
DIV_ID      = 7160


def run(apply: bool) -> None:
    db_path = PATHS.db
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")

    # -- Verify pre-conditions ---------------------------------------------
    cur.execute(
        "SELECT display_name, position_group, school_canonical, is_active "
        "FROM prospects WHERE prospect_id=? AND season_id=?",
        (PROSPECT_ID, SEASON_ID),
    )
    row = cur.fetchone()
    if row is None:
        print(f"[ERROR] prospect_id={PROSPECT_ID} not found -- aborting.")
        conn.close()
        return
    print(f"[PRE-CHECK] pid={PROSPECT_ID}  {row['display_name']}  "
          f"pos={row['position_group']}  school={row['school_canonical']}  "
          f"is_active={row['is_active']}")

    cur.execute(
        "SELECT apex_id, matched_archetype, raw_score, pvc, apex_composite, "
        "apex_tier, failure_mode_primary, capital_base FROM apex_scores "
        "WHERE apex_id=?",
        (APEX_ID,),
    )
    old = cur.fetchone()
    if old is None:
        print(f"[ERROR] apex_id={APEX_ID} not found -- aborting.")
        conn.close()
        return
    print(f"[PRE-STATE] apex_id={APEX_ID}  archetype={old['matched_archetype']}  "
          f"raw={old['raw_score']}  composite={old['apex_composite']}  "
          f"tier={old['apex_tier']}  FM={old['failure_mode_primary']}  "
          f"capital={old['capital_base']}")

    if not apply:
        print("\n[DRY RUN] All writes listed below -- run with --apply 1 to execute.\n")

    print("\n-- 1. UPDATE apex_scores (apex_id=283) -----------------------------")
    print(f"  matched_archetype  : ILB-2 Coverage Eraser -> ILB-1 Green Dot Anchor")
    print(f"  raw_score          : {old['raw_score']} -> 76.5")
    print(f"  apex_composite     : {old['apex_composite']} -> 65.0")
    print(f"  apex_tier          : {old['apex_tier']} -> DAY2")
    print(f"  v_processing       : 6.8 -> 9.0  (ILB-1 weight bump 28%)")
    print(f"  v_athleticism      : 8.7 -> 8.0")
    print(f"  v_scheme_vers      : 7.2 -> 5.0  (PAA Q3 FAILED -- hard cap)")
    print(f"  v_comp_tough       : 7.1 -> 8.0")
    print(f"  v_character        : 7.3 -> 7.0")
    print(f"  v_dev_traj         : 6.9 -> 6.0")
    print(f"  v_production       : 6.4 -> 7.0")
    print(f"  v_injury           : 8.2 -> 7.0")
    print(f"  FM primary         : FM-3 -> FM-6 Role Mismatch")
    print(f"  FM secondary       : FM-6 -> FM-2 Scheme Misfit")
    print(f"  capital_base       : R4 -> R3 Early")
    print(f"  eval_confidence    : Tier B (unchanged)")

    if apply:
        cur.execute("""
            UPDATE apex_scores SET
              matched_archetype      = 'ILB-1 Green Dot Anchor',
              v_processing           = 9.0,
              v_athleticism          = 8.0,
              v_scheme_vers          = 5.0,
              v_comp_tough           = 8.0,
              v_character            = 7.0,
              v_dev_traj             = 6.0,
              v_production           = 7.0,
              v_injury               = 7.0,
              raw_score              = 76.5,
              apex_composite         = 65.0,
              apex_tier              = 'DAY2',
              eval_confidence        = 'Tier B',
              failure_mode_primary   = 'FM-6 Role Mismatch',
              failure_mode_secondary = 'FM-2 Scheme Misfit',
              capital_base           = 'R3 Early',
              capital_adjusted       = 'R3 Early / R2 Late (landing-spot conditional)',
              override_arch          = 'ILB-1',
              override_delta         = 4.0,
              override_rationale     = ?
            WHERE apex_id = 283
        """, (
            "S89 Sports Almanac archetype correction: ILB-2 Coverage Eraser rejected. "
            "ILB-1 Green Dot Anchor confirmed via processing-first mechanism "
            "(Play Recognition=92, Blk Shed=98). Scheme Versatility hard-capped at 5.0 "
            "-- PAA Q3 failed (Man=30, Zone=34). FM-6 primary: scheme-adjusted snap share "
            "35-40% in nickel-primary NFL context. FM-2 secondary. Capital R3 Early base "
            "/ R2 Late upside (landing-spot conditional). Post-draft validation: "
            "Year 1 snap share >=55% confirms FM-6 overstated.",
        ))
        print(f"  [OK] apex_scores updated")

    # -- 2. Notes ----------------------------------------------------------
    notes = [
        (
            "paa_trace",
            (
                "PAA STATUS: PARTIAL (Q1 CLEAR, Q2 CLEAR w/ caveat, Q3 FAILED, Q4 FM-6 elevated)\n"
                "Q1 Production Authenticity: CLEAR -- 4 INT, 7 FF, 103 tackles vs SEC-caliber competition. "
                "Quantitative production gate passed. Minor caveat: run-stop heavy sample; coverage reps "
                "limited in base 4-2-5.\n"
                "Q2 Athleticism/Size Gate: CLEAR w/ caveat -- RAS 9.61 (elite tier). 40-time and explosion "
                "metrics support every-down base deployment. Caveat: size profile (6-1/232) adequate but "
                "not prototypical for true stack-and-shed ILB-1. Physical gate CLEAR; prototypicality PARTIAL.\n"
                "Q3 Coverage Mechanism: FAILED -- Man coverage grade=30, Zone coverage grade=34. Both grades "
                "disqualify every-down ILB-1 deployment in nickel-primary NFL. Capital-determinative gate. "
                "Coverage limitations confirmed as structural, not developmental.\n"
                "Q4 ILB-1 Green Dot Mechanism: FM-6 ELEVATED -- processing and play recognition confirmed "
                "elite (PR=92, anticipatory read pre-snap). Green Dot aptitude is legitimate. FM-6 activates "
                "because full-time snap role in 3-LB base is increasingly rare. Scheme-dependent role "
                "confirmed at 35-40% base snaps in nickel-primary deployment."
            ),
        ),
        (
            "divergence_analysis",
            (
                "DIVERGENCE WATCH: APEX_LOW vs consensus R2 Early (picks 33-50). "
                "APEX base: R3 Early (picks 65-80). Delta: ~1.5 rounds.\n\n"
                "PATTERN A -- Coverage Mechanism Failure (capital-determinative):\n"
                "PAA Q3 failed. Man=30, Zone=34 disqualify every-down ILB-1 deployment. Consensus "
                "credits RAS 9.61 + 4 INT + 7 FF as primary capital signals without applying a "
                "coverage execution floor. The split is at the PAA coverage authenticity premise.\n\n"
                "PATTERN B -- Confidence-Weighting vs Ceiling-Direct Pricing:\n"
                "APEX assigns Tier B with FM-6 active. Scheme-dependent snap share (35-40% base "
                "package only) structurally reduces probability-weighted capital in nickel-primary "
                "landing spots. Consensus prices the ceiling (R2 Late) without scheme-adjusted snap "
                "projection. The split is at the confidence-weighting premise.\n\n"
                "RESOLUTION TRIGGER: LANDING_SPOT_CONFIRMED\n"
                "RESOLUTION METRIC: Year 1 snap share >=55% confirms FM-6 overstated; "
                "35-40% confirms divergence called correctly."
            ),
        ),
        (
            "landing_spot_flag",
            (
                "LANDING SPOT FLAG -- REQUIRED before capital above R3 Early is finalized.\n"
                "Optimal: 3-4 base heavy scheme, DC-empowered Green Dot role, coverage-shielded "
                "deployment (matched on TE/RB, not WR/slot). Target schemes: 3-4 defense with "
                "heavy base package usage.\n"
                "Avoid: Nickel-primary, 4-2-5 base, every-down coverage demands on WRs/slot. "
                "FM-6 activates fully in these destinations.\n"
                "Demario Davis (NO/BAL) represents the ceiling deployment -- DC-maximized ILB-1 "
                "with coverage limitations managed by scheme."
            ),
        ),
        (
            "validation_trigger",
            (
                "POST-DRAFT VALIDATION TRIGGER: Year 1 snap share threshold = 55%.\n"
                ">=55%: FM-6 overstated. Upgrade capital toward R2 Late range. "
                "ILB-1 Green Dot mechanism confirmed at NFL level.\n"
                "35-40%: Divergence called correctly. R3 Early capital confirmed. "
                "FM-6 structural -- nickel compression is real.\n"
                "<35%: Consider FM-6 BUST confirmation (Deion Jones path). "
                "Flag for post-Year-1 audit."
            ),
        ),
    ]

    print("\n-- 2. INSERT notes (4 rows) ----------------------------------------")
    for note_type, note_text in notes:
        print(f"  note_type={note_type}")
        if apply:
            cur.execute(
                "INSERT INTO notes (prospect_id, note_type, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (PROSPECT_ID, note_type, note_text, now, now),
            )
    if apply:
        print("  [OK] 4 notes inserted")

    # -- 3. Override log ---------------------------------------------------
    print("\n-- 3. INSERT override_log (archetype correction) -------------------")
    print(f"  ILB-2 Coverage Eraser -> ILB-1 Green Dot Anchor  |  delta=+4.0pts composite")
    if apply:
        cur.execute("""
            INSERT INTO override_log
              (prospect_id, season_id, model_version, override_type, field_changed,
               old_value, new_value, magnitude, rationale, applied_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            PROSPECT_ID, SEASON_ID, MODEL,
            "archetype_correction",
            "matched_archetype",
            "ILB-2 Coverage Eraser",
            "ILB-1 Green Dot Anchor",
            4.0,
            (
                "S89 Sports Almanac Mode 1 Deep Dive. Play Recognition=92 confirms "
                "processing-first mechanism consistent with ILB-1 Green Dot Anchor, not ILB-2. "
                "PAA Q3 failed (Man=30, Zone=34) -- coverage eraser archetype disqualified. "
                "FM-6 primary replaces FM-3. Capital R3 Early (was R4). "
                "Comp set: Demario Davis R3 HIT / Bobby Wagner R2 ceiling / "
                "Deion Jones bust reference."
            ),
            "analyst",
        ))
        print("  [OK] override_log row inserted")

    # -- 4. Prospect comps -------------------------------------------------
    comps = [
        (
            "hit", "Primary Hit / Mechanism Match", "Demario Davis",
            (
                "Processing-first Green Dot ILB-1. Coverage limitations at draft time; scheme maximized "
                "the ILB-1 function (NO/BAL DC-empowered role). Capital match: R3 2012. Mechanism: "
                "anticipatory read pre-snap, Green Dot, coverage-shielded deployment. "
                "Hit confirmed -- Pro Bowl ILB in correct scheme."
            ),
            "2012", 1,
        ),
        (
            "hit", "Ceiling / Landing-Spot Conditional", "Bobby Wagner",
            (
                "Ceiling comp only -- coverage developed to elite by Year 3+. Wagner required "
                "multi-year scheme investment to reach every-down value; Rodriguez requires same "
                "development arc to approach this outcome. Capital was R2 2012 -- represents upside "
                "scenario (landing-spot conditional). R2 Late capital only with PAA Q3 confirmation."
            ),
            "2012", 2,
        ),
        (
            "miss", "Bust Reference / FM-6 Warning", "Deion Jones",
            (
                "Bust reference -- FM-6 snap compression in nickel-primary scheme. Athleticism + "
                "processing projected to every-down value; FM-6 activated when snap share compressed "
                "in nickel-primary defense. Closest capital warning for wrong landing spot. "
                "R2 2016 -- over-drafted relative to scheme limitation."
            ),
            "2016", 3,
        ),
    ]

    print("\n-- 4. INSERT prospect_comps (3 rows) -------------------------------")
    for comp_type, type_label, player_name, desc, years, sort_order in comps:
        print(f"  [{comp_type}] {player_name} ({years}) -- {type_label}")
        if apply:
            cur.execute("""
                INSERT INTO prospect_comps
                  (prospect_id, season_id, comp_type, type_label, player_name,
                   description, years, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                PROSPECT_ID, SEASON_ID, comp_type, type_label,
                player_name, desc, years, sort_order,
            ))
    if apply:
        print("  [OK] 3 comps inserted")

    # -- 5. Update divergence_flags ----------------------------------------
    print("\n-- 5. UPDATE divergence_flags (div_id=7160) ------------------------")
    print(f"  apex_composite  : 61.0 -> 65.0")
    print(f"  apex_tier       : DAY2 -> DAY2 (unchanged)")
    print(f"  apex_capital    : R4 -> R3 Early")
    print(f"  divergence_flag : APEX_LOW_PVC_STRUCTURAL (unchanged)")
    print(f"  divergence_mag  : MINOR -> MODERATE")
    print(f"  rounds_diff     : -> 1.5")
    if apply:
        cur.execute("""
            UPDATE divergence_flags SET
              apex_composite   = 65.0,
              apex_tier        = 'DAY2',
              apex_capital     = 'R3 Early',
              divergence_flag  = 'APEX_LOW_PVC_STRUCTURAL',
              divergence_mag   = 'MODERATE',
              rounds_diff      = 1.5,
              computed_at      = ?,
              model_version    = ?
            WHERE div_id = ?
        """, (now, MODEL, DIV_ID))
        print("  [OK] divergence_flags updated")

    if apply:
        conn.commit()
        print("\n[COMMITTED] All writes applied.")
    else:
        conn.rollback()
        print("\n[DRY RUN COMPLETE] No writes applied. Run with --apply 1 to execute.")

    conn.close()

    # -- Post-write verification -------------------------------------------
    if apply:
        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        cur2 = conn2.cursor()

        cur2.execute(
            "SELECT matched_archetype, raw_score, pvc, apex_composite, apex_tier, "
            "eval_confidence, failure_mode_primary, failure_mode_secondary, "
            "capital_base, capital_adjusted "
            "FROM apex_scores WHERE apex_id=?",
            (APEX_ID,),
        )
        v = cur2.fetchone()
        print("\n-- VERIFICATION --------------------------------------------------")
        print(f"  apex_scores apex_id={APEX_ID}:")
        print(f"    archetype    = {v['matched_archetype']}")
        print(f"    raw / pvc / composite = {v['raw_score']} / {v['pvc']} / {v['apex_composite']}")
        print(f"    tier         = {v['apex_tier']}")
        print(f"    FM           = {v['failure_mode_primary']} / {v['failure_mode_secondary']}")
        print(f"    capital_base = {v['capital_base']}")

        cur2.execute(
            "SELECT COUNT(*) as cnt FROM notes WHERE prospect_id=?",
            (PROSPECT_ID,),
        )
        n = cur2.fetchone()
        print(f"  notes rows for pid={PROSPECT_ID}: {n['cnt']}")

        cur2.execute(
            "SELECT COUNT(*) as cnt FROM prospect_comps WHERE prospect_id=? AND season_id=?",
            (PROSPECT_ID, SEASON_ID),
        )
        c = cur2.fetchone()
        print(f"  prospect_comps rows for pid={PROSPECT_ID}: {c['cnt']}")

        cur2.execute(
            "SELECT divergence_flag, divergence_mag, rounds_diff, apex_composite, apex_capital "
            "FROM divergence_flags WHERE div_id=?",
            (DIV_ID,),
        )
        d = cur2.fetchone()
        print(f"  divergence_flags div_id={DIV_ID}:")
        print(f"    flag={d['divergence_flag']}  mag={d['divergence_mag']}  "
              f"rounds_diff={d['rounds_diff']}  composite={d['apex_composite']}  "
              f"capital={d['apex_capital']}")

        conn2.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Rodriguez S89 archetype correction")
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    run(apply=bool(args.apply))
