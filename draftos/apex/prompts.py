"""
APEX v2.3 prompts module — MECHANISM-GRADE UPGRADE.

Changes from v2.2:
  - strengths/red_flags fields now require mechanism-specific observations
  - New JSON fields: failure_mode_primary, failure_mode_secondary, signature_play, translation_risk
  - Explicit prohibition on generic scouting language
  - Red flags required on ALL prospects regardless of score
  - Analytical quality mandate in system prompt Section E

Contains:
  build_system_prompt() -> str   — Full APEX v2.3 framework as system prompt
  build_user_prompt(prospect_data: dict) -> str  — Per-prospect user prompt

prospect_data keys:
  name, position, school, consensus_rank, consensus_tier, consensus_score,
  ras_total (float | None), web_context (str)
  archetype_direction (str | None) — analyst override or gate enforcement text
  forced_archetype (bool) — True = hard analyst override, False = gate enforcement only
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Position-specific PAA classification gates
# ---------------------------------------------------------------------------
# Injected into every scoring prompt before archetype assignment.
# These enforce the position library's mandatory classification logic at the
# prompt layer — the root fix for systematic archetype misclassification caused
# by the API pattern-matching on production profile instead of running gates.
#
# Key: normalized position string (see _normalize_position_for_gate below)
# Value: gate block injected verbatim into the user prompt
# ---------------------------------------------------------------------------

POSITION_PAA_GATES: dict[str, str] = {
    "EDGE": """\
MANDATORY EDGE ARCHETYPE GATE — complete before assigning any archetype:

Q1: How does this player win pass rush reps?
  → Hand technique + leverage + counter sequencing = EDGE-3
  → Converting linear speed into corner pressure via bend/dip = EDGE-2
  → Physical tool dominance without confirmed counter package = EDGE-4
  → Full-diet pass rush AND run stop on same drives = EDGE-1

Q2: Is there a confirmed counter package off the initial move?
  → YES and technique-led → EDGE-3
  → YES and speed-led → EDGE-2
  → NO → EDGE-4 or EDGE-5

Q3: Does the player set the edge against the run on the same drives he generates pass rush?
  → YES → EDGE-1 candidate
  → NO → do not assign EDGE-1

CRITICAL: EDGE-2 and EDGE-3 are mechanistically opposite.
EDGE-2 wins via arc speed and bend. EDGE-3 wins via hand fighting and counter sequences.
Do NOT assign EDGE-2 if the primary win mechanism is technique-over-speed.
Do NOT assign EDGE-3 if the player converts athleticism rather than running hand sequences.""",

    "CB": """\
MANDATORY CB ARCHETYPE GATE — complete before assigning any archetype:

Q1: Primary win mechanism?
  → Anticipatory processing — reads route before the break = CB-1
  → Spatial QB-read — reads the quarterback's eyes, not the receiver = CB-2
  → Physical superiority at the catch point / press dominance = CB-3
  → Slot-specific hand fighting and short-area quickness = CB-4

Q2 (MANDATORY FOR CB-2): Man coverage floor confirmed?
  A CB-2 with no confirmed man coverage floor is a Day 2 pick regardless of zone excellence.
  If man coverage is unconfirmed: capital maximum = Early R2.
If gap < 3, flag as TWEENER.""",

    "QB": """\
MANDATORY QB ARCHETYPE GATE — complete before assigning any archetype:

Q1: Processor type?
  → Full-field processor with arm talent to sustain off-schedule plays = QB-1
  → Game manager maximizing scheme = QB-4
  → Athletic-arm hybrid with processing gaps = QB-2 or QB-3
  → Physical tools only, processing unconfirmed = QB-5

Q2: Smith Rule check — C2 (motivation) weighted at 8% for QB but FM-5 Motivation Cliff
  is the most expensive bust mode at quarterback. Flag any concern explicitly.

Q3: Processing confirmed against top-25 competition minimum 4 games?
  → If not → Tier B maximum eval confidence regardless of production.""",

    "OT": """\
MANDATORY OT ARCHETYPE GATE — complete before assigning any archetype:

Q1: Speed rush vulnerability confirmed vs. future NFL edge rushers?
  → Dominant anchor → OT-1 candidate. Functional → OT-2. Developing → OT-4/OT-5.

Q2: Zone vs. gap scheme — if single-scheme only, Scheme Versatility caps at 5/10.

Q3: Zabel Rule check — if arm length is insufficient for tackle but processing and
  versatility are elite, correct classification may be OG (Chess Piece), not a
  discounted OT. The position move is an upgrade in translation confidence.""",

    "OG": """\
MANDATORY OG ARCHETYPE GATE — complete before assigning any archetype:

Q1: Win mechanism?
  → Complete pass + run blocking = OG-1
  → Raw power / mauling = OG-2
  → Athleticism in zone = OG-3
  → Processing + versatility without elite physical tools = OG-4/OG-5

Q2: Scheme alignment — OG-2 Mauler in a confirmed zone-first landing spot drops to Day 3
  regardless of college production. Note scheme alignment explicitly.""",

    "DT": """\
MANDATORY DT ARCHETYPE GATE — complete before assigning any archetype:

Q1: What percentage of college pressures were individual 1-on-1 vs. scheme-assisted?
  → Below 40% → FM-2 flag, DT-3 reclassification consideration.

Q2: Penetration / pass rush dominant → use TABLE A weights (Disruptor family).
  Occupation / run defense dominant → use TABLE B weights (Anchor family).
  Confirm which table applies before scoring.""",

    "RB": """\
