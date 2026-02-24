from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect

BOOTSTRAP_NAME = "0001_schema_v1"

MIGRATION_NAME_RE = re.compile(r"^\d{4}_[a-z0-9][a-z0-9_]*$", re.IGNORECASE)


def ensure_meta_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta_migrations (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          applied_at TEXT NOT NULL
        );
        """
    )


def is_applied(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM meta_migrations WHERE name = ?", (name,)).fetchone()
    return row is not None


def stamp(conn, name: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO meta_migrations(name, applied_at) VALUES (?, ?)", (name, ts))


def _backup_db() -> Path:
    """
    Backup DB before any risky operation (migration).
    Stored under data/exports/backups as a timestamped copy.
    """
    if not PATHS.db.exists():
        return PATHS.db

    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.{ts}"
    shutil.copy2(PATHS.db, backup_path)
    return backup_path


@dataclass(frozen=True)
class Migration:
    name: str
    path: Path


def _discover_migrations(migrations_dir: Path) -> list[Migration]:
    if not migrations_dir.exists():
        return []

    files = sorted([p for p in migrations_dir.glob("*.sql") if p.is_file()])
    migrations: list[Migration] = []

    for p in files:
        name = p.stem

        # Hard guardrail: every migration must be NNNN_description.sql
        if not MIGRATION_NAME_RE.match(name):
            raise RuntimeError(
                f"Invalid migration filename: {p.name}\n"
                f"Expected pattern: NNNN_description.sql (e.g. 0005_add_table_x.sql)\n"
                f"Refusing to run to avoid stamping bad migration IDs."
            )

        migrations.append(Migration(name=name, path=p))

    return migrations


def _apply_sql_file(conn, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    conn.executescript(sql)


def migrate() -> None:
    PATHS.db.parent.mkdir(parents=True, exist_ok=True)

    schema_path = PATHS.root / "draftos" / "db" / "schema.sql"
    migrations_dir = PATHS.root / "draftos" / "db" / "migrations"

    with connect() as conn:
        ensure_meta_table(conn)

        # Bootstrap schema snapshot once.
        if not is_applied(conn, BOOTSTRAP_NAME):
            _backup_db()
            _apply_sql_file(conn, schema_path)
            stamp(conn, BOOTSTRAP_NAME)
            conn.commit()
            print(f"APPLY {BOOTSTRAP_NAME}")
        else:
            print(f"SKIP  {BOOTSTRAP_NAME}")

        # Apply additive migrations in order.
        for mig in _discover_migrations(migrations_dir):
            if is_applied(conn, mig.name):
                print(f"SKIP  {mig.name}")
                continue

            _backup_db()
            _apply_sql_file(conn, mig.path)
            stamp(conn, mig.name)
            conn.commit()
            print(f"APPLY {mig.name}")


if __name__ == "__main__":
    migrate()
    print("OK: migrations applied")