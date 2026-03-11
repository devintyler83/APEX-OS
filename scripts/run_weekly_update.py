# scripts/run_weekly_update.py
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from draftos.config import PATHS


def run(cmd: list[str]) -> None:
    print("RUN:", " ".join(cmd))
    subprocess.check_call(cmd)


def pymod(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def pyfile(path: Path, *args: str) -> list[str]:
    return [sys.executable, str(path), *args]


def _find_one(root: Path, glob_pat: str) -> Path:
    hits = sorted([p for p in root.glob(glob_pat) if p.is_file()])
    if len(hits) == 1:
        return hits[0]
    if len(hits) == 0:
        raise SystemExit(f"FAIL: required script not found: scripts/{glob_pat}")
    names = ", ".join(p.name for p in hits[:10])
    raise SystemExit(f"FAIL: ambiguous scripts/{glob_pat} matched {len(hits)} files: {names}")


def _find_optional(root: Path, glob_pat: str) -> Optional[Path]:
    hits = sorted([p for p in root.glob(glob_pat) if p.is_file()])
    if len(hits) == 1:
        return hits[0]
    if len(hits) == 0:
        return None
    names = ", ".join(p.name for p in hits[:10])
    raise SystemExit(f"FAIL: ambiguous scripts/{glob_pat} matched {len(hits)} files: {names}")


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

    if args.fast:
        args.skip_html = True
        args.skip_packet = True

    root = PATHS.root
    scripts_dir = root / "scripts"

    season = int(args.season)
    model = str(args.model)
    window = int(args.window)

    rankings_dir = root / "data" / "imports" / "rankings" / "raw" / str(season)
    if not rankings_dir.exists() or not rankings_dir.is_dir():
        raise SystemExit(f"FAIL: rankings dir not found: {rankings_dir}")
    print(f"OK: rankings dir: {rankings_dir}")

    # Resolve season/model-specific scripts deterministically
    bootstrap = _find_one(scripts_dir, f"patch_*_bootstrap_prospects_{season}.py")
    consensus = _find_one(scripts_dir, f"build_consensus_{season}.py")
    model_out = _find_one(scripts_dir, f"build_model_outputs_{model}_{season}.py")

    # Canonicalization can be a module (scripts.patch_source_canonicalization_<season>)
    canon_file = _find_optional(scripts_dir, f"patch_source_canonicalization_{season}.py")
    canon_mod = f"scripts.patch_source_canonicalization_{season}"

    # 1) STAGING (no DB writes)
    run(pyfile(scripts_dir / "stage_rankings_csv.py", "--dir", str(rankings_dir), "--season", str(season)))

    # 2) INGEST (WRITE)
    run(pyfile(scripts_dir / "ingest_rankings_staged.py", "--season", str(season), "--apply", "1"))

    # 3) BOOTSTRAP (WRITE)
    run(pyfile(bootstrap, "--apply", "1"))

    # 3b) UNIVERSE APPLY — enforce is_active filter after bootstrap (WRITE)
    # Prevents weekly ingest from inflating active prospect count via inactive source staged files.
    # apply_prospect_universe_2026.py is hardcoded to season_id=1; --apply 1 required for writes.
    run(pymod("scripts.apply_prospect_universe_2026", "--apply", "1"))

    # 4) SOURCE CANONICALIZATION (WRITE)
    # Prefer module entrypoint for consistency, but fail fast if the expected file isn't present.
    if canon_file is None:
        raise SystemExit(f"FAIL: expected canonicalization script not found: scripts/patch_source_canonicalization_{season}.py")
    run(pymod(canon_mod, "--apply", "1"))

    # 5) CONSENSUS (WRITE)
    run(pyfile(consensus, "--apply", "1"))

    # 6) MODEL OUTPUTS (WRITE)
    run(pyfile(model_out, "--apply", "1"))

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
    run(pymod("scripts.export_movers_csv", "--season", str(season), "--model", model, "--window", str(window), "--top", str(args.top)))

    # 14) SOURCE HEALTH EXPORT (read-only)
    run(pymod("scripts.export_source_health_csv", "--season", str(season), "--model", model))

    # 15) CONFIDENCE SUMMARY EXPORT (read-only)
    run(pymod("scripts.export_confidence_summary_csv", "--season", str(season), "--model", model, "--elite-top", "100", "--elite-show", "25"))

    # 16) HTML REPORT PACK (read-only)
    if not args.skip_html:
        run(pymod("scripts.export_reports_html", "--season", str(season), "--model", model, "--window", str(window)))

    # 17) DOCTOR (read-only)
    run(pyfile(scripts_dir / "doctor.py"))

    # 19) TAG TRIGGER EVALUATION (WRITE)
    # Evaluates all active tag_trigger_rules against scored prospects and writes
    # recommendations to prospect_tag_recommendations. Idempotent — INSERT OR IGNORE.
    run(pymod("scripts.evaluate_tag_triggers_2026", "--apply", "1"))

    # 18) SNAPSHOT PACKET (read-only, immutable artifact bundle)
    if not args.skip_packet:
        run(
            pymod(
                "scripts.build_snapshot_packet",
                "--season",
                str(season),
                "--model",
                model,
                "--window",
                str(window),
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
        run(pymod("scripts.verify_packet_manifest"))
        run(pymod("scripts.publish_latest_packet"))
        run(pymod("scripts.verify_packet_manifest", "--latest", "1"))

    print("OK: weekly pipeline completed successfully.")


if __name__ == "__main__":
    main()
