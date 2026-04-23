import sqlite3
from statistics import mean

DB_PATH = "data/edge/draftos.sqlite"

MIN_YEAR = 2016
MIN_TRUSTED_N = 4          # below this, archetype marked untrusted
OUTLIER_N_THRESHOLD = 8    # shrink only if sample < this
OUTLIER_HIGH_MULT = 1.5    # > 1.5x median -> shrink toward median
OUTLIER_LOW_MULT = 0.5     # < 0.5x median -> shrink toward median
SHRINK_FACTOR = 0.5        # move halfway toward reference
WEIGHT_MIN = 0.6           # clamp weights
WEIGHT_MAX = 1.4

# Manual trust downgrades applied after weight computation.
# Format: archetype_code -> note string
MANUAL_UNTRUST = {
    "OG-2": "manual review: sample dominated by low-value contracts despite n>=4",
}

# Position group normalization: any of these raw contract_history values
# get written to pvc_archetype_weights as 'LB'.
LB_GROUPS = {"ILB", "OLB"}

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1) Create pvc_archetype_weights table if not exists
cur.execute("""
CREATE TABLE IF NOT EXISTS pvc_archetype_weights (
  position_group TEXT NOT NULL,
  archetype_code TEXT NOT NULL,
  weight REAL NOT NULL,
  n_contracts INTEGER NOT NULL,
  avg_cap_pct REAL NOT NULL,
  min_cap_pct REAL NOT NULL,
  max_cap_pct REAL NOT NULL,
  trusted INTEGER NOT NULL DEFAULT 1,
  notes TEXT,
  PRIMARY KEY (position_group, archetype_code)
);
""")

# Clear previous contents so reruns are idempotent
cur.execute("DELETE FROM pvc_archetype_weights;")

# 2) Pull archetype-level cap% distribution from contract_history.
# Exclusions applied here:
#   - year_signed >= MIN_YEAR (modern cap era gate — post-2016 contracts only)
#   - cap_pct >= 1.0 (exclude restructures / minimum-salary deals)
#   - archetype_code / position_group NOT NULL
# Note: pvc_eligible lives on historical_comps, not contract_history.
# The year_signed >= MIN_YEAR gate handles the modern era requirement.
cur.execute(f"""
SELECT
  position_group,
  archetype_code,
  COUNT(*) AS n_contracts,
  AVG(cap_pct) AS avg_cap_pct,
  MIN(cap_pct) AS min_cap_pct,
  MAX(cap_pct) AS max_cap_pct
FROM contract_history
WHERE year_signed >= ?
  AND cap_pct >= 1.0
  AND archetype_code IS NOT NULL
  AND position_group IS NOT NULL
GROUP BY position_group, archetype_code
ORDER BY position_group, archetype_code;
""", (MIN_YEAR,))

rows = cur.fetchall()

# Organize by position_group.
# LB normalization: ILB and OLB both fold into 'LB' so the engine's
# position_group key matches what's stored here.
by_pos: dict[str, list] = {}
for r in rows:
    raw_pos = r["position_group"]
    pos = "LB" if raw_pos in LB_GROUPS else raw_pos
    by_pos.setdefault(pos, []).append({
        "position_group": pos,
        "archetype_code": r["archetype_code"],
        "n":   r["n_contracts"],
        "avg": r["avg_cap_pct"],
        "min": r["min_cap_pct"],
        "max": r["max_cap_pct"],
        "notes": [],
    })


def shrink_toward(value: float, target: float, factor: float) -> float:
    return target + factor * (value - target)


# 3) Build weights per position — collect into output_rows before any INSERT
# so that cross-archetype calibration passes can be applied first.
output_rows: list[dict] = []

