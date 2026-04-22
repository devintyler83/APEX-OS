# APEX OS Site Update Pack

## Goal
Update https://apexsignal.app/ so the site still feels like a serious operating system for evaluation, but clearly opens the door for NFL Draft fans who want to build their own board, find archetype-based edges, and use APEX during draft week.

---

## Hard recommendation
Do **not** rebuild the site from scratch.
Keep the current architecture, keep the serious tone, and ship a focused public-facing layer:

1. Update homepage copy
2. Rename **Library** to **Archetypes**
3. Add **For Draft Fans** to the top nav
4. Add a dedicated **For Draft Fans** section on the homepage
5. Add a dedicated **For Draft Fans** page
6. Add a short **How to use APEX on draft week** block
7. Keep the auditability / deterministic story intact

---

## Recommended information architecture

### Top nav
- Product
- How It Works
- Signals
- Archetypes
- For Draft Fans
- Open APEX Board

### Homepage sections
1. Hero
2. Product
3. How It Works
4. Signals
5. Archetypes
6. For Draft Fans
7. Surfaces
8. Why Trust It
9. Final CTA

### New page
- `/for-draft-fans`

Optional later:
- `/archetypes`
- `/draft-week`

---

# Homepage copy

## Hero

**APEX OS**

**The draft operating system for people who want to build a board — not just read one.**

APEX OS takes the rankings, measurables, archetypes, film notes, and market noise around the NFL Draft and turns them into one clean board you can actually defend.

It produces an independent APEX score, compares it to consensus, and surfaces the gap as the signal that matters.

### Hero subcopy
Most draft content tells you what the market thinks.
APEX OS tells you where the market may be wrong.

Every prospect gets an archetype, trait profile, risk map, capital band, and divergence signal so you can stop arguing in circles and start making sharper calls.

### Hero support bullets
- Deterministic scoring. Same inputs, same board.
- Archetypes over vibes. Every player has a real football identity.
- Divergence engine. Find where APEX is higher or lower than consensus.
- Built for fans, creators, analysts, and anyone tired of recycled boards.

### Hero CTAs
Primary: **Open APEX Board**
Secondary: **See how it works**

---

## Product

### Section heading
**Not another mock draft. The system behind the mock.**

### Section intro
APEX OS is not here to spit out another list and call it insight.
It is the logic, structure, and evidence layer behind your board — the system that turns scattered draft inputs into one consistent, independent evaluation process.

### Card 1 — Consensus spine
**Consensus spine**

APEX ingests active source rankings, normalizes the player universe, and builds a weighted market baseline.
That gives you the real draft price before the system adds its own opinion.

### Card 2 — Archetype engine
**Archetype engine**

Every prospect is scored into a clear archetype label, trait profile, and failure-mode risk map.
You are not just comparing WR vs WR or CB vs CB.
You are comparing how different types of players actually win.

### Card 3 — Divergence signals
**Divergence signals**

Once APEX has its own evaluation, it compares that view to consensus and flags where the system is meaningfully higher or lower.
That gap is the whole game: hidden value, overhyped bets, and real edges you can actually explain.

### Card 4 — Decision surfaces
**Decision surfaces**

Big Board, APEX Board, Prospect Detail, Scout Pad, and decision-card outputs all sit on top of the same engine.
One prospect, one system, multiple ways to work the board.

---

## How It Works

### Section heading
**One board. Many inputs. One opinion.**

### Section intro
APEX OS takes in the draft world’s noise, cleans it up, and turns it into a usable operating system.
The process is deterministic by design, so the same inputs always produce the same output.

### Step 1
**Build the market baseline**

Source rankings are ingested, normalized, deduplicated, and weighted into one consensus spine.
That is not the product — it is the market price the product reacts to.

### Step 2
**Score the player independently**

APEX evaluates the prospect from first principles using archetypes, trait vectors, measurables context, and failure modes.
It does not just remix outside opinions with nicer formatting.

### Step 3
**Assign the football identity**

Every player gets an archetype label that defines the way he wins, plus an archetype-fit quality signal like Clean, Solid, Tweener, Compression, or No Fit.
That is what turns player ranking into actual football evaluation.

