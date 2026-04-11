Perplexity Research Integration (§7)

1. Role of Perplexity in APEX OS
Perplexity is a research and enrichment layer only. It never:

Writes directly to the SQLite database.

Modifies source weights, consensus math, or APEX engine logic.

Replaces canonical scout sources or model-output storage rules.

Perplexity produces structured artifacts (CSV or JSON) that are then ingested by existing APEX pipeline scripts under the same deterministic, season-scoped rules.

2. Operating Rules (Inherited Non‑Negotiables)
All Perplexity-driven work must obey the core system rules:

Deterministic only: same prompt + same context must produce the same CSV schema; no ad‑hoc column changes without versioning.

Season‑scoped: 2026 class only (seasonid = 1); no cross‑season enrichment.

Active sources only: Perplexity outputs are not counted as “sources” in consensus, and must never be mixed into sources / sourcerankings.

Idempotent scripts: every ingest script that consumes Perplexity artifacts supports --apply 0/1 and can be run twice safely.

Pipeline layer integrity:

Research → CSV/JSON artifact

Ingest → update specific tables

Consensus / APEX engines remain unchanged.

\## Filesystem Map (Perplexity §7)



\- Root doc: C:\\DraftOS\\PERPLEXITY\_RESEARCH\_INTEGRATION.md

\- Scout research CSVs: C:\\DraftOS\\data\\imports\\rankings\\raw\\2026\\perplexityresearch2026.csv

\- Scout agg CSVs: C:\\DraftOS\\data\\imports\\rankings\\raw\\2026\\perplexityagg2026.csv

\- Comp enrichment CSVs: C:\\DraftOS\\data\\imports\\comps\\perplexity\_historical\_comps\_2026.csv

3. In‑Scope Integration Flows (§7)
3.1 Scout Aggregation (New Source)
Goal: Turn Perplexity Research outputs into a Tier 3 scout source (e.g. perplexity\_agg2026) feeding the consensus layer.

Pattern:

Perplexity produces a CSV with canonical ranking fields:

playername (APEX display\_name format)

school (canonicalized where possible)

position\_raw (original text, mapped later)

rank\_overall (1‑N)

rank\_position (optional)

notes (free text, ignored by math).

A new ingest script (name placeholder):

scripts/ingest\_perplexity\_agg\_2026.py

Reads CSV → populates sourceplayers + sourcerankings for a new sourceid with:

tier = T3, weight = 0.7, isactive = 1.

Uses the same mapping + canonicalization patterns as existing T3 sources.

Consensus engine (buildconsensus2026.py) picks this up automatically as another active source; no consensus logic changes allowed.

3.2 Comp Database Enrichment (historicalcomps)
Goal: Use Perplexity to expand the historical comp library, not to change live APEX scores.

Pattern:

Perplexity runs archetype-specific research prompts, returning structured rows:

playername (comp target)

archetypecode (e.g. EDGE-3, CB-2)

outcome (HIT, PARTIAL, MISS)

compconfidence (A, B, C)

era (short string, e.g. 2010s, 2000s)

mechanism\_summary (why this comp)

fmcode (optional, FM‑1…FM‑6 if clearly mapped).

A new seeding script (name placeholder):

scripts/seed\_perplexity\_comps\_2026.py

Writes into historicalcomps using INSERT OR IGNORE with the same constraints and indices as existing comp seeders.

Never touches FM reference rows or existing seeds; Perplexity data is additive only.

APEX scoring prompt already knows how to consume extra historicalcomps rows; no prompt or engine changes are required for basic comp enrichment.

3.3 Pages / Reports (Outbound Only)
Goal: Use Perplexity Pages as a publication layer for boards, not as an input to APEX.

Pattern:

A Python export script (export\_to\_perplexity\_pages\_2026.py, or similar) produces static HTML / markdown snapshots of the current board state.

These are uploaded or pasted into Perplexity Pages for narrative reports, without any feedback loop into the DB.

4. Artifact Contracts (CSV / JSON)
To keep the pipeline deterministic, every Perplexity flow must obey explicit data contracts.

4.1 Scout Aggregation CSV Contract
Filename pattern: data/imports/rankings\_raw/2026/perplexity\_agg\_board\_YYYYMMDD.csv

Columns (fixed schema):

Column	Type	Required	Notes
playername	TEXT	Yes	Must match or be mappable to prospects.display\_name
school	TEXT	Yes	Prefer canonical school names
position\_raw	TEXT	Yes	Original text, mapped by ingest script
rank\_overall	INTEGER	Yes	1 = highest
rank\_position	INTEGER	No	Optional, position-specific rank
notes	TEXT	No	Narrative only, no math
Ingest script is responsible for:

sourceid assignment and sources row creation.

sourceplayers mapping using existing canonicalization rules.

sourcerankings inserts with proper seasonid, sourceid, rank, and position.

4.2 Comp Enrichment CSV Contract
Filename pattern: data/imports/comps/perplexity\_historical\_comps\_2026.csv

Columns:

Column	Type	Required	Notes
playername	TEXT	Yes	Comp player (e.g. “Patrick Peterson”)
archetypecode	TEXT	Yes	Canonical APEX archetype code
outcome	TEXT	Yes	HIT, PARTIAL, or MISS
compconfidence	TEXT	Yes	A, B, or C
era	TEXT	No	Display only
mechanism\_summary| TEXT	Yes	Mechanism-grade explanation
fmcode	TEXT	No	Optional FM code when clearly justified
The seeding script maps these onto the existing historicalcomps schema, respecting CHECK constraints and indices.

5. Prompting Principles for Perplexity Research
When using Perplexity Research mode for §7:

Use fixed prompt templates for each integration flow so outputs remain schema-stable over time.

Require source citations in every research answer, but treat those as research provenance only; source identity does not flow into APEX’s sources tables.

Where Perplexity returns semi-structured lists, ask it explicitly to emit CSV-compatible rows with the columns above and no extra fields.

Example (scout aggregation) prompt skeleton:

“You are a research assistant for an NFL Draft analytics engine.
Return a ranked list of the top N 2026 prospects based on consensus scouting reports (not model outputs).
For each player, output a single CSV row with the following columns exactly: playername, school, position\_raw, rank\_overall, rank\_position, notes.
Do not include a header row. Do not add any extra columns. Use 2026 draft class only.”

Example (comp enrichment) prompt skeleton:

“You are enriching an internal historical comps database for archetype \[ARCHETYPECODE].
Identify up to 10 historical NFL players who fit this archetype and label each as HIT, PARTIAL, or MISS relative to expectations at draft time.
For each, output a CSV row with columns: playername, archetypecode, outcome, compconfidence, era, mechanism\_summary, fmcode.
Keep fmcode blank unless a single failure mode is clearly dominant.”

6. Governance \& Review
Every new Perplexity-driven ingest script:

Lives under scripts/, follows existing naming and CLI patterns.

Requires a dry run (--apply 0) and doctor check before first write.

Is logged in STATE\_SNAPSHOT.md with scope, affected tables, and run order.

Any change to CSV/JSON contracts or prompt templates must be:

Versioned in this document.

Reflected in corresponding ingest script expectations.

Called out explicitly in the session BOOTSTRAPPACKET.