for pos, archetypes in by_pos.items():
    avgs = [a["avg"] for a in archetypes if a["avg"] is not None]
    if not avgs:
        continue

    # Position-level median for outlier detection
    sorted_avgs = sorted(avgs)
    mid = len(sorted_avgs) // 2
    median_val = (
        sorted_avgs[mid]
        if len(sorted_avgs) % 2 == 1
        else 0.5 * (sorted_avgs[mid - 1] + sorted_avgs[mid])
    )

    # 3a) Apply outlier shrink per archetype (small-n only)
    for a in archetypes:
        v, n, adj = a["avg"], a["n"], a["avg"]
        if n < OUTLIER_N_THRESHOLD:
            if v > OUTLIER_HIGH_MULT * median_val:
                adj = shrink_toward(v, median_val, SHRINK_FACTOR)
                a["notes"].append(
                    f"shrunk high outlier {v:.2f}% toward median {median_val:.2f}%"
                )
            elif v < OUTLIER_LOW_MULT * median_val:
                adj = shrink_toward(v, median_val, SHRINK_FACTOR)
                a["notes"].append(
                    f"shrunk low outlier {v:.2f}% toward median {median_val:.2f}%"
                )
        a["adj_avg"] = adj

    # 3b) Position mean from trusted-n archetypes only
    trusted_avgs = [a["adj_avg"] for a in archetypes if a["n"] >= MIN_TRUSTED_N]
    pos_mean = mean(trusted_avgs) if trusted_avgs else mean(a["adj_avg"] for a in archetypes)

    # 3c) Derive per-archetype weight
    for a in archetypes:
        adj, n = a["adj_avg"], a["n"]
        notes = a["notes"]

        w = adj / pos_mean if pos_mean > 0 else 1.0

        # clamp
        if w < WEIGHT_MIN:
            notes.append(f"weight {w:.3f} clamped to {WEIGHT_MIN:.2f}")
            w = WEIGHT_MIN
        elif w > WEIGHT_MAX:
            notes.append(f"weight {w:.3f} clamped to {WEIGHT_MAX:.2f}")
            w = WEIGHT_MAX

        trusted = 1
        if n < MIN_TRUSTED_N:
            trusted = 0
            notes.append(f"small sample n={n}, marked untrusted")

        output_rows.append({
            "position_group": pos,
            "archetype_code": a["archetype_code"],
            "weight":  round(w, 3),
            "n":       n,
            "avg":     a["avg"],
            "min":     a["min"],
            "max":     a["max"],
            "trusted": trusted,
            "notes":   notes,
        })

# ---------------------------------------------------------------------------
# 4) Manual calibration passes — applied after weight computation, before INSERT
# ---------------------------------------------------------------------------

# Pass A: manual trust downgrade (archetype-specific, numeric weight unchanged)
for row in output_rows:
    if row["archetype_code"] in MANUAL_UNTRUST:
        row["trusted"] = 0
        row["notes"].append(MANUAL_UNTRUST[row["archetype_code"]])

# Pass B: QB-1 ceiling — hard clamp
# QB-1 is the maximum QB archetype weight (franchise-QB market reality).
# Any other QB archetype that exceeds QB-1 is clamped exactly to QB-1.
qb_rows = {r["archetype_code"]: r for r in output_rows if r["position_group"] == "QB"}
if "QB-1" in qb_rows:
    qb1_w = qb_rows["QB-1"]["weight"]
    for code, row in qb_rows.items():
        if code != "QB-1" and row["weight"] > qb1_w:
            row["weight"] = qb1_w
            row["notes"].append(
                "manual calibration: clamped to QB-1 to preserve franchise-QB ceiling"
            )

# Pass C: EDGE-4 contamination guardrail
# EDGE-4 weight must not exceed EDGE-2 weight (Garrett/Hutchinson classification
# pending review — may belong in EDGE-1, not EDGE-4).
# Hard clamp: contaminated signal must not outrank a cleaner archetype
# while review is unresolved.
edge_rows = {r["archetype_code"]: r for r in output_rows if r["position_group"] == "EDGE"}
if "EDGE-4" in edge_rows and "EDGE-2" in edge_rows:
    e4_row = edge_rows["EDGE-4"]
    e2_w   = edge_rows["EDGE-2"]["weight"]
    if e4_row["weight"] > e2_w:
        e4_row["weight"] = e2_w
        e4_row["notes"].append(
            "manual calibration: clamped to EDGE-2 pending archetype contamination review"
        )

# ---------------------------------------------------------------------------
# 5) INSERT all rows
# ---------------------------------------------------------------------------
for row in output_rows:
    notes_str = "; ".join(row["notes"]) if row["notes"] else None
    cur.execute("""
    INSERT INTO pvc_archetype_weights (
      position_group, archetype_code, weight,
      n_contracts, avg_cap_pct, min_cap_pct, max_cap_pct,
      trusted, notes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        row["position_group"],
        row["archetype_code"],
        row["weight"],
        row["n"],
        row["avg"],
        row["min"],
        row["max"],
        row["trusted"],
        notes_str,
    ))

conn.commit()
conn.close()
print("pvc_archetype_weights built.")