### Step 4
**Surface the disagreement**

The system compares APEX rank to consensus rank and labels the delta as APEXHIGH, APEXLOW, ALIGNED, or structural.
That is where the real tension lives.

### Step 5
**Turn it into decisions**

The board, detail panel, tags, Scout Pad, and decision cards make the evaluation usable on draft week.
You are not reading theory.
You are working a board.

---

## Signals

### Section heading
**This is where you find your edge.**

### Section intro
The best output in APEX OS is not the score by itself.
It is the moment where the system’s independent evaluation and the market’s price stop agreeing.

### Signal block 1
**APEXHIGH**

APEX sees a player materially better than the market does.
These are your flag-plant prospects, your my-guys list, and the names you want circled before the board starts moving.

### Signal block 2
**APEXLOW**

The market is pricing a player higher than APEX is willing to go.
These are your bust fades, over-drafted bets, or players whose translation risk is bigger than the hype.

### Signal block 3
**ALIGNED**

Sometimes the system and the market land in the same spot.
That matters too.
Agreement can be conviction, not boredom.

### Signal block 4
**Structural**

Some divergence is expected because of positional value or archetype economics, not because the market is wrong.
APEX makes that distinction explicit so you do not chase fake edges.

### Bridge line
Every divergence comes with a reason.
No black box.
No just-trust-the-model.
Just traceable logic tied to archetype, traits, and risk.

---

## Archetypes

### Section heading
**Stop ranking names. Start ranking player types.**

### Section intro
APEX OS is built on canonical archetypes across positions, each with its own trait weights, mechanisms, and failure paths.
That means a speed-bend EDGE is not scored like a power-counter EDGE, and a route technician WR is not scored like a contested-catch specialist just because both share a position label.

### Body copy
This is the unlock for smart fans.
Once you understand archetypes, you stop asking “is this player good?” and start asking “what kind of player is he, how does that type usually translate, and is the market pricing that correctly?”

Every archetype also lives next to real hit paths, partial hit paths, and bust paths.
That matters because APEX is not trying to win the draft internet for one weekend — it is trying to make calls that can still hold up after the league tells us who was right.

### CTA
**Explore Archetypes**

---

## For Draft Fans

### Section heading
**If you’re the fan with 20 tabs open on draft week, this is your home base.**

### Section intro
APEX OS lets you take the rankings, measurables, clips, notes, and random rabbit holes you are already obsessing over and turn them into one board that actually has structure.

Every prospect gets an archetype, APEX score, tier, capital band, risk map, and consensus comparison, so you can move from “I have a feeling” to “I have a case.”

You are not here to copy the media board.
You are here to find the players the market is missing, understand why they might hit or miss, and build your own board with more rigor than most public draft content ever reaches.

### Draft-week play patterns
- Find your **APEXHIGH** guys at every position and plant your flags before the draft starts.
- Filter by archetype and capital band to build a **rounds 3–5 my-guys list**.
- Use Prospect Detail and Scout Pad as your **on-the-clock notes** when your team picks.
- Learn the historical hit and bust paths tied to each archetype instead of falling for highlight clips and combine theater.

### CTA
**Go to For Draft Fans**

---

## Surfaces

### Section heading
**One engine. Multiple ways to work the board.**

### Section intro
The board is the entry point, but the value is in how each surface turns the same underlying evaluation into a different draft-week job.

### Surface 1
**Big Board**

See the market, your filters, tags, and overall board state in one view.

### Surface 2
**APEX Board**

Sort by the independent APEX opinion and find where your system is willing to be aggressive.

### Surface 3
**Prospect Detail**

Open the full profile: archetype, trait bars, failure modes, comps, divergence, and capital context.

### Surface 4
**Scout Pad**

Quick-glance draft-week view with Draft Call, Market View, Risk Snapshot, Flags, and Draft Day Take.

### Surface 5
**Decision cards**

Condensed prospect calls you can actually use while the picks are happening.

---

## Why Trust It

### Section heading
**Because every hot take should be traceable.**

