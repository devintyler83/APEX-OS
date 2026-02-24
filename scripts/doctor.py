from __future__ import annotations

# Allow running as:
#   python scripts/doctor.py
#   python -m scripts.doctor
#
# When run as a file path, Python sets sys.path[0] to /scripts which breaks
# `import draftos`. We explicitly add repo root.

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from draftos.db.connect import connect  # noqa: E402
from draftos.config import PATHS  # noqa: E402

REQUIRED_TABLES = [
    "meta_migrations",
    "sources",
    "seasons",
    "prospects",
    "source_players",
    "source_player_map",
    "source_rankings",
    "models",
    "model_outputs",
]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")


def main() -> None:
    print(f"ROOT: {PATHS.root}")
    print(f"DB:   {PATHS.db}")

    _require(PATHS.db.exists(), "DB file does not exist. Run migrate first.")

    with connect() as conn:
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }

        missing = [t for t in REQUIRED_TABLES if t not in tables]
        _require(not missing, f"missing tables: {missing}")

        # Phase 1 invariants (seeded basics)
        season = conn.execute(
            "SELECT season_id FROM seasons WHERE draft_year = ?;",
            (2026,),
        ).fetchone()
        _require(season is not None, "season 2026 not seeded (draft_year=2026)")

        model = conn.execute(
            """
            SELECT m.model_id
            FROM models m
            JOIN seasons s ON s.season_id = m.season_id
            WHERE s.draft_year = ? AND m.model_key = ?;
            """,
            (2026, "v1_default"),
        ).fetchone()
        _require(model is not None, "model v1_default not seeded for 2026")

        for t in ["sources", "seasons", "prospects", "source_players", "source_rankings", "models"]:
            c = conn.execute(f"SELECT COUNT(*) AS n FROM {t};").fetchone()["n"]
            print(f"{t}: {c}")

    print("OK: doctor checks passed")


if __name__ == "__main__":
    main()