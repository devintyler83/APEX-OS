#!/usr/bin/env python3
"""
DraftOS SESSION_STATE_MODE1.md auto-updater.
Run at close of every Mode 1 session.

Usage:
python scripts/update_session_state_mode1.py \
  --last-position OG \
  --next-position C \
  --apex-notes "No modifications" \
  --divergence-flags "NONE" \
  --active "Caleb Williams | QB | CHI | APEX scoring" \
  --completed "Malik Nabers | WR | NYG | Archetype assigned -- Elite Speed Power" \
  --threads "NONE"
"""

import argparse
import re
from datetime import date
from pathlib import Path
import sys

STATE_FILE = Path("SESSION_STATE_MODE1.md")

def read_state():
    if not STATE_FILE.exists():
        print("[ERROR] SESSION_STATE_MODE1.md not found in project root.")
        sys.exit(1)
    return STATE_FILE.read_text(encoding="utf-8")

def update_field(content, label, new_value):
    pattern = rf"({re.escape(label)}:\s*)(.+)"
    if not re.search(pattern, content):
        print("[WARNING] Field not found -- skipping: " + label)
        return content
    return re.sub(pattern, rf"\g<1>{new_value}", content)

def update_section(content, header, new_value):
    pattern = rf"(## {re.escape(header)}\n)([\s\S]*?)(?=\n## |\Z)"
    if not re.search(pattern, content):
        print("[WARNING] Section not found -- skipping: " + header)
        return content
    return re.sub(pattern, rf"\g<1>{new_value}\n", content)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--last-position", required=True, help="Last comp build position completed e.g. OG")
    parser.add_argument("--next-position", required=True, help="Next comp build position e.g. C")
    parser.add_argument("--apex-notes", default="No modifications", help="Any APEX framework calibration notes")
    parser.add_argument("--divergence-flags", default="NONE", help="Active divergence flags e.g. APEX_HIGH")
    parser.add_argument("--active", nargs="*", default=[], help="Active evaluations -- one string per player")
    parser.add_argument("--completed", nargs="*", default=[], help="Completed this session -- one string per player")
    parser.add_argument("--threads", nargs="*", default=[], help="Open threads -- one string per thread")
    args = parser.parse_args()

    content = read_state()

    # Date
    content = update_field(content, "Last Updated", str(date.today()))

    # Comp sequence
    content = update_field(content, "Last Position Completed", args.last_position)
    content = update_field(content, "Next Position", args.next_position)

    # Framework state
    content = update_field(content, "APEX Framework", args.apex_notes)
    content = update_field(content, "Active Divergence Flags", args.divergence_flags)

    # Active evaluations
    active_block = "\n".join(args.active) if args.active else "NONE"
    content = update_section(content, "ACTIVE EVALUATIONS", active_block)

    # Completed this session
    completed_block = "\n".join(args.completed) if args.completed else "NONE"
    content = update_section(content, "COMPLETED THIS SESSION", completed_block)

    # Open threads
    threads_block = "\n".join(args.threads) if args.threads else "NONE"
    content = update_section(content, "OPEN THREADS", threads_block)

    # Next session opens with
    next_task = "Resume comp build sequence -- next position: " + args.next_position
    content = update_field(content, "Next Session Opens With", next_task)

    STATE_FILE.write_text(content, encoding="utf-8")
    print("SESSION_STATE_MODE1.md updated. Session closed.")
    print("Next session opens with: " + next_task)

if __name__ == "__main__":
    main()