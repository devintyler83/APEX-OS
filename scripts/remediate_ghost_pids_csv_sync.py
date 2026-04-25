#!/usr/bin/env python3
"""
remediate_ghost_pids_csv_sync.py

One-shot remediation: cross-reference ALL active prospects against
consensusdatabase_4-23-26.csv, deactivate ghost PIDs, fix position_group
normalization, and build a targeted re-score list.

This is the canonical fix for the ghost-PID problem introduced by early
LB/OL/DT catch-all bootstrap ingests. After this runs, the CSV is the
permanent source of truth for position_group and prospect universe.

Usage:
    python -m scripts.remediate_ghost_pids_csv_sync --apply 0   # dry run (default)
    python -m scripts.remediate_ghost_pids_csv_sync --apply 1   # execute

Output:
    Prints full remediation plan regardless of --apply flag.
    With --apply 1: backs up DB, executes all writes, prints re-score command.
"""

import argparse
import csv
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# --- Config -------------------------------------------------------------------

DB_PATH   = Path('data/edge/draftos.sqlite')
CSV_PATH  = Path('consensusdatabase_4-23-26.csv')
SEASON_ID = 1

CALIBRATION_PIDS = frozenset([230, 304, 313, 455, 504, 880, 1050, 1278, 1371, 1391, 1729, 1925])

# Prospects scored in the current session run (rebuilt from same logic as dry run)
CURRENT_SESSION_SCORED_PIDS = frozenset([
    16,28,57,8,61,14,41,31,22,26,39,62,29,68,98,33,38,25,11,66,9,23,40,80,380,1764,
    1636,42,4484,54,3,27,357,78,359,79,3528,1,35,3236,18,72,3551,69,1262,20,71,75,
    3527,1153,3580,3958,2,19,100,3523,105,96,362,364,7,1147,147,55,21,32,1240,3637,
    1179,12,372,383,48,60,74,65,15,3590,56,533,515,554,1128,535,1154,497,629,3823,
    599,564,638,598,609,1114,581,555,577,70,3675,3822,5,3795,487,148,518,3593,2333,
    493,45,510,498,3683,1952,484,338,1941,1169,4383,527,4,543,309,1094,3616,76,489,
    64,3676,3961,2355,10,4347,502,63,135,2131,503,1366,2124,6,2736,114,1909,136,
    2347,3967,1830,1347,4380,4389,37,2075,2406,160,2570,2005,81,4429,1899,2612,2114,
    2407,109,1303,1148,67,2305,102,2510,104,2273,3584,252,2420,3684,97,1922,2011,
    2007,17,1935,2026,2083,2318,3650,1882,4286,1989,2324,3626,49,1836,43,3706,3379,
    88,324,3661,110,3976,36,182,2458,200,2627,141,4431,2087,1828,1853,3802,2694,251,
    2340,143,2164,3641,125,34,2153,3644,1904,2456,1200,13,2125,238,152,4433,77,168,
    3642,83,2423,2014,190,171,3800,2352,225,3818,4468,107,3746,59,183,3879,2544,
    4003,2024,187,3970,227,3401,1987,1072,408,352,3696,1599,53,2384,103,94,138,127,
    2035,1783,949,4032,106,174,3807,217,164,253,4010,2464,198,193,3651,375,3715,58,
    44,3629,1119,3982,1658,333,431,3283,184,1581,306,285,3596,89,3983,2430
])

# --- Position Normalization ----------------------------------------------------

# Unambiguous CSV->DB position mappings
CSV_TO_DB_EXACT = {
    'QB':   'QB',
    'WR':   'WR',
    'RB':   'RB',
    'TE':   'TE',
    'OT':   'OT',
    'CB':   'CB',
    'S':    'S',
    'ILB':  'ILB',
    'OLB':  'OLB',
    'EDGE': 'EDGE',
    'IDL':  'IDL',
    'DT':   'IDL',   # CSV DT -> IDL (our interior DL label)
    'K':    'K',
    'P':    'P',
    'LS':   'LS',
    'FB':   'FB',
}

