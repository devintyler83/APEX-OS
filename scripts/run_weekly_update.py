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


def main() -> None:
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
    args = ap.parse_args()

    if args.window < 2:
        raise SystemExit("FAIL: --window must be >= 2")
    if args.top < 1:
        raise SystemExit("FAIL: --top must be >= 1")

    if args.fast:
        args.skip_html = True
        args.skip_packet = True

    root = PATHS.root
    scripts = root / "scripts"

    rankings_dir = root / "data" / "imports" / "rankings" / "raw" / str(args.season)
    if not rankings_dir.exists() or not rankings_dir.is_dir():
        raise SystemExit(f"FAIL: rankings dir not found: {rankings_dir}")
    print(f"OK: rankings dir: {rankings_dir}")

    # 1) STAGING (no DB writes)
    run(pyfile(scripts / "stage_rankings_csv.py", "--dir", str(rankings_dir), "--season", str(args.season)))

    # 2) INGEST (WRITE)
    run(pyfile(scripts / "ingest_rankings_staged.py", "--season", str(args.season), "--apply", "1"))

    # 3) BOOTSTRAP (WRITE)
    # NOTE: if you add other seasons, create patch_0007_bootstrap_prospects_<season>.py and branch here.
    bootstrap = scripts / f"patch_0007_bootstrap_prospects_{args.season}.py"
    if not bootstrap.exists():
        raise SystemExit(f"FAIL: bootstrap script not found: {bootstrap}")
    run(pyfile(bootstrap, "--apply", "1"))

    # 4) SOURCE CANONICALIZATION (WRITE)
    # NOTE: if you add other seasons, create patch_source_canonicalization_<season>.py and branch here.
    canon_mod = f"scripts.patch_source_canonicalization_{args.season}"
    run(pymod(canon_mod, "--apply", "1"))

    # 5) CONSENSUS (WRITE)
    consensus = scripts / f"build_consensus_{args.season}.py"
    if not consensus.exists():
        raise SystemExit(f"FAIL: consensus script not found: {consensus}")
    run(pyfile(consensus, "--apply", "1"))

    # 6) MODEL OUTPUTS (WRITE)
    # NOTE: if you add other models, create build_model_outputs_<model>_<season>.py and branch here.
    model_outputs = scripts / f"build_model_outputs_{args.model}_{args.season}.py"
    if not model_outputs.exists():
        raise SystemExit(f"FAIL: model outputs script not found: {model_outputs}")
    run(pyfile(model_outputs, "--apply", "1"))

    # 7) SNAPSHOT (WRITE)
    run(pymod("scripts.snapshot_board", "--season", str(args.season), "--model", args.model, "--apply", "1"))

    # 8) SNAPSHOT COVERAGE (WRITE)
    run(pymod("scripts.compute_snapshot_coverage", "--season", str(args.season), "--model", args.model, "--apply", "1"))

    # 9) SNAPSHOT METRICS (WRITE)
    run(
        pymod(
            "scripts.compute_snapshot_metrics",
            "--season",
            str(args.season),
            "--model",
            args.model,
            "--window",
            str(args.window),
            "--apply",
            "1",
        )
    )

    # 10) SOURCE SNAPSHOT METRICS (WRITE)
    run(
        pymod(
            "scripts.compute_source_snapshot_metrics",
            "--season",
            str(args.season),
            "--model",
            args.model,
            "--stale-days",
            str(args.stale_days),
            "--coverage-min",
            str(args.coverage_min),
            "--mad-noisy",
            str(args.mad_noisy),
            "--apply",
            "1",
        )
    )

    # 11) SNAPSHOT CONFIDENCE (WRITE)
    run(pymod("scripts.compute_snapshot_confidence", "--season", str(args.season), "--model", args.model, "--apply", "1"))

    # 11.5) SNAPSHOT INTEGRITY ASSERTION (read-only)
    # If mismatch exists, attempt deterministic SNAPSHOTS-layer repair once, then re-verify.
    try:
        run(pymod("scripts.verify_snapshot_integrity", "--season", str(args.season), "--model", args.model))
    except subprocess.CalledProcessError:
        print("WARN: snapshot integrity check failed, attempting deterministic repair...")
        run(pymod("scripts.repair_snapshot_orphans", "--season", str(args.season), "--model", args.model, "--apply", "1"))
        run(pymod("scripts.verify_snapshot_integrity", "--season", str(args.season), "--model", args.model))

    # 12) BOARD EXPORT (read-only)
    run(pymod("scripts.export_board_csv", "--season", str(args.season), "--model", args.model, "--window", str(args.window)))

    # 13) MOVERS/VOLATILITY EXPORTS (read-only)
    run(
        pymod(
            "scripts.export_movers_csv",
            "--season",
            str(args.season),
            "--model",
            args.model,
            "--window",
            str(args.window),
            "--top",
            str(args.top),
        )
    )

    # 14) SOURCE HEALTH EXPORT (read-only)
    run(pymod("scripts.export_source_health_csv", "--season", str(args.season), "--model", args.model))

    # 15) CONFIDENCE SUMMARY EXPORT (read-only)
    run(
        pymod(
            "scripts.export_confidence_summary_csv",
            "--season",
            str(args.season),
            "--model",
            args.model,
            "--elite-top",
            "100",
            "--elite-show",
            "25",
        )
    )

    # 16) HTML REPORT PACK (read-only)
    if not args.skip_html:
        run(pymod("scripts.export_reports_html", "--season", str(args.season), "--model", args.model, "--window", str(args.window)))
    else:
        print("SKIP: HTML report pack")

    # 17) DOCTOR (read-only)
    run(pyfile(scripts / "doctor.py"))

    # 18) SNAPSHOT PACKET + 19) PUBLISH LATEST PACKET (read-only)
    if not args.skip_packet:
        run(
            pymod(
                "scripts.build_snapshot_packet",
                "--season",
                str(args.season),
                "--model",
                args.model,
                "--window",
                str(args.window),
                "--top",
                str(args.top),
                "--stale-days",
                str(args.stale_days),
                "--coverage-min",
                str(args.coverage_min),
                "--mad-noisy",
                str(args.mad_noisy),
            )
        )
        run(pymod("scripts.publish_latest_packet"))
    else:
        print("SKIP: snapshot packet + publish latest")

    print("OK: weekly pipeline completed successfully.")


if __name__ == "__main__":
    main()
