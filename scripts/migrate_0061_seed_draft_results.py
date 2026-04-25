"""
Migration 0061 — Seed draft_results table with 2026 NFL Draft R1-R2 picks (OVR 1-63).

The draft_results table already exists (created in an earlier migration).
This script seeds it with actual pick data and snapshots APEX/consensus
state at the time of the draft for post-draft validation.

Idempotent: INSERT OR IGNORE on UNIQUE(season_id, pick_overall).
"""

import argparse
import sqlite3
import sys
from datetime import datetime

DB_PATH = r"C:\DraftOS\data\edge\draftos.sqlite"
MIGRATION_ID = "0061"
SEASON_ID = 1

# (pick_overall, pick_round, pick_in_round, prospect_id, player_name, team_name)
# prospect_ids resolved from prospects table (is_active=1) by display_name lookup.
DRAFT_PICKS = [
    (1,  1, 1,  57,   "Fernando Mendoza",      "Las Vegas Raiders"),
    (2,  1, 2,  41,   "David Bailey",           "New York Jets"),
    (3,  1, 3,  61,   "Jeremiyah Love",         "Arizona Cardinals"),
    (4,  1, 4,  31,   "Carnell Tate",           "Tennessee Titans"),
    (5,  1, 5,  16,   "Arvell Reese",           "New York Giants"),
    (6,  1, 6,  39,   "Mansoor Delane",         "Kansas City Chiefs"),
    (7,  1, 7,  8,    "Sonny Styles",           "Washington Commanders"),
    (8,  1, 8,  68,   "Jordyn Tyson",           "New Orleans Saints"),
    (9,  1, 9,  26,   "Spencer Fano",           "Cleveland Browns"),
    (10, 1, 10, 22,   "Francis Mauigoa",        "New York Giants"),
    (11, 1, 11, 28,   "Caleb Downs",            "Dallas Cowboys"),
    (12, 1, 12, 23,   "Kadyn Proctor",          "Miami Dolphins"),
    (13, 1, 13, 9,    "Ty Simpson",             "Los Angeles Rams"),
    (14, 1, 14, 98,   "Olaivavega Ioane",       "Baltimore Ravens"),
    (15, 1, 15, 14,   "Rueben Bain",            "Tampa Bay Buccaneers"),
    (16, 1, 16, 62,   "Kenyon Sadiq",           "New York Jets"),
    (17, 1, 17, 96,   "Blake Miller",           "Detroit Lions"),
    (18, 1, 18, 75,   "Caleb Banks",            "Minnesota Vikings"),
    (19, 1, 19, 25,   "Monroe Freeling",        "Carolina Panthers"),
    (20, 1, 20, 69,   "Makai Lemon",            "Philadelphia Eagles"),
    (21, 1, 21, 3958, "Max Iheanachor",         "Pittsburgh Steelers"),
    (22, 1, 22, 80,   "Akheem Mesidor",         "Los Angeles Chargers"),
    (23, 1, 23, 82,   "Malachi Lawrence",       "Dallas Cowboys"),
    (24, 1, 24, 3,    "KC Concepcion",          "Cleveland Browns"),
    (25, 1, 25, 29,   "Dillon Thieneman",       "Chicago Bears"),
    (26, 1, 26, 136,  "Keylan Rutledge",        "Houston Texans"),
    (27, 1, 27, 35,   "Chris Johnson",          "Miami Dolphins"),
    (28, 1, 28, 54,   "Caleb Lomu",             "New England Patriots"),
    (29, 1, 29, 79,   "Peter Woods",            "Kansas City Chiefs"),
    (30, 1, 30, 3523, "Omar Cooper",            "New York Jets"),
    (31, 1, 31, 42,   "Keldric Faulk",          "Tennessee Titans"),
    (32, 1, 32, 60,   "Jadarian Price",         "Seattle Seahawks"),
    (33, 2, 1,  3557, "De'Zhaun Stribling",     "San Francisco 49ers"),
    (34, 2, 2,  21,   "Chase Bisontis",         "Arizona Cardinals"),
    (35, 2, 3,  27,   "TJ Parker",              "Buffalo Bills"),
    (36, 2, 4,  78,   "Kayden Mcdonald",        "Houston Texans"),
    (37, 2, 5,  72,   "Colton Hood",            "New York Giants"),
    (38, 2, 6,  160,  "Treydan Stukes",         "Las Vegas Raiders"),
    (39, 2, 7,  66,   "Denzel Boston",          "Cleveland Browns"),
    (40, 2, 8,  7,    "R Mason Thomas",         "Kansas City Chiefs"),
    (41, 2, 9,  40,   "Cashius Howell",         "Cincinnati Bengals"),
    (42, 2, 10, 76,   "Christen Miller",        "New Orleans Saints"),
    (43, 2, 11, 19,   "Jacob Rodriguez",        "Miami Dolphins"),
    (44, 2, 12, 81,   "Derrick Moore",          "Detroit Lions"),
    (45, 2, 13, 3551, "Zion Young",             "Baltimore Ravens"),
    (46, 2, 14, 20,   "Josiah Trotter",         "Tampa Bay Buccaneers"),
    (47, 2, 15, 105,  "Germie Bernard",         "Pittsburgh Steelers"),
    (48, 2, 16, 33,   "Avieon Terrell",         "Atlanta Falcons"),
    (49, 2, 17, 3527, "Lee Hunter",             "Carolina Panthers"),
    (50, 2, 18, 3236, "D'Angelo Ponds",         "New York Jets"),
    (51, 2, 19, 2,    "Jake Golday",            "Minnesota Vikings"),
    (52, 2, 20, 71,   "Brandon Cisse",          "Green Bay Packers"),
    (53, 2, 21, 11,   "Cj Allen",               "Indianapolis Colts"),
    (54, 2, 22, 3637, "Eli Stowers",            "Philadelphia Eagles"),
    (55, 2, 23, 18,   "Gabe Jacas",             "New England Patriots"),
    (56, 2, 24, 150,  "Nate Boerkircher",       "Jacksonville Jaguars"),
    (57, 2, 25, 287,  "Logan Jones",            "Chicago Bears"),
    (58, 2, 26, 3528, "Emmanuel Mcneil-warren", "Cleveland Browns"),
    (59, 2, 27, 242,  "Marlin Klein",           "Houston Texans"),
    (60, 2, 28, 1,    "Anthony Hill",           "Tennessee Titans"),
    (61, 2, 29, 6,    "Max Klare",              "Los Angeles Rams"),
    (62, 2, 30, 36,   "Davison Igbinosun",      "Buffalo Bills"),
    (63, 2, 31, 3795, "Jake Slaughter",         "Los Angeles Chargers"),
]


