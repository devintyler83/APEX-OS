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


        # Active sources (post-migration 0005)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sources);").fetchall()}
        if "is_active" in cols:
            active = conn.execute("SELECT COUNT(*) AS n FROM sources WHERE is_active = 1;").fetchone()["n"]
            print(f"sources_active: {active}")

        # Draft Mode checks (migrations 0055–0056)
        views = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view';"
            ).fetchall()
        }

        if "drafted_picks_2026" in tables:
            drafted_n = conn.execute(
                "SELECT COUNT(*) AS n FROM drafted_picks_2026;"
            ).fetchone()["n"]
            print(f"drafted_picks_2026: {drafted_n} rows")

            # No duplicate pick numbers within a season
            dup_picks = conn.execute(
                """
                SELECT COUNT(*) AS n FROM (
                    SELECT season_id, pick_number, COUNT(*) AS c
                    FROM drafted_picks_2026
                    GROUP BY season_id, pick_number
                    HAVING c > 1
                )
                """
            ).fetchone()["n"]
            _require(dup_picks == 0, f"drafted_picks_2026: {dup_picks} duplicate pick_number rows")

            # No duplicate prospect_ids within a season
            dup_pids = conn.execute(
                """
                SELECT COUNT(*) AS n FROM (
                    SELECT season_id, prospect_id, COUNT(*) AS c
                    FROM drafted_picks_2026
                    GROUP BY season_id, prospect_id
                    HAVING c > 1
                )
                """
            ).fetchone()["n"]
            _require(dup_pids == 0, f"drafted_picks_2026: {dup_pids} duplicate prospect_id rows")

            # All season_id values must be 1
            bad_season = conn.execute(
                "SELECT COUNT(*) AS n FROM drafted_picks_2026 WHERE season_id != 1;"
            ).fetchone()["n"]
            _require(bad_season == 0, f"drafted_picks_2026: {bad_season} rows with season_id != 1")

        _require("v_draft_remaining_2026" in views,   "view v_draft_remaining_2026 missing (migration 0056)")
        _require("v_draft_team_board_2026" in views,  "view v_draft_team_board_2026 missing (migration 0056)")

        # PVC archetype weights sanity check
        if "pvc_archetype_weights" in tables:
            w_total = conn.execute(
                "SELECT COUNT(*) AS n FROM pvc_archetype_weights;"
            ).fetchone()["n"]
            w_trusted = conn.execute(
                "SELECT COUNT(*) AS n FROM pvc_archetype_weights WHERE trusted = 1;"
            ).fetchone()["n"]
            w_untrusted = w_total - w_trusted
            _require(w_total >= 60, f"pvc_archetype_weights: only {w_total} rows (expected >=60)")
            print(f"pvc_archetype_weights: {w_total} rows  trusted={w_trusted}  untrusted={w_untrusted}")

            if w_untrusted > 0:
                untrusted_rows = conn.execute(
                    """
                    SELECT position_group, archetype_code, weight, n_contracts, notes
                    FROM pvc_archetype_weights
                    WHERE trusted = 0
                    ORDER BY position_group, archetype_code;
                    """
                ).fetchall()
                for ur in untrusted_rows:
                    note = ur["notes"] or ""
                    print(
                        f"  untrusted: {ur['position_group']}/{ur['archetype_code']}"
                        f"  w={ur['weight']:.3f}  n={ur['n_contracts']}"
                        f"  ({note[:60]})"
                    )

            # Sample join: scored prospects -> weights table
            # ILB/OLB mapped to LB to match normalization in the weights builder.
            sample = conn.execute(
                """
                SELECT p.display_name,
                       p.position_group,
                       substr(a.matched_archetype, 1, instr(a.matched_archetype || ' ', ' ') - 1) AS archetype_code,
                       w.weight,
                       w.trusted
                FROM apex_scores a
                JOIN prospects p ON p.prospect_id = a.prospect_id
                LEFT JOIN pvc_archetype_weights w
                  ON w.position_group = CASE
                       WHEN p.position_group IN ('ILB','OLB') THEN 'LB'
                       ELSE p.position_group
                     END
                 AND w.archetype_code = substr(a.matched_archetype, 1,
                       instr(a.matched_archetype || ' ', ' ') - 1)
                WHERE a.season_id = 1
                  AND a.matched_archetype IS NOT NULL
                  AND p.is_active = 1
                ORDER BY a.apex_composite DESC
                LIMIT 20;
                """
            ).fetchall()

            scored_with_weight = sum(1 for r in sample if r["weight"] is not None)
            scored_without_weight = sum(1 for r in sample if r["weight"] is None)
            print(
                f"pvc_archetype_weights join (top-20 scored sample): "
                f"matched={scored_with_weight}  unmatched={scored_without_weight}"
            )
            if scored_without_weight > 0:
                for r in sample:
                    if r["weight"] is None:
                        print(
                            f"  no weight: {r['display_name']} "
                            f"{r['position_group']}/{r['archetype_code']}"
                        )
        else:
            print("pvc_archetype_weights: table missing (run build_pvc_archetype_weights.py)")

    print("OK: doctor checks passed")


if __name__ == "__main__":
    main()