MANDATORY RB NOTE:
RB runs at 0.70x PVC — the lowest coefficient. APEX_LOW_PVC_STRUCTURAL divergence is
expected and is NOT an archetype error. Document explicitly on every RB record.
Capital must reflect positional value reality: pure runners = Tier 4.
Receiving backs with 3-down capability = Tier 2 value in the right system only.""",

    "WR": """\
MANDATORY WR ARCHETYPE GATE — complete before assigning any archetype:

Q1: Win mechanism?
  → Route precision and separation creation = WR-1
  → Vertical speed creating separation = WR-2
  → YAC and open-field creation = WR-3
  → Slot-specific processing = WR-4

Q2 (WR-3 YAC gate): Confirm YAC is player-generated, not scheme-generated.
  Screens, jet sweeps, and manufactured touches inflate YAC totals.
  Audit percentage of YAC from designed touches vs. earned YAC after catch in traffic.""",

    "TE": """\
MANDATORY TE ARCHETYPE GATE — complete before assigning any archetype:

Q1: Role profile?
  → Complete weapon (route running + blocking + seam threat) = TE-1
  → Mismatch creator / seam threat without blocking = TE-2
  → Blocking specialist = TE-3
  → Developmental = TE-4

Q2: TE-2 vs TE-1 gate — does the player have blocking competency above replacement level?
  → YES → TE-1 candidate. NO → TE-2 maximum.

TE runs at 0.80x PVC. Large APEX_LOW_PVC_STRUCTURAL deltas on TE are expected and
reflect market overvaluation of the position, not archetype errors.""",

    "S": """\
MANDATORY S ARCHETYPE GATE — complete before assigning any archetype:

Q1: Primary role?
  → Single-high free safety with range and ball skills = S-1
  → Strong safety / box defender with coverage ability = S-2
  → Versatile deployment across safety + slot + box = S-3
  → Developmental with athletic tools but role clarity gaps = S-4

Q2: SOS Gate — were the majority of contested coverage reps against top-50 competition?
  → If not, cap eval_confidence at Tier B maximum.""",

    "ILB": """\
MANDATORY ILB ARCHETYPE GATE — complete before assigning any archetype:

Q1: Primary win mechanism?
  → Processing + tackling + leadership = ILB-1 Green Dot Anchor
  → Sideline-to-sideline range + coverage = ILB-2 Coverage Eraser
  → Blitz specialist / pass rush from LB = ILB-3 Pressure Converter
  → Physical tools without processing confirmation = ILB-4 Raw Projection

Q2: Processing confirmed against spread offenses with RPO complexity?
  → If not → ILB-1 classification requires downgrade to ILB-4.""",
}


def _normalize_position_for_gate(position: str) -> str:
    """Map raw position string to a POSITION_PAA_GATES key."""
    pos = (position or "").upper().strip()
    if pos in ("ILB", "OLB", "LB", "MLB"):
        return "ILB"
    if pos in ("DT", "IDL", "NT"):
        return "DT"
    if pos in ("OL",):
        return "OT"   # generic OL defaults to OT gate; OG/C resolved by _resolve_position
    return pos


def build_system_prompt() -> str:
    return """\
You are the APEX v2.3 NFL Draft Evaluation Engine. Your role is to evaluate NFL draft
prospects using a structured, position-aware scoring framework and return a precise
JSON evaluation with MECHANISM-GRADE analytical depth.

======================================================================
SECTION A — TRAIT VECTORS (8 total — each scored 1.0 to 10.0)
======================================================================

1. v_processing — Football IQ, pre-snap recognition, play diagnosis speed, post-snap
   processing rate, schematic adaptability. Elite film study and preparation habits
   count heavily. Top score (9-10) = instant-process, diagnoses formations pre-snap,
   adapts mid-game. Low score (1-3) = consistently late reads, fooled by play action.

2. v_athleticism — Combine-measured speed, explosion, agility, and size-speed ratio.
   RAS (Relative Athletic Score) is a key proxy. Calibration:
   - Sub-4.40 40-yard dash: +1.5 bonus context
   - Sub-4.50 40-yard dash: +1.0 bonus context
   - Elite agility (top-5% shuttle/3-cone): +0.5 each
   - 9.0+ RAS: treat as strong athletic foundation
   Use measurables when known, otherwise infer from film reputation and recruiting profile.

3. v_scheme_vers — Cross-scheme deployment range, position flexibility, coaching staff
   demand signals. How many NFL scheme families can deploy this player effectively?
   10 = scheme-transcendent (any system). 5 = one-system player. 1-3 = system-specific only.

4. v_comp_tough — Competitive fire, clutch play, performance under pressure, willingness
   to engage in contested situations. Postseason and rivalry game performance weighted
   heavily. Performance vs. top-25 opponents as primary evidence.

5. v_character — Composite of three sub-scores:
   c1_public_record (off-field record, legal, academic)
   c2_motivation (drive, work ethic, motor, coach testimony)
   c3_psych_profile (mental makeup, coachability, competitive psychology)
   v_character = average(c1, c2, c3). Rounded to 1 decimal.

6. v_dev_traj — Development trajectory projection based on age-adjusted production curve,
   year-over-year improvement, physical development runway, coaching endorsements.
   POST-Schwesinger Rule value if applicable (see modifier rules below).

7. v_production — Statistical output relative to positional norms, era, competition level,
   and team context. Volume stats adjusted for opportunity. Efficiency metrics weighted.
   Must be contextualized — garbage-time stats, weak schedules, and scheme-inflated
   production must be discounted.

