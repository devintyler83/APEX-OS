import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sqlite3
conn = sqlite3.connect(r'C:\DraftOS\data\edge\draftos.sqlite')
conn.row_factory = sqlite3.Row

print('=== UNMATCHED RAS -- COLLEGE_RAW NOT IN ALIASES ===')
rows = conn.execute("""
    SELECT rs.college_raw, COUNT(*) as cnt
    FROM ras_staging rs
    WHERE rs.matched_prospect_id IS NULL
    AND rs.college_raw IS NOT NULL
    AND rs.college_raw != ''
    AND NOT EXISTS (
        SELECT 1 FROM school_aliases sa
        WHERE sa.school_alias = rs.college_raw
    )
    GROUP BY rs.college_raw
    ORDER BY cnt DESC
    LIMIT 40
""").fetchall()
for r in rows:
    print(f'  {r["cnt"]:4}  {r["college_raw"]}')

print()

print('=== UNMATCHED SOURCE_PLAYERS -- SCHOOL_RAW NOT IN ALIASES ===')
rows = conn.execute("""
    SELECT sp.raw_school, COUNT(*) as cnt
    FROM source_players sp
    LEFT JOIN source_player_map spm
        ON spm.source_player_id = sp.source_player_id
    WHERE spm.prospect_id IS NULL
    AND sp.raw_school IS NOT NULL
    AND sp.raw_school != ''
    AND NOT EXISTS (
        SELECT 1 FROM school_aliases sa
        WHERE sa.school_alias = sp.raw_school
    )
    GROUP BY sp.raw_school
    ORDER BY cnt DESC
    LIMIT 40
""").fetchall()
for r in rows:
    print(f'  {r["cnt"]:4}  {r["raw_school"]}')

conn.close()