# Ambiguous CSV positions — resolved by fallback logic
AMBIGUOUS_CSV_POSITIONS = {'IOL', 'DL', 'LB'}

# School name aliases: CSV school name -> DB school_canonical (all lowercase)
SCHOOL_ALIASES = {
    'lsu':                   'louisiana state',
    'usc':                   'southern california',
    'ole miss':              'mississippi',
    'pitt':                  'pittsburgh',
    'ucf':                   'central florida',
    'byu':                   'brigham young',
    'smu':                   'southern methodist',
    'tcu':                   'texas christian',
    'utsa':                  'texas san antonio',
    'fiu':                   'florida international',
    'uab':                   'alabama birmingham',
    'utep':                  'texas el paso',
    'unlv':                  'nevada las vegas',
    'umass':                 'massachusetts',
    'unt':                   'north texas',
    'uconn':                 'connecticut',
    'fau':                   'florida atlantic',
    'miami (fl)':            'miami',
    'miami (ohio)':          'miami (ohio)',
    'north carolina':        'north carolina',
    'nc state':              'north carolina state',
    'ncsu':                  'north carolina state',
    'penn state':            'penn state',
    'ohio state':            'ohio state',
    'georgia tech':          'georgia tech',
    'texas a&m':             'texas a&m',
    'louisiana state':       'louisiana state',
    'southeastern louisiana':'southeastern louisiana',
}


import re as _re

_SUFFIX_RE = _re.compile(
    r'\b(jr\.?|sr\.?|ii|iii|iv|v)\s*$', _re.IGNORECASE
)
_INITIAL_RE = _re.compile(r'\b([A-Z])\.([A-Z])\.', _re.IGNORECASE)
_TRAILING_INITIAL_RE = _re.compile(r'\b([A-Z])\.$', _re.IGNORECASE)


# Known name-form mismatches between CSV and DB (normalized_csv_name -> normalized_db_name)
# Used for players whose nickname in DB differs from full name in CSV
NAME_FORM_MAP = {
    'kevin concepcion': 'kc concepcion',    # DB ingested as "KC"
    'nick singleton':   'nicholas singleton', # DB uses full first name
    'pj williams':      'pj williams',        # keep as-is (normalize dots)
    'kj henry':         'kj henry',
}


def normalize_name(name: str) -> str:
    """Strip suffixes and normalize dotted initials: 'C.J. Allen Jr.' -> 'cj allen'"""
    s = name.strip()
    # Normalize "C.J." -> "CJ" style initials (two initials with dots)
    s = _INITIAL_RE.sub(lambda m: m.group(1) + m.group(2), s)
    # Normalize trailing initial "A." -> "A"
    s = _TRAILING_INITIAL_RE.sub(lambda m: m.group(1), s)
    # Remove remaining dots from initials
    s = s.replace('.', '')
    # Strip generational suffixes
    s = _SUFFIX_RE.sub('', s).strip()
    normalized = s.lower()
    # Apply known name-form overrides
    return NAME_FORM_MAP.get(normalized, normalized)


def normalize_school(school: str) -> str:
    s = school.strip().lower()
    return SCHOOL_ALIASES.get(s, s)


# --- Position Matching Logic ---------------------------------------------------

def position_match_score(db_pos: str, csv_pos: str) -> int:
    """
    Score how well a DB position_group matches a CSV position.
    Higher = better. Used to identify the canonical PID in a ghost pair.
    """
    if db_pos == csv_pos:
        return 5
    exact_target = CSV_TO_DB_EXACT.get(csv_pos)
    if exact_target and db_pos == exact_target:
        return 4
    # OL can be a valid (unnormalized) OT or IOL
    if csv_pos in ('OT', 'IOL') and db_pos in ('OT', 'OG', 'C', 'OL'):
        return 3
    # DL covers both IDL and EDGE
    if csv_pos == 'DL' and db_pos in ('IDL', 'DT', 'EDGE'):
        return 2
    # Generic LB covers ILB/OLB
    if csv_pos == 'LB' and db_pos in ('ILB', 'OLB', 'LB'):
        return 2
    # DB LB/OL/DT as pure catch-alls score 0 against specific positions
    if db_pos in ('LB', 'OL') and csv_pos not in ('LB', 'IOL', 'OT'):
        return 0
    return 1


