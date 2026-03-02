# scripts/run_weekly_update.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from draftos.config import PATHS


def run(cmd: list[str]) -> None:
    print("RUN:", " ".join(cmd))
    subprocess.check_call(cmd)


def pymod(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def pyfile(path: Path, *args: str) -> list[str]:
    return [sys.executable, str(path), *args]


def main() -> None:
    root = PATHS.root
    scripts = root / "scripts"
    season = 2026
    model = "v1_default"
    window = 3

    rankings_dir = root / "data" / "imports" / "rankings" / "raw" / str(season)
    if not rankings_dir.exists() or not rankings_dir.is_dir():
        raise SystemExit(f"FAIL: rankings dir not found: {rankings_dir}")
    print(f"OK: rankings dir: {rankings_dir}")

    # 1) STAGING (no DB writes)
    run(pyfile(scripts / "stage_rankings_csv.py", "--dir", str(rankings_dir), "--season", str(season)))

    # 2) INGEST (WRITE)
    run(pyfile(scripts / "ingest_rankings_staged.py", "--season", str(season), "--apply", "1"))

    # 3) BOOTSTRAP (WRITE)
    run(pyfile(scripts / "patch_0007_bootstrap_prospects_2026.py", "--apply", "1"))

    # 4) SOURCE CANONICALIZATION (WRITE)
    run(pymod("scripts.patch_source_canonicalization_2026", "--apply", "1"))

    # 5) CONSENSUS (WRITE)
    run(pyfile(scripts / "build_consensus_2026.py", "--apply", "1"))

    # 6) MODEL OUTPUTS (WRITE)
    run(pyfile(scripts / "build_model_outputs_v1_default_2026.py", "--apply", "1"))

    # 7) SNAPSHOT (WRITE)
    run(pymod("scripts.snapshot_board", "--season", str(season), "--model", model, "--apply", "1"))

    # 8) SNAPSHOT COVERAGE (WRITE)
    run(pymod("scripts.compute_snapshot_coverage", "--season", str(season), "--model", model, "--apply", "1"))

    # 9) SNAPSHOT METRICS (WRITE)
    run(
        pymod(
            "scripts.compute_snapshot_metrics",
            "--season",
            str(season),
            "--model",
            model,
            "--window",
            str(window),
            "--apply",
            "1",
        )
    )

    # 10) SOURCE SNAPSHOT METRICS (WRITE)
    run(
        pymod(
            "scripts.compute_source_snapshot_metrics",
            "--season",
            str(season),
            "--model",
            model,
            "--stale-days",
            "7",
            "--coverage-min",
            "0.50",
            "--mad-noisy",
            "50.0",
            "--apply",
            "1",
        )
    )

    # 11) SNAPSHOT CONFIDENCE (WRITE)
    run(
        pymod(
            "scripts.compute_snapshot_confidence",
            "--season",
            str(season),
            "--model",
            model,
            "--apply",
            "1",
        )
    )

    # 11.5) SNAPSHOT INTEGRITY ASSERTION (read-only)
    # If mismatch exists, attempt deterministic SNAPSHOTS-layer repair once, then re-verify.
    try:
        run(pymod("scripts.verify_snapshot_integrity", "--season", str(season), "--model", model))
    except subprocess.CalledProcessError:
        print("WARN: snapshot integrity check failed, attempting deterministic repair...")
        run(pymod("scripts.repair_snapshot_orphans", "--season", str(season), "--model", model, "--apply", "1"))
        run(pymod("scripts.verify_snapshot_integrity", "--season", str(season), "--model", model))

    # 12) BOARD EXPORT (read-only)
    run(pymod("scripts.export_board_csv", "--season", str(season), "--model", model, "--window", str(window)))

    # 13) MOVERS/VOLATILITY EXPORTS (read-only)
    run(pymod("scripts.export_movers_csv", "--season", str(season), "--model", model, "--window", str(window), "--top", "50"))

    # 14) SOURCE HEALTH EXPORT (read-only)
    run(pymod("scripts.export_source_health_csv", "--season", str(season), "--model", model))

    # 15) CONFIDENCE SUMMARY EXPORT (read-only)
    run(pymod("scripts.export_confidence_summary_csv", "--season", str(season), "--model", model, "--elite-top", "100", "--elite-show", "25"))

    # 16) HTML REPORT PACK (read-only)
    run(pymod("scripts.export_reports_html", "--season", str(season), "--model", model, "--window", str(window)))

    # 17) DOCTOR (read-only)
    run(pyfile(scripts / "doctor.py"))

    print("OK: weekly pipeline completed successfully.")


if __name__ == "__main__":
    main()