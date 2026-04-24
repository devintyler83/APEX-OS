#!/usr/bin/env python3
"""
DraftOS — Retroactive SPM normalization patch.
Finds source_players rows (all active sources) that have NO source_player_map entry
and whose stored name_norm matches an active prospect's name_norm. Creates the
missing SPM entries, fixing coverage_factor for affected players in build_consensus.

Works off pre-computed name_norm columns already in source_players and prospects —
no re-normalization needed. Both were populated by the same name_norm_and_key()
function at ingest time.

Session 77.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from draftos.db.connect import connect

AUDIT_DIR = Path(r"C:\DraftOS\data\edge\audit_reports")
SEASON_ID = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n{'='*60}\nSPM Normalization Patch [{mode}]\n{'='*60}\n")

    with connect() as conn:
        # Active prospect name_norm index
        prospects: dict[str, int] = {}
        for r in conn.execute(
            "SELECT prospect_id, name_norm FROM prospects "
            "WHERE season_id=? AND is_active=1 AND name_norm IS NOT NULL",
            (SEASON_ID,),
        ).fetchall():
            prospects[r["name_norm"]] = int(r["prospect_id"])

        print(f"Active prospects indexed: {len(prospects)}")

        # Find all source_players with no SPM entry, across active sources
        unmatched_sp = conn.execute(
            """
            SELECT sp.source_player_id, sp.raw_full_name, sp.name_norm,
                   sp.source_id, s.source_name
            FROM source_players sp
            JOIN sources s ON s.source_id = sp.source_id
            WHERE s.is_active = 1
              AND sp.name_norm IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM source_player_map spm
                WHERE spm.source_player_id = sp.source_player_id
              )
            ORDER BY s.source_name, sp.raw_full_name
            """
        ).fetchall()

        print(f"Unlinked source_players (active sources, name_norm present): {len(unmatched_sp)}")

        # Attempt name_norm match against active prospects
        new_links: list[dict] = []
        no_match: list[dict] = []

        for sp in unmatched_sp:
            norm = sp["name_norm"]
            if norm in prospects:
                new_links.append({
                    "spid": int(sp["source_player_id"]),
                    "pid": prospects[norm],
                    "raw_name": sp["raw_full_name"],
                    "norm": norm,
                    "source_name": sp["source_name"],
                })
            else:
                no_match.append(sp)

        print(f"Matchable via name_norm: {len(new_links)}")
        print(f"Unresolvable (no active prospect match): {len(no_match)}")

        audit_lines: list[str] = []

        if new_links:
            print("\nNew SPM links to create:")
            for link in sorted(new_links, key=lambda x: (x["source_name"], x["raw_name"])):
                msg = (f"  {link['source_name']:35s} | "
                       f"'{link['raw_name']}' -> pid={link['pid']} | norm={link['norm']}")
                print(msg)
                audit_lines.append(msg)

        if not apply:
            print("\nDRY RUN complete. Re-run with --apply 1 to write.")
        else:
            inserted = 0
            skipped = 0
            for link in new_links:
                # Guard: check again in case of duplicate prospect_id per source_player
                existing = conn.execute(
                    "SELECT map_id FROM source_player_map WHERE source_player_id=?",
                    (link["spid"],),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_player_map(
                        source_player_id, prospect_id, match_method, match_score
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (link["spid"], link["pid"], "norm_patch_s77", 0.95),
                )
                inserted += 1

            conn.commit()
            print(f"\nSPM entries inserted: {inserted}, skipped (already linked): {skipped}")

        # ── Audit report — append to file created by Script 1 ─────────────
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = AUDIT_DIR / "spm_audit_2026-04-23.txt"
        write_mode = "a" if audit_path.exists() else "w"
        with open(audit_path, write_mode, encoding="utf-8") as f:
            f.write(f"\n\n=== SPM NORMALIZATION PATCH [{mode}] — {utcnow()} ===\n")
            f.write(f"Unlinked source_players scanned: {len(unmatched_sp)}\n")
            f.write(f"Matchable: {len(new_links)} | Unresolvable: {len(no_match)}\n\n")
            if new_links:
                f.write("--- New links {'(DRY RUN — not written)' if not apply else '(written)'} ---\n")
                for line in audit_lines:
                    f.write(line + "\n")
            if no_match:
                f.write("\n--- Unresolvable source_players (no active prospect match) ---\n")
                for sp in sorted(no_match, key=lambda x: x["source_name"]):
                    f.write(f"  {sp['source_name']:35s} | '{sp['raw_full_name']}' | norm={sp['name_norm']}\n")

        print(f"\nAudit appended: {audit_path}")

        if not apply:
            return

        print(f"\nDone. Now add 'consensus_master_2026: 10.0' to SOURCE_WEIGHTS in "
              f"build_consensus_2026.py, then run:\n"
              f"  python scripts\\build_consensus_2026.py --apply 1")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Patch missing SPM entries for active sources using stored name_norm."
    )
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True,
                        help="0=dry run, 1=write to DB")
    args = parser.parse_args()
    run(apply=bool(args.apply))
