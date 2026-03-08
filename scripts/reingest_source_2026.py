# scripts/reingest_source_2026.py
"""
General-purpose clean re-ingest for a single source.

Replaces all existing data for the named source with the current raw CSV,
then re-runs the standard mapping and bootstrap pipeline.

Steps on --apply 1:
  1. Backup DB
  2. Delete source_player_map entries for this source
  3. Delete source_rankings for this source
  4. Delete source_players for this source
  5. Orphan-cleanup any remaining stale source_player_map entries
  6. Delete staged files for this source from staged/{season}/
  7. Re-stage the raw CSV (stage_rankings_csv --source)
  8. Re-ingest all staged files (ingest_rankings_staged, idempotent for other sources)
  9. Re-run name normalization + auto-mapping (patch_name_normalization_2026)
 10. Re-run bootstrap (bootstrap_prospects_from_sources_2026)
 11. Re-run prospect canonicalization (patch_prospect_canonicalization_2026)

Usage:
  python -m scripts.reingest_source_2026 --source jfosterfilm_2026 --season 2026 --apply 0
  python -m scripts.reingest_source_2026 --source jfosterfilm_2026 --season 2026 --apply 1
"""

from __future__ import annotations

# --- sys.path bootstrap ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import csv
import shutil
import subprocess
from datetime import datetime, timezone

from draftos.config import PATHS
from draftos.db.connect import connect


def utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_db(reason: str) -> Path:
    src = PATHS.db
    ts = utcstamp()
    out_dir = PATHS.root / "data" / "exports" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"draftos_{ts}_{reason}.sqlite"
    dst.write_bytes(Path(src).read_bytes())
    return dst


def run(cmd: list[str]) -> None:
    """Run a subprocess, raising on non-zero exit."""
    print(f"  RUN: {' '.join(cmd)}")
    subprocess.check_call(cmd)


def pymod(*args: str) -> list[str]:
    return [sys.executable, "-m", *args]


def pyfile(path: Path, *args: str) -> list[str]:
    return [sys.executable, str(path), *args]


def get_source_id(conn, source_name: str) -> int | None:
    row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name = ?", (source_name,)
    ).fetchone()
    return int(row["source_id"]) if row else None


def get_season_id(conn, draft_year: int) -> int | None:
    row = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?", (draft_year,)
    ).fetchone()
    return int(row["season_id"]) if row else None


def current_row_counts(conn, source_id: int) -> dict:
    sp = conn.execute(
        "SELECT COUNT(*) as n FROM source_players WHERE source_id = ?", (source_id,)
    ).fetchone()["n"]
    sr = conn.execute(
        """
        SELECT COUNT(*) as n FROM source_rankings sr
        JOIN source_players sp ON sp.source_player_id = sr.source_player_id
        WHERE sp.source_id = ?
        """,
        (source_id,),
    ).fetchone()["n"]
    spm = conn.execute(
        """
        SELECT COUNT(*) as n FROM source_player_map spm
        JOIN source_players sp ON sp.source_player_id = spm.source_player_id
        WHERE sp.source_id = ?
        """,
        (source_id,),
    ).fetchone()["n"]
    return {"source_players": sp, "source_rankings": sr, "source_player_map": spm}


def peek_raw_file(raw_path: Path, n: int = 5) -> tuple[int, list[dict]]:
    """
    Return (ranked_row_count, first_n_ranked_rows) from the raw CSV.
    Only rows with a parseable integer rank value are counted.
    """
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            with raw_path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except Exception:
            continue
    else:
        return 0, []

    ranked = []
    for r in rows:
        # Find rank-like column: OVR, rank, overall, etc.
        rank_val = None
        for col in (r or {}):
            v = str(r[col] or "").strip()
            if v.isdigit() and col.upper() in ("OVR", "RANK", "RK", "OVERALL", "BOARDRANK"):
                rank_val = int(v)
                break
        if rank_val is not None:
            ranked.append({"rank": rank_val, **{k: v for k, v in r.items()}})
    ranked.sort(key=lambda x: x["rank"])
    return len(ranked), ranked[:n]