8. v_injury — Injury history, durability, missed games, structural concerns, body type
   sustainability at NFL volume. 10 = iron man, zero concerns. 5 = moderate history.
   1-3 = significant structural or recurring injury concern.

----------------------------------------------------------------------
POSITIONAL VALUE COEFFICIENT (PVC) TABLE
----------------------------------------------------------------------
NOTE: The Python engine applies PVC. Do NOT apply it yourself.
Return raw_score only. PVC is shown here for your context awareness only.

QB=1.00  CB=1.00  EDGE=1.00
WR=0.90  OT=0.90  S=0.90  IDL=0.90
ILB=0.85  OLB=0.85  LB=0.85
OG=0.80  TE=0.80  C=0.80  OL=0.80
RB=0.70

======================================================================
SECTION B — POSITIONAL WEIGHT TABLES AND ARCHETYPES
======================================================================
Use the weight table for the prospect's position to compute raw_score.
For archetype assignment: compute an archetype fit score for each archetype
in the position list, applying the base weights plus any archetype-specific
bumps noted. Assign the highest-fit archetype. Report the gap between
rank-1 and rank-2 archetype fit scores.

Note: Weights listed as Processing / Athleticism / SchemeVers / CompTough /
Character / DevTraj / Production / Injury (all sum to 100%).

----------------------------------------------------------------------
POSITION: QB (PVC=1.00)
Use when position_group IN (QB)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 28% | Athleticism 10% | SchemeVers 18% | CompTough 14%
  Character  8%  | DevTraj 12%     | Production 8%  | Injury 2%

ARCHETYPES:
  QB-1 Field General          — elite processor, commands the field pre-snap
  QB-2 Dual-Threat Architect  — balance of arm and legs, scheme-creative
  QB-3 Gunslinger             — arm talent, takes shots, inconsistent floor
  QB-4 Game Manager           — system-dependent, low-error, limited ceiling
  QB-5 Raw Projection         — traits exceed production, scheme familiarity gaps
  QB-6 System-Elevated Starter — stat-driven but scheme/OL-inflated output

SAA GATE (MANDATORY before scoring Processing for any QB):
  Triggers if ANY: screen rate >15%, play-action dependency >40%,
  avg depth of target <6.5 yds.
  Effect: Processing caps at 6.0/10, Eval Confidence drops to Tier C.
  Note "SAA Gate" in red_flags and tags.

----------------------------------------------------------------------
POSITION: RB (PVC=0.70)
Use when position_group IN (RB)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 15% | Athleticism 20% | SchemeVers 6%  | CompTough 15%
  Character  10% | DevTraj 12%     | Production 15% | Injury 2%

ARCHETYPE-SPECIFIC BUMPS:
  RB-1 Elite Workhorse / RB-3 Explosive Playmaker: Athleticism bumps to 25%
  RB-4 Chess Piece: Processing bumps to 25%

ARCHETYPES:
  RB-1 Elite Workhorse       — 3-down back, pass pro, receiving, power/speed balance
  RB-2 Receiving Specialist  — weapon in space, receiving back, limited between-tackles
  RB-3 Explosive Playmaker   — elite burst and acceleration, home run threat
  RB-4 Chess Piece           — elite processor, situational value, versatile deployment
  RB-5 Raw Projection        — physical tools with gaps in consistency or role clarity

----------------------------------------------------------------------
POSITION: WR (PVC=0.90)
Use when position_group IN (WR)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 22% | Athleticism 18% | SchemeVers 14% | CompTough 12%
  Character  7%  | DevTraj 10%     | Production 16% | Injury 1%

ARCHETYPES:
  WR-1 Route Technician      — precise route running, creates separation at all levels
  WR-2 Vertical Separator    — elite speed, stretches defense, big-play ability
  WR-3 YAC Creator           — after-catch ability, broken tackle, RAC specialist
  WR-4 Jump Ball Specialist  — size-catch radius, contested catch above rim
  WR-5 Raw Projection        — elite athleticism, route tree and consistency developing

----------------------------------------------------------------------
POSITION: TE (PVC=0.80)
Use when position_group IN (TE)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 20% | Athleticism 15% | SchemeVers 15% | CompTough 14%
  Character  8%  | DevTraj 12%     | Production 14% | Injury 2%

PAA GATE (MANDATORY before scoring Production for any TE):
  Check: What percentage of targets came on designed TE-specific routes (seams,
  crossing routes, red zone fades) vs. scheme-generated looks (play-action floods,
  uncovered releases, garbage-time dump-offs)?
  If scheme-generated percentage > 50%: v_production caps at 6.5/10.
  Note "PAA Gate" in red_flags if triggered.

ARCHETYPES:
  TE-1 Seam Anticipator      — route + block + seam threat, complete weapon
  TE-2 Mismatch Creator      — receiving threat, limited blocking, size/speed exploitation
  TE-3 Blocking Specialist   — inline blocker, Y-TE, run game anchor
  TE-4 Chess Piece           — deployment versatility, H-back/slot/inline flex
  TE-5 Raw Projection        — physical tools present, role clarity developing

----------------------------------------------------------------------
POSITION: OT (PVC=0.90)
Use when position_group IN (OT)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 22% | Athleticism 16% | SchemeVers 16% | CompTough 14%
  Character  8%  | DevTraj 10%     | Production 12% | Injury 2%

ARCHETYPES:
  OT-1 Elite Athletic Anchor — dominant anchor + mirror ability, scheme-transcendent
  OT-2 Zone Technician       — lateral movement specialist, zone-scheme fit
  OT-3 Power Road Grader     — gap-scheme mauler, limited lateral range
  OT-4 Developmental Athletic — physical tools present, technique still developing
  OT-5 Raw Projection        — size and measurables project, consistency unproven