### Body copy
APEX OS is deterministic, versioned, and audit-friendly by design.
The same inputs produce the same output, every override is logged, and the entire system is built to be checked against what actually happens after the draft.

That matters for teams, but it matters for fans too.
It means your strongest takes are not just louder — they are cleaner, more falsifiable, and easier to improve over time.

---

## Final CTA

**Stop reading everyone else’s board. Build one.**

Use APEX OS to find your archetype bets, pressure-test consensus, and walk into draft weekend with a board that feels like yours.

### CTA buttons
- Open APEX Board
- For Draft Fans

---

# For Draft Fans page copy

## Hero

**For Draft Fans**

**Build your board. Find your guys. Defend every call.**

APEX OS is for the fan who wants more than rankings and mock drafts.
It gives you a system for understanding what kind of prospect a player is, how he wins, where he breaks, and whether the market is pricing him correctly.

---

## What you actually get

### Block 1
**A real football identity for every prospect**

Every player gets an archetype label, not just a spot on a list.
That means you can see whether a prospect is a route technician, speed-bend rusher, anticipatory lockdown corner, raw projection, or something in between.

### Block 2
**A cleaner way to find edges**

APEX does not just tell you who it likes.
It shows you where it disagrees with consensus and by how much.
That is how you find true flag plants instead of just reposting the same names everyone else already loves.

### Block 3
**A risk map, not just a ranking**

The system carries failure-mode logic, archetype fit quality, and historical translation context so you can understand not just upside, but how the bet can die.

### Block 4
**Usable draft-week surfaces**

The board, Prospect Detail panel, Scout Pad, and decision cards turn deeper evaluation into something you can actually use on Thursday, Friday, and Saturday.

---

## How to use it on draft week

### Thursday
Build your first-round conviction board.
Find the premium-position prospects where APEX is higher or lower than consensus and decide who you are willing to stand on.

### Friday
Hunt the value pocket.
Filter for APEXHIGH players in the Day 2 range, especially the archetypes the market tends to flatten together.

### Saturday
Start swinging on translation bets.
This is where archetype understanding matters most, because late-round value usually comes from player types the market misreads, not from familiar names.

---

## Why archetypes matter to fans

Most fan boards still rank players like every WR, EDGE, or CB is being asked the same question.
APEX does not do that.

It treats positions as families of different player types, each with their own mechanics, thresholds, and failure paths.
That changes the whole conversation.

Instead of “I like this guy more than consensus,” you get to say, “the market is pricing this archetype wrong, and here is why this specific prospect fits the hit path better than people realize.”

---

## Why divergence matters

Consensus is useful, but it is still the market.
If all you do is follow it, you are not finding signal — you are buying the same stock after everyone else already ran it up.

APEX exists to create an independent opinion first, then compare that opinion to consensus after the fact.
That comparison is the point.

When APEX and consensus diverge, you get something worth thinking about.

---

## Closing CTA

**If you’re serious enough to make your own board, you’re serious enough to use a real system.**

Open APEX Board and start building something sharper than another recycled top 100.

### CTA buttons
- Open APEX Board
- Explore Archetypes

---

# Developer-ready content map

## Anchors / IDs
Use stable section ids so nav and future routing stay clean.

### Homepage
- `#hero`
- `#product`
- `#how-it-works`
- `#signals`
- `#archetypes`
- `#for-draft-fans`
- `#surfaces`
- `#trust`
- `#cta`

### Standalone pages
- `/for-draft-fans`
- `/archetypes` (optional phase 2)
- `/draft-week` (optional phase 2)

---

# Implementation instructions for Claude Code

## Working rules
- Do not redesign the site from scratch.
- Keep the current visual identity, dark theme, and OS / intelligence-tool tone.
- Update copy architecture first.
- Keep existing serious/system language where it creates trust.
- Add a fan-facing layer without diluting the credibility stack.
- Rename any visible “Library” label to “Archetypes” where it refers to the site section/nav.
- Add “For Draft Fans” to the top nav and homepage.
- Create a dedicated For Draft Fans page.
- Preserve existing CTA to Open APEX Board.
- Do not remove deterministic / audit / divergence / versioned framing.
- Tone target: grounded, sharp, slightly obsessive, data-native, exciting but not corny.