def resolve_target_position(csv_pos: str, current_db_pos: str) -> str:
    """
    Determine the canonical DB position_group for a prospect.
    For unambiguous CSV positions, returns the exact mapping.
    For ambiguous (IOL, DL, LB), preserves the existing specific DB position
    if it's already valid, otherwise applies a sensible default.
    """
    exact = CSV_TO_DB_EXACT.get(csv_pos)
    if exact:
        return exact

    if csv_pos == 'IOL':
        # Prefer existing specific interior OL designation
        if current_db_pos in ('OG', 'C'):
            return current_db_pos
        # OT is NOT an IOL — don't keep it
        return 'OG'   # default interior OL to OG

    if csv_pos == 'DL':
        # Prefer existing specific designation if valid
        if current_db_pos in ('IDL', 'EDGE'):
            return current_db_pos
        if current_db_pos == 'DT':
            return 'IDL'
        return 'IDL'  # default DL to IDL

    if csv_pos == 'LB':
        if current_db_pos in ('ILB', 'OLB'):
            return current_db_pos
        return 'ILB'  # default LB to ILB

    # Fallback: use CSV position directly
    return csv_pos


# --- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Remediate ghost PIDs and fix position_group vs CSV.')
    parser.add_argument('--apply', type=int, default=0, choices=[0, 1],
                        help='0=dry run (default), 1=execute')
    args = parser.parse_args()
    dry_run = (args.apply == 0)

    # -- Load CSV ground truth --------------------------------------------------
    csv_players: dict[tuple, dict] = {}
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            name   = row['Player'].strip()
            school = normalize_school(row['School'].strip())
            rank   = int(row['Con'])
            pos    = row['Pos'].strip()
            # Use normalized name as key to handle suffix/initial variations
            key    = (normalize_name(name), school)
            csv_players[key] = {'name': name, 'pos': pos, 'rank': rank, 'school': row['School'].strip()}
    print(f'CSV loaded: {len(csv_players)} prospects')

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # -- Load all active non-calibration prospects from DB ---------------------
    cur.execute('''
        SELECT p.prospect_id, p.full_name, p.position_group, p.school_canonical,
               pcr.consensus_rank
        FROM   prospects p
        LEFT JOIN prospect_consensus_rankings pcr
               ON pcr.prospect_id = p.prospect_id AND pcr.season_id = ?
        WHERE  p.is_active = 1
          AND  p.season_id = ?
        ORDER  BY p.full_name, p.prospect_id
    ''', (SEASON_ID, SEASON_ID))
    all_active = cur.fetchall()
    print(f'Active DB prospects (non-calibration filter applied below): {len(all_active)}')

    # Group by (normalized_name, school_lower) to find ghost pairs
    # Uses normalize_name() to handle suffix/initial variations matching CSV
    db_by_name_school: dict[tuple, list] = {}
    for pid, name, pos, school, rank in all_active:
        if pid in CALIBRATION_PIDS:
            continue
        school_norm = normalize_school(school or '')
        key = (normalize_name(name), school_norm)
        db_by_name_school.setdefault(key, []).append({
            'pid': pid, 'pos': pos, 'rank': rank, 'school_canonical': school,
            'full_name': name
        })

    # -- Analysis --------------------------------------------------------------
    ghost_deactivations: list[dict] = []   # ghosts to deactivate
    position_updates:    list[dict] = []   # canonical position fixes
    ambiguous_updates:   list[dict] = []   # IOL/DL/LB auto-resolved (flagged)
    no_change:           list[dict] = []   # correct already
    csv_unmatched:       list[dict] = []   # CSV rows with no active DB match

    for key, csv_info in sorted(csv_players.items(), key=lambda x: x[1]['rank']):
        csv_pos   = csv_info['pos']
        csv_rank  = csv_info['rank']
        csv_name  = csv_info['name']
        csv_school= csv_info['school']

        entries = db_by_name_school.get(key, [])
        if not entries:
            csv_unmatched.append({'rank': csv_rank, 'name': csv_name, 'pos': csv_pos, 'school': csv_school})
            continue

        if len(entries) == 1:
            e = entries[0]
            target = resolve_target_position(csv_pos, e['pos'])
            entry = {
                'pid': e['pid'], 'name': csv_name, 'old_pos': e['pos'],
                'new_pos': target, 'csv_pos': csv_pos, 'csv_rank': csv_rank,
                'consensus_rank': e['rank'],
            }
            if e['pos'] == target:
                no_change.append(entry)
            elif csv_pos in AMBIGUOUS_CSV_POSITIONS:
                ambiguous_updates.append(entry)
            else:
                position_updates.append(entry)
            continue

        # -- Ghost split: multiple active PIDs ---------------------------------
        # Score each against CSV position; best match = canonical
        scored = sorted(
            entries,
            key=lambda e: (-position_match_score(e['pos'], csv_pos), e['pid'])
        )
        canonical = scored[0]
        ghosts    = scored[1:]

        target = resolve_target_position(csv_pos, canonical['pos'])

        # Register canonical position update if needed
        if canonical['pos'] != target:
            entry = {
                'pid': canonical['pid'], 'name': csv_name,
                'old_pos': canonical['pos'], 'new_pos': target,
                'csv_pos': csv_pos, 'csv_rank': csv_rank,
                'consensus_rank': canonical['rank'],
            }
            if csv_pos in AMBIGUOUS_CSV_POSITIONS:
                ambiguous_updates.append(entry)
            else:
                position_updates.append(entry)

        # Register ghost deactivations
        for g in ghosts:
            ghost_deactivations.append({
                'ghost_pid':       g['pid'],
                'ghost_pos':       g['pos'],
                'ghost_rank':      g['rank'],
                'canonical_pid':   canonical['pid'],
                'canonical_pos':   canonical['pos'],
                'canonical_target':target,
                'name':            csv_name,
                'csv_pos':         csv_pos,
                'csv_rank':        csv_rank,
                'ghost_was_scored':  g['pid'] in CURRENT_SESSION_SCORED_PIDS,
                'canonical_was_scored': canonical['pid'] in CURRENT_SESSION_SCORED_PIDS,
            })

    # -- Build re-score list ----------------------------------------------------
    rescore: dict[int, list[str]] = {}  # pid -> [reason, ...]

    canonical_pos_changed_pids = {u['pid'] for u in position_updates + ambiguous_updates}

    for g in ghost_deactivations:
        cpid = g['canonical_pid']
        # Ghost was scored this session, canonical was not -> canonical has no score for this session
        if g['ghost_was_scored'] and not g['canonical_was_scored']:
            rescore.setdefault(cpid, []).append(
                f"ghost pid={g['ghost_pid']} absorbed session score; canonical unscored"
            )
        # Canonical was scored BUT will have position changed -> wrong archetype used
        if g['canonical_was_scored'] and cpid in canonical_pos_changed_pids:
            rescore.setdefault(cpid, []).append(
                f"position changing {g['canonical_pos']}->{g['canonical_target']}; session score used wrong archetype"
            )

    # Any standalone canonical (not a ghost pair) that was scored AND position changes
    for u in position_updates + ambiguous_updates:
        if u['pid'] in CURRENT_SESSION_SCORED_PIDS:
            rescore.setdefault(u['pid'], []).append(
                f"position changing {u['old_pos']}->{u['new_pos']}; session score used wrong archetype"
            )

    # -- Print Report ----------------------------------------------------------
    sep = '=' * 72

    print()
    print(sep)
    print('  GHOST PID + POSITION REMEDIATION — DRY RUN REPORT')
    print(f'  Mode : {"DRY RUN — no writes" if dry_run else "EXECUTE"}')
    print(f'  DB   : {DB_PATH}')
    print(f'  CSV  : {CSV_PATH}')
    print(sep)

    # Ghost deactivations
    print(f'\n{"-"*72}')
    print(f'  GHOST DEACTIVATIONS  ({len(ghost_deactivations)} ghosts -> is_active=0 + apex_scores deleted)')
    print(f'{"-"*72}')
    print(f'  {"CSV#":<6} {"Name":<32} {"Ghost PID":<10} {"Ghost Pos":<10} {"Canonical PID":<15} {"Can. Pos->Target":<18} {"Was Scored?"}')
    for g in sorted(ghost_deactivations, key=lambda x: x['csv_rank']):
        scored_flag = f'ghost={"Y" if g["ghost_was_scored"] else "N"} / canon={"Y" if g["canonical_was_scored"] else "N"}'
        target_str  = f'{g["canonical_pos"]}->{g["canonical_target"]}' if g['canonical_pos'] != g['canonical_target'] else g['canonical_pos']
        print(f'  #{g["csv_rank"]:<5} {g["name"]:<32} pid={g["ghost_pid"]:<8} {g["ghost_pos"]:<10} pid={g["canonical_pid"]:<13} {target_str:<18} {scored_flag}')

    # Unambiguous position updates
    print(f'\n{"-"*72}')
    print(f'  POSITION UPDATES — UNAMBIGUOUS  ({len(position_updates)} canonical PIDs)')
    print(f'{"-"*72}')
    print(f'  {"CSV#":<6} {"Name":<32} {"PID":<8} {"Old Pos":<12} {"-> New Pos":<12} {"CSV Pos"}')
    for u in sorted(position_updates, key=lambda x: x['csv_rank']):
        print(f'  #{u["csv_rank"]:<5} {u["name"]:<32} pid={u["pid"]:<6} {u["old_pos"]:<12} -> {u["new_pos"]:<12} ({u["csv_pos"]})')

    # Ambiguous position updates (IOL/DL/LB)
    print(f'\n{"-"*72}')
    print(f'  POSITION UPDATES — AMBIGUOUS (IOL/DL/LB auto-resolved)  ({len(ambiguous_updates)})')
    print(f'  NOTE: These are applied automatically. Review before confirming --apply 1.')
    print(f'{"-"*72}')
    print(f'  {"CSV#":<6} {"Name":<32} {"PID":<8} {"Old Pos":<12} {"-> New Pos":<12} {"CSV Pos"}')
    for u in sorted(ambiguous_updates, key=lambda x: x['csv_rank']):
        print(f'  #{u["csv_rank"]:<5} {u["name"]:<32} pid={u["pid"]:<6} {u["old_pos"]:<12} -> {u["new_pos"]:<12} ({u["csv_pos"]})')

    # Re-score list
    print(f'\n{"-"*72}')
    print(f'  RE-SCORE REQUIRED  ({len(rescore)} prospects)')
    print(f'  (canonical PID scored at wrong position, or ghost absorbed the session score)')
    print(f'{"-"*72}')
    for pid in sorted(rescore.keys()):
        for reason in rescore[pid]:
            print(f'  pid={pid:<6}  {reason}')
    if rescore:
        rescore_ids = ','.join(str(p) for p in sorted(rescore.keys()))
        print(f'\n  Re-score command (run AFTER --apply 1):')
        print(f'  python -m scripts.run_apex_scoring_2026 --prospect-ids {rescore_ids} --force --apply 1')

    # CSV unmatched
    if csv_unmatched:
        print(f'\n{"-"*72}')
        print(f'  CSV UNMATCHED — no active DB row found  ({len(csv_unmatched)})')
        print(f'  (these prospects exist in CSV but not in DB as active is_active=1)')
        print(f'{"-"*72}')
        for u in sorted(csv_unmatched, key=lambda x: x['rank']):
            print(f'  #{u["rank"]:<5} {u["name"]:<32} {u["pos"]:<8} {u["school"]}')

    # Summary
    print(f'\n{"-"*72}')
    print(f'  SUMMARY')
    print(f'{"-"*72}')
    print(f'  Ghost PIDs to deactivate:              {len(ghost_deactivations)}')
    print(f'  Unambiguous position updates:          {len(position_updates)}')
    print(f'  Ambiguous position updates (IOL/DL/LB):{len(ambiguous_updates)}')
    print(f'  Prospects needing re-score:            {len(rescore)}')
    print(f'  Clean (no action needed):              {len(no_change)}')
    print(f'  CSV rows with no active DB match:      {len(csv_unmatched)}')
    print()

    if dry_run:
        print('[DRY RUN] No changes written. Re-run with --apply 1 to execute.')
        conn.close()
        return

    # -- EXECUTE ---------------------------------------------------------------
    ts     = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = DB_PATH.with_suffix(f'.sqlite.bak_ghost_remediation_{ts}')
    shutil.copy2(DB_PATH, backup)
    print(f'[BACKUP] {backup}')
    print()

    errors = 0

    # 1. Deactivate ghost PIDs + delete apex_scores + divergence_flags
    print(f'[STEP 1] Deactivating {len(ghost_deactivations)} ghost PIDs...')
    for g in ghost_deactivations:
        try:
            cur.execute('DELETE FROM apex_scores WHERE prospect_id = ?',      (g['ghost_pid'],))
            cur.execute('DELETE FROM divergence_flags WHERE prospect_id = ?', (g['ghost_pid'],))
            cur.execute('UPDATE prospects SET is_active = 0 WHERE prospect_id = ?', (g['ghost_pid'],))
            print(f'  DEACTIVATED pid={g["ghost_pid"]} ({g["ghost_pos"]}) ← ghost of {g["name"]} (canonical pid={g["canonical_pid"]})')
        except Exception as e:
            print(f'  ERROR pid={g["ghost_pid"]}: {e}')
            errors += 1

    # 2. Fix position_group on canonical PIDs (unambiguous)
    print(f'\n[STEP 2] Applying {len(position_updates)} unambiguous position updates...')
    for u in position_updates:
        try:
            cur.execute('UPDATE prospects SET position_group = ? WHERE prospect_id = ?', (u['new_pos'], u['pid']))
            print(f'  pid={u["pid"]} {u["name"]}: {u["old_pos"]} -> {u["new_pos"]}')
        except Exception as e:
            print(f'  ERROR pid={u["pid"]}: {e}')
            errors += 1

    # 3. Fix position_group on ambiguous positions (IOL/DL/LB auto-resolved)
    print(f'\n[STEP 3] Applying {len(ambiguous_updates)} ambiguous position updates...')
    for u in ambiguous_updates:
        try:
            cur.execute('UPDATE prospects SET position_group = ? WHERE prospect_id = ?', (u['new_pos'], u['pid']))
            print(f'  pid={u["pid"]} {u["name"]}: {u["old_pos"]} -> {u["new_pos"]} (CSV={u["csv_pos"]})')
        except Exception as e:
            print(f'  ERROR pid={u["pid"]}: {e}')
            errors += 1

    conn.commit()
    conn.close()

    print()
    print(sep)
    print(f'  REMEDIATION COMPLETE — {"0 errors" if errors == 0 else f"{errors} ERRORS (check above)"}')
    print(sep)
    print(f'  Ghost PIDs deactivated:   {len(ghost_deactivations)}')
    print(f'  Position updates applied: {len(position_updates) + len(ambiguous_updates)}')
    print()

    if rescore:
        rescore_ids = ','.join(str(p) for p in sorted(rescore.keys()))
        print(f'  NEXT STEP — Re-score {len(rescore)} prospects at corrected positions:')
        print()
        print(f'  python -m scripts.run_apex_scoring_2026 \\')
        print(f'    --prospect-ids {rescore_ids} \\')
        print(f'    --force --apply 1')
    else:
        print('  No re-scoring required — all canonical PIDs scored correctly.')

    print()


if __name__ == '__main__':
    main()