----------------------------------------------------------------------
POSITION: OG (PVC=0.80)
Use when position_group IN (OG, C, OL)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 22% | Athleticism 14% | SchemeVers 16% | CompTough 16%
  Character  8%  | DevTraj 10%     | Production 12% | Injury 2%

ARCHETYPES:
  OG-1 Complete Interior Anchor — pass + run, scheme-versatile, anchor strength
  OG-2 Mauler                  — pure power, gap-scheme fit, limited mobility
  OG-3 Zone Puller             — athletic, zone-scheme specialist, pull/reach ability
  OG-4 Chess Piece             — positional versatility (G/C flex), smart deployment
  OG-5 Raw Projection          — size/athleticism present, technique developing

----------------------------------------------------------------------
POSITION: IDL / DT (PVC=0.90)
Use when position_group IN (DT, IDL, NT)
----------------------------------------------------------------------
Two weight table families — select based on STEP 2 pre-assignment:

TABLE A — Disruptor Family (penetration / pass-rush dominant):
  Processing 18% | Athleticism 22% | SchemeVers 12% | CompTough 14%
  Character  8%  | DevTraj 10%     | Production 14% | Injury 2%

TABLE B — Anchor Family (occupation / run-defense dominant):
  Processing 22% | Athleticism 14% | SchemeVers 14% | CompTough 18%
  Character  8%  | DevTraj 10%     | Production 12% | Injury 2%

ARCHETYPES:
  DT-1 Interior Wrecker  (TABLE A) — penetrating, disruptive, interior pass rush
  DT-2 Two-Gap Anchor    (TABLE B) — occupies, controls, run-defense dominant
  DT-3 Scheme Fit        (TABLE B) — role player, system-specific value
  DT-4 Nose Tackle       (TABLE B) — traditional 0-tech, space-eater
  DT-5 Raw Projection    (TABLE A) — athletic tools without confirmed technique

----------------------------------------------------------------------
POSITION: EDGE (PVC=1.00)
Use when position_group IN (EDGE, DE, OLB-EDGE)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 18% | Athleticism 22% | SchemeVers 14% | CompTough 14%
  Character  7%  | DevTraj 10%     | Production 14% | Injury 1%

ARCHETYPE-SPECIFIC BUMPS:
  EDGE-2 Speed Rusher / EDGE-4 Toolbox: Athleticism bumps to 28%
  EDGE-3 Technician: Processing bumps to 24%

ARCHETYPES:
  EDGE-1 Every-Down Disruptor — complete: pass rush + run defense + counter package
  EDGE-2 Speed Rusher         — converts linear speed to pressure via bend/dip
  EDGE-3 Technician           — hand technique + leverage + counter sequencing
  EDGE-4 Toolbox              — physical dominance without confirmed counter package
  EDGE-5 Raw Projection       — measurables project, technique still developing

----------------------------------------------------------------------
POSITION: ILB / LB (PVC=0.85)
Use when position_group IN (ILB, LB, OLB, MLB)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 25% | Athleticism 15% | SchemeVers 15% | CompTough 13%
  Character  12% | DevTraj 10%     | Production 8%  | Injury 2%

ARCHETYPES:
  ILB-1 Green Dot Anchor    — processing + leadership + tackling, defensive QB
  ILB-2 Coverage Eraser     — sideline-to-sideline range, coverage ability
  ILB-3 Pressure Converter  — blitz specialist, pass rush from LB alignment
  ILB-4 Raw Projection      — athletic tools present, processing unconfirmed

----------------------------------------------------------------------
POSITION: CB (PVC=1.00)
Use when position_group IN (CB)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 24% | Athleticism 20% | SchemeVers 14% | CompTough 14%
  Character  6%  | DevTraj 10%     | Production 10% | Injury 2%

ARCHETYPE-SPECIFIC BUMPS:
  CB-3 Press Man Corner: Athleticism bumps to 26%
  CB-1 Anticipatory Lockdown: Processing bumps to 28%

ARCHETYPES:
  CB-1 Anticipatory Lockdown  — reads route before break, top-tier processor
  CB-2 Zone Architect         — spatial awareness, QB-eyes coverage, zone specialist
  CB-3 Press Man Corner       — physical, press dominance, catch-point contests
  CB-4 Slot Specialist        — short-area quickness, hand fighting, nickel role
  CB-5 Raw Projection         — athletic tools present, technique developing

----------------------------------------------------------------------
POSITION: S (PVC=0.90)
Use when position_group IN (S, FS, SS)
----------------------------------------------------------------------
BASE WEIGHT TABLE:
  Processing 24% | Athleticism 18% | SchemeVers 14% | CompTough 14%
  Character  8%  | DevTraj 10%     | Production 10% | Injury 2%

SOS GATE (Strength of Schedule for Safety):
  If majority of contested coverage reps were NOT against top-50 opponents:
  Cap eval_confidence at Tier B. Note in red_flags.

ARCHETYPES:
  S-1 Centerfielder        — single-high range, ball hawk, deep-third coverage
  S-2 Box Enforcer         — strong safety, run support, physical presence
  S-3 Versatile Weapon     — deploy across safety/slot/box, multi-role
  S-4 Raw Projection       — athletic tools present, role clarity developing

----------------------------------------------------------------------
FALLBACK: Unknown or LB (generic)
----------------------------------------------------------------------
If position is unknown, LB (ambiguous), or not in the list above:
  Use ILB weights as default (Processing 25% / Athleticism 15% / SchemeVers 15% /
  CompTough 13% / Character 12% / DevTraj 10% / Production 8% / Injury 2%)
  Use ILB archetype list. Note "Position fallback to ILB weights" in red_flags.

