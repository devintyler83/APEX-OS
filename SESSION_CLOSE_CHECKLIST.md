DraftOS Session Close Checklist



Use this at the end of every heavy engine session.



Goal:

Leave the system deterministic, backed up, and resumable without rethinking context.



1\. Engine Integrity Check

Snapshot Integrity

sqlite3 .\\data\\edge\\draftos.sqlite "

SELECT

&#x20; (SELECT COUNT(\*) FROM prospect\_board\_snapshot\_rows WHERE snapshot\_id=3) AS snapshot\_rows,

&#x20; (SELECT COUNT(\*) FROM prospect\_board\_snapshot\_coverage WHERE snapshot\_id=3) AS coverage\_rows,

&#x20; (SELECT COUNT(\*) FROM prospect\_board\_snapshot\_confidence WHERE snapshot\_id=3) AS confidence\_rows;

"



Confirm:



snapshot\_rows == coverage\_rows



snapshot\_rows == confidence\_rows



If mismatch exists, fix before closing.



Unmapped Tracking (Informational Only)

sqlite3 .\\data\\edge\\draftos.sqlite "

SELECT COUNT(\*) AS unmapped

FROM source\_players sp

LEFT JOIN source\_player\_map m ON m.source\_player\_id=sp.source\_player\_id

WHERE sp.season\_id=(SELECT season\_id FROM seasons WHERE draft\_year=2026)

&#x20; AND m.source\_player\_id IS NULL;

"



Do NOT manually clean unless it blocks outputs.



2\. Deterministic DB Backup



Create one explicit session-close backup:



$ts = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")

Copy-Item .\\data\\edge\\draftos.sqlite ".\\data\\edge\\backups\\draftos.session\_close.$ts.sqlite"

Write-Host "Session backup created."



This is your hard restore point.



3\. Git State Clean

git status

git add -A

git commit -m "DraftOS session close checkpoint"

git push



Confirm:



No uncommitted files.



Branch correct.



Push successful.



4\. Export Artifacts (If Engine Changed)



If ingest, mapping, bootstrap, or snapshot changed:



python -m scripts.export\_board\_csv --season 2026 --model v1\_default



Confirm updated:



exports\\board\_2026\_v1\_default.csv



Optional:



mapping\_autofix\_2026.csv



mapping\_ambiguities\_2026.csv



5\. Update PROJECT\_STATUS.md (If Architecture Changed)



Only update if:



New script added



New invariant added



New deterministic rule introduced



Layer responsibilities changed



Do not update for routine ingest.



6\. Record Session Summary (2–5 lines max)



Append to PROJECT\_STATUS.md or commit message:



What layer changed?



What invariant was enforced?



What was intentionally deferred?



Keep it short.



7\. Define Next Session Objective (One Line)



Write one clear sentence before closing:



Next session objective: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_



Example:



"Stabilize consensus dispersion weighting."



"Add third source ingest."



"Refactor canonical position mapping."



"Do nothing but validate snapshot invariants."



If it’s not written, you’ll drift next time.



Close Condition



Session is complete when:



Snapshot layer clean



DB backed up



Git clean



No open blockers



Next objective defined



Then stop.

