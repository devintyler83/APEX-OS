"""
scripts/reconcile_consensus_vs_jfosterfilm_2026.py

Reconciliation of APEX model rankings vs. jFosterFilm consensus rankings
for the 300-prospect S90 universe (season_id=1, 2026 draft).

Purpose
-------
Diagnostic / audit artifact.  Identifies prospects where the APEX engine's
implied overall rank diverges by >=25 positions from a weighted composite
of the engine consensus rank and jFosterFilm's CON (consensus) rank.  Also
performs name/mapping sanity checks to verify the jfosterfilm source_player_map
is clean for all flagged prospects.

This script is READ-ONLY against all core scoring tables.

Schema notes (confirmed against live DB)
-----------------------------------------
- prospect_measurables.consensus_rank  = jFosterFilm CON rank (stored as
  consensus_rank, not "con" — CLAUDE.md Session 69 note).
- No apex_ovr_rank column in apex_scores: derived via
  ROW_NUMBER() OVER (ORDER BY apex_composite DESC) within the 300-prospect set.
- source_players.raw_full_name = player name (not player_name).
- source_players has no prospect_id column; mapping goes through source_player_map.

Output
------
- Table  : apex_jfoster_reconciliation_2026  (DELETE + INSERT, read from any run)
- Table  : consensus_reconciliation_2026      (INSERT OR REPLACE, season-scoped)
                                              Created by Migration 0053.
- CSV    : data/apex_jfoster_reconciliation_2026_session90.csv

recon_bucket encoding (consensus_reconciliation_2026):
  HIGH         : |divergence| >= 25 AND APEX ranks prospect HIGHER than market
                 (apex_ovr_rank < combined → divergence_25 < -24)
  LOW          : |divergence| >= 25 AND APEX ranks prospect LOWER
                 (divergence_25 > 24)
  NONE         : |divergence| < 25 AND has jFoster CON coverage
  COVERAGE_GAP : no jFoster CON rank available for this prospect

divergence_delta in consensus_reconciliation_2026:
  consensus_rank_engine - apex_ovr_rank
  Positive = APEX bullish (matches divergence_flags.divergence_rank_delta sign).

Usage
-----
    python -m scripts.reconcile_consensus_vs_jfosterfilm_2026 --apply 0   # dry run
    python -m scripts.reconcile_consensus_vs_jfosterfilm_2026 --apply 1   # write
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from draftos.config import PATHS
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEASON_ID         = 1
MODEL_VERSION     = "apex_v2.3"
JFOSTER_SOURCE_ID = 1

# Weighting for combined rank (jFoster-blended divergence signal only)
W_ENGINE  = 0.6
W_JFOSTER = 0.4

# Divergence flag threshold
DIV_THRESHOLD = 25

OUTPUT_CSV = PATHS.root / "data" / "apex_jfoster_reconciliation_2026_session90.csv"

# ---------------------------------------------------------------------------
# DDL: apex_jfoster_reconciliation_2026 (existing diagnostic table)
# ---------------------------------------------------------------------------

_CREATE_JFOSTER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS apex_jfoster_reconciliation_2026 (
    prospect_id             INTEGER PRIMARY KEY,
    display_name            TEXT,
    school_canonical        TEXT,
    position_group          TEXT,
    apex_ovr_rank           INTEGER,
    consensus_rank_engine   INTEGER,
    consensus_rank_jfoster  INTEGER,
    consensus_rank_combined INTEGER,
    divergence_25           INTEGER,
    abs_divergence_25       INTEGER,
    div25_flag              INTEGER,
    name_match_status       TEXT,
    computed_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_JFOSTER_INSERT_SQL = """
