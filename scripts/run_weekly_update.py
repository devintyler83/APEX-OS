# scripts/run_weekly_update.py
from __future__ import annotations

import argparse
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


def build_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="DraftOS weekly pipeline runner (deterministic, idempotent).")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--top", type=int, default=50, help="Top N per risers/fallers in movers exports.")
    ap.add_argument("--stale-days", type=int, default=7)
    ap.add_argument("--coverage-min", type=float, default=0.50)
    ap.add_argument("--mad-noisy", type=float, default=50.0)

    ap.add_argument("--skip-html", action="store_true", help="Skip HTML report pack generation.")
    ap.add_argument("--skip-packet", action="store_true", help="Skip snapshot packet build and publish.")
    ap.add_argument("--fast", action="store_true", help="Equivalent to --skip-html --skip-packet.")

    return ap.parse_args()


def main() -> None:
    args = build_args()

    if args.fast:
        args.skip_html = True
        args.skip_packet = True

    root = PATHS.root
    scripts = root / "scripts"

    season = int(args.season)
    model = str(args.model)
    window = int(args.window)

    rankings_dir = root / "data" / "imports" / "rankings" / "raw" / str(season)
    if not rankings_dir.exists() or not rankings_dir.is_dir():
        raise SystemExit(f"FAIL: rankings dir not found: {rankings_dir}")
    print(f"OK: rankings dir: {rankings_dir}")

    # 1) STAGING (no DB writes)
    run(pyfile(scripts / "stage_rankings_csv.py", "--dir", str(rankings_dir), "--season", str(season)))

    # 2) INGEST (WRITE)
    run(pyfile(scripts / "ingest_rankings_staged.py", "--season", str(season), "--apply", "1"))

    # 3) BOOTSTRAP (WRITE) (season-specific today)
    if season != 2026:
        raise SystemExit("FAIL: run_weekly_update currently supports bootstrap for season=2026 only. Add season switch when ready.")
    run(pyfile(scripts / "patch_0007_bootstrap_prospects_2026.py", "--apply", "1"))

    # 4) SOURCE CANONICALIZATION (WRITE) (season-specific today)
    if season != 2026:
        raise SystemExit("FAIL: run_weekly_update currently supports source canonicalization for season=2026 only.")
    run(pymod("scripts.patch_source_canonicalization_2026", "--apply", "1"))

    # 5) CONSENSUS (WRITE) (season-specific today)
    if season != 2026:
        raise SystemExit("FAIL: run_weekly_update currently supports consensus builder for season=2026 only.")
    run(pyfile(scripts / "build_consensus_2026.py", "--apply", "1"))

    # 6) MODEL OUTPUTS (WRITE) (model-specific today)
    if season != 2026 or model != "v1_default":
        raise SystemExit("FAIL: run_weekly_update currently supports model outputs for season=2026 model=v1_default only.")
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
            str(int(args.stale_days)),
            "--coverage-min",
            str(float(args.coverage_min)),
            "--mad-noisy",
            str(float(args.mad_noisy)),
            "--apply",
            "1",
        )
    )

    # 11) SNAPSHOT CONFIDENCE (WRITE)
    run(pymod("scripts.compute_snapshot_confidence", "--season", str(season), "--model", model, "--apply", "1"))

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
    run(
        pymod(
            "scripts.export_movers_csv",
            "--season",
            str(season),
            "--model",
            model,
            "--window",
            str(window),
            "--top",
            str(int(args.top)),
        )
    )

    # 14) SOURCE HEALTH EXPORT (read-only)
    run(pymod("scripts.export_source_health_csv", "--season", str(season), "--model", model))

    # 15) CONFIDENCE SUMMARY EXPORT (read-only)
    run(
        pymod(
            "scripts.export_confidence_summary_csv",
            "--season",
            str(season),
            "--model",
            model,
            "--elite-top",
            "100",
            "--elite-show",
            "25",
        )
    )

    # 16) HTML REPORT PACK (read-only)
    if not args.skip_html:
        run(pymod("scripts.export_reports_html", "--season", str(season), "--model", model, "--window", str(window)))
    else:
        print("SKIP: HTML report pack")

    # 17) DOCTOR (read-only)
    run(pyfile(scripts / "doctor.py"))

    # 18) SNAPSHOT PACKET (read-only, immutable artifact bundle)
    if not args.skip_packet:
        run(pymod("scripts.build_snapshot_packet", "--season", str(season), "--model", model))

        # 19) PUBLISH LATEST PACKET (read-only pointer to newest immutable packet)
        run(pymod("scripts.publish_latest_packet"))
    else:
        print("SKIP: snapshot packet + publish")

    print("OK: weekly pipeline completed successfully.")


if __name__ == "__main__":
    main()