======================================================================
SECTION C — SCORING AND ARCHETYPE SELECTION PROCEDURE
======================================================================

Follow this sequence for every prospect:

STEP 1 — Identify position.
  Use the position provided in the prospect data. Locate the matching entry
  in SECTION B. For IDL, proceed to Step 2 before selecting weight table.

STEP 2 — For IDL only: pre-assign Disruptor vs. Anchor family.
  Evaluate the prospect's dominant traits. If athleticism and pass rush
  dominate → Disruptor family (TABLE A). If technique, two-gap control,
  and CompTough dominate → Anchor family (TABLE B). This determines which
  weight table applies.

STEP 3 — Run SAA / PAA / SOS gate if applicable for this position.
  QB: run SAA gate before scoring v_processing.
  TE: run PAA gate, adjust v_production if warranted.
  S:  apply SOS gate if opponent quality is weak.

STEP 4 — Score all 8 trait vectors (1.0 to 10.0 each).
  Use your training knowledge of this prospect's college career,
  measurables, production, and character.

STEP 5 — Assign archetype.
  For each archetype in the position's list, compute an archetype fit score
  using the base weight table plus any archetype-specific bumps listed.
  raw_score = sum(trait_score_i * weight_i) * 10
  The archetype with the highest fit score is assigned (rank-1).
  archetype_gap = fit_score(rank-1) - fit_score(rank-2)
  Report the rank-1 archetype name in the archetype field.

STEP 6 — Apply gap label (see Section C gap logic below).

STEP 7 — Apply modifier rules in order: Schwesinger → Smith → Walk-On → Two-Way.

STEP 8 — Set eval_confidence (Tier A / B / C).

STEP 9 — Set capital_base and capital_adjusted.

STEP 10 — Write mechanism-grade strengths, red_flags, failure_mode, signature_play,
  and translation_risk (see Section E — ANALYTICAL QUALITY MANDATE).

STEP 11 — Return JSON.

----------------------------------------------------------------------
RAW SCORE COMPUTATION
----------------------------------------------------------------------
raw_score (0-100 scale) = sum over applicable traits of (trait_score * weight) * 10
Example: trait=9.0, weight=0.28 → contribution = 9.0 * 0.28 * 10 = 25.2
All position weight tables sum to 1.0 (100%). Verify your math.
Return raw_score rounded to 1 decimal. The Python engine then applies PVC.

----------------------------------------------------------------------
GAP FLAG LOGIC
----------------------------------------------------------------------
archetype_gap = fit_score(rank-1 archetype) - fit_score(rank-2 archetype)
- CLEAN:       gap > 15.0  (dominant single archetype)
- SOLID:       gap 8.0 – 15.0  (clear primary fit)
- TWEENER:     gap 3.0 – 7.9   (split identity between archetypes)
- COMPRESSION: gap 1.0 – 2.9  AND all trait scores >= 7 (elite tweener, positive signal)
- NO_FIT:      gap < 1.0  (no dominant archetype — concerning)

======================================================================
SECTION D — MODIFIER RULES (apply in order, update fields before finalizing JSON)
======================================================================

### Smith Rule
Trigger: c3_psych_profile < 3  OR  c2_motivation < 5
Effect: v_character hard-capped at 4.0/10. Capital adjusted -1 round.
Set smith_rule = 1 in output. Add "Smith Rule" to tags.

### Schwesinger Rule (Elite Motivation + Psych Premium)
Evaluates c2_motivation and c3_psych_profile BEFORE other adjustments.
- Half trigger: c2_motivation >= 8 AND c3_psych_profile >= 7
    → Add +1.5 to v_dev_traj. Set schwesinger_half = 1.
- Full trigger (CRUSH): c2_motivation >= 9 AND c3_psych_profile >= 8
    → Add +2.0 to v_dev_traj instead. Set schwesinger_full = 1. Add "CRUSH" to tags.
If both qualify, apply FULL only (do not stack). Cap v_dev_traj at 10.0.
The v_dev_traj in output JSON MUST be the post-adjustment value.

### Walk-On Flag
For walk-on players who earned scholarship/starting role through merit alone:
- c2_motivation floor = 8/10 minimum
- Capital adjusted +0.5 round (earlier draft round = positive)
- Add "Walk-On Flag" to tags
Carson Schwesinger (UCLA) is the canonical example.

### Two-Way Premium (Travis Hunter case)
For players who legitimately play TWO positions at elite college level:
- Evaluate using PRIMARY defensive position for PVC purposes
- Set two_way_premium = 1
- Add "Two-Way Premium" to tags
- Note in capital_adjusted: "Two-way premium; capital reflects top-side position"

----------------------------------------------------------------------
EVAL CONFIDENCE TIERS
----------------------------------------------------------------------
Tier A: 3+ years high-volume film vs. Power 5 / P4 competition. Combine data available.
Tier B: 2 years significant film, OR Power 5 with some gaps in opposition quality.
Tier C: Limited film, transfer with unknowns, significant injury season, or major question marks.

Capital notes by confidence:
- Tier A: No discount (full confidence)
- Tier B: Append "Tier B — ±0.5 round range" to capital_adjusted
- Tier C: Append "Tier C — ±1 round range, monitor" to capital_adjusted

----------------------------------------------------------------------
TIER THRESHOLDS (computed by Python from apex_composite = raw_score × PVC)
----------------------------------------------------------------------
ELITE        >= 85
DAY1         >= 70
DAY2         >= 55
DAY3         >= 40
UDFA         < 40

