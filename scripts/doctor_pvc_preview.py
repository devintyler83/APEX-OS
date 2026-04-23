import sqlite3

DB_PATH = "data/edge/draftos.sqlite"

# Curated test set: adjust PIDs/names to your actual table
TEST_PLAYERS = [
    # CB spectrum
    ("CB-1", None),   # archetype-only filter
    ("CB-3", None),
    ("CB-4", None),
    ("CB-5", None),
    # EDGE spectrum
    ("EDGE-1", None),
    ("EDGE-5", None),
    # S spectrum
    ("S-3", None),
    ("S-5", None),
    # RB spectrum
    ("RB-1", None),
    ("RB-3", None),
]

def fetch_sample_rows(conn, archetype_code, player_name_like=None, limit=3):
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    params = {"arch": archetype_code, "limit": limit}
    name_clause = ""
    if player_name_like:
        name_clause = "AND LOWER(p.player_name) LIKE LOWER(:name)"
        params["name"] = f"%{player_name_like}%"

    cur.execute(f"""
      SELECT
        p.prospect_id,
        p.display_name AS player_name,
        p.position_group,
        s.matched_archetype AS archetype_code,
        s.raw_score,
        s.apex_composite,
        s.pvc
      FROM apex_scores s
      JOIN prospects p ON p.prospect_id = s.prospect_id
      WHERE s.season_id = 1
        AND s.model_version = (SELECT MAX(model_version) FROM apex_scores WHERE season_id = 1)
        AND s.matched_archetype LIKE :arch || '%'
        {name_clause}
      ORDER BY s.apex_composite DESC
      LIMIT :limit;
    """, params)
    return cur.fetchall()

def get_position_pvc(position_group):
    PVC_TABLE = {
        "QB": 1.0, "CB": 1.0, "EDGE": 1.0,
        "WR": 0.90, "OT": 0.90, "S": 0.90, "IDL": 0.90,
        "ILB": 0.85, "OLB": 0.85, "LB": 0.85,
        "OG": 0.80, "TE": 0.80, "C": 0.80,
        "RB": 0.70,
        "OL": 0.80,  # generic fallback used in prospects
    }
    return PVC_TABLE.get(position_group, 1.0)

def pvc_preview():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=== PVC Archetype Preview ===")
    print("player | pos | arch | raw_score | base_PVC | arch_PVC | apex_comp")

    for arch_code, name_like in TEST_PLAYERS:
        rows = fetch_sample_rows(conn, arch_code, name_like, limit=2)
        if not rows:
            continue
        print(f"\n-- {arch_code} --")
        for r in rows:
            base_pvc = get_position_pvc(r["position_group"])
            arch_pvc = r["pvc"]  # effective PVC stored on apex_scores row
            print(
                f"{r['player_name']} | {r['position_group']} | {r['archetype_code']} | "
                f"{r['raw_score']:.1f} | {base_pvc:.3f} | {arch_pvc:.3f} | {r['apex_composite']:.1f}"
            )

    conn.close()

if __name__ == "__main__":
    pvc_preview()