"""
S116: Write CB scoring notes to the notes table.
Run: python -m scripts._write_cb_notes_s116 --apply 0|1
"""
import sqlite3
import datetime
import argparse

DB_PATH = "data/edge/draftos.sqlite"
NOTE_TYPE = "scout"

NOTES = [
    # (prospect_id, note_text)
    (39, (
        "CB-1 CONFIRMED S116. PAA all four gates CLEAR. FM-2 flag withdrawn — outcome data resolves "
        "raw metrics gap (Zone=93rd pct, Man/Press=90th pct, QB Rating=56.2 across 2450 snaps vs "
        "80th pct competition). Arm length structural cap: 30-inch arms (10th pct). Competitive "
        "Toughness and Injury/Durability vectors reflect contested-catch limitation vs 6-3+ boundary "
        "receivers — not a mechanism discount. Scheme versatility confirmed: Virginia Tech zone + LSU "
        "man systems, no landing spot gate required. Production elite: 8 career INTs, 27 PDs, under "
        "27pct completion rate on 200+ coverage snaps. Score at CB-1 Production ceiling. "
        "Eval Confidence: Tier A."
    )),
    (38, (
        "CB-1 CONFIRMED S116. PAA all four gates CLEAR with full scouting data. Q3 resolved: 65.7 QB "
        "rating, McMillan result is sample-of-one vs generational prospect, not FM-1 pattern. Q4 "
        "resolved: anticipatory processing confirmed. Secondary CB-1 anticipatory trait developing "
        "underneath CB-3 athleticism profile — highest-upside combination in archetype. Bust risk "
        "materially lower than standard CB-3. FM-4 flag ACTIVE: January 2025 ACL tear. Pro Day "
        "4.37/38-inch vertical on surgically repaired knee is highly mitigating. Injury/Durability "
        "reflects surgery with recovery modifier — not a full-round capital discount, durability "
        "asterisk required. Eval Confidence: Tier A on coverage mechanism, Tier B on durability until "
        "Year 1 NFL snaps confirm knee holds. Capital note: FM-4 flag must be reflected in any "
        "recommendation above Day 2 threshold."
    )),
    (33, (
        "CB-1 CONFIRMED S116. PAA all four gates CLEAR. CB-2 override recommendation from prior "
        "session WITHDRAWN. CB-1 confirmed by full scouting data and PFF outcome data. Prior metrics "
        "(Zone=66.7, Man=58.3) understated mechanism — outcome data: Man/Press=80th pct, Zone=75th "
        "pct. Concept-reading mechanism transfers across coverage shells. Size cap: 180 lbs. "
        "Competitive Toughness and Injury/Durability reflect contested-catch limitation vs physical "
        "boundary receivers (QB rating 85.7 reflects this) — not FM-1. Athleticism is real; size "
        "creates matchup ceiling. Scheme note: Press-man ceiling activates highest, zone functional "
        "but not primary strength. Mandatory Landing Spot Note required above Day 1 capital threshold. "
        "Eval Confidence: Tier A on mechanism. Size cap is structural, not developmental."
    )),
    (72, (
        "CB-3 CONFIRMED S116. PAA all four gates CLEAR with full data. Q3 resolved: Tetairoa McMillan "
        "held to 38 yards, QB rating 66.0. Q4 resolved: anticipatory processing developing, confirmed "
        "in scouting report. FM-1 risk materially reduced. Prior Zone=36.1 raw metric was technique "
        "sub-component measurement, not coverage outcome — outcome data: Zone=87th pct. FM-2 concern "
        "withdrawn. One-year starter sample: mechanism confirmed but not stress-tested across multi-year "
        "body of work. Penalty flag: 4 penalties in 2025. Discipline scores reflect this. Competitive "
        "Toughness scores aggression positively. Deep ball tracking = developmental area, not structural "
        "FM-3. Eval Confidence: Tier B."
    )),
    (35, (
        "CB-2 CONFIRMED S116. PAA all four gates CLEAR. FM-2 flag from prior session WITHDRAWN — "
        "outcome data: Man/Press=82nd pct, Zone=77th pct, gap=5 points. SOS discount: 72nd pct "
        "opponent quality (Mountain West). Production score capped at 8/10 pending NFL sample — "
        "mechanism confirmed, discount is confidence modifier not mechanism flag. Combine resolved "
        "athleticism question: 9.67 RAS, 93rd pct historically, 4.40 forty. QB rating 49.6 = best "
        "coverage outcome in CB batch. 1732 snaps across 42 games. Eval Confidence: Tier B (SOS gap "
        "cannot be fully resolved pre-draft). First NFL season is the confirmation gate."
    )),
    (71, (
        "CB-3 CONFIRMED S116. PAA Q2 FM-2 flag WITHDRAWN — outcome data: Man/Press=78th pct, "
        "Zone=74th pct, 4-point gap. Q3 partial clear. FM-1 monitoring flag ACTIVE: overreacts to "
        "route fakes, opening hips early, relying on recovery speed to bail out instead of trusting "
        "technique — reactive-dominant processing confirmed. Not triggered yet; athleticism "
        "compensating. Monitor as career develops. Q4 reactive processing confirmed: Processing score "
        "caps at 6/10 per framework rules. FM-4 flag ACTIVE: forearm/wrist issue 2024 + apparent "
        "knee exit vs LSU and Texas A&M in 2025. Two separate injury events in consecutive years — "
        "medical clearance required before Round 1 capital recommendation. Injury/Durability reflects "
        "two-year consecutive pattern. Eval Confidence: Tier B (Q4 reactive flag + injury history)."
    )),
    (3236, (
        "CB-1 CONFIRMED S116. PAA all four gates CLEAR. Coverage=100th pct, Man/Press=97th pct, "
        "Zone=90th pct, QB rating=55.9 across 2146 snaps vs 80th pct competition. Prior divergence "
        "APEX_LOW -95 diagnosis: ARCHETYPE MISMATCH ARTIFACT — prior CB-3 label produced lower APEX "
        "score than CB-1 mechanism warrants. Reclassify from anomaly flag to archetype-correction-"
        "pending. Do not suppress or artifact-tag. Expect divergence to compress materially after "
        "archetype correction and rescore. Size structural cap: 5ft 8.5in, 182 lbs, short arms. "
        "Contested-catch limitation vs 6-3+ boundary receivers — Injury/Durability and Competitive "
        "Toughness reflect physical mismatch risk on specific matchup types. Deployment note: near-"
        "zero slot reps. CB-4 secondary trait documented for flexibility question. Mandatory Landing "
        "Spot Note — Cover 3 best fit. Pure man-coverage boundary scheme creates FM-6 risk given size. "
        "Eval Confidence: Tier A on mechanism. Size creates deployment dependency, not mechanism "
        "uncertainty."
    )),
    (74, (
        "CB-2 CONFIRMED S116. PAA all four gates CLEAR with full data. Q3 resolved: QB rating 58.1 "
        "vs 78th pct competition. FM-1 risk eliminated. Man coverage floor confirmed above 60 "
        "(Man/Press=79th pct outcome). Bust risk drops to lower-moderate per CB-2 doctrine — do not "
        "apply full Moderate bust weighting. Penalty flag: 13 flags over last two seasons. Discipline "
        "score reflects this. Competitive Toughness scores aggression positively — press-heavy "
        "deployments will generate flag volume, factor into Scheme Versatility score. XP-4 applies: "
        "technique trajectory pointing up (sophomore to junior improvement confirmed). Dev Trajectory "
        "scores above base CB-2 rate. FM-6 Mandatory Landing Spot Note: heavy Cover 1 man scheme is "
        "capital destruction — pattern-match Cover 3 or zone-primary system required. Any capital "
        "recommendation above Day 2 threshold requires landing spot confirmation. Eval Confidence: "
        "Tier A on mechanism, Tier B on NFL penalty translation."
    )),
    (338, (
        "CB-4 CONFIRMED S116. PAA all four gates CLEAR for CB-4 archetype context. FM-2 flag from "
        "prior session WITHDRAWN — outcome data: Man/Press=84th pct, Zone=79th pct. Age flag "
        "CRITICAL: turns 25 in August. Six college seasons of mileage. Finished product — no "
        "development premium. Dev Trajectory scored flat. Price current ability only. Tackling: 20pct "
        "missed tackle rate caps tackling component of Competitive Toughness. Run Defense outcome "
        "(90th pct) scores separately and stays high — motor is real, technique is poor. QB rating "
        "80.8 reflects honest coverage ceiling. Value proposition: run defense + blitz package "
        "(5 sacks 2025) + zone instincts from slot — not coverage dominance. FM-6 Mandatory Landing "
        "Spot Note: zone-heavy scheme, creative sub-package deployment required. NOT outside boundary. "
        "Cover 1 man-heavy or boundary-primary defense = organizational FM-6 before first snap. "
        "Eval Confidence: Tier A (finished product, no projection uncertainty)."
    )),
    (13, (
        "CB-1 CONFIRMED S116 (re-confirmation of S75 classification with full PAA gate data). PAA "
        "all four gates CLEAR. Prior CB-5 Raw Projection label incorrect and withdrawn — reclassified "
        "CB-1 Outside Press Cornerback in S75, now updated to CB-1 Anticipatory Lockdown with full "
        "combine confirmation. Age premium: 21.7 years old, September 2004 DOB — youngest CB in "
        "batch. Advanced processing confirmed at this age. XP-4 applies — Dev Trajectory scores above "
        "average. Production discount explanation: PROD=49.5 reflects deflections not converting to "
        "interceptions — ball-tracking development gap, not mechanism failure. Coverage quality "
        "(79th pct, QB rating 69.8) confirms mechanism. Score coverage quality not interception "
        "totals. Production cap at 7/10 pending NFL ball-tracking development. Combine confirmation: "
        "best 10-yard split among all CBs (1.51s, 82nd pct), 130-inch broad (92nd pct), 4.42 forty. "
        "Frame concern (182 lbs) is developmental — score in Injury/Durability not mechanism vectors. "
        "Market pricing gap: Round 4 projection is a stat-line discount. CB-1 mechanism confirmed "
        "against SEC/CFP competition at age 21. Expect APEX_HIGH divergence signal post-rescore. "
        "Eval Confidence: Tier A on mechanism, Tier B on frame durability until NFL season confirms."
    )),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Batch-fetch display names to avoid N+1 per-row queries
    pids = [pid for pid, _ in NOTES]
    rows = conn.execute(
        f"SELECT prospect_id, display_name FROM prospects "
        f"WHERE prospect_id IN ({','.join('?' * len(pids))}) AND season_id=1",
        pids,
    ).fetchall()
    names = {row[0]: row[1] for row in rows}

    print(f"\nCB scoring notes — {'DRY RUN' if not args.apply else 'WRITING'}")
    print(f"Players: {len(NOTES)}")

    for pid, note_text in NOTES:
        name = names.get(pid, f"pid={pid}")
        print(f"  {name} (pid={pid}): {len(note_text)} chars")
        if args.apply:
            conn.execute(
                "INSERT INTO notes (prospect_id, note_type, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, NOTE_TYPE, note_text, now, now),
            )

    if args.apply:
        conn.commit()
        count = conn.execute(
            f"SELECT COUNT(*) FROM notes WHERE prospect_id IN ({','.join('?' * len(pids))})",
            pids,
        ).fetchone()[0]
        print(f"\nNotes in DB for these {len(pids)} players: {count}")
    else:
        print("\n[DRY RUN] No writes. Pass --apply 1 to commit.")

    conn.close()


if __name__ == "__main__":
    main()
