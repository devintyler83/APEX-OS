from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as:
#   python scripts/patch_0005_0006_soft_deprecate_nfldraftbuzz.py
#   python -m scripts.patch_0005_0006_soft_deprecate_nfldraftbuzz   (only if scripts is a package)
#
# Running by file path sets sys.path[0] = C:\DraftOS\scripts, which breaks `import draftos`.
# We explicitly add repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.config import PATHS  # noqa: E402

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_path(base_dir: Path, name: str) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{name}.backup.{TS}"


def backup_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    dst = _backup_path(PATHS.exports / "backups", path.name)
    shutil.copy2(path, dst)
    return dst


def backup_db(reason: str) -> Path:
    if not PATHS.db.exists():
        raise FileNotFoundError(f"DB not found: {PATHS.db}")
    dst = PATHS.exports / "backups" / f"draftos.sqlite.backup.{TS}.{reason}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PATHS.db, dst)
    return dst


def write_text_if_changed(path: Path, new_text: str) -> bool:
    old = path.read_text(encoding="utf-8")
    if old == new_text:
        return False
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


def ensure_migration(path: Path, sql: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sql.strip() + "\n", encoding="utf-8", newline="\n")


def patch_schema_sources_block(schema_path: Path) -> bool:
    """
    Update draftos/db/schema.sql so fresh bootstrap includes:
      is_active INTEGER NOT NULL DEFAULT 1
      superseded_by_source_id INTEGER
    """
    text = schema_path.read_text(encoding="utf-8")

    if "is_active" in text and "superseded_by_source_id" in text:
        return False

    m = re.search(
        r"(CREATE TABLE IF NOT EXISTS sources\s*\(\s*[\s\S]*?\n\);)",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise RuntimeError("Could not locate 'CREATE TABLE IF NOT EXISTS sources' block in schema.sql")

    block = m.group(1)
    if "is_active" in block or "superseded_by_source_id" in block:
        return False

    insert = (
        "  is_active INTEGER NOT NULL DEFAULT 1,\n"
        "  superseded_by_source_id INTEGER,\n"
    )

    # Insert right before the last ')' in the sources table block.
    patched_block = re.sub(r"\n\);\s*$", "\n" + insert + ");", block, flags=re.IGNORECASE)

    new_text = text.replace(block, patched_block)
    return write_text_if_changed(schema_path, new_text)


def patch_doctor_print_active(doctor_path: Path) -> bool:
    """
    Add sources_active output in doctor.
    """
    text = doctor_path.read_text(encoding="utf-8")

    if "sources_active" in text:
        return False

    anchor = 'for t in ["sources", "seasons", "prospects", "source_players", "source_rankings", "models"]:'
    if anchor not in text:
        raise RuntimeError("doctor.py structure not recognized. Expected table-count loop anchor.")

    needle = 'print(f"{t}: {c}")'
    idx = text.rfind(needle)
    if idx == -1:
        raise RuntimeError("Could not find expected print line in doctor.py.")

    line_end = text.find("\n", idx)
    if line_end == -1:
        line_end = len(text)

    insertion = (
        "\n\n        # Active sources (post-migration 0005)\n"
        "        cols = {r[\"name\"] for r in conn.execute(\"PRAGMA table_info(sources);\").fetchall()}\n"
        "        if \"is_active\" in cols:\n"
        "            active = conn.execute(\"SELECT COUNT(*) AS n FROM sources WHERE is_active = 1;\").fetchone()[\"n\"]\n"
        "            print(f\"sources_active: {active}\")\n"
    )

    new_text = text[: line_end + 1] + insertion + text[line_end + 1 :]
    return write_text_if_changed(doctor_path, new_text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", type=int, default=0, help="1=apply changes; 0=preview only")
    args = ap.parse_args()
    apply = bool(args.apply)

    schema_path = PATHS.root / "draftos" / "db" / "schema.sql"
    migrations_dir = PATHS.root / "draftos" / "db" / "migrations"
    doctor_path = PATHS.root / "scripts" / "doctor.py"

    mig_0005 = migrations_dir / "0005_sources_active_cols.sql"
    mig_0006 = migrations_dir / "0006_deprecate_nfldraftbuzz_old.sql"

    sql_0005 = """
    -- Add soft-deprecation controls for sources.
    -- Additive, idempotent.
    ALTER TABLE sources ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE sources ADD COLUMN superseded_by_source_id INTEGER;
    """

    sql_0006 = """
    -- Soft-deprecate the older NFLDraftBuzz ingest if both exist.
    -- Idempotent: safe to re-run.
    -- Policy:
    --   - NFLDraftBuzz_v2 is the active source
    --   - NFLDraftBuzz (old) becomes inactive and points to v2
    UPDATE sources
    SET is_active = 1
    WHERE source_name IN ('PFF', 'NFLDraftBuzz_v2');

    UPDATE sources
    SET is_active = 0,
        superseded_by_source_id = (
          SELECT s2.source_id FROM sources s2 WHERE s2.source_name = 'NFLDraftBuzz_v2'
        )
    WHERE source_name = 'NFLDraftBuzz'
      AND EXISTS (SELECT 1 FROM sources s2 WHERE s2.source_name = 'NFLDraftBuzz_v2');
    """

    print(f"ROOT: {PATHS.root}")
    print(f"DB:   {PATHS.db}")

    if not apply:
        print("\nPREVIEW ONLY (no changes applied). Re-run with --apply 1 to execute.\n")
        print(f"Would create migrations:\n  {mig_0005}\n  {mig_0006}")
        print(f"Would patch files:\n  {schema_path}\n  {doctor_path}")
        return

    # Risky ops: DB backup first
    bp = backup_db("soft_deprecate_sources")
    print(f"DB BACKUP: {bp}")

    # Backup files
    bp_schema = backup_file(schema_path)
    bp_doctor = backup_file(doctor_path)
    print(f"FILE BACKUP: {bp_schema}")
    print(f"FILE BACKUP: {bp_doctor}")

    ensure_migration(mig_0005, sql_0005)
    ensure_migration(mig_0006, sql_0006)
    print(f"MIGRATIONS: ensured {mig_0005.name}, {mig_0006.name}")

    changed_schema = patch_schema_sources_block(schema_path)
    print(f"PATCH schema.sql: {'CHANGED' if changed_schema else 'NO CHANGE'}")

    changed_doctor = patch_doctor_print_active(doctor_path)
    print(f"PATCH doctor.py: {'CHANGED' if changed_doctor else 'NO CHANGE'}")

    print("\nNEXT:")
    print("  python -m draftos.db.migrate")
    print("  python -m scripts.doctor")


if __name__ == "__main__":
    main()