def _fetch_apex_snapshot(cur, prospect_id):
    cur.execute(
        "SELECT apex_composite, apex_tier FROM apex_scores WHERE prospect_id=? AND season_id=?",
        (prospect_id, SEASON_ID),
    )
    row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


def _fetch_consensus_rank(cur, prospect_id):
    cur.execute(
        "SELECT consensus_rank FROM prospect_consensus_rankings WHERE prospect_id=? AND season_id=?",
        (prospect_id, SEASON_ID),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _fetch_divergence(cur, prospect_id):
    cur.execute(
        "SELECT divergence_rank_delta FROM divergence_flags WHERE prospect_id=? AND season_id=?",
        (prospect_id, SEASON_ID),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _verify_prospect_ids(cur):
    """Confirm all prospect_ids exist as is_active=1 before writing."""
    missing = []
    for (ovr, rnd, pir, pid, name, team) in DRAFT_PICKS:
        cur.execute(
            "SELECT 1 FROM prospects WHERE prospect_id=? AND is_active=1", (pid,)
        )
        if not cur.fetchone():
            missing.append((ovr, pid, name))
    return missing


def run(apply: bool):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Gate: already migrated?
    cur.execute("SELECT 1 FROM meta_migrations WHERE name=?", (MIGRATION_ID,))
    if cur.fetchone():
        print(f"Migration {MIGRATION_ID} already applied. Exiting.")
        conn.close()
        sys.exit(0)

    # Verify all prospect_ids resolve
    missing = _verify_prospect_ids(cur)
    if missing:
        print("ERROR: The following prospect_ids do not exist as is_active=1:")
        for (ovr, pid, name) in missing:
            print(f"  OVR {ovr:2d}  pid={pid}  {name}")
        conn.close()
        sys.exit(1)

    # Build rows with snapshot data
    rows = []
    now = datetime.utcnow().isoformat()
    for (ovr, rnd, pir, pid, name, team) in DRAFT_PICKS:
        apex_score, apex_tier = _fetch_apex_snapshot(cur, pid)
        consensus_rank = _fetch_consensus_rank(cur, pid)
        div_delta = _fetch_divergence(cur, pid)
        rows.append((
            pid, SEASON_ID, ovr, rnd, pir, team,
            apex_score, apex_tier, consensus_rank, div_delta,
            now, now,
        ))

    if not apply:
        print(f"[DRY RUN] Migration {MIGRATION_ID} — seed draft_results (2026 R1-R2)")
        print(f"[DRY RUN] {len(rows)} rows would be inserted")
        apex_covered = sum(1 for r in rows if r[6] is not None)
        con_covered  = sum(1 for r in rows if r[8] is not None)
        div_covered  = sum(1 for r in rows if r[9] is not None)
        print(f"[DRY RUN] APEX snapshot coverage:      {apex_covered}/{len(rows)}")
        print(f"[DRY RUN] Consensus rank coverage:     {con_covered}/{len(rows)}")
        print(f"[DRY RUN] Divergence delta coverage:   {div_covered}/{len(rows)}")
        print("[DRY RUN] No changes written.")
        conn.close()
        return

    inserted = 0
    for row in rows:
        cur.execute("""
            INSERT OR IGNORE INTO draft_results
              (prospect_id, season_id, pick_overall, pick_round, pick_in_round,
               team_name, apex_score_at_draft, apex_tier_at_draft,
               consensus_rank_at_draft, divergence_at_draft,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)
        inserted += cur.rowcount

    cur.execute(
        "INSERT INTO meta_migrations (name, applied_at) VALUES (?, ?)",
        (MIGRATION_ID, now),
    )

    conn.commit()
    conn.close()

    apex_covered = sum(1 for r in rows if r[6] is not None)
    con_covered  = sum(1 for r in rows if r[8] is not None)
    div_covered  = sum(1 for r in rows if r[9] is not None)
    print(f"[APPLY] Migration {MIGRATION_ID} applied.")
    print(f"[APPLY] {inserted} rows inserted into draft_results.")
    print(f"[APPLY] APEX snapshot coverage:      {apex_covered}/{len(rows)}")
    print(f"[APPLY] Consensus rank coverage:     {con_covered}/{len(rows)}")
    print(f"[APPLY] Divergence delta coverage:   {div_covered}/{len(rows)}")
    print("[APPLY] meta_migrations updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    run(apply=bool(args.apply))
