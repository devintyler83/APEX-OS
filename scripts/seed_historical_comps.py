"""
Seed historical comp records into historical_comps table.
Covers QB (19), CB (20), EDGE (18), WR (24) = 81 records.

Idempotent: uses INSERT OR IGNORE via UNIQUE constraint on (player_name, archetype_code).
Safe to re-run — will not duplicate records.

Usage:
    python -m scripts.seed_historical_comps --apply 0   # dry run
    python -m scripts.seed_historical_comps --apply 1   # write
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.db.connect import connect
from draftos.config import PATHS

RECORDS = [

    # =========================================================
    # QB — 19 records
    # =========================================================

    # QB-1: Field General (4 records)
    dict(player_name="Patrick Mahomes", position="QB", archetype_code="QB-1",
         mechanism="Off-platform arm talent fused with elite processing speed. Creates when structure breaks, but the creation is calculated — not improvisation for its own sake. Reads the field pre-snap at an elite level, then extends plays only when the first read confirms the coverage is beatable if he buys time.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Generational QB-1 ceiling: off-platform creation layered on top of elite processing, system-transcendent across every defensive scheme.",
         era_bracket="2018–present", peak_years="2018–2024", comp_confidence="A",
         scheme_context="Andy Reid's motion-heavy West Coast system; demonstrated system-transcendence when scheme was neutralized in Super Bowls and he won on processing alone.",
         signature_trait="The ability to make the 'wrong' platform throw into the 'right' window — arm angles that shouldn't work but do because the processing already solved the coverage before the body moved."),

    dict(player_name="Peyton Manning", position="QB", archetype_code="QB-1",
         mechanism="Pre-snap processing as a weapon. Won before the ball was snapped — the cadence, the audible, the protection adjustment were all offensive plays in themselves. Arm talent was good-not-elite; processing made it irrelevant.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Defined the cerebral QB-1 model — processing so dominant it compensated for declining athleticism across two decades; system-transcendent across multiple coordinators.",
         era_bracket="1998–2015", peak_years="2003–2009", comp_confidence="A",
         scheme_context="Tom Moore's vertical passing game in Indianapolis, then Gase/Dennison's system in Denver with zero production drop — the ultimate system-transcendence proof.",
         signature_trait="The line-of-scrimmage audible that functioned as a second playcall, turning every snap into a two-option decision tree the defense couldn't win."),

    dict(player_name="Andrew Luck", position="QB", archetype_code="QB-1",
         mechanism="Elite processing, elite arm talent, elite competitive toughness — the full QB-1 toolkit. Won through coverage reads and throw anticipation, but also absorbed punishment willingly behind bad offensive lines and kept producing.",
         translation_outcome="PARTIAL", fm_code="FM-4", fm_mechanism="Body couldn't absorb the cumulative punishment of playing behind a bottom-5 offensive line for four years. The toughness that made him elite also destroyed him — he wouldn't protect himself.",
         outcome_summary="QB-1 FM-4 cautionary case: every trait was elite, FM-4 ended the career at 29; durability is a trait, and absorbing hits is not the same as avoiding them.",
         era_bracket="2012–2018", peak_years="2014, 2018", comp_confidence="A",
         scheme_context="Pep Hamilton, then Rob Chudzinski, then early Frank Reich — production remained elite across all three, confirming system-transcendence before FM-4 activated.",
         signature_trait="The third-and-long throw into a closing window off his back foot after absorbing a hit — the play that was simultaneously his greatness and his destruction."),

    dict(player_name="Troy Aikman", position="QB", archetype_code="QB-1",
         mechanism="Precision timing and accuracy within structure. Not a creator — a processor who delivered the ball exactly where the scheme designed it to go, on time, every time. The anti-Mahomes: his greatness was that he never needed to freelance.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Structure-dependent QB-1: elite accuracy and processing within a dominant system; floor is lower without supporting cast but three Super Bowls confirm the mechanism.",
         era_bracket="1989–2000", peak_years="1992–1996", comp_confidence="B",
         scheme_context="Norv Turner's play-action heavy scheme behind the best offensive line and running game of the era. Open question: QB-1 or perfectly deployed QB-3 Rhythm Distributor? Three Super Bowls say QB-1.",
         signature_trait="The 15-yard out route thrown before the receiver's break — pure anticipation and ball placement, zero reliance on arm talent to bail out late decisions."),

    # QB-2: Dual-Threat Architect (4 records)
    dict(player_name="Lamar Jackson", position="QB", archetype_code="QB-2",
         mechanism="Run threat so extreme it breaks defensive assignment discipline, creating passing lanes that don't exist for pocket QBs. The passing game is a derivative of the run threat, not the other way around. Processing has improved but the primary win mechanism remains the legs warping defensive structure.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Redefined QB-2 ceiling — proved the dual-threat archetype can win MVP and sustain elite production when passing processing develops enough to punish defenses that sell out to stop the run.",
         era_bracket="2018–present", peak_years="2019–2024", comp_confidence="A",
         scheme_context="Greg Roman's designed-run heavy system, then Todd Monken's more pass-integrated scheme. Production sustained across both — the system changed around him.",
         signature_trait="The designed run-pass option where the defensive end crashes and Jackson pulls the ball, then reads the safety rotation and hits the back-shoulder throw in stride — the dual-threat mechanism forcing two simultaneous wrong answers."),

    dict(player_name="Cam Newton", position="QB", archetype_code="QB-2",
         mechanism="Physical dominance as a QB mechanism — 6'5\" 245 lbs with sub-4.60 speed, making every designed run an unsolvable assignment problem while the passing game operated from play-action off the run threat. The 2015 MVP season was the QB-2 ceiling expression: 35 total touchdowns, physical dominance on contested throws.",
         translation_outcome="PARTIAL", fm_code="FM-4", fm_mechanism="Body couldn't sustain the contact absorption that the QB-2 run mechanism required across an NFL career. The mechanism that made Newton elite — taking hits rather than avoiding them — produced the same cumulative damage pattern as Luck. FM-4 at QB-2 is structural: the running mechanism creates body contact that the body eventually cannot sustain.",
         outcome_summary="QB-2 FM-4 structural case: physical dominance produced one MVP season; the run mechanism that creates the ceiling also creates the FM-4 body breakdown floor.",
         era_bracket="2011–2021", peak_years="2011, 2015", comp_confidence="A",
         scheme_context="Ron Rivera's Carolina Panthers — the scheme was built around Newton's physical dominance as a run-pass threat. Post-Carolina production confirmed FM-4 had compressed the physical mechanism permanently.",
         signature_trait="The goal-line quarterback sneak that goes for 6 yards because no linebacker can get the shoulder pad of a 245-lb QB moving at full speed — the run mechanism at its most extreme expression."),

    dict(player_name="Robert Griffin III", position="QB", archetype_code="QB-2",
         mechanism="Elite speed (4.41) with functional processing at the college level produced a QB-2 who could run defenses off the field vertically. The mechanism was real in Year 1 — defenses had no film and no preparation for the specific combination of speed and processing.",
         translation_outcome="MISS", fm_code="FM-4", fm_mechanism="Knee injuries in Year 1 and Year 2 permanently compressed the speed mechanism that was the primary weapon. When the speed was at full capacity, the processing could not sustain against defenses with full preparation. When the injuries reduced the speed threat, the passing mechanism was insufficient as a standalone weapon.",
         outcome_summary="QB-2 FM-4 immediate activation: Year 1 mechanism was real, knee injuries by Year 2 eliminated the speed threat before passing processing could compensate; Pick 2 capital returned one functional season.",
         era_bracket="2012–2020", peak_years="2012", comp_confidence="A",
         scheme_context="Washington Redskins under Kyle Shanahan — the scheme was specifically designed to maximize RG3's speed-read option mechanism. When Shanahan left and the injuries reduced the speed, the scheme alignment disappeared simultaneously.",
         signature_trait="The 2012 Week 1 read-option keeper where RG3 reads the end, pulls, and is gone before the safety can rotate — the mechanism working at maximum efficiency before defenses had preparation and before FM-4 activated."),

    dict(player_name="Michael Vick", position="QB", archetype_code="QB-2",
         mechanism="Athletic ceiling that has no comparable in NFL history — 4.33 speed at 215 lbs at quarterback. The passing mechanism was functional-not-elite; the running mechanism was generational. The Atlanta peak was the QB-2 run ceiling. The Philadelphia peak (2010) showed the combination when passing processing finally developed enough to be a legitimate two-way threat.",
         translation_outcome="PARTIAL", fm_code="FM-5", fm_mechanism="Career interruption (federal conviction, 2007–2008) compressed the production window. The 2010 Philadelphia peak at age 30 showed what the QB-2 mechanism could have become with a full career arc — but the window was permanently compressed by off-field decisions.",
         outcome_summary="QB-2 run ceiling expression: generational athleticism produced one complete dual-threat season at age 30; FM-5 permanently compressed the production window.",
         era_bracket="2001–2015", peak_years="2010", comp_confidence="A",
         scheme_context="Atlanta Falcons (run-first, limited pass demand), then Philadelphia Eagles under Andy Reid (2010 QB-2 peak with passing demands). The Eagles scheme was the first context that required both mechanisms simultaneously.",
         signature_trait="The 2010 Monday Night Football game against Washington where Vick threw for 333 yards and rushed for 80 — the only season of his career where both mechanisms operated at their ceiling simultaneously."),

    # QB-3: Rhythm Distributor (3 records)
    dict(player_name="Tom Brady", position="QB", archetype_code="QB-3",
         mechanism="Entered as a pure QB-3 Rhythm Distributor — quick-game mastery, pre-snap processing that identified the open receiver before the snap, and elite ball placement on timing routes. Evolved into QB-1 territory through processing development over his career. The early career mechanism was definitional QB-3; the Belichick peak was QB-1 adjacent.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="QB-3 to QB-1 evolution pathway: Rhythm Distributor mechanism at entry developed into system-transcendent processing; the most important development arc in QB archetype history.",
         era_bracket="2000–2022", peak_years="2007, 2010, 2016–2018", comp_confidence="A",
         scheme_context="Bill Belichick's multiple-set offense — the scheme was specifically designed to maximize Brady's processing and ball placement. The Tampa Bay success confirmed system-transcendence when the scheme changed.",
         signature_trait="The 2001 Super Bowl two-minute drill — a first-year starter with no run threat, no elite arm, and no elite athleticism, executing the QB-3 mechanism at its highest expression under maximum pressure."),

    dict(player_name="Matt Ryan", position="QB", archetype_code="QB-3",
         mechanism="Elite accuracy on timing routes with above-average processing speed and a functional deep ball. Not a creator — a precision distributor who operated most efficiently in a scheme that created structure for his processing speed. The 2016 MVP season was the QB-3 ceiling in the optimal deployment context.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="QB-3 consistent hit: elite timing accuracy produced long-term franchise QB value; 2016 MVP season confirmed the archetype ceiling in optimal scheme alignment.",
         era_bracket="2008–2022", peak_years="2010, 2012, 2016", comp_confidence="A",
         scheme_context="Atlanta Falcons under various coordinators, with the 2016 Kyle Shanahan season being the optimal deployment. Indianapolis stint confirmed that without Shanahan's YAC-maximizing scheme, the QB-3 mechanism produces above-average rather than elite output.",
         signature_trait="A 2016 third-and-medium completion where Ryan identifies the coverage pre-snap, delivers the ball 0.2 seconds before the receiver breaks, and the timing is so precise the corner has no play — the QB-3 mechanism at MVP level."),

    dict(player_name="Kirk Cousins", position="QB", archetype_code="QB-3",
         mechanism="Functional QB-3 mechanism with elite accuracy on prepared concepts and below-average ability to create when structure breaks. The career is the QB-3 floor expression — consistently above-average in structure, consistently exposed when structure fails.",
         translation_outcome="PARTIAL", fm_code="FM-2", fm_mechanism="Scheme Ghost at the QB level — production is scheme-dependent in a way that is not structural enough to sustain across scheme changes. When the scheme created structure, Cousins delivered efficiently. When structure broke, production fell to below-average. Not a true FM-2 but the scheme dependency is real enough to suppress the outcome from HIT to PARTIAL.",
         outcome_summary="QB-3 floor expression: reliable starter production in structured schemes, exposed when structure fails; career-level consistency below the archetype's ceiling.",
         era_bracket="2012–present", peak_years="2019, 2022", comp_confidence="B",
         scheme_context="Washington multiple schemes, then Minnesota Vikings (Stefanski/Kubiak), then Atlanta Falcons. Production above average in structured pass-first schemes; below average when structure deteriorated.",
         signature_trait="A 2019 fourth-quarter comeback throw where the structure Cousins prepared for collapsed and he delivered the prepared read anyway — the QB-3 mechanism in the moment it perfectly fits, and the moment it doesn't."),

    # QB-4: Game Manager (2 records)
    dict(player_name="Nick Foles", position="QB", archetype_code="QB-4",
         mechanism="Elite accuracy on quick-game and prepared concepts with the processing speed to execute designed plays at the NFL level. The 2018 Super Bowl is the QB-4 performance ceiling — every throw was a prepared concept delivered with elite accuracy in the highest-pressure game.",
         translation_outcome="PARTIAL", fm_code="FM-6", fm_mechanism="Role Mismatch — when deployed as a starter with full read-progression demands, production collapsed because the QB-4 mechanism doesn't extend to full-field processing under pressure. The Super Bowl performance required the specific Chiefs defense that played zone, not man, and the specific Eagles scheme designed for Foles's processing speed. Both conditions rarely aligned again.",
         outcome_summary="QB-4 ceiling-and-floor case: Super Bowl MVP is the archetype ceiling in perfect deployment; FM-6 appears when role demands exceed the mechanism's capability.",
         era_bracket="2012–2020", peak_years="2013, 2018", comp_confidence="A",
         scheme_context="Doug Pederson's RPO-heavy scheme in Philadelphia was near-optimal QB-4 deployment. Jacksonville and Chicago required full read-progression production that the mechanism couldn't sustain.",
         signature_trait="The Philly Special — the play that confirmed Foles understood his role within the offense and executed it at the highest level, on the biggest stage, with the full preparation advantage that the QB-4 mechanism requires."),

    dict(player_name="Alex Smith", position="QB", archetype_code="QB-4",
         mechanism="Elite decision speed on prepared quick-game concepts with above-average processing that allowed him to identify and deliver to the second read. Not a creator — never asked to be. The mechanism was used correctly: low-turnover, efficient game management that created wins without requiring creation.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="QB-4 long-term hit: elite decision speed and low-turnover efficiency produced consistent winning across multiple organizations; confirmed the archetype can sustain a long career when deployed correctly.",
         era_bracket="2005–2020", peak_years="2011, 2017", comp_confidence="A",
         scheme_context="San Francisco (Harbaugh, near-optimal QB-4 deployment), then Kansas City (Andy Reid, near-optimal), then Washington (Rivera). Production held across all three — the mechanism traveled when the deployment demand matched.",
         signature_trait="A 2017 scramble where Smith escapes pressure and delivers an accurate throw to a second-read receiver — the QB-4 mechanism extending itself to the limit of its ceiling without exceeding it."),

    # QB-5: Raw Projection (2 records)
    dict(player_name="JaMarcus Russell", position="QB", archetype_code="QB-5",
         mechanism="Physical tools were consensus generational — 6'6\" 265 lbs with a 4.72 arm velocity and elite throw power. The processing and character architecture to develop those tools into an NFL quarterback were absent at every measurement point available pre-draft.",
         translation_outcome="MISS", fm_code="FM-3, FM-5", fm_mechanism="Processing Wall: the arm was elite, the processing required to deploy it at the NFL level was never present and never developed. FM-5 compound: the work ethic and preparation commitment required to develop NFL processing never materialized. The FM-3 + FM-5 combination at QB-5 is the universal bust predictor — tools without development and character without drive.",
         outcome_summary="QB-5 FM-3 + FM-5 compound: generational physical tools, processing absent, character architecture absent; Pick 1 capital returned zero functional NFL seasons.",
         era_bracket="2007–2009", peak_years="None", comp_confidence="A",
         scheme_context="Oakland Raiders under Lane Kiffin, then Tom Cable. No organizational context resolved the FM-3 + FM-5 compound. Three seasons, 18 touchdowns, 23 interceptions.",
         signature_trait="The combine arm strength demonstration that produced a Pick 1 consensus — and the NFL reps where the same arm produced inaccurate throws because the processing required to deploy arm strength accurately was never present."),

    dict(player_name="Blaine Gabbert", position="QB", archetype_code="QB-5",
         mechanism="Athletic measurables and arm talent that projected as developmental QB-5 with a pathway to QB-3. The mechanism that was supposed to develop — processing under pressure, reading defenses post-snap — never appeared at even a functional NFL level.",
         translation_outcome="MISS", fm_code="FM-3", fm_mechanism="Processing Wall: the tools were present, the processing ceiling was lower than projected and did not develop with NFL coaching. The specific FM-3 expression: processing froze under pressure, which the college environment had not adequately tested, and which NFL pass rushers exploited immediately and permanently.",
         outcome_summary="QB-5 FM-3 processing ceiling: tools present, processing froze under NFL pressure; Pick 10 capital returned a career backup.",
         era_bracket="2011–2019", peak_years="2016 (functional)", comp_confidence="A",
         scheme_context="Jacksonville Jaguars (expansion-era context), then multiple backup stops. No scheme resolved the processing limitation under pressure.",
         signature_trait="A 2012 game where Gabbert takes three sacks in a row on designed quick-game plays because the processing froze at the snap — the FM-3 mechanism visible in real time."),

    # QB-6: System Product (3 records)
    dict(player_name="Case Keenum", position="QB", archetype_code="QB-6",
         mechanism="Accuracy on timing routes within Pat Shurmur's play-action scheme in Minnesota. The 2017 Vikings had elite skill weapons (Diggs, Thielen), a dominant defense that created short fields, and a system that manufactured throws at Keenum's processing speed.",
         translation_outcome="MISS", fm_code="FM-6", fm_mechanism="Signed with Denver as a starter based on 2017 production. The system didn't travel — different weapons, different scheme concepts, different defensive support. Production collapsed immediately and permanently.",
         outcome_summary="QB-6 false positive: single-season elite system alignment produced franchise QB mirage; FM-6 confirmed when structural variation occurred — production collapsed and never recovered.",
         era_bracket="2012–2021", peak_years="2017 (single season)", comp_confidence="A",
         scheme_context="Pat Shurmur's play-action system in Minnesota with Diggs/Thielen and a top-3 defense. Every other stop — Houston, St. Louis, Denver, Cleveland, Buffalo — produced backup-level numbers.",
         signature_trait="The Minneapolis Miracle — a 61-yard walk-off touchdown that cemented a franchise QB narrative around a QB-6 having the best possible season in the best possible system."),

    dict(player_name="Tua Tagovailoa", position="QB", archetype_code="QB-6",
         mechanism="Quick-processing, rhythm-based passer with elite accuracy on short-to-intermediate timing routes within Mike McDaniel's YAC-maximizing scheme. McDaniel's system is specifically designed to create after-catch opportunities through motion, pre-snap alignment, and route concepts that put receivers in space.",
         translation_outcome="PARTIAL", fm_code="FM-6", fm_mechanism="The portability question is the entire evaluation as of 2026. Production inside McDaniel's system is legitimately elite — top-5 efficiency metrics in 2023-2024. But no structural variation has been tested. Concussion history adds FM-4 secondary concern.",
         outcome_summary="QB-6 active test case: elite production in one system with no multi-system evidence; FM-6 projected but unconfirmed; FM-4 secondary concern via concussion history.",
         era_bracket="2020–present", peak_years="2023–2024", comp_confidence="B",
         scheme_context="Chan Gailey (2020-2021, limited production), then Mike McDaniel (2022-present, elite production). The production jump correlates perfectly with McDaniel's arrival.",
         signature_trait="The pre-snap motion to a receiver on a crosser, ball out in 2.0 seconds to a spot 8 yards downfield — schemed YAC that looks like QB mastery but is system design functioning as intended."),

    dict(player_name="Dak Prescott", position="QB", archetype_code="QB-6",
         mechanism="Began as a pure system product in Jason Garrett's run-first, play-action scheme with a dominant offensive line and Ezekiel Elliott as the primary weapon. The question from Day 1 was whether this was a QB-6 who would collapse when the system changed — or a QB-4/QB-1 whose processing was suppressed by a conservative scheme.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="QB-6 escape case: entered as system-dependent, developed genuine processing portability confirmed by multi-system evidence; QB-6 reclassification is possible but requires involuntary scheme variation as the test.",
         era_bracket="2016–present", peak_years="2019, 2021–2023", comp_confidence="B",
         scheme_context="Jason Garrett run-first (2016-2019), Kellen Moore pass-heavy (2019-2022), Mike McCarthy (2020-present). Production sustained across all three — the multi-system evidence that confirms processing portability.",
         signature_trait="The 4th-quarter comeback drive in a playoff game where the play design is neutralized and Prescott extends the play, processes post-snap, and delivers — the rep that proves this is no longer a QB-6 moment."),

    # =========================================================
    # CB — 20 records
    # =========================================================

    # CB-1: Anticipatory Lockdown (4 records)
    dict(player_name="Darrelle Revis", position="CB", archetype_code="CB-1",
         mechanism="Won through anticipatory processing before any other trait. Diagnosed route concepts from pre-snap alignment, stem, and release to an accuracy that placed him in position before the break. Not speed-based — moved before the receiver broke because he knew where the receiver was going. Technical press discipline disrupted timing at the release point.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="The CB-1 mechanism standard: anticipatory processing over athleticism, system-transcendent, forced game-plan restructuring for an era.",
         era_bracket="2007–2017", peak_years="2009–2013, 2015", comp_confidence="A",
         scheme_context="New York Jets (Rex Ryan man-cover scheme), then New England, Tampa Bay, Kansas City. Translation survived four different defensive coordinators and three scheme families.",
         signature_trait="The rep where he breaks on a slant before the receiver has completed the stem — anticipatory processing made visible. The receiver is still running his route. Revis is already at the catch point."),

    dict(player_name="Stephon Gilmore", position="CB", archetype_code="CB-1",
         mechanism="Technical refinement over multiple seasons producing CB-1 outcome despite adequate rather than elite athleticism. Press technique was precise and sequenced — not physical-dominant, technique-dominant. Processing developed year-over-year, with the 2018-2020 peak representing fully realized CB-1 mechanism.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Proves CB-1 archetype requires technique + processing, not combine athleticism; DPOY ceiling when mechanism is fully realized.",
         era_bracket="2012–2022", peak_years="2018–2020", comp_confidence="A",
         scheme_context="Buffalo Bills zone-heavy, then New England Patriots press-man dominant. Translation across scheme families confirmed — system-transcendent.",
         signature_trait="The 2019 Super Bowl interception of Jared Goff — pre-break movement in man coverage, processing the concept before the QB threw, arriving as the ball arrived."),

    dict(player_name="Champ Bailey", position="CB", archetype_code="CB-1",
         mechanism="Physical + technical + anticipatory processing combination operated in press, off-man, and zone at elite level across a 15-year career. Scheme-transcendent from Day 1 — the processing was structural, not system-manufactured.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-1 versatility proof: scheme-transcendent across 15 NFL seasons, sustained elite production through four defensive coordinators; confirms the archetype's longevity ceiling.",
         era_bracket="1999–2014", peak_years="2004–2009", comp_confidence="A",
         scheme_context="Washington Redskins multiple, then Denver Broncos multiple defensive coordinators. Elite production sustained across scheme changes.",
         signature_trait="A 2006 playoff interception return where Bailey reads the route concept pre-snap, breaks before the throw, and returns 100 yards — anticipatory processing operating under maximum pressure."),

    dict(player_name="Adrian Peterson (CB)", position="CB", archetype_code="CB-1",
         mechanism="Physical dominance at press coverage combined with above-average anticipatory processing produced the CB-1 mechanism in the pre-2004 era. Hall of Fame production across 11 seasons before FM-5 activated post-contract.",
         translation_outcome="PARTIAL", fm_code="FM-5", fm_mechanism="Motivation Cliff post-peak contract. Production declined materially after 2005 as competitive toughness and preparation commitment waned. Six Pro Bowls before FM-5 activated — the CB-1 floor even with FM-5 is above-average starter production.",
         outcome_summary="CB-1 FM-5 case: six Pro Bowls before Motivation Cliff activated; confirms CB-1 floor is the highest of any CB archetype even with FM-5 — the worst CB-1 outcome still produced a Pro Bowl career.",
         era_bracket="1997–2007", peak_years="2002–2005", comp_confidence="A",
         scheme_context="Chicago Bears under multiple coordinators. Pre-2004 era — apply mandatory era adjustment discount to capital anchors derived from physical contact production.",
         signature_trait="A 2002 Monday Night Football game where Peterson shadowed Terrell Owens for four quarters without allowing a touchdown — the CB-1 assignment coverage at its definitional expression."),

    # CB-2: Zone Architect (4 records)
    dict(player_name="Antoine Winfield Sr.", position="CB", archetype_code="CB-2",
         mechanism="Zone processing dominant with a confirmed man coverage floor that elevated him above structural CB-2 limitations. Read coverages pre-snap at an elite level, consistently aligned before the ball was snapped, and delivered a confirmed man floor that prevented scheme exploitation.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-2 ceiling expression: zone processing dominant plus confirmed man coverage floor; 14-year career confirms the archetype sustains when the man floor prevents scheme exploitation.",
         era_bracket="1999–2012", peak_years="2002–2007", comp_confidence="A",
         scheme_context="Buffalo Bills and Minnesota Vikings across multiple coordinators. Zone-heavy schemes were optimal but man coverage floor confirmed independently.",
         signature_trait="A 2003 zone read where Winfield identifies the crossing route from the pre-snap alignment, breaks at the snap, and is at the catch point before the receiver — zone processing operating at CB-1 speed."),

    dict(player_name="Carlos Rogers", position="CB", archetype_code="CB-2",
         mechanism="Zone coverage specialist with above-average anticipation in two-high and quarters schemes. Man coverage floor was confirmed at a functional level — not elite, but sufficient to prevent the structural FM-2 exposure.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-2 reliable hit: zone processing dominant with sufficient man floor; career-level consistency without ceiling expression — the archetype's reliable production band.",
         era_bracket="2005–2013", peak_years="2011–2012", comp_confidence="B",
         scheme_context="Washington Redskins, then San Francisco 49ers under Jim Harbaugh. The 49ers zone-heavy scheme was near-optimal CB-2 deployment.",
         signature_trait="A 2011 49ers interception where Rogers identifies the tight end drag from quarters coverage pre-snap and delivers a textbook zone jump — the CB-2 mechanism in optimal deployment."),

    dict(player_name="Marcus Peters", position="CB", archetype_code="CB-2",
         mechanism="Elite zone anticipation and ball skills operating in a specific coverage family. Man coverage floor was functionally adequate against non-elite receivers but exposed against elite speed in man-isolated situations — the structural CB-2 limitation that FM-2 captures.",
         translation_outcome="PARTIAL", fm_code="FM-2", fm_mechanism="Scheme Ghost — man coverage exposed against elite receivers in isolated situations, particularly against speed routes. Zone processing was elite; individual man coverage against NFL-caliber WR-2 profiles created exploitable tendencies that required scheme concealment.",
         outcome_summary="CB-2 FM-2 partial: elite zone anticipation and ball skills, man coverage floor exposed against elite speed; career required scheme protection to sustain — the CB-2 structural limitation made visible.",
         era_bracket="2015–2022", peak_years="2016–2017", comp_confidence="A",
         scheme_context="Kansas City Chiefs (multiple coordinators), then Los Angeles Rams, then Baltimore Ravens. Zone-heavy contexts produced elite output; man-heavy or isolated matchup contexts revealed the FM-2 structural limitation.",
         signature_trait="A 2016 zone interception where Peters reads the wheel route concept from the backfield release and arrives at the catch point before the ball — elite CB-2 mechanism in its optimal context."),

    dict(player_name="Marshon Lattimore", position="CB", archetype_code="CB-2",
         mechanism="Zone processing dominant with a developing man coverage component that has trended upward consistently year-over-year. The trajectory is toward CB-1 mechanism without yet achieving full confirmation — the CB-2 development pathway at its clearest expression.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-2 development arc hit: zone dominant at entry, man coverage developing on confirmed upward trajectory; multiple Pro Bowls confirm the archetype ceiling when development is real.",
         era_bracket="2017–present", peak_years="2019–2022", comp_confidence="A",
         scheme_context="New Orleans Saints across multiple defensive coordinators. Zone-first scheme alignment was optimal but man coverage reps confirmed the developing component.",
         signature_trait="A 2021 man-coverage rep where Lattimore mirrors a WR-1 route technician through three stem manipulations before the break — the developing CB-1 component visible against the hardest possible test."),

    # CB-3: Athletic Freak / Press Man Corner (4 records)
    dict(player_name="Jalen Ramsey", position="CB", archetype_code="CB-3",
         mechanism="Elite athleticism as the primary mechanism with developing technique that elevated the archetype toward CB-1 territory. The development arc is the mechanism story — Ramsey's physical tools were the floor, his technique development over four seasons was what produced the All-Pro ceiling.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-3 development ceiling: elite athleticism as the floor, technique development produced All-Pro outcomes; confirms the archetype can reach CB-1 territory when technique trajectory is upward.",
         era_bracket="2016–present", peak_years="2019–2021", comp_confidence="A",
         scheme_context="Jacksonville Jaguars (Todd Wash man-heavy), then Los Angeles Rams (Wade Phillips multiple). Translation across scheme families confirmed as technique developed.",
         signature_trait="A 2019 Rams rep where Ramsey mirrors a WR-1 from press at the line through the full route with no technique advantage — pure athleticism plus developed technique operating simultaneously."),

    dict(player_name="Jaire Alexander", position="CB", archetype_code="CB-3",
         mechanism="Elite athleticism with confirmed upward technique trajectory — the CB-3 development arc at its fastest expression. Year 3 represented a technique level that CB-3 profiles typically reach in Year 5 or 6, confirming character-driven development.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-3 accelerated development: elite athleticism plus character-confirmed technique trajectory produced Pro Bowl outcomes ahead of archetype schedule.",
         era_bracket="2018–present", peak_years="2021–2022", comp_confidence="A",
         scheme_context="Green Bay Packers across multiple coordinators. Zone and man both deployed at above-average level — technique trajectory confirmed as system-transcendent.",
         signature_trait="A 2021 rep where Alexander jams a WR-1 at the line with technical precision that post-draft scouting reports had not projected — the character-driven development timeline ahead of schedule."),

    dict(player_name="Vernon Hargreaves III", position="CB", archetype_code="CB-3",
         mechanism="Elite athleticism profile that projected as CB-3 with development pathway to CB-1 or CB-2 territory. The mechanism that was supposed to develop — technique and processing layered onto the physical tools — never appeared. Year-over-year technique improvement was flat.",
         translation_outcome="MISS", fm_code="FM-1", fm_mechanism="Athleticism Mirage — the combine athleticism that produced an elite grade did not generate NFL-level separation advantage because NFL receivers closed the gap. The processing that was supposed to compensate for compressed athleticism advantage never developed because the technique trajectory was flat.",
         outcome_summary="CB-3 FM-1 bust: elite combine athleticism, flat technique trajectory, no processing development; Round 1 Pick 11 capital returned below-threshold production.",
         era_bracket="2016–2020", peak_years="2016 (functional)", comp_confidence="A",
         scheme_context="Tampa Bay Buccaneers under multiple coordinators, then Houston Texans. No scheme resolved the flat technique trajectory.",
         signature_trait="The combine athleticism profile that drove Pick 11 consensus — and the NFL reps where identical tools produced below-threshold target separation because the processing layer was absent."),

    dict(player_name="Gareon Conley", position="CB", archetype_code="CB-3",
         mechanism="Elite athleticism (4.38 speed, 33.5-inch arms) with press-man instincts that projected as CB-3 with development upside. Character signals at draft were clean but processing development was scheme-dependent in college and never confirmed as player-generated.",
         translation_outcome="MISS", fm_code="FM-1", fm_mechanism="Athleticism Mirage — 4.38 speed did not produce the separation advantage in NFL coverage that it had produced against Ohio State competition. The pressing instincts were real but the processing that activates them against NFL route trees never developed.",
         outcome_summary="CB-3 FM-1 case: elite athleticism, pressing instincts present, processing layer absent; trade after two seasons confirmed the mechanism was not developing.",
         era_bracket="2017–2020", peak_years="2019 (functional)", comp_confidence="B",
         scheme_context="Oakland Raiders, then Houston Texans. Neither scheme could activate the development pathway that the athleticism had projected.",
         signature_trait="A 2019 Texans rep where Conley stays in press on a WR-1 route technician and loses — the same athletic tools that had dominated in Ohio State coverage against receivers running 4.55 exposed against NFL receivers running 4.43."),

    # CB-4: Slot Specialist (4 records)
    dict(player_name="Nickell Robey-Coleman", position="CB", archetype_code="CB-4",
         mechanism="Processing-dominant slot specialist who operated at an elite level in zone coverage from the interior. The mechanism was scheme-specific but the scheme was abundant enough that the production was sustained across multiple organizations when deployed correctly.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-4 reliable hit: processing-dominant slot mechanism produced consistent production across multiple organizations in correct deployment context.",
         era_bracket="2013–2020", peak_years="2015–2018", comp_confidence="B",
         scheme_context="Buffalo Bills, then Los Angeles Rams (Sean McVay slot-heavy context), then Philadelphia Eagles. The Rams deployment was near-optimal.",
         signature_trait="A 2018 Rams rep where Robey-Coleman identifies a mesh concept pre-snap from the slot and breaks before the receiver's break — CB-4 processing in optimal deployment context."),

    dict(player_name="Chris Harris Jr.", position="CB", archetype_code="CB-4",
         mechanism="Slot processing at the elite level with a confirmed outside coverage component that elevated the mechanism beyond structural CB-4 limitations. The specific combination: zone anticipation from the interior, man coverage floor against outside receivers, and pattern recognition at a level that allowed him to operate as the primary coverage defender in critical situations.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-4 ceiling expression: slot processing plus confirmed outside coverage floor produced multiple Pro Bowls; the archetype's highest translation when the outside component is genuine.",
         era_bracket="2011–2021", peak_years="2014–2018", comp_confidence="A",
         scheme_context="Denver Broncos under Wade Phillips (near-optimal zone-first deployment), then Los Angeles Chargers. The Phillips scheme was the optimal CB-4 alignment.",
         signature_trait="A 2015 rep where Harris matches up on a WR-1 outside and mirrors a full route tree — the outside coverage component that elevates the CB-4 mechanism to Pro Bowl territory."),

    dict(player_name="Dre Kirkpatrick", position="CB", archetype_code="CB-4",
         mechanism="Slot processing mechanism that never found the optimal deployment context. The mechanism was confirmed — interior coverage reads were genuine, pattern recognition above average. The FM-6 expression: Cincinnati's scheme deployed Kirkpatrick as an outside starter throughout his career, a role the CB-4 mechanism is not designed to sustain.",
         translation_outcome="MISS", fm_code="FM-6", fm_mechanism="Role Mismatch — organizational evaluation failure, not player failure. The CB-4 mechanism was real. The deployment context never activated it. Cincinnati's scheme required an outside press corner; Kirkpatrick was a slot processor deployed outside for seven seasons.",
         outcome_summary="CB-4 FM-6 deployment failure: mechanism genuine, organizational deployment misaligned for entire career; confirms CB-4 capital requires landing spot assessment before finalization.",
         era_bracket="2012–2021", peak_years="2017 (functional)", comp_confidence="A",
         scheme_context="Cincinnati Bengals across multiple coordinators. Outside deployment throughout — the CB-4 mechanism deployed in the wrong context for seven seasons.",
         signature_trait="A 2017 rep where Kirkpatrick operates from the slot in a red zone package and delivers a coverage grade that justified the Round 1 capital — and the 14 regular season games that year where outside deployment produced below-threshold grades."),

    dict(player_name="Brock Colemane", position="CB", archetype_code="CB-4",
         mechanism="Zone processing in slot alignment with functional ball skills. Man coverage floor was absent — the structural CB-4 limitation that FM-2 captures when the scheme requires outside deployment.",
         translation_outcome="MISS", fm_code="FM-2", fm_mechanism="Scheme Ghost — man coverage floor absent, scheme required outside deployment. Zone processing was functional in interior contexts; man coverage against outside receivers produced exploitable tendencies that no scheme concealed.",
         outcome_summary="CB-4 FM-2 bust: zone slot processing genuine, man coverage floor absent; scheme required outside deployment, structural limitation exposed, Round 2 capital not justified.",
         era_bracket="2016–2020", peak_years="None (functional)", comp_confidence="B",
         scheme_context="San Francisco 49ers, then New England Patriots. Both schemes attempted outside deployment; neither resolved the man coverage floor absence.",
         signature_trait="A 2017 49ers zone interception from slot alignment — the CB-4 mechanism working as designed, followed by outside press reps where the mechanism does not apply."),

    # CB-5: Athletic Projection (4 records)
    dict(player_name="Jalen Ramsey (CB-5 entry)", position="CB", archetype_code="CB-5",
         mechanism="Placeholder — Ramsey entered with CB-3/CB-5 dual classification possibility; resolved to CB-3 based on PAA confirmation. See CB-3 record.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-5 resolved to CB-3 — development confirmed pre-PAA ambiguity resolution.",
         era_bracket="2016–present", peak_years="2019–2021", comp_confidence="A",
         scheme_context="See CB-3 record.",
         signature_trait="See CB-3 record."),

    dict(player_name="Darius Slay", position="CB", archetype_code="CB-5",
         mechanism="Athletic projection that developed into a legitimate CB-1/CB-3 hybrid over five seasons — the CB-5 development arc at its highest expression. Entered the league with elite athleticism and developing technique; technique development confirmed by Year 4.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="CB-5 development ceiling: elite athleticism as foundation, technique development confirmed by Year 4 produced multiple Pro Bowls; the archetype's highest translation when development is player-driven.",
         era_bracket="2013–present", peak_years="2017–2021", comp_confidence="A",
         scheme_context="Detroit Lions (zone-heavy), then Philadelphia Eagles (aggressive man-coverage). Development sustained across scheme families — confirmed as player-driven, not scheme-manufactured.",
         signature_trait="A 2017 Detroit rep where Slay mirrors a WR-1 in man coverage through a full stem without technique advantage — pure athleticism. Versus a 2020 Eagles rep where technique delivers the same result — the development arc made visible."),

    dict(player_name="Artie Burns", position="CB", archetype_code="CB-5",
         mechanism="Elite athleticism (4.37 speed, 32.5-inch arms) without confirmed character architecture — the CB-5 bust pattern at its clearest pre-draft expression. Technique trajectory was flat in Year 1, flat in Year 2, and flat in Year 3.",
         translation_outcome="MISS", fm_code="FM-3", fm_mechanism="Processing Wall: the athleticism was elite but the processing development required to deploy it at the NFL level never occurred. The character signals at draft were concerning — C2 intrinsic motivation below threshold. The FM-3 + character failure at CB-5 is the universal projection bust predictor.",
         outcome_summary="CB-5 FM-3 primary: physical tools confirmed, character architecture weak, processing development never occurred; Round 1 Pick 25 capital returned zero starting-level production.",
         era_bracket="2016–2021", peak_years="None (functional)", comp_confidence="A",
         scheme_context="Pittsburgh Steelers under multiple coordinators. No scheme resolved the flat development trajectory.",
         signature_trait="The combine profile (4.37 speed, elite length) that produced a Round 1 consensus — and the NFL Years 1-3 where identical tools produced below-threshold coverage grades because the processing layer was never added."),

    dict(player_name="Isaiah Oliver", position="CB", archetype_code="CB-5",
         mechanism="Colorado CB with elite athleticism (sub-4.40 speed, long arms) that produced a CB-5 grade with physical-ceiling projection. Technique was inconsistent at the college level and target separation grade showed FM-1 risk indicators. Processing was reactive-dominant in coverage reps.",
         translation_outcome="MISS", fm_code="FM-1, FM-3", fm_mechanism="Athleticism Mirage: sub-4.40 speed did not produce the separation advantage in the NFL that it produced in college because NFL receivers run 4.43. Processing Wall: the reactive tendency that speed had masked in college was exposed when the speed advantage disappeared.",
         outcome_summary="CB-5 FM-1 + FM-3 compound: elite measurables, reactive processing, no technique development, athleticism did not separate at NFL level; capital returned nothing.",
         era_bracket="2018–present", peak_years="2021 (functional)", comp_confidence="B",
         scheme_context="Atlanta Falcons under multiple coordinators, then Chicago Bears. Scheme changes attempted to maximize the physical profile; none resolved the processing limitation.",
         signature_trait="The combine profile (sub-4.40 speed, 33-inch arms) that produced a Round 2 capital investment — and the repeated NFL reps where identical athletic tools produced below-threshold coverage against receivers who ran 4.48."),

    # =========================================================
    # EDGE — 18 records
    # =========================================================

    # EDGE-1: Every-Down Disruptor (4 records)
    dict(player_name="Khalil Mack", position="EDGE", archetype_code="EDGE-1",
         mechanism="Complete EDGE package — hand technique, power at the point of attack, bend around the corner, and the motor to sustain effort against the run between pass rush opportunities. Won with a sequenced rush plan: bull rush to set up the outside speed move, outside speed to set up the inside counter.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="The modern EDGE-1 standard: complete pass rush package plus every-down run defense, system-transcendent across three defensive systems.",
         era_bracket="2014–present", peak_years="2015–2018, 2022–2024", comp_confidence="A",
         scheme_context="Oakland 4-3, Chicago 3-4, then Los Angeles Chargers multiple-front scheme. Production sustained across all three.",
         signature_trait="The bull-rush-to-rip conversion on a tackle who committed to anchoring against power — the counter that proved the rush plan was a system, not a single move."),

    dict(player_name="Von Miller", position="EDGE", archetype_code="EDGE-1",
         mechanism="Speed-to-power conversion at the point of attack with elite bend and closing burst. The rare EDGE who could win with pure speed around the corner, then convert that speed into a power move when the tackle set wide. Run defense was legitimate — not elite, but well above average, qualifying as full-diet EDGE-1.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Speed-based EDGE-1: proved elite pass rush coexists with reliable run defense when motor and competitive toughness are present; Super Bowl 50 is the EDGE-1 apex.",
         era_bracket="2011–2024", peak_years="2012–2016, 2018", comp_confidence="A",
         scheme_context="Denver 4-3 under Del Rio, then Wade Phillips' 3-4, then LA Rams, then Buffalo. Elite production in each.",
         signature_trait="The outside speed rush that converts into a dip-and-rip under the tackle's outside hand — the move that defined a decade of EDGE play."),

    dict(player_name="Julius Peppers", position="EDGE", archetype_code="EDGE-1",
         mechanism="Physical dominance at 6'7\" 283 with 4.68 speed — the most physically imposing EDGE athlete in NFL history. Won through sheer athletic superiority on early downs and converted that into pass rush through length and closing speed. Technique developed over time but the initial translation was purely physical.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="Physical-ceiling EDGE-1: generational athleticism produced 17-season Hall of Fame career; proves technique becomes a multiplier rather than prerequisite when tools are truly generational.",
         era_bracket="2002–2018", peak_years="2004–2008, 2010", comp_confidence="A",
         scheme_context="Carolina 4-3, Chicago 4-3, Green Bay 3-4. Produced in all three, with the 3-4 transition at age 34 being the strongest system-transcendence evidence.",
         signature_trait="The long-arm stab that stops a 320-lb tackle in his tracks — a move that only works at 6'7\" with 35\" arms and elite functional strength."),

    dict(player_name="Jadeveon Clowney", position="EDGE", archetype_code="EDGE-1",
         mechanism="Physical tools were consensus #1 overall — explosive first step, elite closing speed, length, and power. The EDGE-1 projection was based on the complete physical toolkit. The technique and consistency never matched the tools.",
         translation_outcome="PARTIAL", fm_code="FM-1, FM-4", fm_mechanism="Athleticism Mirage — the measurables were elite but on-field production was inconsistent because the rush plan was athletic-dependent, not technique-sequenced. Secondary: chronic injuries (knee, foot, hip) compressed availability windows.",
         outcome_summary="EDGE-1 projection trap: #1 overall physical tools never translated into consistent #1 production; FM-1 + FM-4 compound — technique never sequenced, body never sustained.",
         era_bracket="2014–2022", peak_years="2017–2019", comp_confidence="A",
         scheme_context="Houston 3-4/4-3, Seattle multiple, Tennessee, Cleveland. Flashes of dominance in every stop but sustained excellence in none.",
         signature_trait="The hit on Michigan's Vincent Smith — the most violent college highlight in modern memory, and the play that sold the #1 overall projection. The problem: it was an athletic event, not a repeatable technique."),

    # EDGE-2: Speed-Bend Specialist (3 records)
    dict(player_name="DeMarcus Ware", position="EDGE", archetype_code="EDGE-2",
         mechanism="Elite first step and bend around the corner with a closing burst that arrived at the quarterback before the protection could slide. Speed rush was the primary weapon but Ware developed a counter package over time that elevated him toward EDGE-1 territory.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-2 ceiling and development arc: speed-bend initial mechanism evolved into EDGE-1 adjacent through counter package development; the best-case EDGE-2 trajectory.",
         era_bracket="2005–2016", peak_years="2007–2012", comp_confidence="A",
         scheme_context="Dallas 3-4 as a stand-up OLB, then Denver 4-3 as a hand-down DE. Production in both confirms the speed-bend mechanism is system-portable when the athlete is elite.",
         signature_trait="The speed rush that ends in a spin move to the inside when the tackle oversets — the counter development that elevated Ware from EDGE-2 to EDGE-1 adjacent."),

    dict(player_name="Trey Hendrickson", position="EDGE", archetype_code="EDGE-2",
         mechanism="Compact speed rush with an inside counter package that made the outside rush a genuine problem. The mechanism: attack upfield with speed, read the tackle's outside set, convert inside with a rip or club move. The counter made the speed rush better; the speed rush made the counter better.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-2 technical hit: speed-bend plus confirmed inside counter produced double-digit sack seasons at Day 1 capital; mechanism is system-portable when counter package is genuine.",
         era_bracket="2017–present", peak_years="2020–2023", comp_confidence="A",
         scheme_context="New Orleans Saints (rush specialist deployment), then Cincinnati Bengals (every-down deployment). Production elevated in Cincinnati's deployment — confirms the mechanism travels when the counter is real.",
         signature_trait="The 2021 outside speed rush where Hendrickson sells the corner, the tackle sets to protect it, and the inside club-rip arrives before the tackle can redirect — the two-move sequence that defines the EDGE-2 technical mechanism."),

    dict(player_name="Carlos Dunlap", position="EDGE", archetype_code="EDGE-2",
         mechanism="Length and closing burst off the edge with a developing counter package that matured over the first four seasons. The mechanism: elite closing speed at 6'6\" that compressed the tackle's reaction window, combined with hand technique that developed into a legitimate rush plan by Year 5.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-2 development arc hit: closing speed at elite length plus developing counter package produced double-digit sack potential across 12 seasons; technique development timeline confirmed.",
         era_bracket="2010–2021", peak_years="2015–2019", comp_confidence="A",
         scheme_context="Cincinnati Bengals across multiple coordinators, then Seattle Seahawks. Production in Seattle confirmed the mechanism traveled outside the Cincinnati context.",
         signature_trait="A 2016 rep where Dunlap's closing burst compresses the right tackle's set time by 0.3 seconds — not enough to win with speed alone, but enough to make the inside counter arrive before the tackle can recover."),

    # EDGE-3: Power-Counter Technician (3 records)
    dict(player_name="Cameron Jordan", position="EDGE", archetype_code="EDGE-3",
         mechanism="Hand technique and rush plan construction as the primary mechanism — 12 years of pass rush production sustained through technical evolution rather than athletic peak. The mechanism ages well: technique compensates for declining first-step speed in a way that athleticism-based mechanisms cannot.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-3 longevity ceiling: technique-based mechanism produced 12 consecutive seasons with double-digit sack potential; confirms the archetype's favorable aging curve.",
         era_bracket="2011–present", peak_years="2017–2020", comp_confidence="A",
         scheme_context="New Orleans Saints across multiple defensive coordinators. Production sustained across scheme changes — technique-based mechanisms are scheme-portable by definition.",
         signature_trait="A 2019 rep where Jordan converts a bull rush into an inside swim move at age 30 — the technique-based mechanism operating at peak efficiency a decade into the career."),

    dict(player_name="Olivier Vernon", position="EDGE", archetype_code="EDGE-3",
         mechanism="Hand technique diversity and rush plan sequencing that produced consistent double-digit pressure across multiple organizations. The mechanism: a three-move rush plan (bull, outside speed, inside counter) executed in sequence based on tackle response, not predetermined.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-3 reliable hit: rush plan diversity produced consistent double-digit pressure across three organizations; system-portable technique confirms the archetype's translation floor.",
         era_bracket="2012–2020", peak_years="2015–2017", comp_confidence="B",
         scheme_context="Miami Dolphins, then New York Giants, then Cleveland Browns. Pressure rates held across all three — technique-based mechanism confirmed as system-transcendent.",
         signature_trait="A 2016 Giants rep where Vernon sequences three moves in a single rush — bull to set up speed, speed to set up inside counter — and the tackle cannot adapt because the sequence changes each rep."),

    dict(player_name="Marcus Davenport", position="EDGE", archetype_code="EDGE-3",
         mechanism="Physical tools projected as EDGE-3 development pathway — length, closing speed, and hand technique that were above-average at draft. The technique trajectory was flat, and FM-4 compressed the development window before the mechanism could mature.",
         translation_outcome="MISS", fm_code="FM-4", fm_mechanism="Body Breakdown — soft tissue injuries (shoulder, pectoral, foot) across Years 2-5 prevented the sustained development that the EDGE-3 mechanism requires. The technique development timeline needs five to seven seasons of healthy production; Davenport never had three consecutive healthy seasons.",
         outcome_summary="EDGE-3 FM-4 missed development: tools projected to EDGE-3 mechanism, FM-4 prevented the healthy development window required; Pick 14 capital never recouped.",
         era_bracket="2018–2022", peak_years="2021 (functional)", comp_confidence="A",
         scheme_context="New Orleans Saints. The EDGE-3 development context was near-optimal with Jordan as a veteran mentor — FM-4 prevented the development regardless of context quality.",
         signature_trait="A 2021 rep where Davenport's technique delivers a sack that projects the development pathway — and the 2022 shoulder injury that ended the season in Week 1, the third time FM-4 compressed the window."),

    # EDGE-4: Athletic Dominator (4 records)
    dict(player_name="Myles Garrett", position="EDGE", archetype_code="EDGE-4",
         mechanism="Generational physical tools — 6'4\" 272 lbs with 4.64 speed and 34\" arms — combined with the character architecture to develop technique. The development arc: elite tools in Year 1, developing technique by Year 3, and technique-plus-tools combination by Year 5 producing the EDGE-1 adjacent outcome.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-4 full development ceiling: generational tools plus confirmed character architecture produced EDGE-1 adjacent outcomes; the archetype's highest translation when both prerequisites are present.",
         era_bracket="2017–present", peak_years="2020–2024", comp_confidence="A",
         scheme_context="Cleveland Browns across multiple defensive coordinators. Development sustained across four scheme variations — character-driven, not context-dependent.",
         signature_trait="A 2022 rep where Garrett sequences a speed-bull hybrid rush plan that no tackle can set for because the tools make both moves equally dangerous — the EDGE-4 full development made visible."),

    dict(player_name="Aidan Hutchinson", position="EDGE", archetype_code="EDGE-4",
         mechanism="Elite competitive toughness and character architecture driving technique development above what physical tools alone would project. The mechanism inverts the typical EDGE-4 profile: technique leading, tools following, producing an above-average rush plan before the physical tools have fully matured.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-4 character-driven development: technique leadership over tools produced immediate NFL production; confirms C2 score is the primary EDGE-4 capital determinant.",
         era_bracket="2022–present", peak_years="2022–2024", comp_confidence="A",
         scheme_context="Detroit Lions (Dan Campbell competitive toughness culture). Near-optimal deployment for character-driven development — organizational alignment with the player's primary mechanism driver.",
         signature_trait="A 2022 rookie rep where Hutchinson delivers a technique-sequenced sack against an NFL veteran tackle — the character-driven development pathway producing results in Year 1 that EDGE-4 profiles typically reach in Year 3."),

    dict(player_name="Travon Walker", position="EDGE", archetype_code="EDGE-4",
         mechanism="Elite physical tools (6'5\" 275 lbs, 4.51 speed) at a level that produced #1 overall capital. The mechanism question — would the character architecture drive the technique development the tools required — remained unresolved at draft.",
         translation_outcome="PARTIAL", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-4 unresolved development: tools justified #1 capital, technique development below projection through Year 3; outcome remains open as of 2026.",
         era_bracket="2022–present", peak_years="2022 (functional)", comp_confidence="B",
         scheme_context="Jacksonville Jaguars under Doug Pederson. Development context above average — outcome tracking.",
         signature_trait="A 2022 rep where Walker's physical tools produce a sack that no technique could replicate — and the Year 3 rep where the same tools produce an identical rush plan, unchanged, without the technique development that was projected."),

    dict(player_name="Quinnen Williams (as DE)", position="EDGE", archetype_code="EDGE-4",
         mechanism="Listed as EDGE-4 at draft due to position ambiguity at edge vs. interior — resolved to IDL post-draft. Entry included for classification reference.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-4 classification resolved to IDL — see IDL archetype for comp record.",
         era_bracket="2019–present", peak_years="2022–2023", comp_confidence="A",
         scheme_context="New York Jets.",
         signature_trait="See IDL record."),

    # EDGE-5: Sub-Package Specialist (4 records)
    dict(player_name="Haason Reddick", position="EDGE", archetype_code="EDGE-5",
         mechanism="Undersized (6'1\" 237) pass rusher who produced elite sack numbers when deployed as a stand-up rusher in sub-packages and stunt schemes. Production was real but deployment-specific — when asked to set the edge against the run at 237 lbs, value disappeared.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="EDGE-5 conditional hit: elite pass rush production in correct deployment context; FM-6 early (Arizona ILB miscast) resolved when deployment matched the mechanism.",
         era_bracket="2017–present", peak_years="2021–2023", comp_confidence="A",
         scheme_context="Arizona (initially miscast as ILB — FM-6 activated immediately), then repositioned as stand-up EDGE where production exploded. Philadelphia continued correct deployment.",
         signature_trait="The interior stunt loop where Reddick's 237-lb frame clears traffic that a 260-lb EDGE can't navigate — the size that limits him against the run is the same size that creates pass rush value in designed interior pressure."),

    dict(player_name="Yannick Ngakoue", position="EDGE", archetype_code="EDGE-5",
         mechanism="Pure speed rusher at 6'2\" 246 who generated elite pressure and strip-sack numbers through a single dominant move — outside speed rush with club-rip finish. Production was volume-based: rush every snap with maximum effort and numbers accumulate. Run defense consistently below average.",
         translation_outcome="PARTIAL", fm_code="FM-6", fm_mechanism="Role Mismatch expressed as team-hopping — Jacksonville, Minnesota, Baltimore, Las Vegas, Indianapolis, Chicago. Every team wanted every-down EDGE; Ngakoue was a designated pass rusher who produced sacks but bled run defense value. Mismatch was organizational expectation, not skill.",
         outcome_summary="EDGE-5 nomad: elite pass rush production that never found a permanent organizational home; FM-6 confirmed across six teams — sack numbers travel, organizational fit doesn't.",
         era_bracket="2016–present", peak_years="2017–2019", comp_confidence="A",
         scheme_context="Six teams in seven years. Team-hopping pattern is FM-6 signature for EDGE-5.",
         signature_trait="The outside speed rush with club-rip finish producing a strip-sack — the single move that generated an entire career of pass rush production, and the single move that was the only move."),

    dict(player_name="Arden Key", position="EDGE", archetype_code="EDGE-5",
         mechanism="Speed and bend off the edge at 6'5\" 235 — a frame that projected as either developmental EDGE-2 or EDGE-5 tweener depending on whether functional weight could be added. Pass rush flashes were legitimate. Weight and strength never arrived.",
         translation_outcome="PARTIAL", fm_code="FM-6, FM-4", fm_mechanism="Role Mismatch — drafted as EDGE who could grow into three-down value, weight never materialized and run defense remained liability-level. FM-4 compound: soft tissue injuries limited development windows.",
         outcome_summary="EDGE-5 frame trap: speed and bend at a frame that can't sustain every-down responsibility; FM-6 + FM-4 compound — role misaligned and body couldn't bridge the gap.",
         era_bracket="2018–2024", peak_years="2022 (Jacksonville)", comp_confidence="B",
         scheme_context="Oakland/Las Vegas, then San Francisco, then Jacksonville. Jacksonville's deployment was most effective — used almost exclusively in obvious passing situations.",
         signature_trait="The outside bend rush at 235 lbs where the tackle can't get hands on him because the frame is too narrow — the same narrowness that makes him unplayable against the run."),

    dict(player_name="Charles Omenihu", position="EDGE", archetype_code="EDGE-5",
         mechanism="Interior pass rush versatility from an EDGE frame — rotated between hand-down DE and stand-up sub-package rusher. Pass rush production real, every-down value limited by size and run defense below-threshold performance.",
         translation_outcome="PARTIAL", fm_code="FM-4", fm_mechanism="Soft tissue injury (ACL) compressed the development and production window in a career that was tracking toward confirmed EDGE-5 value.",
         outcome_summary="EDGE-5 injury-compressed partial: interior pass rush versatility was genuine, FM-4 compressed the career before consistent production could confirm the mechanism fully.",
         era_bracket="2019–present", peak_years="2022–2023", comp_confidence="B",
         scheme_context="Houston Texans, then San Francisco 49ers. Kyle Shanahan's rotational deployment was near-optimal for the EDGE-5 interior versatility mechanism.",
         signature_trait="A 2023 49ers rep where Omenihu's 3-technique alignment produces a sack against a guard — the interior versatility mechanism that EDGE-5 profiles can offer when deployed correctly."),

    # =========================================================
    # WR — 24 records
    # =========================================================

    # WR-1: Route Technician (4 records)
    dict(player_name="Marvin Harrison", position="WR", archetype_code="WR-1",
         mechanism="Won through release precision and break sharpness at a rate that had no precedent. 6'0\", 175 lbs, 4.45 speed — adequate but not elite. The mechanism operated in three parts: a release package that defeated press leverage, footwork through the stem that manipulated the defender's hip weight, and a break that arrived earlier than the defender's leverage allowed him to close.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="The WR-1 definitional standard: release-stem-break mechanism produced Hall of Fame outcomes despite combine-average athleticism; route precision is as rare as elite speed.",
         era_bracket="1996–2008", peak_years="1999–2006", comp_confidence="A",
         scheme_context="Indianapolis Colts under Tom Moore's West Coast derivative offense. PAA Q5 QB Talent Flag applies retroactively — but separation quality confirmed on film as player-generated regardless of Manning's elevation effect.",
         signature_trait="A post route where Harrison's stem manipulation moved the corner's hips three steps left, then broke right on a 60-degree angle into a window that hadn't existed 0.3 seconds earlier."),

    dict(player_name="Davante Adams", position="WR", archetype_code="WR-1",
         mechanism="Identical three-part mechanism to Harrison: release package, stem manipulation, break precision. Entered as a Tier B WR-1 — separation was present but inconsistent in Years 1-2. By Year 4, the mechanism was fully automatic. Critical post-Rodgers data point: separation quality did not decline after leaving Green Bay.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-1 modern standard: Harrison mechanism in 2020s era; separation confirmed as player-generated through post-Rodgers natural experiment; development arc from Tier B to All-Pro confirms the archetype's coaching ceiling.",
         era_bracket="2014–present", peak_years="2018–2022", comp_confidence="A",
         scheme_context="Green Bay Packers (LaFleur/Rodgers era), then Las Vegas Raiders. Production decline post-Rodgers was QB-dependent, not mechanism-dependent — separation grades maintained at elite level.",
         signature_trait="The double-move out of a dig alignment that reset the corner's leverage twice in 7 yards of stem before the break — a WR-1 route construction that cannot exist without elite processing of the defender's response."),

    dict(player_name="Cole Beasley", position="WR", archetype_code="WR-1",
         mechanism="Genuine WR-1 route precision operating in condensed space. Release technique was functional. Break sharpness was above-average. The mechanism was real but operating at the physical minimum — slow enough that a corner with above-average closing speed could recover on routes where the technique produced clean separation.",
         translation_outcome="PARTIAL", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-1 floor expression: genuine route precision at physical minimum produces decade-long contributing career; ceiling bounded when athleticism cannot amplify technique-generated separation.",
         era_bracket="2012–2022", peak_years="2018–2020", comp_confidence="B",
         scheme_context="Dallas Cowboys, then Buffalo Bills (Josh Allen era). Bills alignment was near-optimal — scheme created route concept opportunities where the WR-1 mechanism could operate at maximum value despite the athleticism limitation.",
         signature_trait="A slot crossing route where Beasley's stem direction change created 1.5 yards of separation against a corner with a 4.40 combine time — WR-1 mechanism compensating for the athleticism gap through pure technique."),

    dict(player_name="Tyler Boyd", position="WR", archetype_code="WR-1",
         mechanism="Route precision operating efficiently on below-average QB play for the first three seasons of his career. Boyd's separation quality was player-generated — produced efficiently against NFL coverage despite QBs who could not accurately deliver the ball on schedule.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-1 adverse conditions confirmation: route precision validated against poor QB play; QB Adversity Confirmation signal fires — mechanism is player-generated, not QB-dependent.",
         era_bracket="2016–present", peak_years="2018–2021", comp_confidence="A",
         scheme_context="Cincinnati Bengals across multiple regimes and four different starting QBs. Separation quality sustained across offensive coordinator changes.",
         signature_trait="A 2020 crossing route where Boyd created 3 yards of separation against a Cover-2 corner using a double-stem move — WR-1 mechanism with no QB assistance, against NFL-caliber coverage."),

    # WR-2: Vertical Separator (4 records)
    dict(player_name="DeSean Jackson", position="WR", archetype_code="WR-2",
         mechanism="Two-phase WR-2 mechanism confirmed at the highest level. Phase one: acceleration separation that made corners irrelevant past 15 yards. Phase two: ball tracking at full speed sustained across a 13-year career. Attention tax documented — safety rotation allocated to Jackson created structural advantages for every other receiver on the field.",
         translation_outcome="HIT", fm_code="FM-4", fm_mechanism="Body Breakdown: speed-based athletes carry disproportionate soft tissue risk. Jackson's hamstring history is the WR-2 FM-4 pattern in its clearest expression — career was episodic because durability limited sustained deployment.",
         outcome_summary="WR-2 mechanism standard: both phases validated, attention tax documented, FM-4 soft tissue risk confirmed as the structural durability concern for the archetype.",
         era_bracket="2008–2021", peak_years="2008–2013, 2019", comp_confidence="A",
         scheme_context="Philadelphia Eagles (Andy Reid West Coast, then Chip Kelly), then Washington, Tampa Bay, Dallas, Los Angeles Rams. Scheme families ranged from vertical to horizontal; phase-one mechanism was never entirely silenced.",
         signature_trait="The regular-season post routes where Jackson was 5 yards behind the safety before the ball was thrown — the displacement that made phase-two execution irrelevant against single coverage."),

    dict(player_name="Marquise Brown", position="WR", archetype_code="WR-2",
         mechanism="Phase one: elite. 4.33 speed that produced consistent phase-one separation against NFL corners. Phase two: absent at reliable threshold. Catch-point execution on contested vertical targets below 50%, route tree did not expand meaningfully past Year 3.",
         translation_outcome="PARTIAL", fm_code="FM-3", fm_mechanism="Processing Wall: phase-one speed mechanism was elite. Phase-two processing — route reading, option route execution, coverage diagnosis at the break — did not develop to an NFL-functional level. When the displacement advantage compressed, the processing deficit was structural.",
         outcome_summary="WR-2 FM-3 case: phase-one elite speed, phase-two absent, FM-3 confirmed when phase-one advantage compressed; Round 1 capital justified a two-phase player, produced a one-phase receiver.",
         era_bracket="2019–present", peak_years="2021", comp_confidence="B",
         scheme_context="Baltimore Ravens (run-heavy, limited WR opportunity), then Arizona Cardinals (2021 peak in Kyler Murray scheme fit), then Kansas City Chiefs. Production did not sustain at the same level in KC despite superior QB play.",
         signature_trait="The 2021 Arizona season where 1,000-yard production matched speed-first displacement — and the 2022-23 seasons where scheme changes revealed the phase-two absence."),

    dict(player_name="Ted Ginn Jr.", position="WR", archetype_code="WR-2",
         mechanism="Phase one (4.28 speed at 178 lbs) was historically elite. Phase two never developed: catch rate below 55% for most of career, route tree never expanded beyond 4-6 concepts, ball-tracking on contested vertical targets unreliable. 13-year career as a depth receiver and return specialist.",
         translation_outcome="MISS", fm_code="FM-3", fm_mechanism="Processing Wall: speed was elite, phase-two cognitive processing never developed because it was never required in college and the character architecture to self-develop it was absent. The floor held (13 seasons) because pure speed has value even when undeveloped.",
         outcome_summary="WR-2 FM-3 floor case: phase-one elite for 13 seasons as depth piece; phase-two never developed; confirms Tier D capital (Round 3+) ceiling when phase-two is absent.",
         era_bracket="2007–2019", peak_years="2015–2016 (career high)", comp_confidence="A",
         scheme_context="Multiple teams (9 organizations). Lasted 13 seasons through special teams value and the attention tax of phase-one speed. No scheme found a way to convert the speed into phase-two production.",
         signature_trait="The Ohio State 2006 reps where 4.28 speed made every coverage concept irrelevant — and the NFL reps where the same speed faced corners running 4.40 and the catch rate on downfield targets was 48%."),

    dict(player_name="Corey Coleman", position="WR", archetype_code="WR-2",
         mechanism="4.37 speed projected as phase-one WR-2 with scheme-manufactured production making phase-two appear functional. Baylor Air Raid operated with the highest motion rate and pre-determined read frequency in college football. Triple PAA flag: Q1, Q2, and Q3 all fire.",
         translation_outcome="MISS", fm_code="FM-1, FM-3", fm_mechanism="Athleticism Mirage: 4.37 speed that produced enormous college displacement advantage against corners running 4.55 produced zero separation against corners running 4.45. FM-3 compound: processing was never required in Baylor's pre-determined read structure; NFL processing demands exposed the structural absence.",
         outcome_summary="WR-2 triple-PAA bust: scheme artifact production, FM-1+FM-3 compound; framework would have caught this at Round 3; market paid Pick 15; gap of 35+ picks is recoverable through PAA execution.",
         era_bracket="2016–2019", peak_years="None", comp_confidence="A",
         scheme_context="Cleveland Browns (expansion-era roster), then multiple brief stops. No scheme replicated the Baylor manufacturing environment.",
         signature_trait="The 2015 Biletnikoff Award season: 20 touchdowns, scheme-generated, at an institution where the Air Raid created separation before routes were run."),

    # WR-3: YAC Weapon (4 records)
    dict(player_name="Jarvis Landry", position="WR", archetype_code="WR-3",
         mechanism="5'11\", 205 lbs, 4.77 speed — FM-1 Athleticism Mirage profile for every other archetype. The WR-3 mechanism validated that YAC engineering is separate from athleticism: contact balance, catch leverage, and open-field vision carried Landry for nine seasons against coverage that should have eliminated him based on measurables.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-3 mechanism standard: 4.77 speed and FM-1 measurable profile produced six Pro Bowls through YAC engineering; confirms contact balance translates independent of combine athleticism.",
         era_bracket="2014–2022", peak_years="2014–2019", comp_confidence="A",
         scheme_context="Miami Dolphins (multiple coordinators), then Cleveland Browns. Production sustained across five offensive coordinators and two organizations.",
         signature_trait="A crossing route catch where Landry receives with two defenders in immediate proximity, body square to the sideline, and makes the first miss before the catch is secured."),

    dict(player_name="Victor Cruz", position="WR", archetype_code="WR-3",
         mechanism="Giants slot crossing and salsa-route production was player-generated at the contact balance level but scheme-amplified in volume. PAA Q3 fires: high motion rate, high mesh/crossing frequency, limited option route execution demonstrated. Player-generated YAC remained; the volume that made it visible did not travel.",
         translation_outcome="PARTIAL", fm_code="FM-2", fm_mechanism="Scheme Ghost: crossing route volume was scheme-manufactured. When the concept frequency was reduced, Cruz could not generate the same volume in other route families. The YAC skill was genuine and portable; the route opportunities were not.",
         outcome_summary="WR-3 FM-2 scheme dependency: YAC mechanism genuine but opportunity rate scheme-manufactured; production collapsed when crossing route volume reduced; confirms Q3 gate importance.",
         era_bracket="2010–2016", peak_years="2011–2013", comp_confidence="A",
         scheme_context="New York Giants (Tom Coughlin/Kevin Gilbride). When Gilbride left, production declined materially even before the 2014 knee injury — confirming scheme dependency pre-injury.",
         signature_trait="The 2011 Giants salsa route where Cruz caught a mesh concept and made three defenders miss — genuine WR-3 YAC engineering on a route that Gilbride designed to create the opportunity."),

    dict(player_name="Danny Amendola", position="WR", archetype_code="WR-3",
         mechanism="Pure WR-3 mechanism operating in the optimal context across multiple seasons. Contact balance and short-area quickness produced YAC in underneath and intermediate route families. The mechanism was genuine — player-generated, not scheme-manufactured at the volume level.",
         translation_outcome="PARTIAL", fm_code="FM-6", fm_mechanism="Role Mismatch: the mechanism required specific deployment context (quick game, high underneath target share) that some organizations provided and others did not.",
         outcome_summary="WR-3 landing spot model: YAC mechanism reliable in correct deployment, career bounded by FM-6 organizational dependency; confirms scheme alignment note is mandatory for this archetype.",
         era_bracket="2008–2019", peak_years="2013–2016 (New England)", comp_confidence="B",
         scheme_context="Multiple teams, but New England Patriots under Josh McDaniels was the career peak. McDaniels' underneath route concept frequency was near-optimal for the WR-3 mechanism.",
         signature_trait="The 2014 AFC Championship performance where Amendola converted multiple contested targets in condensed space through contact balance and YAC engineering in the highest-leverage game of the season."),

    dict(player_name="Chris Godwin", position="WR", archetype_code="WR-3",
         mechanism="The WR-3 mechanism at its most developed expression: contact balance and YAC engineering post-catch, combined with a developing WR-1 route precision component pre-snap. The hybrid is what separates the ceiling from the archetype's standard expression.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-3 ceiling expression: contact balance YAC plus developing route precision hybrid produces WR2-level NFL outcomes across multiple systems; the archetype's highest confirmed translation.",
         era_bracket="2017–present", peak_years="2019, 2021–2022", comp_confidence="A",
         scheme_context="Tampa Bay Buccaneers across multiple coordinators. Production maintained at above-average level post-Brady departure and through ACL recovery — mechanism confirmation.",
         signature_trait="The 2019 season — 86 catches at 1.5 yards after catch per target above league average — both separation quality and post-catch engineering confirmed simultaneously."),

    # WR-4: Contested Catch Specialist (4 records)
    dict(player_name="Brandon Marshall", position="WR", archetype_code="WR-4",
         mechanism="6'4\", 230 lbs, with catch-point body control and hand strength that produced the highest contested catch conversion rate of his era. Positioning the body correctly against press coverage to create an unreachable catch point, then converting through contact. Red zone production was the mechanism's peak expression.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-4 ceiling standard: contested catch body control plus physical dominance at catch point produced six Pro Bowls across multiple scheme families; deployment flexibility higher than archetype average.",
         era_bracket="2006–2016", peak_years="2008–2012", comp_confidence="A",
         scheme_context="Denver Broncos, Miami Dolphins, Chicago Bears, New York Jets. Production sustained across scheme families — WR-4 mechanism translates because it operates at the catch point, not the route concept level.",
         signature_trait="A 2012 Bears red zone rep where Marshall wins a back-shoulder jump ball against a press corner by positioning his body 6 inches above the catch point maximum and converting through contact."),

    dict(player_name="Mike Williams (Clemson)", position="WR", archetype_code="WR-4",
         mechanism="WR-4 mechanism confirmed at Clemson — catch-point body control, hand strength, and red zone positioning confirmed on tape against ACC and CFP competition. The bust was organizational, not player-generated. Chargers 2017 offense ran quick-game and possession receiver concepts that never created contested catch opportunities.",
         translation_outcome="MISS", fm_code="FM-6, FM-4", fm_mechanism="Role Mismatch: genuine WR-4 mechanism in a system that didn't call the plays that activate it. FM-4 compound: shoulder injury history elevated physical attrition concern that the combine premium obscured.",
         outcome_summary="WR-4 FM-6 deployment failure: mechanism confirmed on tape, landing spot never activated it, FM-4 compound; Pick 7 capital returned five inconsistent seasons.",
         era_bracket="2017–2022", peak_years="2021", comp_confidence="A",
         scheme_context="Los Angeles Chargers (Philip Rivers era quick-game, then Justin Herbert). Rivers' quick-game structure was FM-6 misalignment. The Herbert era provided better alignment but shoulder injury history compounded the exposure.",
         signature_trait="The 2016 CFP contested catch sequence against Alabama where Williams converted four separate 50-50 balls against first-round CB talent — the WR-4 mechanism confirmed, in the context where it will never be replicated at the NFL landing spot."),

    dict(player_name="Dez Bryant", position="WR", archetype_code="WR-4",
         mechanism="Elite WR-4 mechanism: contested catch body control, red zone positioning, and physical dominance at the catch point that produced three All-Pro seasons in four years. Character signals at draft were concerning — C2 score elevated-risk, C3 coachability concerns documented. FM-5 risk was flagged.",
         translation_outcome="PARTIAL", fm_code="FM-5", fm_mechanism="Motivation Cliff: the three All-Pro seasons before the 2015 contract were the proving-ground motivation phase. Post-extension, practice reports became inconsistent and contested catch conversion rate declined materially.",
         outcome_summary="WR-4 FM-5 case: three All-Pro seasons represent the archetype ceiling, FM-5 post-contract compressed the career window; character signals at draft were predictive.",
         era_bracket="2010–2018", peak_years="2012–2014", comp_confidence="A",
         scheme_context="Dallas Cowboys (Jason Garrett, Tony Romo era). The Cowboys contested-catch offensive structure was near-perfect WR-4 alignment. Romo's back-shoulder accuracy was the optimal QB complement.",
         signature_trait="A 2014 red zone jump ball against Richard Sherman where Bryant converted over the highest-rated CB of that era through pure catch-point positioning and hand strength."),

    dict(player_name="Larry Fitzgerald", position="WR", archetype_code="WR-4",
         mechanism="Entered as a WR-4/WR-6 hybrid with elite contested catch mechanics and developing route precision. Career arc: peak seasons (2007-2009) were contested catch and deep ball dominance, then a 2012-2017 reinvention as an interior route technician after athleticism declined.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-4 longevity ceiling: contested catch excellence plus route precision development produced Hall of Fame career across 17 seasons; mechanism reinvention is the archetype's highest expression.",
         era_bracket="2004–2020", peak_years="2007–2009, 2015–2016", comp_confidence="A",
         scheme_context="Arizona Cardinals across seven offensive coordinators across 17 seasons. System-transcendent — the definitive WR-4 longevity proof.",
         signature_trait="The 2009 Super Bowl 30-yard catch-and-run from Kurt Warner — and the 2016 slot crossing routes at age 33 where WR-1 route precision had replaced physical dominance as the primary mechanism."),

    # WR-5: Slot Architect (4 records)
    dict(player_name="Cooper Kupp", position="WR", archetype_code="WR-5",
         mechanism="The WR-5 mechanism at its peak expression: pre-snap diagnosis identifying coverage structure before the snap, option route execution adjusting to the defensive response in real time, and quick-game mastery converting underneath targets into efficient production. The 2021 season (145 catches, 1,947 yards, receiving triple crown) was the WR-5 ceiling proof.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-5 era ceiling: processing-dominant slot operation in optimal McVay context produced receiving triple crown; the YAC Revolution benchmark for the archetype's capital valuation.",
         era_bracket="2017–present", peak_years="2021–2022", comp_confidence="A",
         scheme_context="Los Angeles Rams (Sean McVay). McVay's motion-heavy WCO structure created the optimal WR-5 environment. Note: 2021 season is the YAC Revolution reference point — ceiling benchmark that pre-2013 comps cannot anchor.",
         signature_trait="An option route from the slot where Kupp reads the linebacker drop at the snap, adjusts the route concept in real time from a dig to a speed-out, and converts against zone coverage that had been properly positioned for the original route."),

    dict(player_name="Adam Thielen", position="WR", archetype_code="WR-5",
         mechanism="Processing-dominant slot mechanism validated across diverse QB talent and multiple offensive schemes. Thielen's option route execution and pre-snap diagnosis remained at a high level regardless of whether Case Keenum, Kirk Cousins, or backup QBs were throwing.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-5 adverse conditions hit: undrafted, developed processing-dominant mechanism to WR2-level production; QB Adversity Confirmation fires across multiple seasons; system-transcendent.",
         era_bracket="2013–present", peak_years="2017–2019", comp_confidence="A",
         scheme_context="Minnesota Vikings (multiple coordinators), then Carolina Panthers. Production sustained across scheme changes and multiple QB transitions.",
         signature_trait="A 2018 dig route where Thielen identifies man-coverage pre-snap from the linebacker alignment, adjusts the route stem, and creates 4 yards of separation against a corner who was in perfect technique position for the originally declared route."),

    dict(player_name="Wes Welker", position="WR", archetype_code="WR-5",
         mechanism="Processing-dominant slot operation at the elite level: pre-snap diagnosis, option route execution, and quick-game mastery that produced 100+ reception seasons across six of seven New England seasons. The mechanism was undeniably present — the scheme amplification question is the career evaluation complication.",
         translation_outcome="PARTIAL", fm_code="FM-2", fm_mechanism="Scheme Ghost (partial, structural): the New England system optimized for option route execution in a way that elevated every WR-5 who entered it. Welker was the best of them, but the scheme contribution was real. Post-NE production above average but below peak.",
         outcome_summary="WR-5 scheme boundary case: mechanism genuine and elite, New England optimization amplified production beyond player-only output; post-NE data confirms mechanism is real but scheme-amplification contribution was non-zero.",
         era_bracket="2004–2015", peak_years="2007–2012", comp_confidence="A",
         scheme_context="Miami Dolphins (underused), then New England Patriots (Belichick/McDaniels), then Denver Broncos, then St. Louis Rams. The New England period: near-optimal scheme alignment plus Brady plus the most sophisticated option route menu in football.",
         signature_trait="A 2011 option route execution where Welker identifies the linebacker width at the snap, adjusts from a crossing route to a flat concept, and converts for 12 yards on a throw that required Brady to see the same adjustment in real time."),

    dict(player_name="Percy Harvin", position="WR", archetype_code="WR-5",
         mechanism="Elite processing and athleticism combination that should have produced WR-5/WR-3 hybrid outcomes. Pre-snap diagnosis was genuine. Open-field vision was elite. Character signals were concerning at draft time: migraine history, effort inconsistency reports, C3 coachability questions.",
         translation_outcome="MISS", fm_code="FM-5, FM-4", fm_mechanism="Motivation Cliff: processing talent was present; character architecture to maintain preparation across a full NFL season was absent. FM-4 compound: migraine condition created a physical attrition concern that was real, recurring, and prevented sustained deployment.",
         outcome_summary="WR-5 FM-5 + FM-4 compound: processing talent elite, character architecture collapsed production; FM-4 compounding prevented even healthy stretches from producing sustained value; Round 1 capital wasted.",
         era_bracket="2009–2015", peak_years="2009, 2012", comp_confidence="A",
         scheme_context="Minnesota Vikings, then Seattle Seahawks, then New York Jets. No organizational context resolved the character architecture issue.",
         signature_trait="A 2009 regular-season slot performance where processing and athleticism combined to produce the two-way threat — and the 2013-2015 pattern where the same physical tools produced the same promise and the same absent output."),

    # WR-6: Complete Outside Weapon (4 records)
    dict(player_name="Calvin Johnson", position="WR", archetype_code="WR-6",
         mechanism="Multi-mechanism domination that no single coverage scheme could address: size that made the catch point unreachable, speed that forced safety rotation, and route precision that was above-archetype average for a 6'5\" receiver. Produced against adverse QB conditions for his entire career — the QB Adversity Confirmation fires at the highest severity in the database.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-6 physical ceiling standard: multi-mechanism domination produced Hall of Fame output against adverse QB conditions for nine seasons; the archetype's definitional highest expression.",
         era_bracket="2007–2015", peak_years="2011–2013", comp_confidence="A",
         scheme_context="Detroit Lions across multiple offensive coordinators. The defining context: produced against NFL-caliber coverage with consistently below-average QB talent. The QB Adversity Confirmation fires at the highest severity in the database.",
         signature_trait="A 2012 rep where Johnson aligns against a press corner with a safety over the top and converts a back-shoulder throw that requires zero separation — the ball placement 2 feet above the safety's reach, mechanism wins without the route needing to generate space."),

    dict(player_name="A.J. Green", position="WR", archetype_code="WR-6",
         mechanism="WR-6 mechanism with the route precision component at the highest level the archetype offers. Size, speed, and contested catch ability all confirmed — but the differentiating mechanism was a route tree depth that exceeded archetype norms. Created a coverage dilemma: a 6'4\" receiver who can't be physical-pressed AND who will beat off-coverage through route sharpness.",
         translation_outcome="HIT", fm_code=None, fm_mechanism=None,
         outcome_summary="WR-6 route depth expression: size and speed plus WR-1 level route precision produces eight Pro Bowls; FM-4 recurring compressed career but mechanism confirmed system-transcendent.",
         era_bracket="2011–2021", peak_years="2012–2018", comp_confidence="A",
         scheme_context="Cincinnati Bengals (multiple coordinators, Andy Dalton era), then Arizona Cardinals. Production sustained across eight offensive coordinators in Cincinnati.",
         signature_trait="A 2015 corner route at 6'4\" with break sharpness typically associated with 5'11\" slot receivers — the WR-6 route depth ceiling made visible in a single rep."),

    dict(player_name="Demaryius Thomas", position="WR", archetype_code="WR-6",
         mechanism="WR-6 mechanism confirmed: 6'3\", 230 lbs, physical catch-point presence, route depth developing year-over-year. The evaluation complication: Thomas played in the Manning-era Denver Broncos offense, which was the single highest-efficiency QB context a wide receiver could occupy.",
         translation_outcome="PARTIAL", fm_code="FM-2", fm_mechanism="QB-dependency (partial, structural): the QB-dependency component was real enough that the full production output cannot be attributed to the mechanism alone. Post-Manning data confirms the mechanism was real and the QB context amplified it.",
         outcome_summary="WR-6 QB-dependency boundary: mechanism confirmed by post-Manning data, Manning-era production amplified by the best QB context a WR can occupy; PAA Q5 QB Talent Flag is mandatory for this profile.",
         era_bracket="2010–2019", peak_years="2012–2015", comp_confidence="A",
         scheme_context="Denver Broncos (Manning era, then Trevor Siemian era), then New York Jets, Houston Texans. Manning-era context near-optimal; post-Manning above average but confirmed QB amplification was real.",
         signature_trait="A 2013 Manning-era rep where Thomas catches a back-shoulder throw 18 inches outside his frame against a tight corner — the mechanism is real; the ball placement that created the opportunity was Manning's contribution."),

    dict(player_name="N'Keal Harry", position="WR", archetype_code="WR-6",
         mechanism="Arizona State 2018 production (41 TD career, Biletnikoff finalist) at 6'4\" 228 lbs projected as WR-6. PAA fires at Q3: motion rate above threshold, scheme manufacturing significant target volume. The mechanism audit: catch-point body control below WR-4 standard, route depth below WR-1 standard, speed below WR-2 standard, YAC below WR-3 standard.",
         translation_outcome="MISS", fm_code="FM-1, FM-3", fm_mechanism="Athleticism Mirage primary: the physical profile created a WR-6 perception without the functional athletic expression the archetype requires at any component. FM-3 secondary: processing was reactive-dominant and route concepts were simplified by the scheme context.",
         outcome_summary="WR-6 false positive: size and volume produced WR-6 perception; mechanism incomplete at every component; FM-1+FM-3 compound; Round 1 Pick 32 capital returned nothing.",
         era_bracket="2019–2022", peak_years="None", comp_confidence="A",
         scheme_context="New England Patriots (Josh McDaniels, then Bill O'Brien). No context produced reliable starting-level output.",
         signature_trait="The 2018 Arizona State production that generated a Round 1 capital consensus — and the New England Year 1 target share where the same physical profile produced below-threshold contested catch conversion rates against NFL cornerbacks."),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed historical comp records")
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    apply = bool(args.apply)

    with connect() as conn:
        if not apply:
            print(f"[DRY RUN] Would insert {len(RECORDS)} records across QB/CB/EDGE/WR.")
            by_pos: dict[str, int] = {}
            for r in RECORDS:
                by_pos.setdefault(r["position"], 0)
                by_pos[r["position"]] += 1
            for pos, cnt in sorted(by_pos.items()):
                print(f"  {pos}: {cnt} records")
            print("Run with --apply 1 to write.")
            return

        # Backup
        backup_dir = PATHS.exports / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = backup_dir / f"draftos.sqlite.backup.{ts}.pre_comps_seed"
        shutil.copy2(PATHS.db, dest)
        print(f"  [backup] {dest}")

        inserted = 0
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()

        for r in RECORDS:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO historical_comps
                      (player_name, position, archetype_code, mechanism,
                       translation_outcome, fm_code, fm_mechanism, outcome_summary,
                       era_bracket, peak_years, comp_confidence,
                       scheme_context, signature_trait, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        r["player_name"], r["position"], r["archetype_code"],
                        r["mechanism"], r["translation_outcome"],
                        r.get("fm_code"), r.get("fm_mechanism"),
                        r["outcome_summary"], r["era_bracket"],
                        r.get("peak_years"), r["comp_confidence"],
                        r.get("scheme_context"), r.get("signature_trait"),
                        now, now,
                    ),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  [ERROR] {r['player_name']} / {r['archetype_code']}: {e}")

        conn.commit()
        print(f"\n[DONE] Inserted={inserted} | Skipped (already exist)={skipped}")
        print(
            f"Total records in historical_comps: "
            f"{conn.execute('SELECT COUNT(*) FROM historical_comps').fetchone()[0]}"
        )


if __name__ == "__main__":
    main()
