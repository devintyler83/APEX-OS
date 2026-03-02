from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "edge" / "draftos.sqlite"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_cmd(args: list[str]) -> str:
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=str(ROOT),
            stderr=subprocess.STDOUT
        )
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        return "N/A"


def list_scripts() -> list[str]:
    scripts = []
    for p in ROOT.rglob("*.py"):
        if ".venv" in str(p):
            continue
        scripts.append(str(p.relative_to(ROOT)))
    return sorted(scripts)


def detect_stubs() -> list[str]:
    stubs = []
    for p in ROOT.rglob("*.py"):
        if ".venv" in str(p):
            continue
        try:
            text = p.read_text(encoding="utf-8")
            if len(text.strip()) < 40:
                stubs.append(str(p.relative_to(ROOT)))
            if "TODO:DEFERRED" in text:
                stubs.append(str(p.relative_to(ROOT)) + " (DEFERRED)")
        except Exception:
            continue
    return sorted(set(stubs))


def main():
    print("=== DRAFTOS SYSTEM SNAPSHOT ===")
    print(f"generated_utc: {utc_now()}")
    print()

    print("## Git")
    print("branch:", git_cmd(["rev-parse", "--abbrev-ref", "HEAD"]))
    print("commit:", git_cmd(["rev-parse", "HEAD"]))
    status = git_cmd(["status", "--porcelain"])
    print("status:", "clean" if not status else status)
    print()

    if not DB_PATH.exists():
        print("ERROR: Database not found:", DB_PATH)
        raise SystemExit(2)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("## Tables")
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    for t in table_names:
        print("-", t)
    print()

    print("## Row Counts (key tables)")
    key_tables = [
        "sources",
        "seasons",
        "prospects",
        "source_players",
        "source_player_map",
        "source_rankings",
        "models",
        "model_outputs",
    ]
    for t in key_tables:
        if t in table_names:
            try:
                count = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"- {t}: {count}")
            except Exception as e:
                print(f"- {t}: ERROR ({e})")
    print()

    print("## Migrations")
    if "meta_migrations" in table_names:
        rows = cursor.execute(
            "SELECT name, applied_at FROM meta_migrations ORDER BY id"
        ).fetchall()
        if rows:
            for name, applied_at in rows:
                print(f"- {name} @ {applied_at}")
        else:
            print("(none)")
    else:
        print("meta_migrations table missing")
    print()

    print("## Active Season")
    if "seasons" in table_names:
        cols = [c[1] for c in cursor.execute("PRAGMA table_info(seasons)").fetchall()]
        if "is_active" in cols:
            active = cursor.execute(
                "SELECT * FROM seasons WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            print(active if active else "(none)")
        else:
            print("no is_active column")
    else:
        print("seasons table missing")
    print()

    print("## Script Inventory")
    for s in list_scripts():
        print("-", s)
    print()

    print("## Stub / Deferred Detection")
    for s in detect_stubs():
        print("-", s)
    print()

    conn.close()
    print("=== END SNAPSHOT ===")


if __name__ == "__main__":
    main()