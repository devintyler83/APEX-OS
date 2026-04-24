"""
S76: Flag LT Overton as POSITIONAL_MISCLASSIFICATION in apex_overrides.
Excludes him from all future EDGE scoring batches until position is corrected.
Run: python -m scripts.overton_misclassification_flag_s76 --apply 0|1
"""
import argparse
import datetime
import shutil
import sqlite3

DB_PATH = "data/edge/draftos.sqlite"
SEASON_ID = 1

OVERRIDE_TYPE = "POSITIONAL_MISCLASSIFICATION"
OVERRIDE_VALUE = "EDGE"
RATIONALE = (
    "LT Overton physical profile (274 lbs, Run Defense 53.5, Pass Rush 20.3, "
    "Anchor 75) is IDL/5T-hybrid, not EDGE at any archetype. No viable pass rush "
    "mechanism confirmed. Scouting confirms 5T-only positional fit. Removing from "
    "EDGE scoring pool pending full position reclassification in Session 77. Do not "
    "rescore as EDGE. -144 divergence is position classification error, not APEX "
    "scoring error."
)
APPLIED_BY = "session_s76_misclassification_audit"

_CREATE_OVERRIDES_SQL = """
CREATE TABLE IF NOT EXISTS apex_overrides (
    override_id    INTEGER PRIMARY KEY,
    prospect_id    INTEGER NOT NULL,
    season_id      INTEGER NOT NULL DEFAULT 1,
    override_type  TEXT    NOT NULL,
    override_value TEXT,
    rationale      TEXT,
    applied_by     TEXT,
    applied_at     TEXT    NOT NULL,
    UNIQUE(prospect_id, season_id, override_type),
    FOREIGN KEY(prospect_id) REFERENCES prospects(prospect_id)
)
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Step 1 — Lookup
    rows = conn.execute(
        "SELECT prospect_id, display_name, position_group FROM prospects "
        "WHERE display_name LIKE '%Overton%' AND is_active=1 AND season_id=?",
        (SEASON_ID,),
    ).fetchall()

    edge_rows = [r for r in rows if r["position_group"] == "EDGE"]

    if len(edge_rows) == 0:
        print("ERROR: No active EDGE Overton found. Aborting.")
        conn.close()
        return
    if len(edge_rows) > 1:
        print(f"ERROR: Multiple active EDGE Overton rows: {[dict(r) for r in edge_rows]}. Aborting.")
        conn.close()
        return

    pid = edge_rows[0]["prospect_id"]
    display_name = edge_rows[0]["display_name"]
    position_group = edge_rows[0]["position_group"]
    print(f"\nTarget: {display_name} | pid={pid} | position_group={position_group}")

    # Current apex_scores row
    score_row = conn.execute(
        "SELECT apex_composite, apex_tier, matched_archetype FROM apex_scores "
        "WHERE prospect_id=? AND season_id=?",
        (pid, SEASON_ID),
    ).fetchone()
    if score_row:
        print(f"  Current apex_scores: composite={score_row['apex_composite']} "
              f"tier={score_row['apex_tier']} archetype={score_row['matched_archetype']}")
    else:
        print("  Current apex_scores: (none)")

    # Step 2 — Dry run output
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"\n{'DRY RUN' if not args.apply else 'WRITING'} — apex_overrides INSERT OR REPLACE:")
    print(f"  prospect_id    = {pid}")
    print(f"  season_id      = {SEASON_ID}")
    print(f"  override_type  = {OVERRIDE_TYPE!r}")
    print(f"  override_value = {OVERRIDE_VALUE!r}")
    print(f"  applied_by     = {APPLIED_BY!r}")
    print(f"  rationale      = {RATIONALE[:80]}...")

    if not args.apply:
        print("\n[DRY RUN] No writes. Pass --apply 1 to commit.")
        conn.close()
        return

    # Step 3 — Apply
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = f"data/edge/draftos.sqlite.bak_overton_flag_{ts}"
    shutil.copy2(DB_PATH, backup)
    print(f"\nBackup: {backup}")

    conn.execute(_CREATE_OVERRIDES_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO apex_overrides "
        "(prospect_id, season_id, override_type, override_value, rationale, applied_by, applied_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pid, SEASON_ID, OVERRIDE_TYPE, OVERRIDE_VALUE, RATIONALE, APPLIED_BY, now),
    )
    conn.commit()
    print(f"Override written for pid={pid}, {display_name}.")

    # Step 4 — Verification
    result = conn.execute(
        "SELECT override_type, rationale, applied_by FROM apex_overrides WHERE prospect_id=? AND season_id=?",
        (pid, SEASON_ID),
    ).fetchone()
    print(f"\nVerification:")
    print(f"  override_type = {result['override_type']}")
    print(f"  applied_by    = {result['applied_by']}")
    print(f"  rationale     = {result['rationale'][:80]}...")

    conn.close()


if __name__ == "__main__":
    main()
