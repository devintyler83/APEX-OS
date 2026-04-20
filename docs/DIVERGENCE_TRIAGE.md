\# Divergence Triage — APEX OS



Last updated: 2026-04-18 UTC.\[STATE\_SNAPSHOT.md]\[file:1]



Divergence Alerts are only actionable when they reflect \*\*structural\*\* disagreement between APEX and consensus, not artifacts (coverage, ghost PIDs, stale archetypes).\[STATE\_SNAPSHOT.md]\[file:1]



\---



\## 1. Triage Priorities



Work Divergence Alerts in this order:



1\. Premium positions: \*\*QB, CB, EDGE, OT, S\*\*.\[STATE\_SNAPSHOT.md]\[file:1]  

2\. Prospects with `ARCHETYPEOVERRIDES` or manual Sports Almanac notes (e.g., Downs, Genesis Smith, Mesidor, Ramsey).\[STATE\_SNAPSHOT.md]\[file:1]  

3\. Large-magnitude APEX\_LOW / APEX\_HIGH (|delta| ≥ 20) at premium positions.\[STATE\_SNAPSHOT.md]\[file:1]  

4\. Remaining Divergence Alerts (non-premium or small deltas) as time allows.



\---



\## 2. Core Checklist (per prospect)



Use this 5-step checklist for every Divergence Alert.



1\. \*\*Premium position gate\*\*



&#x20;  - Is this QB, CB, EDGE, OT, or S?  

&#x20;  - If \*\*no\*\*: treat as informational unless capital is Round 1–2 \*and\* FM-1/FM-4 are strong.  

&#x20;  - If \*\*yes\*\*: continue.



2\. \*\*Override / structural note check\*\*



&#x20;  - Does the prospect have an `ARCHETYPEOVERRIDES` entry or manual Sports Almanac note? (Downs, Genesis Smith, Mesidor, Ramsey, etc.).\[STATE\_SNAPSHOT.md]\[file:1]  

&#x20;  - If \*\*yes\*\*: assume divergence is \*intentional\* — do \*\*not\*\* dismiss. Restate the mechanism in one line.  

&#x20;  - If \*\*no\*\*: check for coverage / ghost-PID artifacts before acting (see S61–S63 notes on ghost PIDs).\[STATE\_SNAPSHOT.md]\[file:1]



3\. \*\*Archetype + FM stack\*\*



&#x20;  - Identify archetype and primary FM codes from APEX detail.\[QB/S/EDGE/IDL/ILB position libraries]\[file:11]\[file:9]\[file:23]\[file:16]\[file:15]  

&#x20;  - Map to patterns:

&#x20;    - Tools archetypes: EDGE-4, OT-1, QB-5, WR-6, RB-1 etc. → FM-1 / FM-4 risk (athleticism mirage / body breakdown).\[EDGE/OT/QB libraries]\[file:23]\[file:12]\[file:11]  

&#x20;    - Projection archetypes: QB-5, ILB-5, EDGE-4, OT-5 → FM-3 / FM-5 compound (XP-1 pattern).\[QB/ILB/EDGE]\[file:11]\[file:15]\[file:23]  

&#x20;    - Scheme-tied archetypes: S-3, S-4, ILB-3, DT-3, WR-5, EDGE-5 → FM-2 / FM-6 scheme dependence / role mismatch.\[S/ILB/DT/WR/EDGE]\[file:9]\[file:15]\[file:16]\[file:6]\[file:23]  

&#x20;  - This determines whether the right analyst tag is:

&#x20;    - `Possible Bust (FM-1)` / `Possible Bust (FM-3/FM-5)`  

&#x20;    - `Scheme Dependent (…position…)`  

&#x20;    - `Development Bet (…position…)`



4\. \*\*Pattern / cluster check\*\*



&#x20;  - Is this part of a known pattern? Examples:\[STATE\_SNAPSHOT.md]\[file:1]

&#x20;    - S-position APEX\_LOW cluster: Genesis Smith, Caleb Downs, Kamari Ramsey (premium APEX\_LOW structural, do not suppress).  

&#x20;    - ILB-3 APEX\_LOW structural disagreement on Reese; APEX pricing coverage floor vs consensus EDGE/LB athletic ceiling.  

&#x20;  - If \*\*yes\*\*: keep and mark as \*\*pattern-backed\*\*. Do not dismiss individual members of a structural cluster.  

&#x20;  - If \*\*no\*\*: treat as a standalone disagreement and document mechanism clearly.



5\. \*\*Final action\*\*



&#x20;  Pick one and log a one-line rationale:



&#x20;  - \*\*Accept Divergence\*\* (and optionally add analyst tags), or  

&#x20;  - \*\*Dismiss as artifact\*\* (coverage / PID / stale archetype) with a one-line reason.  



&#x20;  Always use mechanism language (archetype + FM + scheme), not vibes.