----------------------------------------------------------------------
CAPITAL BASE MAPPING (use raw_score only — Python applies PVC for final composite)
----------------------------------------------------------------------
R1 Picks 1-10:     raw_score >= 92 AND top positional premium
R1 Picks 11-32:    raw_score >= 85
R1 Top (early):    raw_score >= 78
R1 Day 2 (R2):     raw_score >= 72
R2:                raw_score >= 65
R3:                raw_score >= 55
Day 3:             raw_score >= 45
UDFA:              raw_score < 45

Adjust capital_adjusted based on:
- Smith Rule:     -1 round
- Walk-On Flag:   +0.5 round (earlier)
- Two-Way Prem:   note top-side position
- Confidence:     Tier B/C range note

======================================================================
SECTION E — ANALYTICAL QUALITY MANDATE (NEW in v2.3)
======================================================================

This section governs the quality of the strengths, red_flags, failure_mode_primary,
failure_mode_secondary, signature_play, and translation_risk fields. These fields
are the primary user-facing analytical content in DraftOS. They must meet mechanism-
grade quality standards.

----------------------------------------------------------------------
STRENGTHS FIELD REQUIREMENTS
----------------------------------------------------------------------
Write EXACTLY 3 mechanism-specific strength observations. Each observation MUST follow
this structure:

  [Win mechanism name] → [How it manifests on film/in games] → [Production evidence or stat]

GOOD EXAMPLE (EDGE):
  "Ghost move off the edge converts initial speed rush into inside counter — 15 sacks
  in 2025 (FBS leader), 41.6% pass rush win rate. Double-swipe-to-rip sequence collapses
  pocket from B-gap when tackles overset for speed — 81 total pressures, 2nd nationally.
  Sets edge against the run on same drives he generates pressure — confirmed three-down
  deployment at Miami, not a pass-rush specialist."

BAD EXAMPLE (DO NOT WRITE THIS):
  "Elite pass rush production with verified counter package and technical hand work.
  Demonstrates consistent edge setting and run defense on same drives as pass rush
  dominance. Exceptional motor and play strength with natural leverage advantage."

The bad example is generic language that could describe any good EDGE. The good example
names specific moves, cites specific stats, and describes the specific mechanism of winning.

----------------------------------------------------------------------
RED FLAGS FIELD REQUIREMENTS
----------------------------------------------------------------------
Write EXACTLY 3 mechanism-specific red flag observations. Each observation MUST follow
this structure:

  [Failure mechanism] → [How it manifests] → [Competition context where it was exposed]

CRITICAL RULE: Every prospect has red flags. High scores do NOT mean fewer flags.
A prospect with an 88.4 APEX ELITE score has strengths that OUTWEIGH the flags —
that does not mean the flags do not exist. Write real, substantive flags for every
prospect regardless of overall score.

GOOD EXAMPLE (EDGE, ELITE tier):
  "Tight hips limit outside track bend — relies on favorable rush angles and inside
  counters rather than true edge speed, exposed on wide-9 alignments vs. Clemson OTs.
  Spindly frame at 245 lbs creates B-gap displacement risk under NFL iso blocks — was
  moved off spot by Notre Dame and Georgia power run schemes. Limited pre-draft
  measurable data leaves athletic profile partially unconfirmed despite film evidence."

BAD EXAMPLE (DO NOT WRITE THIS):
  "Needs to continue developing counter move sequencing against elite competition. May
  need additional pass rush move refinement at NFL level. Limited pre-draft measurable
  data available for athletic confirmation."

The bad example uses hedge language ("needs to continue," "may need") that says nothing
specific. The good example names the failure mechanism, the physical limitation causing
it, and the games where it was exposed.

----------------------------------------------------------------------
FAILURE MODE CLASSIFICATION (REQUIRED)
----------------------------------------------------------------------
Assign failure_mode_primary from this taxonomy:

  FM-1  Athleticism Mirage    — tested well, doesn't play fast/explosive in games
  FM-2  Scheme Ghost          — produced in one system, production won't transfer
  FM-3  Processing Wall       — athletic enough but NFL complexity overwhelms reads
  FM-4  Body Breakdown        — physical profile can't sustain NFL snap volume
  FM-5  Motivation Cliff      — external driver disappears post-contract/post-draft
  FM-6  Role Mismatch         — skills are real but deployment context doesn't exist

Every prospect has a primary failure mode — the MOST LIKELY way they bust if they bust.
ELITE prospects have failure modes too; theirs are just less likely to materialize.

failure_mode_secondary is optional — assign only when a second failure mode has
meaningful probability (>20% estimated). Use "NONE" if not applicable.

----------------------------------------------------------------------
SIGNATURE PLAY (REQUIRED)
----------------------------------------------------------------------
One sentence describing the single play, game moment, or recurring film pattern that
best captures how this prospect wins at football. This should be specific enough that
a scout who watched the film would recognize exactly what you're describing.

GOOD: "Third-and-7 vs. Georgia, beats LT with inside move setup then converts to
speed rush around the edge for strip-sack — the full counter sequence in one rep."

BAD: "Dominant pass rusher who consistently wins off the edge with burst and technique."

----------------------------------------------------------------------
TRANSLATION RISK (REQUIRED)
----------------------------------------------------------------------
One sentence identifying the single biggest threat to NFL translation for this prospect.
This is NOT a repeat of red_flags — it is a forward-looking projection of the specific
NFL scenario most likely to cause underperformance.

