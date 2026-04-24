#!/usr/bin/env python3
"""
DraftOS — Ingest consensus_master_2026 as dominant canonical source.
Source: consensusdatabase_4-23-26.csv (741 players, pre-aggregated consensus)
Weight: 10.0 (authoritative anchor — dominates weighted_base in build_consensus)
Session 77 | Migration: none required (uses existing schema)

Actual schema (verified against DB):
  sources:          source_name, source_type, notes, is_active
  source_players:   source_id, season_id, source_player_key, raw_full_name, raw_school,
                    raw_position, raw_json, ingested_at, name_norm, name_key
  source_player_map: source_player_id UNIQUE, prospect_id, match_method, match_score
  source_rankings:  source_id, season_id, source_player_id, overall_rank, position_raw,
                    ranking_date, ingested_at
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from draftos.db.connect import connect
from draftos.normalize.names import name_norm_and_key

CONSENSUS_CSV = Path(r"C:\DraftOS\data\consensusdatabase_4-23-26.csv")
AUDIT_DIR = Path(r"C:\DraftOS\data\edge\audit_reports")
SOURCE_NAME = "consensus_master_2026"
SOURCE_NOTES = (
    "Pre-aggregated consensus of 741 prospects. Weight=10.0. "
    "Authoritative anchor source — dominant signal in weighted_base. "
    "CSV: consensusdatabase_4-23-26.csv. Added Session 77."
)
RANKING_DATE = "2026-04-23"
SEASON_ID = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def player_key(name: str, school: str, pos: str) -> str:
    raw = f"{name.strip().lower()}|{school.strip().lower()}|{pos.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_csv() -> list[dict]:
    rows = []
    with open(CONSENSUS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["Player"].strip()
            norm, key = name_norm_and_key(name)
            rows.append({
                "name": name,
                "pos": row["Pos"].strip(),
                "school": row["School"].strip(),
                "rank": int(row["Con"]),
                "norm": norm,
                "key": key,
                "pkey": player_key(name, row["School"].strip(), row["Pos"].strip()),
            })
    return rows


def ensure_source(conn, apply: bool) -> int:
    row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name=?", (SOURCE_NAME,)
    ).fetchone()
    if row:
        sid = int(row["source_id"])
        print(f"Source already exists: {SOURCE_NAME} (id={sid})")
        return sid
    if not apply:
        print(f"[DRY RUN] Would create source: {SOURCE_NAME}")
        return -1
    conn.execute(
        "INSERT INTO sources (source_name, source_type, notes, is_active) VALUES (?, ?, ?, ?)",
        (SOURCE_NAME, "ranking", SOURCE_NOTES, 1),
    )
    sid = int(conn.execute(
        "SELECT source_id FROM sources WHERE source_name=?", (SOURCE_NAME,)
    ).fetchone()["source_id"])
    print(f"Created source: {SOURCE_NAME} (id={sid})")
    return sid


def load_active_prospects(conn) -> dict[str, dict]:
    """Returns dict keyed by name_norm -> {pid, display_name}."""
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT prospect_id, display_name, name_norm FROM prospects "
        "WHERE season_id=? AND is_active=1 AND name_norm IS NOT NULL",
        (SEASON_ID,),
    ).fetchall():
        out[r["name_norm"]] = {"pid": int(r["prospect_id"]), "name": r["display_name"]}
    return out


def run(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n{'='*60}\nConsensus Master Ingest [{mode}]\n{'='*60}\n")

    if not CONSENSUS_CSV.exists():
        raise SystemExit(f"FAIL: CSV not found: {CONSENSUS_CSV}")

    csv_rows = load_csv()
    print(f"CSV loaded: {len(csv_rows)} players")

    with connect() as conn:
        source_id = ensure_source(conn, apply)
        prospects = load_active_prospects(conn)
        print(f"Active prospects loaded: {len(prospects)}")

        matched: list[dict] = []
        unmatched: list[dict] = []
        for row in csv_rows:
            if row["norm"] and row["norm"] in prospects:
                p = prospects[row["norm"]]
                matched.append({**row, "pid": p["pid"], "db_name": p["name"]})
            else:
                unmatched.append(row)

        print(f"\nMatched:   {len(matched)}")
        print(f"Unmatched: {len(unmatched)}")

        if not apply:
            print("\nUnmatched sample (first 30 by rank):")
            for r in sorted(unmatched, key=lambda x: x["rank"])[:30]:
                print(f"  rank={r['rank']:>4} | {r['name']:35s} | {r['pos']:6s} | norm={r['norm']}")
            print("\nDRY RUN complete. Re-run with --apply 1 to write.")
            return

        if source_id == -1:
            raise SystemExit("ERROR: source_id not created — cannot proceed.")

        ingested_at = utcnow()
        sp_inserted = 0
        sp_existed = 0
        sr_inserted = 0
        sr_existed = 0
        spm_inserted = 0
        spm_existed = 0

        for m in matched:
            # ── 1. source_players ──────────────────────────────────────────
            existing_sp = conn.execute(
                "SELECT source_player_id FROM source_players "
                "WHERE source_id=? AND season_id=? AND source_player_key=?",
                (source_id, SEASON_ID, m["pkey"]),
            ).fetchone()

            if existing_sp:
                spid = int(existing_sp["source_player_id"])
                sp_existed += 1
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_players(
                        source_id, season_id, source_player_key,
                        raw_full_name, raw_school, raw_position,
                        raw_class_year, raw_json, ingested_at,
                        name_norm, name_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id, SEASON_ID, m["pkey"],
                        m["name"], m["school"], m["pos"],
                        None,
                        json.dumps({"rank": m["rank"], "name": m["name"],
                                    "school": m["school"], "pos": m["pos"]},
                                   ensure_ascii=False),
                        ingested_at,
                        m["norm"], m["key"],
                    ),
                )
                row = conn.execute(
                    "SELECT source_player_id FROM source_players "
                    "WHERE source_id=? AND season_id=? AND source_player_key=?",
                    (source_id, SEASON_ID, m["pkey"]),
                ).fetchone()
                spid = int(row["source_player_id"])
                sp_inserted += 1

            # ── 2. source_rankings ─────────────────────────────────────────
            existing_sr = conn.execute(
                "SELECT ranking_id FROM source_rankings "
                "WHERE source_id=? AND season_id=? AND source_player_id=? AND ranking_date=?",
                (source_id, SEASON_ID, spid, RANKING_DATE),
            ).fetchone()

            if existing_sr:
                sr_existed += 1
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_rankings(
                        source_id, season_id, source_player_id,
                        overall_rank, position_rank, position_raw,
                        grade, tier, ranking_date, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id, SEASON_ID, spid,
                        m["rank"], None, m["pos"],
                        None, None, RANKING_DATE, ingested_at,
                    ),
                )
                sr_inserted += 1

            # ── 3. source_player_map ───────────────────────────────────────
            existing_spm = conn.execute(
                "SELECT map_id FROM source_player_map WHERE source_player_id=?",
                (spid,),
            ).fetchone()

            if existing_spm:
                spm_existed += 1
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_player_map(
                        source_player_id, prospect_id, match_method, match_score
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (spid, m["pid"], "normalized_4layer", 1.0),
                )
                spm_inserted += 1

        conn.commit()

        print(f"\nsource_players  — inserted: {sp_inserted}, existed: {sp_existed}")
        print(f"source_rankings — inserted: {sr_inserted}, existed: {sr_existed}")
        print(f"source_player_map inserted: {spm_inserted}, existed: {spm_existed}")

        # ── Audit report ───────────────────────────────────────────────────
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = AUDIT_DIR / "spm_audit_2026-04-23.txt"
        with open(audit_path, "w", encoding="utf-8") as f:
            f.write(f"CONSENSUS MASTER INGEST AUDIT — {utcnow()}\n\n")
            f.write(f"Source: {SOURCE_NAME} | Weight: 10.0 | Players in CSV: {len(csv_rows)}\n")
            f.write(f"Matched: {len(matched)} | Unmatched: {len(unmatched)}\n")
            f.write(f"source_players inserted: {sp_inserted} | source_rankings inserted: {sr_inserted} | SPM inserted: {spm_inserted}\n\n")
            f.write("=== UNMATCHED PLAYERS (not in active prospect universe — no DB write) ===\n")
            for r in sorted(unmatched, key=lambda x: x["rank"]):
                f.write(f"  rank={r['rank']:>4} | {r['name']:35s} | {r['pos']:6s} | {r['school']}\n")

        print(f"\nAudit written: {audit_path}")
        print(f"\nDone. Next: run patch_spm_normalization_2026.py --apply 1, "
              f"then add consensus_master_2026: 10.0 to SOURCE_WEIGHTS in build_consensus_2026.py, "
              f"then run build_consensus_2026.py --apply 1")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest consensus_master_2026 as dominant canonical source (weight=10.0)."
    )
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True,
                        help="0=dry run, 1=write to DB")
    args = parser.parse_args()
    run(apply=bool(args.apply))