INSERT INTO apex_jfoster_reconciliation_2026 (
    prospect_id, display_name, school_canonical, position_group,
    apex_ovr_rank, consensus_rank_engine, consensus_rank_jfoster,
    consensus_rank_combined, divergence_25, abs_divergence_25,
    div25_flag, name_match_status, computed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# ---------------------------------------------------------------------------
# DDL: consensus_reconciliation_2026 (season-scoped recon store, Migration 0053)
# ---------------------------------------------------------------------------

_CREATE_RECON_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS consensus_reconciliation_2026 (
    prospect_id      INTEGER NOT NULL,
    season_id        INTEGER NOT NULL DEFAULT 1,
    has_jfoster_con  INTEGER NOT NULL DEFAULT 0 CHECK (has_jfoster_con IN (0, 1)),
    jfoster_con_rank INTEGER,
    apex_rank        INTEGER NOT NULL,
    consensus_rank   INTEGER NOT NULL,
    divergence_delta INTEGER NOT NULL,
    recon_bucket     TEXT    NOT NULL
                     CHECK (recon_bucket IN ('HIGH', 'LOW', 'NONE', 'COVERAGE_GAP')),
    notes            TEXT,
    PRIMARY KEY (prospect_id, season_id)
)
"""

_RECON_UPSERT_SQL = """
INSERT INTO consensus_reconciliation_2026 (
    prospect_id, season_id, has_jfoster_con, jfoster_con_rank,
    apex_rank, consensus_rank, divergence_delta, recon_bucket, notes
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (prospect_id, season_id) DO UPDATE SET
    has_jfoster_con  = excluded.has_jfoster_con,
    jfoster_con_rank = excluded.jfoster_con_rank,
    apex_rank        = excluded.apex_rank,
    consensus_rank   = excluded.consensus_rank,
    divergence_delta = excluded.divergence_delta,
    recon_bucket     = excluded.recon_bucket,
    notes            = excluded.notes
"""

# Column names for CSV export
_CSV_FIELDS = [
    "prospect_id", "display_name", "school_canonical", "position_group",
    "apex_ovr_rank", "consensus_rank_engine", "consensus_rank_jfoster",
    "consensus_rank_combined", "divergence_25", "abs_divergence_25",
    "div25_flag", "name_match_status",
]

# ---------------------------------------------------------------------------
# Query: 300-prospect working set
# ---------------------------------------------------------------------------

_WORKING_SET_SQL = """
WITH ranked AS (
    SELECT
        p.prospect_id,
        p.display_name,
        p.school_canonical,
        p.position_group,
        a.apex_composite,
        pcr.consensus_rank,
        ROW_NUMBER() OVER (ORDER BY a.apex_composite DESC) AS apex_ovr_rank
    FROM apex_scores a
    JOIN prospects p
        ON p.prospect_id = a.prospect_id
       AND p.season_id   = a.season_id
    JOIN prospect_consensus_rankings pcr
        ON pcr.prospect_id = a.prospect_id
       AND pcr.season_id   = a.season_id
       AND pcr.is_active   = 1
    WHERE a.season_id    = ?
      AND a.model_version = ?
      AND p.is_active    = 1
      AND (a.is_calibration_artifact = 0 OR a.is_calibration_artifact IS NULL)
      AND pcr.consensus_rank <= 300
)
SELECT
    r.prospect_id,
    r.display_name,
    r.school_canonical,
    r.position_group,
    r.apex_ovr_rank,
    r.consensus_rank             AS consensus_rank_engine,
    pm.consensus_rank            AS consensus_rank_jfoster,
    r.apex_composite
FROM ranked r
LEFT JOIN prospect_measurables pm
    ON pm.prospect_id = r.prospect_id
   AND pm.season_id   = ?
ORDER BY r.consensus_rank
"""

_JFOSTER_MAP_SQL = """
SELECT
    spm.prospect_id,
    sp.raw_full_name
FROM source_player_map spm
JOIN source_players sp ON sp.source_player_id = spm.source_player_id
WHERE sp.source_id = ?
  AND spm.prospect_id IN ({placeholders})
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def backup_db() -> Path:
    src     = PATHS.db
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst     = out_dir / f"draftos_{ts}_reconcile_jfoster.sqlite"
    shutil.copy2(src, dst)
    return dst


def _normalize_name(name: str) -> str:
    """Lower-case, strip accents, remove punctuation, collapse whitespace."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(c if c.isalnum() or c == " " else "" for c in ascii_str.lower())
    return " ".join(cleaned.split())


def _combined_rank(engine_rank: int, jfoster_rank: int | None) -> int:
    if jfoster_rank is None:
        return engine_rank
    return round(engine_rank * W_ENGINE + jfoster_rank * W_JFOSTER)


def _name_match_status(display_name: str, jfoster_names: list[str]) -> str:
    if not jfoster_names:
        return "missing"
    if len(jfoster_names) > 1:
        return "multi_map"
    raw = jfoster_names[0]
    if raw == display_name:
        return "exact"
    if _normalize_name(raw) == _normalize_name(display_name):
        return "normalized_match"
    return "mismatch"


def _recon_bucket(divergence_25: int, jfoster_rank: int | None) -> str:
    """
    Compute recon_bucket for consensus_reconciliation_2026.

    divergence_25 = apex_ovr_rank - combined_rank
      Negative → apex_ovr_rank < combined → APEX rates prospect HIGHER → 'HIGH'
      Positive → APEX rates prospect LOWER → 'LOW'

    Sign convention matches divergence_flags.divergence_rank_delta:
      positive divergence_delta = APEX bullish.
    """
    if jfoster_rank is None:
        return "COVERAGE_GAP"
    if abs(divergence_25) < DIV_THRESHOLD:
        return "NONE"
    return "HIGH" if divergence_25 < 0 else "LOW"


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _build_records(conn) -> list[dict]:
    """
    Fetch the 300-prospect working set, compute combined rank, divergence,
    name-match status, and recon fields.  Returns a list of record dicts.
    """
    rows = conn.execute(
        _WORKING_SET_SQL,
        (SEASON_ID, MODEL_VERSION, SEASON_ID),
    ).fetchall()

    if not rows:
        print("ERROR: no rows returned from working-set query. Check model_version and universe.")
        sys.exit(1)

    # Build jFosterFilm name map for all prospect_ids in one query
    all_pids = [r["prospect_id"] for r in rows]
    placeholders = ",".join("?" * len(all_pids))
    jfoster_name_map: dict[int, list[str]] = {pid: [] for pid in all_pids}
    map_rows = conn.execute(
        _JFOSTER_MAP_SQL.format(placeholders=placeholders),
        [JFOSTER_SOURCE_ID] + all_pids,
    ).fetchall()
    for mr in map_rows:
        pid = mr["prospect_id"]
        if pid in jfoster_name_map:
            jfoster_name_map[pid].append(mr["raw_full_name"])

    ts = datetime.now(timezone.utc).isoformat()
    records: list[dict] = []

    for r in rows:
        pid            = r["prospect_id"]
        engine_rank    = r["consensus_rank_engine"]
        jfoster_rank   = r["consensus_rank_jfoster"]
        apex_ovr_rank  = r["apex_ovr_rank"]
        combined       = _combined_rank(engine_rank, jfoster_rank)
        divergence     = apex_ovr_rank - combined
        abs_div        = abs(divergence)
        flag           = 1 if abs_div >= DIV_THRESHOLD else 0
        jnames         = jfoster_name_map.get(pid, [])
        match_status   = _name_match_status(r["display_name"], jnames)
        bucket         = _recon_bucket(divergence, jfoster_rank)
        # divergence_delta: consensus_rank_engine - apex_ovr_rank
        # positive = APEX bullish (matches divergence_flags.divergence_rank_delta sign)
        delta          = engine_rank - apex_ovr_rank

        records.append({
            "prospect_id":             pid,
            "display_name":            r["display_name"],
            "school_canonical":        r["school_canonical"],
            "position_group":          r["position_group"],
            "apex_ovr_rank":           apex_ovr_rank,
            "consensus_rank_engine":   engine_rank,
            "consensus_rank_jfoster":  jfoster_rank,
            "consensus_rank_combined": combined,
            "divergence_25":           divergence,
            "abs_divergence_25":       abs_div,
            "div25_flag":              flag,
            "name_match_status":       match_status,
            "computed_at":             ts,
            # recon fields
            "has_jfoster_con":         1 if jfoster_rank is not None else 0,
            "recon_bucket":            bucket,
            "divergence_delta":        delta,
        })

    return records


def _print_summary(records: list[dict]) -> None:
    flagged   = [r for r in records if r["div25_flag"]]
    no_jfoster = [r for r in records if r["consensus_rank_jfoster"] is None]
    missing_map = [r for r in records if r["name_match_status"] == "missing"]
    mismatch    = [r for r in records if r["name_match_status"] == "mismatch"]

    print(f"  Total prospects in universe  : {len(records)}")
    print(f"  With jFoster CON rank        : {len(records) - len(no_jfoster)}")
    print(f"  Without jFoster CON rank     : {len(no_jfoster)}")
    print(f"  div25_flag=1 (|div| >= {DIV_THRESHOLD}) : {len(flagged)}")
    print(f"  Name match — exact           : {sum(1 for r in records if r['name_match_status']=='exact')}")
    print(f"  Name match — normalized      : {sum(1 for r in records if r['name_match_status']=='normalized_match')}")
    print(f"  Name match — multi_map       : {sum(1 for r in records if r['name_match_status']=='multi_map')}")
    print(f"  Name match — missing         : {len(missing_map)}")
    print(f"  Name match — mismatch        : {len(mismatch)}")
    print()

    # recon_bucket distribution
    bucket_counts: dict[str, int] = {}
    for r in records:
        b = r["recon_bucket"]
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
    print(f"  recon_bucket HIGH            : {bucket_counts.get('HIGH', 0)}"
          f"  (APEX bullish vs market, |div|>={DIV_THRESHOLD})")
    print(f"  recon_bucket LOW             : {bucket_counts.get('LOW', 0)}"
          f"  (APEX bearish vs market, |div|>={DIV_THRESHOLD})")
    print(f"  recon_bucket NONE            : {bucket_counts.get('NONE', 0)}"
          f"  (jFoster covered, small delta)")
    print(f"  recon_bucket COVERAGE_GAP    : {bucket_counts.get('COVERAGE_GAP', 0)}"
          f"  (no jFoster CON rank)")
    print()

    # Top 10 by abs divergence
    top10 = sorted(records, key=lambda r: r["abs_divergence_25"], reverse=True)[:10]
    print(f"  {'Rank':>4}  {'Name':<28} {'Pos':<6} {'ApxRk':>5} {'EngRk':>5} "
          f"{'JffRk':>5} {'CmbRk':>5} {'Div':>5} {'Bucket':<12} {'MatchStatus':<18}")
    print(f"  {'-'*4}  {'-'*28} {'-'*6} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*12} {'-'*18}")
    for i, r in enumerate(top10, 1):
        jffr = str(r["consensus_rank_jfoster"]) if r["consensus_rank_jfoster"] is not None else "—"
        flag_marker = "  *** " if r["div25_flag"] else "      "
        print(
            f"{flag_marker}{i:>2}.  "
            f"{r['display_name']:<28} {r['position_group']:<6} "
            f"{r['apex_ovr_rank']:>5} {r['consensus_rank_engine']:>5} "
            f"{jffr:>5} {r['consensus_rank_combined']:>5} "
            f"{r['divergence_25']:>+5}  {r['recon_bucket']:<12} {r['name_match_status']:<18}"
        )
    print()

    if mismatch:
        print("  NAME MISMATCHES (raw jFosterFilm name != display_name, normalized also differs):")
        for r in mismatch:
            print(f"    pid={r['prospect_id']} display='{r['display_name']}'")

    if no_jfoster:
        print()
        print("  PROSPECTS WITH NO jFoster CON RANK (engine consensus only):")
        for r in sorted(no_jfoster, key=lambda x: x["consensus_rank_engine"])[:15]:
            print(
                f"    pid={r['prospect_id']:>5d}  {r['display_name']:<28} "
                f"pos={r['position_group']:<6} eng_rank={r['consensus_rank_engine']:>3}  "
                f"match_status={r['name_match_status']}"
            )
        if len(no_jfoster) > 15:
            print(f"    ... and {len(no_jfoster)-15} more")


def _write_csv(records: list[dict]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"  CSV  : {OUTPUT_CSV}")


def _run(apply: bool) -> None:
    with connect() as conn:
        # -- Verify universe available ----------------------------------------
        apex_count = conn.execute(
            "SELECT COUNT(*) FROM apex_scores WHERE season_id=? AND model_version=? "
            "AND (is_calibration_artifact=0 OR is_calibration_artifact IS NULL)",
            (SEASON_ID, MODEL_VERSION),
        ).fetchone()[0]
        if apex_count == 0:
            print(f"ERROR: no apex_v2.3 rows found (season_id={SEASON_ID}). Aborting.")
            sys.exit(1)

        print(f"Mode          : {'APPLY' if apply else 'DRY RUN'}")
        print(f"Universe      : model={MODEL_VERSION}, season_id={SEASON_ID}, top-300 consensus")
        print(f"Weight        : engine={W_ENGINE:.1f}  jFoster={W_JFOSTER:.1f}")
        print(f"Flag threshold: |divergence| >= {DIV_THRESHOLD}")
        print()

        # -- Build records (all computation in Python) -----------------------
        records = _build_records(conn)

        # -- Print summary regardless of mode --------------------------------
        _print_summary(records)

        if not apply:
            print("Dry run complete. No changes written.")
            return

        # -- Apply: backup, write tables, write CSV --------------------------
        backup_path = backup_db()
        print(f"Backup : {backup_path}")

        # ── apex_jfoster_reconciliation_2026 (diagnostic, DELETE+INSERT) ────
        conn.execute(_CREATE_JFOSTER_TABLE_SQL)
        deleted = conn.execute(
            "DELETE FROM apex_jfoster_reconciliation_2026"
        ).rowcount
        if deleted:
            print(f"Cleared {deleted} existing rows from apex_jfoster_reconciliation_2026.")

        conn.executemany(
            _JFOSTER_INSERT_SQL,
            [
                (
                    r["prospect_id"], r["display_name"], r["school_canonical"],
                    r["position_group"], r["apex_ovr_rank"],
                    r["consensus_rank_engine"], r["consensus_rank_jfoster"],
                    r["consensus_rank_combined"], r["divergence_25"],
                    r["abs_divergence_25"], r["div25_flag"],
                    r["name_match_status"], r["computed_at"],
                )
                for r in records
            ],
        )

        count   = conn.execute("SELECT COUNT(*) FROM apex_jfoster_reconciliation_2026").fetchone()[0]
        flagged = conn.execute(
            "SELECT COUNT(*) FROM apex_jfoster_reconciliation_2026 WHERE div25_flag=1"
        ).fetchone()[0]
        print(f"Table  : apex_jfoster_reconciliation_2026 — {count} rows, {flagged} flagged")

        # ── consensus_reconciliation_2026 (season-scoped, INSERT OR REPLACE) ─
        conn.execute(_CREATE_RECON_TABLE_SQL)
        conn.executemany(
            _RECON_UPSERT_SQL,
            [
                (
                    r["prospect_id"],
                    SEASON_ID,
                    r["has_jfoster_con"],
                    r["consensus_rank_jfoster"],
                    r["apex_ovr_rank"],
                    r["consensus_rank_engine"],
                    r["divergence_delta"],
                    r["recon_bucket"],
                    None,  # notes: not populated by this script
                )
                for r in records
            ],
        )
        conn.commit()

        recon_count = conn.execute(
            "SELECT COUNT(*) FROM consensus_reconciliation_2026 WHERE season_id=?",
            (SEASON_ID,),
        ).fetchone()[0]
        bucket_dist = conn.execute(
            "SELECT recon_bucket, COUNT(*) FROM consensus_reconciliation_2026 "
            "WHERE season_id=? GROUP BY recon_bucket ORDER BY COUNT(*) DESC",
            (SEASON_ID,),
        ).fetchall()
        dist_str = "  ".join(f"{b}={n}" for b, n in bucket_dist)
        print(f"Table  : consensus_reconciliation_2026 — {recon_count} rows  [{dist_str}]")

        _write_csv(records)
        print()
        print("Apply complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile APEX implied rank vs. jFosterFilm CON rank for the "
            "300-prospect S90 universe (season_id=1)."
        )
    )
    parser.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="0 = dry run (default), 1 = write tables + CSV",
    )
    args = parser.parse_args()
    _run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
