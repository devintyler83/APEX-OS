"""
DraftOS Ingest Pipeline
=======================
Usage:
  python ingest.py --source pff       --file "C:/DraftOS/data/imports/rankings/raw/2026/pff_2026.csv"
  python ingest.py --source ras       --file "C:/DraftOS/data/imports/rankings/raw/2026/ras_2026.csv"
  python ingest.py --source all       --dir  "C:/DraftOS/data/imports/rankings/raw/2026"
  python ingest.py --consensus        # recompute consensus from all active sources
  python ingest.py --divergence       # recompute divergence flags

Place this file at: C:/DraftOS/draftos/ingest.py
Requires: names.py, positions.py, schools.py in same directory
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Import normalizers (draftos/normalize/) ──────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "normalize"))
from names import name_norm_and_key, strip_suffix, _strip_leading_position_prefix
from positions import normalize_position
from schools import normalize_school_raw, school_key

# ── Config ───────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent.parent / "data" / "edge" / "draftos.sqlite"
SEASON_ID = 1
DRAFT_YEAR = 2026
MODEL_VERSION = "apex_v2.2"

# ── Source registry ──────────────────────────────────────────
# Maps filename stem -> (source_key, source_name, column_map)
# column_map: keys are our canonical names, values are possible CSV header variants
SOURCE_REGISTRY = {
    "pff_2026": {
        "source_key":  "pff",
        "source_name": "Pro Football Focus",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name", "player", "name"],
            "position":   ["Position", "Pos", "position", "pos"],
            "ovr_rank":   ["Rank", "RNK", "RK", "rank", "rnk", "rk"],
            "school":     ["School", "College", "school", "college", "Team"],
            "grade":      ["Grade", "grade", "Score"],
            "pos_rank":   ["POS Rank", "Pos Rank", "pos_rank"],
        }
    },
    "ras_2026": {
        "source_key":  "ras",
        "source_name": "Relative Athletic Score",
        "source_type": "ras",
        "cols": {
            "name":       ["Name", "Player", "name", "player"],
            "position":   ["Pos", "Position", "pos", "position"],
            "school":     ["College", "School", "college", "school"],
            "year":       ["Year", "year"],
            "ras_score":  ["RAS", "ras", "RAS Score"],
            # RAS is ranked by score desc — we derive ovr_rank from row order
        }
    },
    "espn_2026": {
        "source_key":  "espn",
        "source_name": "ESPN",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
    "cbssports_2026": {
        "source_key":  "cbs",
        "source_name": "CBS Sports",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
    "nytimes_2026": {
        "source_key":  "nyt",
        "source_name": "New York Times",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
        }
    },
    "thedraftnetwork_2026": {
        "source_key":  "draftnetwork",
        "source_name": "The Draft Network",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
    "theringer_2026": {
        "source_key":  "ringer",
        "source_name": "The Ringer",
        "source_type": "ranking",
        "split_pos_school": True,   # "Position, School" in one column
        "cols": {
            "name":       ["Player", "Name"],
            "pos_school": ["Position, School", "Pos, School", "Info"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "grade":      ["Grade"],
        }
    },
    "tankathon_2026": {
        "source_key":  "tankathon",
        "source_name": "Tankathon",
        "source_type": "ranking",
        "split_pos_school": True,   # "Position, School" in one column
        "cols": {
            "name":       ["Player", "Name"],
            "pos_school": ["Position, School", "Pos, School", "Info"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
        }
    },
    "nfldraftbuzz_2026_v2": {
        "source_key":  "nfldraftbuzz",
        "source_name": "NFL Draft Buzz",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
    "pfsn_2026": {
        "source_key":  "pfsn",
        "source_name": "PFSN",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
    "jfosterfilm_2026": {
        "source_key":  "jfosterfilm",
        "source_name": "JFosterFilm",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
    "bnbfootball_2026": {
        "source_key":  "bnbfootball",
        "source_name": "BnB Football",
        "source_type": "ranking",
        "cols": {
            "name":       ["Player", "Name"],
            "position":   ["Position", "Pos"],
            "ovr_rank":   ["Rank", "RNK", "RK"],
            "school":     ["School", "College"],
            "grade":      ["Grade"],
        }
    },
}

# ── DB helpers ───────────────────────────────────────────────

def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def find_col(headers: list[str], candidates: list[str]) -> Optional[str]:
    """Case-insensitive column header lookup."""
    h_lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in h_lower:
            return h_lower[c.lower()]
    return None

def make_prospect_key(full_name: str, position: str, year: int) -> str:
    """Stable slug key: 'cam-ward-qb-2026'"""
    _, nk = name_norm_and_key(full_name)
    pos = re.sub(r"[^a-z0-9]", "", position.lower())
    return f"{nk}-{pos}-{year}"

def row_hash(source_key: str, raw_name: str, season: int) -> str:
    s = f"{source_key}|{raw_name.lower().strip()}|{season}"
    return hashlib.sha1(s.encode()).hexdigest()[:16]

def split_pos_school(val: str) -> tuple[str, str]:
    """Split 'CB, Ohio State' or 'CB / Ohio State' into (pos, school)."""
    for sep in [",", "/", "|", " - "]:
        if sep in val:
            parts = val.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return val.strip(), ""

# ── Source bootstrap ─────────────────────────────────────────

def bootstrap_sources(conn: sqlite3.Connection):
    """Insert all known sources into the sources table (additive, idempotent)."""
    for stem, cfg in SOURCE_REGISTRY.items():
        conn.execute("""
            INSERT OR IGNORE INTO sources
              (source_name, source_type, is_active)
            VALUES (?, ?, 1)
        """, (stem, cfg["source_type"]))
    conn.commit()
    print("  Sources bootstrapped.")

# ── CSV ingest ───────────────────────────────────────────────

def ingest_csv(conn: sqlite3.Connection, csv_path: Path, source_stem: str):
    cfg = SOURCE_REGISTRY.get(source_stem)
    if not cfg:
        print(f"  [WARN] No registry entry for '{source_stem}' — skipping.")
        return

    source_key = cfg["source_key"]
    split_combined = cfg.get("split_pos_school", False)

    # Get source_id — look up by file stem (source_name in production DB)
    row = conn.execute(
        "SELECT source_id FROM sources WHERE source_name = ?", (source_stem,)
    ).fetchone()
    if not row:
        print(f"  [ERROR] Source '{source_stem}' not found in DB. Run bootstrap first.")
        return
    source_id = row["source_id"]

    season_id = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?", (DRAFT_YEAR,)
    ).fetchone()["season_id"]

    print(f"  Ingesting {csv_path.name} -> source_id={source_id} ({source_key})")

    inserted_players = 0
    inserted_rankings = 0
    skipped = 0
    now = datetime.utcnow().isoformat()

    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        cols = cfg["cols"]

        # Resolve column names
        name_col     = find_col(headers, cols.get("name", []))
        pos_col      = find_col(headers, cols.get("position", []))
        school_col   = find_col(headers, cols.get("school", []))
        rank_col     = find_col(headers, cols.get("ovr_rank", []))
        pos_rank_col = find_col(headers, cols.get("pos_rank", []))
        grade_col    = find_col(headers, cols.get("grade", []))
        ras_col      = find_col(headers, cols.get("ras_score", []))
        pos_school_col = find_col(headers, cols.get("pos_school", [])) if split_combined else None
        year_col     = find_col(headers, cols.get("year", []))

        if not name_col:
            print(f"  [ERROR] Cannot find name column in {csv_path.name}. Headers: {headers}")
            return

        for row_num, row in enumerate(reader, start=2):
            raw_name = (row.get(name_col) or "").strip()
            if not raw_name:
                continue

            # ── Position + School ────────────────────────────
            raw_pos = ""
            raw_school = ""

            if split_combined and pos_school_col:
                combined = (row.get(pos_school_col) or "").strip()
                raw_pos, raw_school = split_pos_school(combined)
            else:
                raw_pos    = (row.get(pos_col) or "").strip() if pos_col else ""
                raw_school = (row.get(school_col) or "").strip() if school_col else ""

            # ── Normalize ────────────────────────────────────
            clean_name = _strip_leading_position_prefix(raw_name)
            base_name, suffix = strip_suffix(clean_name)
            _, name_key = name_norm_and_key(raw_name)

            norm_pos = normalize_position(raw_pos)
            pos_canonical = norm_pos.canonical
            pos_group     = norm_pos.group
            school_norm   = normalize_school_raw(raw_school)
            school_k      = school_key(raw_school) or "unknown"

            # ── Ranks / scores ───────────────────────────────
            def safe_int(v):
                try: return int(str(v).strip().replace(",", ""))
                except: return None
            def safe_float(v):
                try: return float(str(v).strip().replace(",", ""))
                except: return None

            # RAS source: rank by row order (already sorted high→low by RAS score)
            if source_key == "ras":
                ovr_rank = row_num - 1   # row 2 = rank 1
            else:
                ovr_rank = safe_int(row.get(rank_col)) if rank_col else None

            pos_rank  = safe_int(row.get(pos_rank_col)) if pos_rank_col else None
            grade     = safe_float(row.get(grade_col)) if grade_col else None
            ras_score = safe_float(row.get(ras_col)) if ras_col else None

            # Store all extra columns in raw_json
            raw_json = json.dumps({k: row[k] for k in row if k not in [
                name_col, pos_col, school_col, rank_col,
                pos_rank_col, grade_col, ras_col
            ]})

            # ── source_player_key (stable hash) ─────────────
            sp_key = row_hash(source_key, raw_name, DRAFT_YEAR)

            # ── Upsert source_player ─────────────────────────
            conn.execute("""
                INSERT OR IGNORE INTO source_players
                  (source_id, season_id, source_player_key,
                   raw_full_name, raw_school, raw_position,
                   raw_class_year, raw_json, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_id, season_id, sp_key,
                raw_name, school_norm, raw_pos,
                safe_int(row.get(year_col)) if year_col else None,
                raw_json, now
            ))
            inserted_players += 1

            sp_id = conn.execute(
                "SELECT source_player_id FROM source_players WHERE source_player_key = ? AND source_id = ?",
                (sp_key, source_id)
            ).fetchone()["source_player_id"]

            # ── Upsert/resolve canonical prospect ────────────
            # Try exact match on name_key + position_group
            # If no match, insert as new prospect (map can be reviewed later)
            prospect_key = make_prospect_key(clean_name, pos_canonical, DRAFT_YEAR)

            # Check if prospect exists (by key)
            existing = conn.execute(
                "SELECT prospect_id FROM prospects WHERE prospect_key = ?",
                (prospect_key,)
            ).fetchone()

            if not existing:
                # Also try fuzzy: same name_key + same position_group
                fuzzy = conn.execute("""
                    SELECT prospect_id, prospect_key FROM prospects
                    WHERE prospect_key LIKE ?
                    AND position_group = ?
                    AND season_id = ?
                """, (f"%-{name_key}-%", pos_group, season_id)).fetchone()

                if fuzzy:
                    prospect_id = fuzzy["prospect_id"]
                    match_method = "fuzzy"
                    match_score  = 0.90
                else:
                    # Insert new canonical prospect
                    parts = base_name.strip().split(" ", 1)
                    first = parts[0] if parts else ""
                    last  = parts[1] if len(parts) > 1 else ""

                    conn.execute("""
                        INSERT OR IGNORE INTO prospects
                          (season_id, prospect_key, first_name, last_name,
                           full_name, display_name, suffix,
                           position_group, position_raw,
                           school_canonical,
                           created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        season_id, prospect_key,
                        first, last,
                        base_name, base_name, suffix,
                        pos_group, pos_canonical,
                        school_norm or "Unknown",
                        now, now
                    ))
                    # Look up by key first; fall back to composite key if INSERT was ignored
                    r = conn.execute(
                        "SELECT prospect_id FROM prospects WHERE prospect_key = ?",
                        (prospect_key,)
                    ).fetchone()
                    if not r:
                        r = conn.execute("""
                            SELECT prospect_id FROM prospects
                            WHERE season_id = ? AND full_name = ?
                              AND school_canonical = ? AND position_group = ?
                        """, (season_id, base_name, school_norm or "Unknown", pos_group)
                        ).fetchone()
                    if not r:
                        skipped += 1
                        continue
                    prospect_id  = r["prospect_id"]
                    match_method = "exact"
                    match_score  = 1.0
            else:
                prospect_id  = existing["prospect_id"]
                match_method = "exact"
                match_score  = 1.0

            # ── source_player_map ────────────────────────────
            conn.execute("""
                INSERT OR IGNORE INTO source_player_map
                  (source_player_id, prospect_id,
                   match_method, match_score, reviewed)
                VALUES (?, ?, ?, ?, 0)
            """, (sp_id, prospect_id, match_method, match_score))

            # ── source_rankings ──────────────────────────────
            conn.execute("""
                INSERT OR REPLACE INTO source_rankings
                  (source_id, season_id, source_player_id,
                   overall_rank, position_rank, position_raw,
                   grade, ranking_date, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_id, season_id, sp_id,
                ovr_rank, pos_rank, raw_pos,
                grade,
                datetime.utcnow().date().isoformat(),
                now
            ))

            # ── RAS special: upsert into ras table ───────────
            if source_key == "ras" and ras_score is not None:
                conn.execute("""
                    INSERT OR REPLACE INTO ras
                      (prospect_id, ras_total, source_id, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (prospect_id, ras_score, source_id, now))

            inserted_rankings += 1

    conn.commit()

    conn.commit()

    print(f"    Players staged:   {inserted_players}")
    print(f"    Rankings stored:  {inserted_rankings}")
    print(f"    Skipped:          {skipped}")


# ── Consensus engine ─────────────────────────────────────────

def compute_consensus(conn: sqlite3.Connection):
    """
    Recompute consensus_rankings for all prospects from all active sources.
    Deterministic. Safe to rerun — REPLACE semantics.
    """
    print("\n  Computing consensus rankings...")

    season_id = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?", (DRAFT_YEAR,)
    ).fetchone()["season_id"]

    active_count = conn.execute(
        "SELECT COUNT(*) as n FROM sources WHERE is_active = 1"
    ).fetchone()["n"]

    # Get all prospects with at least one active source ranking
    prospects_with_rankings = conn.execute("""
        SELECT DISTINCT spm.prospect_id
        FROM source_player_map spm
        JOIN source_rankings sr ON sr.source_player_id = spm.source_player_id
        JOIN sources s ON s.source_id = sr.source_id
        WHERE s.is_active = 1
    """).fetchall()

    updated = 0
    now = datetime.utcnow().isoformat()

    for prow in prospects_with_rankings:
        pid = prow["prospect_id"]

        ranks = conn.execute("""
            SELECT sr.overall_rank, sr.position_rank
            FROM source_rankings sr
            JOIN source_player_map spm ON spm.source_player_id = sr.source_player_id
            JOIN sources s ON s.source_id = sr.source_id
            WHERE spm.prospect_id = ?
              AND s.is_active = 1
              AND sr.overall_rank IS NOT NULL
        """, (pid,)).fetchall()

        if not ranks:
            continue

        ovr = [r["overall_rank"] for r in ranks if r["overall_rank"] is not None]
        pos = [r["position_rank"] for r in ranks if r["position_rank"] is not None]

        def median(lst):
            if not lst: return None
            s = sorted(lst)
            n = len(s)
            mid = n // 2
            return s[mid] if n % 2 else (s[mid-1] + s[mid]) / 2

        def stddev(lst):
            if len(lst) < 2: return None
            mean = sum(lst) / len(lst)
            return (sum((x - mean) ** 2 for x in lst) / (len(lst) - 1)) ** 0.5

        def rank_to_round(r):
            if r is None: return None
            if r <= 32:  return 1
            if r <= 64:  return 2
            if r <= 96:  return 3
            if r <= 136: return 4
            if r <= 176: return 5
            if r <= 220: return 6
            return 7

        def tier_from_rank(r):
            if r is None: return None
            if r <= 10:  return "R1 Early"
            if r <= 20:  return "R1 Mid"
            if r <= 32:  return "R1 Late"
            if r <= 64:  return "Day 2 Early"
            if r <= 105: return "Day 2 Late"
            if r <= 220: return "Day 3"
            return "UDFA"

        avg_ovr    = round(sum(ovr) / len(ovr), 1) if ovr else None
        med_ovr    = median(ovr)
        med_round  = rank_to_round(med_ovr)
        avg_pos    = round(sum(pos) / len(pos), 1) if pos else None
        med_pos    = median(pos)

        conn.execute("""
            INSERT OR REPLACE INTO consensus_rankings
              (prospect_id, season_id, computed_at,
               source_count, coverage_pct,
               avg_ovr_rank, median_ovr_rank,
               min_ovr_rank, max_ovr_rank, rank_std_dev,
               avg_pos_rank, median_pos_rank,
               median_draft_round, consensus_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pid, season_id, now,
            len(ovr),
            round(len(ovr) / active_count, 3) if active_count else 0,
            avg_ovr, med_ovr,
            min(ovr) if ovr else None, max(ovr) if ovr else None,
            round(stddev(ovr), 2) if stddev(ovr) is not None else None,
            avg_pos, med_pos,
            med_round, tier_from_rank(med_ovr)
        ))
        updated += 1

    conn.commit()
    print(f"  Consensus updated for {updated} prospects ({active_count} active sources).")


