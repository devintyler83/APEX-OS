#!/usr/bin/env python3
"""
DraftOS — Migration 0049 + BigBoard Measurables Ingest
Rebuilds prospect_measurables with UNIQUE(prospect_id, season_id, source).
Ingests BigBoard_Size_Testing_Scores_4-23-26.csv as source='bigboard_2026'.
Session 77.
"""
from __future__ import annotations
import argparse, csv, os, re, shutil, sys, unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from draftos.db.connect import connect

BIGBOARD_CSV = r"C:\DraftOS\draftos\ingest\rankings\BigBoard_Size_Testing_Scores_4-23-26.csv"
AUDIT_DIR    = r"C:\DraftOS\data\edge\audit_reports"
AUDIT_PATH   = os.path.join(AUDIT_DIR, "measurables_ingest_0049.txt")
BACKUP_DIR   = r"C:\DraftOS\data\exports\backups"
DB_PATH      = r"C:\DraftOS\data\edge\draftos.sqlite"
MIGRATION    = "0049"
SOURCE       = "bigboard_2026"
SEASON_YEAR  = 2026

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def normalize(name: str) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.strip().lower()
    name = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", name)
    name = re.sub(r"[.\-]", " ", name)
    return re.sub(r"\s+", " ", name).strip()

def _f(val):
    if val is None or str(val).strip() in ("", "nan", "NaN", "N/A"):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def _i(val):
    f = _f(val)
    return int(round(f)) if f is not None else None

def backup(apply: bool):
    if not apply:
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = os.path.join(BACKUP_DIR, f"draftos_{ts}_pre_migration_0049.sqlite")
    shutil.copy2(DB_PATH, dst)
    print(f"Backup: {dst}")

MIGRATION_NAME = "0049_bigboard_measurables"

