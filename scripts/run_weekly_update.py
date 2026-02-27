from __future__ import annotations

# --- sys.path bootstrap ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# --- end bootstrap ---

import argparse
import subprocess
from typing import List


def run(cmd: List[str], *, cwd: Path, check: bool = True) -> int:
    print("\n" + "=" * 90)
    print("RUN:", " ".join(cmd))
    print("=" * 90)
    p = subprocess.run(cmd, cwd=str(cwd))
    if check and p.returncode != 0:
        raise SystemExit(f"FAIL: command failed ({p.returncode}): {' '.join(cmd)}")
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--model", type=str, default="v1_default")

    ap.add_argument("--stage-dir", type=str, default="", help="Folder containing raw rankings CSVs")
    ap.add_argument("--ranking-date", type=str, default="", help="Override ranking_date YYYY-MM-DD for ALL ingested files")

    ap.add_argument("--export-min-sources", type=int, default=8)
    ap.add_argument("--export-elite-min-sources", type=int, default=6)
    ap.add_argument("--export-qb-min-sources", type=int, default=6)

    ap.add_argument("--apply", type=int, default=0)
    args = ap.parse_args()

    cwd = ROOT

    print("DraftOS Weekly Update Orchestrator")
    print(f"ROOT:   {ROOT}")
    print(f"SEASON: {args.season}")
    print(f"MODEL:  {args.model}")
    print(f"APPLY:  {args.apply}")
    if args.stage_dir:
        print(f"STAGE:  {args.stage_dir}")
    if args.ranking_date:
        print(f"AS-OF:  {args.ranking_date}")

    # Always safe checks first
    run(["python", "-m", "draftos.db.migrate"], cwd=cwd, check=True)
    run(["python", "-m", "scripts.doctor"], cwd=cwd, check=True)

    if args.apply != 1:
        print("\nDRY RUN orchestrator: stopping after migrate+doctor. Re-run with --apply 1 to execute write steps.")
        return

    # 1) Stage (optional). Stage script now skips junk files instead of failing.
    if args.stage_dir:
        run(["python", "scripts/stage_rankings_csv.py", "--dir", args.stage_dir, "--season", str(args.season)], cwd=cwd)

    # 2) Ingest staged (writes + backup inside)
    ingest_cmd = ["python", "scripts/ingest_rankings_staged.py", "--season", str(args.season), "--apply", "1"]
    if args.ranking_date:
        ingest_cmd += ["--ranking-date", args.ranking_date]
    run(ingest_cmd, cwd=cwd)

    # 3) Bootstrap prospects/maps (writes + backup inside)
    run(["python", "scripts/patch_0007_bootstrap_prospects_2026.py", "--apply", "1"], cwd=cwd)

    # 4) Consensus (writes + backup inside)
    run(["python", "scripts/build_consensus_2026.py", "--draft-year", str(args.season), "--apply", "1"], cwd=cwd)

    # 5) Model outputs (writes + backup inside)
    run(
        [
            "python",
            "scripts/build_model_outputs_v1_default_2026.py",
            "--draft-year",
            str(args.season),
            "--model",
            args.model,
            "--apply",
            "1",
        ],
        cwd=cwd,
    )

    # 6) Doctor gate
    run(["python", "-m", "scripts.doctor"], cwd=cwd, check=True)

    # 7) Exports (no DB writes)
    run(
        ["python", "scripts/export_board_csv.py", "--draft-year", str(args.season), "--model", args.model, "--min-sources", "1"],
        cwd=cwd,
    )
    run(
        [
            "python",
            "scripts/export_board_csv.py",
            "--draft-year",
            str(args.season),
            "--model",
            args.model,
            "--min-sources",
            str(args.export_min_sources),
        ],
        cwd=cwd,
    )
    run(
        [
            "python",
            "scripts/export_board_csv.py",
            "--draft-year",
            str(args.season),
            "--model",
            args.model,
            "--tier",
            "Elite",
            "--min-sources",
            str(args.export_elite_min_sources),
        ],
        cwd=cwd,
    )
    run(
        [
            "python",
            "scripts/export_board_csv.py",
            "--draft-year",
            str(args.season),
            "--model",
            args.model,
            "--position-group",
            "QB",
            "--min-sources",
            str(args.export_qb_min_sources),
        ],
        cwd=cwd,
    )

    print("\nOK: weekly pipeline completed successfully.")


if __name__ == "__main__":
    main()