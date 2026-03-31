#!/usr/bin/env python3
"""
APEX OS Session Briefing — Mode 1 Sports Almanac / Analytical.
Run at the start of every Mode 1 session.
Usage: python scripts/open_session_mode1.py
"""

from pathlib import Path
from datetime import date
import re
import sys

STATE_FILE = Path("SESSION_STATE_MODE1.md")
SEPARATOR = "=" * 60

def read_state():
    if not STATE_FILE.exists():
        print(f"\n[ERROR] SESSION_STATE_MODE1.md not found in project root.")
        print("Create it from the Mode 1 SESSION_STATE template before proceeding.")
        sys.exit(1)
    return STATE_FILE.read_text()

def extract_field(content, label):
    pattern = rf"{re.escape(label)}:\s*(.+)"
    match = re.search(pattern, content)
    return match.group(1).strip() if match else "NOT SET"

def extract_section(content, header):
    pattern = rf"## {re.escape(header)}\n([\s\S]*?)(?=\n## |\Z)"
    match = re.search(pattern, content)
    if not match:
        return "NOT SET"
    lines = [l.strip() for l in match.group(1).strip().splitlines() if l.strip()]
    return "\n  ".join(lines) if lines else "NONE"

def staleness_warning(last_updated_str):
    try:
        last = date.fromisoformat(last_updated_str)
        delta = (date.today() - last).days
        if delta == 0:
            return None
        elif delta <= 3:
            return f"[NOTE] SESSION_STATE_MODE1.md last updated {delta} day(s) ago — verify accuracy."
        else:
            return f"[WARNING] SESSION_STATE_MODE1.md is {delta} days old — confirm active evaluations before proceeding."
    except ValueError:
        return "[WARNING] Last Updated date is not valid ISO format — check SESSION_STATE_MODE1.md."

def main():
    content = read_state()

    last_updated        = extract_field(content, "Last Updated")
    session_baseline    = extract_field(content, "Session Baseline")
    active_evals        = extract_section(content, "ACTIVE EVALUATIONS")
    completed           = extract_section(content, "COMPLETED THIS SESSION")
    open_threads        = extract_section(content, "OPEN THREADS")
    archetype_version   = extract_field(content, "Archetype Library Version")
    apex_notes          = extract_field(content, "APEX Framework")
    divergence_flags    = extract_field(content, "Active Divergence Flags")
    last_position       = extract_field(content, "Last Position Completed")
    next_position       = extract_field(content, "Next Position")
    next_task           = extract_field(content, "Next Session Opens With")

    stale = staleness_warning(last_updated)

    print(f"\n{SEPARATOR}")
    print("  DRAFTOS — MODE 1 SESSION BRIEFING")
    print(f"  {date.today().strftime('%A, %B %d, %Y')}")
    print(SEPARATOR)

    if stale:
        print(f"\n  {stale}")

    print(f"\n  SESSION BASELINE:       {session_baseline}")
    print(f"  STATE FILE DATE:        {last_updated}")

    print(f"\n{SEPARATOR}")
    print("  ACTIVE EVALUATIONS")
    print(SEPARATOR)
    if active_evals in ("NONE", "NOT SET"):
        print("\n  NONE — no players in active evaluation")
    else:
        for line in active_evals.splitlines():
            print(f"\n  {line}")

    print(f"\n{SEPARATOR}")
    print("  COMPLETED THIS SESSION")
    print(SEPARATOR)
    if completed in ("NONE", "NOT SET"):
        print("\n  NONE")
    else:
        for line in completed.splitlines():
            print(f"\n  {line}")

    print(f"\n{SEPARATOR}")
    print("  OPEN THREADS")
    print(SEPARATOR)
    if open_threads in ("NONE", "NOT SET"):
        print("\n  NONE")
    else:
        for line in open_threads.splitlines():
            print(f"\n  {line}")

    print(f"\n{SEPARATOR}")
    print("  FRAMEWORK STATE")
    print(SEPARATOR)
    print(f"\n  ARCHETYPE LIBRARY:      {archetype_version}")
    print(f"  APEX NOTES:             {apex_notes}")
    print(f"  DIVERGENCE FLAGS:       {divergence_flags}")

    print(f"\n{SEPARATOR}")
    print("  COMP BUILD SEQUENCE")
    print(SEPARATOR)
    print(f"\n  LAST POSITION:          {last_position}")
    print(f"  NEXT POSITION:          {next_position}")

    print(f"\n{SEPARATOR}")
    print("  THIS SESSION OPENS WITH")
    print(SEPARATOR)
    print(f"\n  {next_task}")
    print(f"\n{SEPARATOR}\n")

if __name__ == "__main__":
    main()
