"""
audit_position_overrides_2026.py
Read-only audit of TOP50_POSITION_OVERRIDES against canonical DB state.
No writes. Safe to run at any time.

Usage:
    python scripts/audit_position_overrides_2026.py
"""

import sqlite3

DB_PATH = r"C:\DraftOS\data\edge\draftos.sqlite"

# Extracted from run_apex_scoring_2026.py (as of 2026-03-15)
TOP50_POSITION_OVERRIDES = {
    # OL -> specific sub-position
    21:   "OT",    # Chase Bisontis    (Texas A&M)
    22:   "OG",    # Francis Mauigoa   (Miami)
    23:   "OT",    # Kadyn Proctor     (Alabama)
    25:   "OT",    # Monroe Freeling   (Georgia)
    26:   "OT",    # Spencer Fano      (Utah)
    54:   "OT",    # Caleb Lomu        (Utah)
    55:   "OT",    # Emmanuel Pregnon  (Oregon)
    96:   "OT",    # Blake Miller      (Clemson)
    98:   "OG",    # Olaivavega Ioane  (Penn State)
    136:  "OG",    # Keylan Rutledge   (Georgia)
    225:  "C",     # Connor Lew        (Auburn)
    # DT -> IDL
    75:   "IDL",   # Caleb Banks       (Florida)
    78:   "IDL",   # Kayden Mcdonald   (Ohio State)
    79:   "IDL",   # Peter Woods       (Clemson)
    # LB -> ILB / OLB
    1:    "ILB",   # Anthony Hill      (Texas)
    4:    "ILB",   # Lee Hunter        (Texas Tech)
    5:    "ILB",   # Max Iheanachor    (Arizona State)
    6:    "TE",    # Max Klare         (Ohio State)
    7:    "ILB",   # R Mason Thomas    (Oklahoma)
    8:    "ILB",   # Sonny Styles      (Ohio State)
    9:    "ILB",   # Ty Simpson        (Alabama)
    10:   "ILB",   # Zion Young        (Missouri)
    11:   "ILB",   # Cj Allen          (Georgia)
    12:   "ILB",   # Omar Cooper       (Indiana)
    16:   "OLB",   # Arvell Reese      (Ohio State)
    18:   "ILB",   # Gabe Jacas        (Illinois)
    20:   "ILB",   # Josiah Trotter    (Missouri)
}


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print(f"\n{'-'*85}")
    print(f"TOP50_POSITION_OVERRIDES AUDIT  --  {len(TOP50_POSITION_OVERRIDES)} entries")
    print(f"{'-'*85}")
    print(f"{'PID':<6} {'NAME':<28} {'DB_POS':<8} {'OVERRIDE':<9} {'APEX_ARCH':<26} {'STATUS'}")
    print(f"{'-'*85}")

    conflicts = []
    clean     = []

    # DB positions that are valid "parents" for each sub-position override
    POSITION_MAP = {
        "OT":   {"OT", "OL"},
        "OG":   {"OG", "OL"},
        "C":    {"C",  "OL"},
        "IDL":  {"IDL", "DT", "DL"},
        "ILB":  {"ILB", "LB"},
        "OLB":  {"OLB", "LB"},
        "EDGE": {"EDGE", "DL", "LB"},
        "TE":   {"TE"},
    }

    for pid, override_pos in sorted(TOP50_POSITION_OVERRIDES.items()):
        cur.execute("""
            SELECT p.full_name, p.display_name, p.position_group,
                   a.matched_archetype, p.is_active
            FROM prospects p
            LEFT JOIN apex_scores a
                   ON a.prospect_id = p.prospect_id
                  AND a.model_version = (
                          SELECT MAX(model_version) FROM apex_scores
                          WHERE prospect_id = p.prospect_id
                      )
            WHERE p.prospect_id = ?
        """, (pid,))
        row = cur.fetchone()

        if not row:
            print(f"{pid:<6} {'[NOT FOUND]':<28} {'--':<8} {override_pos:<9} {'--':<26} WARN: PID MISSING")
            conflicts.append((pid, "PID_NOT_FOUND", override_pos, ""))
            continue

        name      = row["display_name"] or row["full_name"]
        db_pos    = row["position_group"] or "--"
        arch      = row["matched_archetype"] or "--"
        is_active = row["is_active"]

        valid_db  = POSITION_MAP.get(override_pos, {override_pos})
        match     = (db_pos in valid_db) or (db_pos == override_pos)

        if not is_active:
            status = "SKIP: is_active=0"
        elif match:
            status = "OK"
        else:
            status = "CONFLICT"

        print(f"{pid:<6} {name:<28} {db_pos:<8} {override_pos:<9} {arch:<26} {status}")

        if status == "OK":
            clean.append(pid)
        elif status == "CONFLICT":
            conflicts.append((pid, db_pos, override_pos, name))
        # SKIP and MISSING logged separately below

    print(f"{'-'*85}")

    missing   = [(pid, db, ov, nm) for pid, db, ov, nm in conflicts if db == "PID_NOT_FOUND"]
    true_conf = [(pid, db, ov, nm) for pid, db, ov, nm in conflicts if db != "PID_NOT_FOUND"]

    print(f"\nSUMMARY: {len(clean)} clean | {len(true_conf)} conflicts | {len(missing)} missing PIDs\n")

    if true_conf:
        print("CONFLICTS REQUIRING REVIEW:")
        for pid, db_pos, override_pos, name in true_conf:
            print(f"  pid={pid:<5} {name:<28}  DB='{db_pos}'  override='{override_pos}'")
        print()
        print("ACTION: Each conflict must be manually reviewed.")
        print("  If override is stale  -> remove from TOP50_POSITION_OVERRIDES.")
        print("  If DB position wrong  -> fix prospects table via migration script.")
    else:
        print("No conflicts. TOP50_POSITION_OVERRIDES is clean.")

    if missing:
        print()
        print("MISSING PIDs (no prospects row found):")
        for pid, _, override_pos, _ in missing:
            print(f"  pid={pid}  override='{override_pos}'")

    conn.close()


if __name__ == "__main__":
    run()