## Exact implementation tasks
1. Update homepage hero copy using the copy in this document.
2. Replace existing Product, How It Works, Signals, Library/Archetypes, Users-related copy with the new blocks above.
3. Add a new homepage section with id `for-draft-fans`.
4. Add a new top-nav item linking to `#for-draft-fans` or `/for-draft-fans` depending on routing preference.
5. Rename nav label and section label from `Library` to `Archetypes`.
6. Add a standalone `/for-draft-fans` page using the copy above.
7. Ensure CTA buttons point to the existing APEX Board entry point.
8. Keep page performance and layout intact; this is a content architecture update, not a framework migration.
9. If the site is a single static page, implement `/for-draft-fans` as either:
   - a second HTML page, or
   - a route if the framework supports it.
10. If helpful, tighten supporting microcopy around Scout Pad / Prospect Detail / APEX Board so they match the new fan-facing story.

---

# Claude Code master prompt

Use this prompt in Claude Code exactly as your starting instruction:

```text
You are updating the public-facing APEX OS marketing site at https://apexsignal.app/.

Your goal is NOT to redesign the brand.
Your goal is to sharpen the messaging architecture so the site still feels like a serious deterministic NFL Draft operating system, but now clearly speaks to NFL Draft fans who want to build their own board, use archetypes, find divergence-based edges, and work the product during draft week.

Hard constraints:
- Keep the current visual identity and overall layout language unless a small content-driven adjustment is needed.
- Do not rebuild from scratch.
- Preserve the credibility stack: deterministic, versioned, audit-friendly, divergence-driven, archetype-based.
- Rename “Library” to “Archetypes” in the nav / homepage where appropriate.
- Add “For Draft Fans” to the top navigation.
- Add a homepage section for For Draft Fans.
- Add a dedicated For Draft Fans page.
- Keep “Open APEX Board” as the primary CTA.
- Maintain a sharp, grounded, data-native tone. Exciting, but never cheesy.

Execution requirements:
1. Audit the current site structure and locate the files/components powering the homepage and navigation.
2. Apply the copy deck exactly where appropriate, adapting only for technical fit and existing component structure.
3. Keep section ids and nav anchors clean and future-proof.
4. If the site supports multiple pages, create /for-draft-fans.
5. If the site is single-page only, add the homepage section now and prepare the code structure so a dedicated page can be added cleanly next.
6. Do not invent new product claims beyond the provided copy deck.
7. After implementation, provide a concise changelog of files edited and any follow-up recommendations.

Use the following copy deck as source of truth:

[PASTE THE FULL COPY DECK FROM THIS DOCUMENT HERE]
```

---

# Claude Code shorter operator prompt

If you want the fast version:

```text
Update apexsignal.app without redesigning it.

Tasks:
- Rename Library -> Archetypes
- Add For Draft Fans to nav
- Add a new homepage For Draft Fans section
- Add a standalone For Draft Fans page
- Replace homepage copy with the supplied APEX OS copy deck
- Keep current visual identity and keep Open APEX Board as primary CTA
- Preserve deterministic / divergence / auditability / archetype framing
- Return edited files + concise changelog

I will paste the copy deck next.
```

---

# If Claude needs direct build instructions

## File-level implementation checklist
- Find homepage template/component
- Find nav/header component
- Find section labels / headings / CTA strings
- Search for string `Library`
- Search for Users section copy
- Search for hero headline and subhead
- Add new route or page file for `for-draft-fans`
- Verify links
- Run local preview/build

## Suggested git commit sequence
1. `feat: update apex os homepage messaging architecture`
2. `feat: add for draft fans page and nav link`
3. `refactor: rename library section to archetypes`

---

# Minimal manual handoff if needed

If you get blocked and need to hand this off manually, give Claude Code these two things only:
1. This markdown file
2. The repo/path for the website source

Then use this one-line instruction:

```text
Implement this update pack exactly, keep the design, ship the copy and routing changes, and return the changed files plus preview instructions.
```

