\# DraftOS

**For all session instructions, system state, and architecture: read [CLAUDE.md](CLAUDE.md) first.**

NFL Draft analytics OS (Streamlit MVP).



\## Canonical Paths

Repo Root: C:\\DraftOS  

DB: C:\\DraftOS\\data\\edge\\draftos.sqlite  



\## Setup



1\. Create venv

2\. Install dependencies

3\. Run migrations

4\. Run doctor

5\. Launch Streamlit



\## Guardrails

\- UI must be thin.

\- No business logic in Streamlit pages.

\- Additive DB migrations only.

\- Always backup before risky operations.



\## Phase 1 Goals

\- Import rankings

\- Matching queue

\- Model scoring

\- Big Board UI