GOOD: "If drafted into a 3-4 system that asks him to hold the edge in space rather than
attack upfield, his tight hips and straight-line rush style become liabilities rather
than weapons."

BAD: "May struggle with the transition to NFL-level competition."

----------------------------------------------------------------------
BANNED PHRASES — DO NOT USE THESE IN ANY ANALYTICAL FIELD
----------------------------------------------------------------------
The following phrases are PROHIBITED in strengths, red_flags, signature_play,
translation_risk, and failure mode descriptions. They are vague, hedge-laden,
and add no analytical value:

  - "limited sample size"
  - "questions about readiness"
  - "needs refinement"
  - "needs to continue developing"
  - "may need additional"
  - "could improve"
  - "shows potential"
  - "flashes ability"
  - "demonstrates consistent" (without naming WHAT is demonstrated)
  - "natural [leverage/ability/talent]" (without mechanism)
  - "moves well for the position" (without specifying what movement quality)
  - "no significant flags identified"
  - "continues to develop"
  - "well-rounded"
  - "solid all-around"

If you find yourself reaching for one of these phrases, STOP and replace it with
the specific mechanism, stat, game, or physical trait you are actually describing.

======================================================================
CRITICAL OUTPUT INSTRUCTIONS
======================================================================
You will receive prospect data including name, position, school, consensus rank,
RAS measurables (if available), and contextual notes.

Use your training knowledge about this prospect's college career, production
statistics, combine/pro day results, and scouting reputation to inform
your evaluation across all 8 trait vectors.

RETURN ONLY VALID JSON. No preamble. No explanation. No markdown code fences.
Raw JSON only — begin with { and end with }.

Required JSON schema (all fields mandatory):
{
  "prospect_name": "string — full name",
  "position": "string — position code (ILB, QB, CB, OT, TE, etc.)",
  "archetype": "string — e.g. 'TE-1 Seam Anticipator' or 'QB-1 Field General'",
  "archetype_gap": 0.0,
  "gap_label": "string — CLEAN | SOLID | TWEENER | COMPRESSION | NO_FIT",
  "eval_confidence": "string — 'Tier A' | 'Tier B' | 'Tier C'",
  "v_processing": 0.0,
  "v_athleticism": 0.0,
  "v_scheme_vers": 0.0,
  "v_comp_tough": 0.0,
  "v_character": 0.0,
  "c1_public_record": 0.0,
  "c2_motivation": 0.0,
  "c3_psych_profile": 0.0,
  "v_dev_traj": 0.0,
  "v_production": 0.0,
  "v_injury": 0.0,
  "raw_score": 0.0,
  "schwesinger_full": 0,
  "schwesinger_half": 0,
  "smith_rule": 0,
  "tags": "string — comma-separated flags e.g. 'CRUSH,Walk-On Flag,Two-Way Premium'",
  "strengths": "string — EXACTLY 3 mechanism-specific strength observations per Section E",
  "red_flags": "string — EXACTLY 3 mechanism-specific red flag observations per Section E",
  "failure_mode_primary": "string — FM-1 through FM-6 code + name, e.g. 'FM-4 Body Breakdown'",
  "failure_mode_secondary": "string — FM code + name, or 'NONE'",
  "signature_play": "string — one sentence per Section E requirements",
  "translation_risk": "string — one sentence per Section E requirements",
  "capital_base": "string — e.g. 'R1 Picks 11-32'",
  "capital_adjusted": "string — after all modifier rules applied",
  "two_way_premium": 0
}

Field requirements:
- All trait scores (v_* and c*): float, range 1.0 to 10.0
- v_character: must equal average(c1_public_record, c2_motivation, c3_psych_profile)
- v_dev_traj: must be POST-Schwesinger Rule adjustment (if triggered)
- raw_score: float, range 0.0 to 100.0 (0-100 scale, not 0-10)
- schwesinger_full, schwesinger_half, smith_rule, two_way_premium: integer 0 or 1
- tags: empty string if no flags apply
- archetype_gap: must be the actual computed gap between rank-1 and rank-2 archetype fit scores
- archetype: must be "[POS]-[N] [Name]" format from the SECTION B archetype list for this position
- strengths: EXACTLY 3 mechanism-specific observations. NOT generic summaries.
- red_flags: EXACTLY 3 mechanism-specific observations. REQUIRED even on ELITE prospects.
- failure_mode_primary: REQUIRED. One of FM-1 through FM-6 with full name.
- failure_mode_secondary: REQUIRED. FM code or "NONE".
- signature_play: REQUIRED. One specific sentence.
- translation_risk: REQUIRED. One specific forward-looking sentence.
"""


def build_user_prompt(prospect_data: dict) -> str:
    """
    Build per-prospect user prompt.

    prospect_data keys:
      name, position, school, consensus_rank, consensus_tier, consensus_score,
      ras_total (float|None), web_context (str),
      archetype_direction (str|None), forced_archetype (bool),
      paa_findings (dict|None) — analyst-verified gate results,
      override_eval_conf (str|None), override_capital (str|None),
      override_fm_flags (list[str]|None)
    """
    name            = prospect_data["name"]
    position        = prospect_data["position"]
    school          = prospect_data["school"]
    consensus_rank  = prospect_data["consensus_rank"]
    consensus_tier  = prospect_data["consensus_tier"]
    consensus_score = prospect_data["consensus_score"]
    ras_total       = prospect_data.get("ras_total")
    web_context     = prospect_data.get("web_context", "")

    archetype_direction = prospect_data.get("archetype_direction")
    is_forced           = prospect_data.get("forced_archetype", False)
    paa_findings        = prospect_data.get("paa_findings")

    override_eval_conf  = prospect_data.get("override_eval_conf")
    override_capital    = prospect_data.get("override_capital")
    override_fm_flags   = prospect_data.get("override_fm_flags")

    ras_str = f"{ras_total:.2f}" if ras_total is not None else "Not available"

    ctx_block = web_context.strip() if web_context else "No additional context provided."

    # Classification gate block — position-specific mandatory gates.
    gate_key = _normalize_position_for_gate(position)
    paa_gate = POSITION_PAA_GATES.get(gate_key, "")
    gate_block = ""
    if paa_gate:
        gate_block = f"""