def migration_applied(conn) -> bool:
    row = conn.execute(
        "SELECT name FROM meta_migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None

def run_migration(conn, apply: bool):
    if migration_applied(conn):
        print(f"Migration {MIGRATION} already applied — skipping rebuild.")
        return

    pre_count = conn.execute(
        "SELECT COUNT(*) FROM prospect_measurables"
    ).fetchone()[0]
    print(f"Pre-migration row count: {pre_count}")

    if not apply:
        print(f"[DRY RUN] Would rebuild prospect_measurables with UNIQUE(prospect_id, season_id, source)")
        return

    # Columns present in both old and new schema — excludes jff_ovr_rank, jff_pos_rank,
    # consensus_rank (jfosterfilm-only columns dropped in new schema).
    COPY_COLS = (
        "prospect_id, season_id, source, age, height_in, weight_lbs, "
        "arm_length, wingspan, hand_size, ten_yard_split, forty_yard_dash, "
        "shuttle, three_cone, vertical_jump, broad_jump, "
        "ath_score, size_score, speed_score, acc_score, agi_score, prod_score, "
        "created_at, updated_at"
    )

    conn.executescript(f"""
        PRAGMA foreign_keys = OFF;

        ALTER TABLE prospect_measurables RENAME TO prospect_measurables_old_0049;

        CREATE TABLE prospect_measurables (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id     INTEGER NOT NULL REFERENCES prospects(prospect_id),
            season_id       INTEGER NOT NULL DEFAULT 1,
            source          TEXT    NOT NULL DEFAULT 'jfosterfilm_2026',
            age             REAL,
            height_in       REAL,
            weight_lbs      INTEGER,
            arm_length      REAL,
            wingspan        REAL,
            hand_size       REAL,
            ten_yard_split  REAL,
            forty_yard_dash REAL,
            shuttle         REAL,
            three_cone      REAL,
            vertical_jump   REAL,
            broad_jump      REAL,
            ath_score       REAL,
            size_score      REAL,
            speed_score     REAL,
            acc_score       REAL,
            agi_score       REAL,
            prod_score      REAL,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(prospect_id, season_id, source)
        );

        CREATE INDEX IF NOT EXISTS idx_measurables_pid
            ON prospect_measurables(prospect_id);

        INSERT INTO prospect_measurables ({COPY_COLS})
        SELECT {COPY_COLS} FROM prospect_measurables_old_0049;

        DROP TABLE prospect_measurables_old_0049;

        PRAGMA foreign_keys = ON;
    """)

    post_count = conn.execute(
        "SELECT COUNT(*) FROM prospect_measurables"
    ).fetchone()[0]
    print(f"Post-migration row count: {post_count}")

    if post_count != pre_count:
        raise SystemExit(
            f"FAIL: row count mismatch after migration. "
            f"pre={pre_count} post={post_count}. Rolling back."
        )

    conn.execute(
        "INSERT INTO meta_migrations (name, applied_at) VALUES (?, datetime('now'))",
        (MIGRATION_NAME,)
    )
    conn.commit()
    print(f"Migration {MIGRATION} applied and verified.")

def load_bigboard():
    rows = []
    with open(BIGBOARD_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append({
                "name":    row["PLAYER"].strip(),
                "norm":    normalize(row["PLAYER"]),
                "age":     _f(row.get("AGE")),
                "height":  _f(row.get("HEIGHT")),
                "weight":  _i(row.get("WEIGHT")),
                "arm":     _f(row.get("ARM")),
                "wing":    _f(row.get("WING")),
                "hand":    _f(row.get("HAND")),
                "ten":     _f(row.get("10Y")),
                "forty":   _f(row.get("40YD")),
                "shuttle": _f(row.get("SHUTTLE")),
                "cone":    _f(row.get("3 CONE")),
                "vert":    _f(row.get("VERT")),
                "broad":   _f(row.get("BROAD")),
                "ath":     _f(row.get("ATH")),
                "size":    _f(row.get("SIZE")),
                "speed":   _f(row.get("SPEED")),
                "acc":     _f(row.get("ACC")),
                "agi":     _f(row.get("AGI")),
                "prod":    _f(row.get("PROD")),
            })
    return rows

def ingest_bigboard(conn, apply: bool, season_id: int):
    bb_rows = load_bigboard()
    print(f"BigBoard CSV loaded: {len(bb_rows)} players")

    prospects = conn.execute(
        "SELECT prospect_id, display_name FROM prospects WHERE season_id=? AND is_active=1",
        (season_id,)
    ).fetchall()
    norm_to_pid = {normalize(p[1] or ""): int(p[0]) for p in prospects if p[1]}

    matched, unmatched = [], []
    for row in bb_rows:
        pid = norm_to_pid.get(row["norm"])
        if pid:
            matched.append({"pid": pid, **row})
        else:
            unmatched.append(row)

    print(f"Matched:   {len(matched)}")
    print(f"Unmatched: {len(unmatched)}")

    if not apply:
        print("\nUnmatched sample (first 20):")
        for r in unmatched[:20]:
            print(f"  {r['name']}")
        return matched, unmatched

    inserted = updated = 0
    for m in matched:
        existing = conn.execute(
            "SELECT id FROM prospect_measurables WHERE prospect_id=? AND season_id=? AND source=?",
            (m["pid"], season_id, SOURCE)
        ).fetchone()

        vals = (
            m["age"], m["height"], m["weight"],
            m["arm"], m["wing"], m["hand"],
            m["ten"], m["forty"], m["shuttle"], m["cone"],
            m["vert"], m["broad"],
            m["ath"], m["size"], m["speed"],
            m["acc"], m["agi"], m["prod"],
            utcnow()
        )

        if existing:
            conn.execute("""
                UPDATE prospect_measurables SET
                    age=?, height_in=?, weight_lbs=?,
                    arm_length=?, wingspan=?, hand_size=?,
                    ten_yard_split=?, forty_yard_dash=?, shuttle=?, three_cone=?,
                    vertical_jump=?, broad_jump=?,
                    ath_score=?, size_score=?, speed_score=?,
                    acc_score=?, agi_score=?, prod_score=?,
                    updated_at=?
                WHERE id=?
            """, (*vals, int(existing[0])))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO prospect_measurables (
                    prospect_id, season_id, source,
                    age, height_in, weight_lbs,
                    arm_length, wingspan, hand_size,
                    ten_yard_split, forty_yard_dash, shuttle, three_cone,
                    vertical_jump, broad_jump,
                    ath_score, size_score, speed_score,
                    acc_score, agi_score, prod_score,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    datetime('now'), datetime('now')
                )
            """, (
                m["pid"], season_id, SOURCE,
                m["age"], m["height"], m["weight"],
                m["arm"], m["wing"], m["hand"],
                m["ten"], m["forty"], m["shuttle"], m["cone"],
                m["vert"], m["broad"],
                m["ath"], m["size"], m["speed"],
                m["acc"], m["agi"], m["prod"]
            ))
            inserted += 1

    conn.commit()
    print(f"Inserted: {inserted} | Updated: {updated}")
    return matched, unmatched

def write_audit(matched, unmatched, apply: bool):
    os.makedirs(AUDIT_DIR, exist_ok=True)
    mode = "APPLY" if apply else "DRY RUN"
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        f.write(f"MEASURABLES INGEST 0049 [{mode}] — {utcnow()}\n\n")
        f.write(f"BigBoard players: {len(matched)+len(unmatched)}\n")
        f.write(f"Matched: {len(matched)} | Unmatched: {len(unmatched)}\n\n")
        f.write("=== UNMATCHED (no DB PID — not ingested) ===\n")
        for r in unmatched:
            f.write(f"  {r['name']}\n")
    print(f"Audit written: {AUDIT_PATH}")

def main(apply: bool):
    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n{'='*60}\nMigration 0049 + BigBoard Ingest [{mode}]\n{'='*60}\n")

    backup(apply)

    with connect() as conn:
        season_id = conn.execute(
            "SELECT season_id FROM seasons WHERE draft_year=?", (SEASON_YEAR,)
        ).fetchone()[0]

        run_migration(conn, apply)
        matched, unmatched = ingest_bigboard(conn, apply, season_id)
        write_audit(matched, unmatched, apply)

    print("\nDone.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    main(apply=bool(args.apply))
