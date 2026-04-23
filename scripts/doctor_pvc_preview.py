import sqlite3

DB_PATH = "data/edge/draftos.sqlite"

# Archetype bands to sample (2 rows each, top by apex_composite)
TEST_ARCHETYPES = [
    # CB spectrum
    "CB-1", "CB-2", "CB-3", "CB-4", "CB-5",
    # EDGE spectrum
    "EDGE-1", "EDGE-2", "EDGE-3", "EDGE-4", "EDGE-5",
    # S spectrum — all 5 bands
    "S-1", "S-2", "S-3", "S-4", "S-5",
    # RB spectrum
    "RB-1", "RB-2", "RB-3",
    # ILB/OLB
    "ILB-1", "ILB-3",
]

def fetch_sample_rows(conn, archetype_code, limit=2):
    cur = conn.cursor()
    cur.execute("""
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
        AND p.is_active = 1
        AND s.is_calibration_artifact = 0
        AND s.model_version = (
          SELECT MAX(model_version) FROM apex_scores
          WHERE season_id = 1
        )
        AND s.matched_archetype LIKE ? || '%'
      ORDER BY s.apex_composite DESC
      LIMIT ?
    """, (archetype_code, limit))
    return cur.fetchall()

BASE_PVC = {
    "QB": 1.0, "CB": 1.0, "EDGE": 1.0,
    "WR": 0.90, "OT": 0.90, "S": 0.90, "IDL": 0.90,
    "ILB": 0.85, "OLB": 0.85, "LB": 0.85,
    "OG": 0.80, "TE": 0.80, "C": 0.80,
    "RB": 0.70,
    "OL": 0.80,
}

def pvc_preview():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=== PVC Archetype Preview ===")
    print(f"{'player':<28} | {'pos':<5} | {'arch':<30} | {'raw':>5} | {'base':>5} | {'eff':>6} | {'comp':>6} | flag")

    prev_pos = None
    for arch_code in TEST_ARCHETYPES:
        rows = fetch_sample_rows(conn, arch_code, limit=2)
        if not rows:
            continue
        pos_prefix = arch_code.split("-")[0]
        if pos_prefix != prev_pos:
            print()
            prev_pos = pos_prefix
        print(f"-- {arch_code} --")
        for r in rows:
            base = BASE_PVC.get(r["position_group"], 1.0)
            eff = r["pvc"]
            flag = ""
            # Flag rows where eff_pvc == base_pvc exactly (likely pre-archetype-weight legacy)
            if abs(eff - base) < 0.0001 and base < 1.0:
                flag = " LEGACY?"
            print(
                f"  {r['player_name']:<28} | {r['position_group']:<5} | {r['archetype_code']:<30} | "
                f"{r['raw_score']:>5.1f} | {base:>5.3f} | {eff:>6.4f} | {r['apex_composite']:>6.1f} |{flag}"
            )

    conn.close()

if __name__ == "__main__":
    pvc_preview()