# ── Divergence engine ────────────────────────────────────────

def compute_divergence(conn: sqlite3.Connection):
    """
    Compute divergence between APEX composite and consensus implied score.
    Divergence score = APEX composite - consensus_implied_score
    consensus_implied_score = linear transform: rank 1 → 100, rank 250 → 0
    """
    print("\n  Computing divergence flags...")

    season_id = conn.execute(
        "SELECT season_id FROM seasons WHERE draft_year = ?", (DRAFT_YEAR,)
    ).fetchone()["season_id"]

    def rank_to_implied_score(rank):
        """Convert consensus rank to an implied 0-100 score for comparison."""
        if rank is None: return None
        return max(0, round(100 - (rank - 1) * (100 / 250), 1))

    def rounds_diff(apex_capital, consensus_round):
        """Parse APEX capital string to a round number for comparison."""
        if not apex_capital or consensus_round is None:
            return None
        cap = apex_capital.lower()
        if "top 5" in cap or "picks 1" in cap:
            apex_round = 1
        elif "11-32" in cap or "r1" in cap or "round 1" in cap:
            apex_round = 1
        elif "early r2" in cap or "r1 late" in cap:
            apex_round = 1.5
        elif "r2" in cap or "round 2" in cap or "day 2" in cap:
            apex_round = 2
        elif "r3" in cap or "round 3" in cap:
            apex_round = 3
        else:
            return None
        return round(consensus_round - apex_round, 1)

    scored = conn.execute("""
        SELECT a.prospect_id, a.apex_composite, a.apex_tier, a.capital_adjusted,
               c.median_ovr_rank, c.consensus_tier, c.median_draft_round
        FROM apex_scores a
        JOIN consensus_rankings c ON c.prospect_id = a.prospect_id
        WHERE a.model_version = ?
    """, (MODEL_VERSION,)).fetchall()

    updated = 0
    now = datetime.utcnow().isoformat()

    for row in scored:
        pid             = row["prospect_id"]
        apex_comp       = row["apex_composite"]
        cons_rank       = row["median_ovr_rank"]
        cons_round      = row["median_draft_round"]
        cons_implied    = rank_to_implied_score(cons_rank)
        rd              = rounds_diff(row["capital_adjusted"], cons_round)

        if apex_comp is None or cons_implied is None:
            continue

        diff = round(apex_comp - cons_implied, 1)

        if abs(diff) >= 15:
            flag = "APEX HIGH" if diff > 0 else "APEX LOW"
            mag  = "MAJOR"
        elif abs(diff) >= 8:
            flag = "APEX HIGH" if diff > 0 else "APEX LOW"
            mag  = "MODERATE"
        elif abs(diff) >= 3:
            flag = "APEX HIGH" if diff > 0 else "APEX LOW"
            mag  = "MINOR"
        else:
            flag = "ALIGNED"
            mag  = "MINOR"

        favors = 1 if diff > 0 else (-1 if diff < 0 else 0)

        conn.execute("""
            INSERT OR REPLACE INTO divergence_flags
              (prospect_id, season_id, computed_at, model_version,
               apex_composite, apex_tier, apex_capital,
               consensus_ovr_rank, consensus_tier, consensus_round,
               divergence_score, rounds_diff,
               divergence_flag, divergence_mag, apex_favors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pid, season_id, now, MODEL_VERSION,
            apex_comp, row["apex_tier"], row["capital_adjusted"],
            cons_rank, row["consensus_tier"], cons_round,
            diff, rd, flag, mag, favors
        ))
        updated += 1

    conn.commit()
    print(f"  Divergence flags computed for {updated} prospects.")
    print(f"    APEX HIGH (MAJOR/MODERATE): " + str(conn.execute("""
        SELECT COUNT(*) FROM divergence_flags
        WHERE divergence_flag='APEX HIGH' AND divergence_mag IN ('MAJOR','MODERATE')
    """).fetchone()[0]))
    print(f"    APEX LOW  (MAJOR/MODERATE): " + str(conn.execute("""
        SELECT COUNT(*) FROM divergence_flags
        WHERE divergence_flag='APEX LOW' AND divergence_mag IN ('MAJOR','MODERATE')
    """).fetchone()[0]))
    print(f"    ALIGNED:                    " + str(conn.execute("""
        SELECT COUNT(*) FROM divergence_flags WHERE divergence_flag='ALIGNED'
    """).fetchone()[0]))


# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DraftOS Ingest Pipeline")
    parser.add_argument("--db",         default=str(DB_PATH), help="Path to draftos.db")
    parser.add_argument("--source",     help="Source stem (e.g. pff_2026) or 'all'")
    parser.add_argument("--file",       help="Path to CSV file")
    parser.add_argument("--dir",        help="Directory containing all CSVs (used with --source all)")
    parser.add_argument("--consensus",  action="store_true", help="Recompute consensus rankings")
    parser.add_argument("--divergence", action="store_true", help="Recompute divergence flags")
    parser.add_argument("--bootstrap",  action="store_true", help="Bootstrap sources table only")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERROR] DB not found at {db_path}")
        print("  Run migrations first: python migrate.py")
        sys.exit(1)

    conn = get_conn(db_path)

    if args.bootstrap:
        print("\n=== Bootstrapping sources ===")
        bootstrap_sources(conn)

    elif args.source == "all" and args.dir:
        csv_dir = Path(args.dir)
        bootstrap_sources(conn)
        csvs = sorted(csv_dir.glob("*.csv"))
        print(f"\n=== Ingesting {len(csvs)} CSV files from {csv_dir} ===")
        for csv_file in csvs:
            stem = csv_file.stem
            if stem in SOURCE_REGISTRY:
                print(f"\n--- {stem} ---")
                ingest_csv(conn, csv_file, stem)
            else:
                print(f"  [SKIP] No registry entry for '{stem}'")
        print("\n=== Running consensus engine ===")
        compute_consensus(conn)

    elif args.source and args.file:
        bootstrap_sources(conn)
        print(f"\n=== Ingesting {args.source} ===")
        ingest_csv(conn, Path(args.file), args.source)
        print("\n=== Running consensus engine ===")
        compute_consensus(conn)

    elif args.consensus:
        compute_consensus(conn)

    elif args.divergence:
        compute_divergence(conn)

    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    main()