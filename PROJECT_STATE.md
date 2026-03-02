DraftOS Project State (Checkpoint)



Date: 2026-03-02

Repo Root: C:\\DraftOS

Canonical DB: C:\\DraftOS\\data\\edge\\draftos.sqlite



Current Phase



Phase 1 complete: Core deterministic engine functional.

Snapshot layer operational.

Consensus + coverage + confidence pipeline producing exports.



Still no Streamlit Big Board UI work.



What Works (End-to-End Engine)

Deterministic Core



Deterministic DB path resolution via draftos/config.py.



Migration runner is additive, logs APPLY/SKIP, and backs up DB automatically.



Doctor gate passes (python -m scripts.doctor).



All writes create pre-operation DB backups.



Multi-Source Ingest (Proven at Scale)



Large 2026 ingest completed.



Rankings ingested:



players\_new ≈ 7023



rankings\_new ≈ 14580



Idempotent via UNIQUE constraints.



Soft deprecation active:



sources.is\_active



sources.superseded\_by\_source\_id



Canonical source map operational.



Identity + Mapping Layer (Major Milestone)

Name Normalization



Conservative auto-inserts into source\_player\_map.



Large-scale patch runs successful.



Diagnostics exported:



exports\\mapping\_autofix\_2026.csv



exports\\mapping\_ambiguities\_2026.csv



School Canonicalization



Learned aliases from mapped data.



\~147 new aliases inserted.



School canonical backfill applied.



Bootstrap Prospect Creation



Deterministic grouping by:



name\_key



school\_canonical



position\_group



minimum distinct source count



bootstrap\_prospects\_from\_sources\_2026 inserted:



1074 new prospects



Prospect UNIQUE constraint respected.



Autoresolve Improvements



Taxonomy-aligned position logic.



Multiple deterministic resolution rules:



school + pos unique



pos unique



dominant school + pos



Hundreds of additional mappings resolved and applied.



Snapshot Layer (Operational)



For 2026 / model v1\_default:



Snapshot coverage computed.



Snapshot confidence computed (v2 foundations).



Snapshot export working:



exports\\board\_2026\_v1\_default.csv



Snapshot invariants enforced:



Confidence is computed from snapshot\_rows universe.



Coverage rows pruned if not present in snapshot\_rows.



Idempotent delete-and-recompute per snapshot\_id.



Current Data State (As of 2026-03-02)



seasons: 1 (2026)



models: 1 (v1\_default)



sources: multiple (active-only used for aggregation)



prospects: >1000 (bootstrapped + seeded)



source\_players: \~10k+



source\_rankings: \~14k+



Snapshot:



snapshot\_rows ≈ 802



coverage\_rows aligned to snapshot\_rows



confidence\_rows aligned to snapshot\_rows



Unmapped source\_players remain, but reduced substantially from initial post-ingest volume.



Core Architectural Decisions (Locked)



Raw ingest data is never deleted.



Soft deprecation only (active-only query seam).



Canonical position taxonomy aligned to NFL.com + ESPN.



Prospect identity derived deterministically.



Snapshot rows define the universe.



Coverage and confidence annotate snapshot rows only.



All scripts idempotent.



Every write operation backs up the DB.



Explicitly Deferred (Intentional Holds)



These are paused by design. Do NOT work on unless they directly unblock engine outputs.



Manual resolution of remaining open mapping review queue rows.

Defer until richer source coverage improves automatic resolution.



Broad school canonical expansion beyond learned aliases.

Only revisit if it unlocks automated mapping.



UI / Streamlit Big Board implementation.



Cosmetic report enhancements.



Engine integrity > polish.



Current Priorities (Next Session Focus)



Verify snapshot integrity:



snapshot\_rows == coverage\_rows == confidence\_rows



No orphan coverage rows.



No orphan confidence rows.



Confirm unmapped count trend:



Track reduction but avoid manual cleanup.



Prepare consensus math refinement (if needed):



Dispersion modeling tuning



Weighted canonical source influence



Only after snapshot stability:



Begin consensus model iteration or additional source ingest.



High-Value Scripts (Core Engine)



scripts/patch\_name\_normalization\_2026.py



scripts/build\_mapping\_review\_queue\_2026.py



scripts/autoresolve\_mapping\_review\_queue\_2026.py



scripts/apply\_review\_queue\_mappings\_2026.py



scripts/learn\_school\_aliases\_from\_mapped\_2026.py



scripts/bootstrap\_prospects\_from\_sources\_2026.py



scripts/compute\_snapshot\_coverage.py



scripts/compute\_snapshot\_confidence.py



scripts/export\_board\_csv.py



Blockers



None.



Remaining open mapping ambiguity is intentional and not blocking the engine.



System Status Summary



DraftOS now:



Ingests multi-source rankings at scale.



Canonicalizes positions deterministically.



Learns school aliases automatically.



Bootstraps prospects from cross-source evidence.



Maps source players deterministically.



Computes coverage + confidence.



Exports deterministic board snapshot.



Phase 1 engine is operational.



Next work is refinement, not foundational construction.