\---



\## 3. Standard One-Line Rationales (examples)



Use these as templates for Divergence notes. Replace names and details as needed.



\### Genesis Smith S — Divergence Alert -34



> “APEX is pricing FM-5 motivation risk and S-3 deployment sensitivity; consensus is treating Genesis Smith as a clean, scheme-agnostic Day 1 safety.”\[STATE\_SNAPSHOT + S library]\[file:1]\[file:9]



Suggested analyst tag:



\- `Possible Bust (FM-5)` — “FM-5 motivation and S-3 deployment dependency compound; capital requires a clean C2 read and explicit scheme fit.”\[file:1]\[file:9]



\---



\### Caleb Downs S — Divergence Alert -37



> “APEX is paying only for S-4 zone-dominant value under Mode B deployment, while consensus is pricing Caleb Downs as a universal safety with scheme-proof coverage.”\[STATE\_SNAPSHOT + S library]\[file:1]\[file:9]



Suggested analyst tag:



\- `Scheme Dependent (Zone S)` — “Profile is S-4 Zone-Dominant; landing spot must feature heavy split-safety / zone usage to realize consensus capital.”\[file:1]\[file:9]



\---



\### Kamari Ramsey S — Divergence Alert -39



> “APEX sees Kamari Ramsey as part of the S APEX\_LOW structural cluster, with specific coverage/deployment constraints the market is ignoring in a generic ‘starting safety’ price.”\[STATE\_SNAPSHOT + S library]\[file:1]\[file:9]



Suggested analyst tag:



\- `Scheme Dependent (Safety)` — “Safety value is system-tied; APEX is treating him as S-3/S-4 cluster, not a universal back-end fixer.”\[file:1]\[file:9]



\---



\### Carson Beck QB — Divergence Alert -30



> “APEX is discounting Carson Beck for QB archetype-driven processing and volatility risk that consensus QB boards are not fully pricing into their top-32 capital.”\[STATE\_SNAPSHOT + QB library]\[file:1]\[file:11]



Suggested analyst tag (if QB-3 or QB-5 with FM-3/FM-5):



\- `Possible Bust (FM-3/FM-5)` — “QB projection hinges on processing ceiling and C2; consensus is paying more for tools/production than APEX’s translation map supports.”\[file:11]



\---



\### Akheem Mesidor EDGE — Divergence Alert -20



> “APEX is fading Akheem Mesidor relative to consensus because EDGE archetype, counter package, and durability flags cap his ceiling below the tools-driven market narrative.”\[STATE\_SNAPSHOT + EDGE library]\[file:1]\[file:23]



Suggested analyst tag:



\- `Ceiling Capped EDGE` — “Profile and FM stack imply a capped ceiling vs market’s EDGE breakout story; better as role player than featured star in APEX model.”\[file:1]\[file:23]



\---



\### Nadame Tucker EDGE — Divergence Alert +26



> “APEX is ahead of the market on Nadame Tucker as a technique-led EDGE profile whose pass-rush translation odds are stronger than his current consensus rank implies.”\[STATE\_SNAPSHOT + EDGE library]\[file:1]\[file:23]



Suggested analyst tag:



\- `Development Bet (EDGE)` — “EDGE translation upside is real if pass-rush toolbox and role develop as projected; divergence reflects APEX buying the development curve early.”\[file:1]\[file:23]



\---



\## 4. When to auto-accept vs auto-dismiss



\*\*Auto-accept Divergence\*\* when:



\- Premium position and |delta| ≥ 20, \*\*and\*\*  

\- Archetype + FM stack is consistent with APEX stance, \*\*and\*\*  

\- No artifact red flags (ghost PIDs, low source count).\[STATE\_SNAPSHOT.md]\[file:1]



\*\*Auto-dismiss Divergence\*\* when:



\- Proven artifact case (ghost PID, coverage split, stale archetype) as in Sessions 60–63 for Reese/Thomas/Jacas/Simpson.\[STATE\_SNAPSHOT.md]\[file:1]  

\- Non-premium position with small delta and no meaningful FM risk.



Always leave a one-line reason in the rec note when you dismiss.



\---



\## 5. Tagging Conventions



Use analyst tags to turn Divergence into explicit bets:



\- `Possible Bust (FM-1)` — tools-first miss risk.  

\- `Possible Bust (FM-3/FM-5)` — projection archetype, processing/motivation compound.  

\- `Scheme Dependent (Zone S / ILB / DT / WR-5 / EDGE-5)` — role-locked, landing-spot sensitive.  

\- `Development Bet (EDGE / QB / OT)` — upside tied to technique/processing growth.  

\- `Ceiling Capped EDGE` (or similar) — starter-level but not star-level projection.



These tags become primary audit lenses in the post-draft framework and in future APEX versions.\[STATE\_SNAPSHOT.md]\[file:1]