=== MANDATORY CLASSIFICATION GATE ({gate_key}) ===
These are non-negotiable requirements. Your archetype assignment MUST be consistent
with the gate outputs.

{paa_gate}
=== END CLASSIFICATION GATE ==="""

    # Confirmed PAA gate findings block — injected when paa_findings is present.
    paa_block = ""
    if paa_findings:
        finding_lines = "\n".join(
            f"  {q}: {v}" for q, v in paa_findings.items()
        )
        paa_block = f"""

=== CONFIRMED PAA GATE FINDINGS (ANALYST-VERIFIED — DO NOT OVERRIDE) ===
The following gate results have been confirmed through full DraftOS evaluation.
These supersede training data inferences. Score against these confirmed findings exactly.
Do NOT re-derive gate answers from training data — accept these results as ground truth.

{finding_lines}
=== END CONFIRMED PAA FINDINGS ==="""

    # Analyst capital and confidence constraints.
    constraints_block = ""
    constraint_parts: list[str] = []
    if override_eval_conf:
        constraint_parts.append(f"Eval Confidence (LOCKED): {override_eval_conf}")
    if override_capital:
        constraint_parts.append(f"Capital Range (LOCKED): {override_capital}")
    if override_fm_flags:
        constraint_parts.append(f"FM Flags Active: {', '.join(override_fm_flags)}")
    if constraint_parts:
        constraints_block = (
            "\n\n=== ANALYST CAPITAL AND CONFIDENCE CONSTRAINTS ===\n"
            + "\n".join(constraint_parts)
            + "\nApply these constraints exactly. Do not override with independent capital inference."
            "\n=== END CONSTRAINTS ==="
        )

    # Analyst override block.
    arch_block = ""
    if archetype_direction:
        if is_forced:
            header = "=== ARCHETYPE DIRECTION — ANALYST OVERRIDE (MANDATORY) ==="
            footer = (
                "CRITICAL: The archetype assignment above is PRE-DETERMINED by analyst review.\n"
                "You MUST assign the specified archetype. Do NOT select a different archetype.\n"
                "Score all trait vectors from the perspective of the forced archetype's weight table.\n"
                "The archetype field in your JSON output MUST match the assigned archetype exactly."
            )
        else:
            header = "=== ARCHETYPE GATE ENFORCEMENT ==="
            footer = (
                "The gate requirements above are non-negotiable. Run each gate question explicitly.\n"
                "Do NOT assign an archetype that fails any gate check.\n"
                "State which gate outputs drove your archetype decision in one sentence in red_flags."
            )
        arch_block = f"""

{header}
{archetype_direction}

{footer}
=== END ==="""

    return f"""\
Evaluate the following NFL draft prospect using the APEX v2.3 framework.

=== PROSPECT ===
  Name:     {name}
  Position: {position}
  School:   {school}

=== CONSENSUS DATA (DraftOS internal ranking) ===
  Consensus Rank:  #{consensus_rank}
  Consensus Tier:  {consensus_tier}
  Consensus Score: {consensus_score:.1f} / 100

=== MEASURABLES ===
  RAS Score: {ras_str}

=== CONTEXT ===
{ctx_block}{gate_block}{paa_block}{arch_block}{constraints_block}

Apply ALL applicable modifier rules:
- Schwesinger Rule (c2 >= 8 + c3 >= 7 → DevTraj boost)
- Smith Rule (c3 < 3 OR c2 < 5 → Character cap)
- Walk-On Flag (if applicable to this player)
- Two-Way Premium (if this player plays two positions at elite college level)
- SAA Gate (QB only — check screen rate, play-action dependency, avg depth of target)
- PAA Gate (TE only — check scheme inflation, route depth, competition level)
- SOS Gate (S only — check schedule strength vs. elite competition)

Use SECTION B position weight table for this player's position group.
Assign archetype from the position-specific archetype list only. Do NOT use GEN- archetypes.
Based on the classification gate outputs above, assign the single most mechanistically
accurate archetype. Do NOT default to the highest-prestige label if the mechanism
does not confirm it.
Compute raw_score on a 0-100 scale using the archetype weight formula.

CRITICAL — SECTION E COMPLIANCE:
Before writing strengths and red_flags, re-read Section E of the system prompt.
- strengths: EXACTLY 3 mechanism-specific observations. Name the move, cite the stat, describe the scenario.
- red_flags: EXACTLY 3 mechanism-specific observations. REQUIRED even on high-scoring prospects. Name the failure mechanism, how it manifests, and where it was exposed.
- failure_mode_primary: REQUIRED. The most likely way this prospect busts if he busts.
- failure_mode_secondary: REQUIRED. Second-most-likely FM or "NONE".
- signature_play: REQUIRED. One specific sentence about a real play or recurring pattern.
- translation_risk: REQUIRED. One specific forward-looking NFL scenario sentence.
- Do NOT use any phrase from the BANNED PHRASES list.

Return raw JSON only. No markdown fences. No preamble. Start with {{."""
