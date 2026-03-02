\# DraftOS Master Plan



This document defines the long-term roadmap.

It is not system state.

It defines architectural direction and acceptance criteria.



\---



\# Core Doctrine (Immutable)



\- Deterministic only.

\- Additive migrations only.

\- No historical mutation.

\- Season scoped only.

\- Active sources only (sources.is\_active = 1 enforced in math).

\- Idempotent scripts only.

\- Each architectural layer has exactly one responsibility.



\---



\# Architectural Layers (Fixed)



RAW CSVs

STAGING (normalized schema)

INGEST (source\_rankings)

BOOTSTRAP (prospects + maps)

CONSENSUS (math layer)

MODEL OUTPUTS (contract layer)

SNAPSHOTS (historical state layer)

EXPORTS (presentation layer)



No layer may recompute logic belonging to another.



\---



\# Phase 1 — Multi-Source Ingest (FOUNDATION)



Goal:

Reliable ingestion of multiple ranking sources.



Must Include:

\- Canonical prospect mapping

\- source\_rankings table

\- Active-only enforcement

\- Idempotent upserts



Acceptance Criteria:

\- Re-running ingest produces identical DB state

\- No duplicate source\_rankings rows

\- sources.is\_active toggle properly excludes from consensus



Doctor Checks:

\- Table existence validation

\- Row counts stable across reruns



Status:

\[ ] Not Started

\[ ] In Progress

\[ ] Complete



\---



\# Phase 2 — Deterministic Consensus Engine



Goal:

Compute consensus rank + score across active sources only.



Must Include:

\- Deterministic ranking math

\- No probabilistic logic

\- Full explainable payload



Acceptance Criteria:

\- Same input state produces same consensus output

\- Changing is\_active on a source recomputes consensus correctly

\- No cross-season contamination



Doctor Checks:

\- Consensus output stable across reruns

\- Active-only validation query passes



Status:

\[ ] Not Started

\[ ] In Progress

\[ ] Complete



\---



\# Phase 3 — Snapshot + Delta Tracking



Goal:

Weekly frozen board state with delta\_rank and delta\_score.



Must Include:

\- prospect\_board\_snapshots table

\- snapshot date

\- delta\_rank

\- delta\_score

\- coverage delta



Acceptance Criteria:

\- Snapshot is immutable after write

\- Delta calculations correct between snapshots

\- Re-running snapshot script does not duplicate snapshot



Doctor Checks:

\- Snapshot immutability validation

\- No duplicate snapshot rows

\- Delta correctness query passes



Status:

\[ ] Not Started

\[ ] In Progress

\[ ] Complete



\---



\# Phase 4 — Variance + Confidence Bands



Goal:

Quantify ranking spread across sources.



Must Include:

\- Standard deviation or range

\- Coverage count

\- Confidence tier classification



Acceptance Criteria:

\- Variance deterministic

\- Active-only respected

\- Position-specific logic not duplicated



Doctor Checks:

\- Variance recalculates identically across reruns



Status:

\[ ] Not Started

\[ ] In Progress

\[ ] Complete



\---



\# Phase 5 — Source Weighting (Versioned)



Goal:

Introduce deterministic weighting model.



Must Include:

\- Versioned weighting schema

\- No implicit weight changes

\- Explicit model version tagging



Acceptance Criteria:

\- Model version stored in model\_outputs

\- Changing weights requires version increment

\- Historical outputs preserved



Doctor Checks:

\- Model version consistency validation

\- No mutation of prior model outputs



Status:

\[ ] Not Started

\[ ] In Progress

\[ ] Complete



\---



\# Deferred / Backlog (Ordered)



1\.

2\.

3\.



\---



\# Definition of Production-Ready (Global)



A feature is production-ready only if:



\- Idempotent

\- Season-scoped

\- Active-only compliant

\- Additive migration

\- Survives full rerun without drift

\- Passes doctor checks

\- Integrated into weekly orchestrator

