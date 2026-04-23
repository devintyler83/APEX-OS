"""
run_cb_audit_pack.py

Convenience wrapper: run the full CB divergence audit pack for a given season.
Read-only — does not modify the database. Safe to run at any time.

Usage:
    python run_cb_audit_pack.py [--season-id 1]
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run(cmd: list[str]) -> None:
    print(f"\n>>> RUN: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CB divergence diagnostics for a given season_id (DB season).",
    )
    parser.add_argument("--season-id", type=int, default=1,
                        help="DB season_id (default: 1 for 2026).")
    args = parser.parse_args()
    sid = str(args.season_id)

    run([PY, "-m", "scripts.cb_divergence_snapshot", "--season-id", sid])
    run([PY, "-m", "scripts.cb4_tweener_audit",      "--season-id", sid])
    run([PY, "-m", "scripts.cb3_fm1_stresstest",     "--season-id", sid])


if __name__ == "__main__":
    main()