def staged_files_for_source(source_name: str, season: int) -> list[Path]:
    staged_dir = PATHS.imports / "rankings" / "staged" / str(season)
    if not staged_dir.exists():
        return []
    prefix = f"{source_name}_staged_"
    return sorted(p for p in staged_dir.iterdir() if p.name.startswith(prefix) and p.suffix.lower() == ".csv")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Clean re-ingest for a single source. Replaces all existing data."
    )
    ap.add_argument("--source", required=True, help="source_name to re-ingest")
    ap.add_argument("--season", type=int, required=True, help="Draft year (e.g. 2026)")
    ap.add_argument(
        "--apply",
        type=int,
        default=0,
        choices=[0, 1],
        help="0 = dry run (no changes), 1 = apply (deletes + re-ingest)",
    )
    args = ap.parse_args()

    source_name: str = args.source
    season: int = args.season
    dry_run: bool = args.apply == 0

    # ── Locate raw file ────────────────────────────────────────────────────────
    raw_path = PATHS.imports / "rankings" / "raw" / str(season) / f"{source_name}.csv"
    if not raw_path.exists():
        raise SystemExit(f"FAIL: raw CSV not found: {raw_path}")

    # ── Inspect raw file ───────────────────────────────────────────────────────
    ranked_count, top_rows = peek_raw_file(raw_path)

    # ── DB lookups ────────────────────────────────────────────────────────────
    with connect() as conn:
        source_id = get_source_id(conn, source_name)
        if source_id is None:
            raise SystemExit(
                f"FAIL: source '{source_name}' not found in sources table. "
                f"Seed it via migration before re-ingesting."
            )
        season_id = get_season_id(conn, season)
        if season_id is None:
            raise SystemExit(f"FAIL: season {season} not found in seasons table.")

        counts = current_row_counts(conn, source_id)

    # ── Staged files ───────────────────────────────────────────────────────────
    old_staged = staged_files_for_source(source_name, season)

    # ── DRY RUN REPORT ────────────────────────────────────────────────────────
    print()
    print(f"SOURCE:  {source_name}  (source_id={source_id})")
    print(f"SEASON:  {season}  (season_id={season_id})")
    print(f"RAW CSV: {raw_path}")
    print()
    print("CURRENT DB STATE (will be deleted):")
    print(f"  source_players    : {counts['source_players']}")
    print(f"  source_rankings   : {counts['source_rankings']}")
    print(f"  source_player_map : {counts['source_player_map']}")
    print()
    print(f"STAGED FILES TO DELETE ({len(old_staged)}):")
    for f in old_staged:
        print(f"  {f.name}")
    print()
    print(f"NEW FILE: {ranked_count} ranked rows  (total rows with integer rank)")
    print(f"TOP {len(top_rows)} RANKED ROWS:")
    for r in top_rows:
        print(f"  rank={r['rank']}  {r}")
    print()

    if dry_run:
        print("DRY RUN: no changes made. Rerun with --apply 1 to execute.")
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # APPLY
    # ═══════════════════════════════════════════════════════════════════════════

    # Step 1 — Backup
    bk = backup_db(f"reingest_{source_name}")
    print(f"BACKUP: {bk}")

    # Steps 2–5 — Delete existing data for this source
    print(f"\nDELETING existing data for source_id={source_id} ({source_name})...")
    with connect() as conn:
        # Step 2: delete source_player_map entries for this source
        conn.execute(
            """
            DELETE FROM source_player_map
            WHERE source_player_id IN (
                SELECT source_player_id FROM source_players WHERE source_id = ?
            )
            """,
            (source_id,),
        )
        spm_del = conn.total_changes
        print(f"  DELETED source_player_map rows: {spm_del}")

        # Step 3: delete source_rankings for this source
        conn.execute(
            """
            DELETE FROM source_rankings
            WHERE source_player_id IN (
                SELECT source_player_id FROM source_players WHERE source_id = ?
            )
            """,
            (source_id,),
        )
        sr_del = conn.total_changes - spm_del
        print(f"  DELETED source_rankings rows: {sr_del}")

        # Step 4: delete source_players for this source
        conn.execute(
            "DELETE FROM source_players WHERE source_id = ?",
            (source_id,),
        )
        sp_del = conn.total_changes - spm_del - sr_del
        print(f"  DELETED source_players rows: {sp_del}")

        # Step 5: orphan cleanup — source_player_map entries with no source_player
        conn.execute(
            """
            DELETE FROM source_player_map
            WHERE source_player_id NOT IN (
                SELECT source_player_id FROM source_players
            )
            """
        )
        orphan_del = conn.total_changes - spm_del - sr_del - sp_del
        print(f"  DELETED orphaned source_player_map rows: {orphan_del}")

        conn.commit()

    # Step 6 — Delete old staged files
    print(f"\nDELETING {len(old_staged)} staged file(s)...")
    for f in old_staged:
        f.unlink()
        print(f"  DELETED: {f.name}")

    # Step 7 — Re-stage
    print(f"\nSTAGING {source_name}...")
    run(pymod(
        "scripts.stage_rankings_csv",
        "--source", source_name,
        "--season", str(season),
        "--apply", "1",
    ))

    # Step 8 — Re-ingest (full staged dir, idempotent for other sources)
    print(f"\nINGESTING staged files (season={season})...")
    run(pyfile(
        ROOT / "scripts" / "ingest_rankings_staged.py",
        "--season", str(season),
        "--apply", "1",
    ))

    # Step 9 — Name normalization + auto-mapping
    print(f"\nRUNNING name normalization + auto-mapping...")
    run(pymod(
        "scripts.patch_name_normalization_2026",
        "--season", str(season),
        "--apply", "1",
    ))

    # Step 10 — Bootstrap prospects
    print(f"\nRUNNING bootstrap prospects...")
    run(pymod(
        "scripts.bootstrap_prospects_from_sources_2026",
        "--season", str(season),
        "--apply", "1",
    ))

    # Step 11 — Prospect canonicalization
    print(f"\nRUNNING prospect canonicalization...")
    run(pymod(
        "scripts.patch_prospect_canonicalization_2026",
        "--season", str(season),
        "--apply", "1",
    ))

    # ── Post-apply verification ────────────────────────────────────────────────
    print(f"\nVERIFICATION:")
    with connect() as conn:
        final = current_row_counts(conn, source_id)
        print(f"  source_players    : {final['source_players']}")
        print(f"  source_rankings   : {final['source_rankings']}")
        print(f"  source_player_map : {final['source_player_map']}")

    print(f"\nOK: reingest complete for {source_name}.")


if __name__ == "__main__":
    main()
