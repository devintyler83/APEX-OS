\# DraftOS Run Log (Last Known Good)



\## Environment

Windows, PowerShell, venv active.



\## Engine Gates

cd C:\\DraftOS

python -m draftos.db.migrate

python -m scripts.doctor



\## Ingest

PFF:

python -m draftos.ingest.rankings.loader --csv "C:\\DraftOS\\data\\imports\\rankings\\pff\_2026.csv"

python -m draftos.ingest.rankings.writer --season 2026 --source "PFF" --csv "C:\\DraftOS\\data\\imports\\rankings\\pff\_2026.csv" --dry-run 0



NFLDraftBuzz scraping:

Requests-based scraper blocked 403.

Playwright scraper succeeded:

python scripts\\scrape\_nfldraftbuzz\_2026\_playwright.py --pages 41 --headful 1 --out "C:\\DraftOS\\data\\imports\\rankings\\nfldraftbuzz\_2026.csv"

v2 fixed CSV:

python scripts\\scrape\_nfldraftbuzz\_2026\_playwright.py --pages 41 --headful 1 --out "C:\\DraftOS\\data\\imports\\rankings\\nfldraftbuzz\_2026\_v2.csv"



Ingest NFLDraftBuzz\_v2:

python -m draftos.ingest.rankings.loader --csv "C:\\DraftOS\\data\\imports\\rankings\\nfldraftbuzz\_2026\_v2.csv"

python -m draftos.ingest.rankings.writer --season 2026 --source "NFLDraftBuzz\_v2" --csv "C:\\DraftOS\\data\\imports\\rankings\\nfldraftbuzz\_2026\_v2.csv" --dry-run 0



\## Soft Deprecation Patch

python scripts\\patch\_0005\_0006\_soft\_deprecate\_nfldraftbuzz.py --apply 1

python -m draftos.db.migrate

python -m scripts.doctor

Expected doctor output includes:

sources: 3

sources\_active: 2

