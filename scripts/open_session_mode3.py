#!/usr/bin/env python3
"""
APEX OS Session Briefing — Mode 3 UI Card and Visual Systems Designer.
Run at the start of every Mode 3 session.
Usage: python scripts/open_session_mode3.py
"""

from pathlib import Path
from datetime import date
import re
import sys

STATE_FILE = Path("SESSION_STATE_MODE3.md")
SEPARATOR = "=" * 60

def read_state():
    if not STATE_FILE.exists():
        print(f"\n[ERROR] SESSION_STATE_MODE3.md not found in project root.")
        print("Create it from the Mode 3 SESSION_STATE template before proceeding.")
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
            return f"[NOTE] SESSION_STATE_MODE3.md last updated {delta} day(s) ago — verify accuracy."
        else:
            return f"[WARNING] SESSION_STATE_MODE3.md is {delta} days old — confirm component state before proceeding."
    except ValueError:
        return "[WARNING] Last Updated date is not valid ISO format — check SESSION_STATE_MODE3.md."

def main():
    content = read_state()

    last_updated        = extract_field(content, "Last Updated")
    session_baseline    = extract_field(content, "Session Baseline")
    components_built    = extract_section(content, "COMPONENTS BUILT THIS SESSION")
    color_decisions     = extract_field(content, "Color decisions")
    type_decisions      = extract_field(content, "Typography decisions")
    layout_decisions    = extract_field(content, "Layout decisions")
    open_threads        = extract_section(content, "OPEN THREADS")
    file_manifest       = extract_section(content, "FILE MANIFEST")
    next_task           = extract_field(content, "Next Session Opens With")

    stale = staleness_warning(last_updated)

    print(f"\n{SEPARATOR}")
    print("  DRAFTOS — MODE 3 SESSION BRIEFING")
    print(f"  {date.today().strftime('%A, %B %d, %Y')}")
    print(SEPARATOR)

    if stale:
        print(f"\n  {stale}")

    print(f"\n  SESSION BASELINE:       {session_baseline}")
    print(f"  STATE FILE DATE:        {last_updated}")

    print(f"\n{SEPARATOR}")
    print("  COMPONENTS BUILT THIS SESSION")
    print(SEPARATOR)
    if components_built in ("NONE", "NOT SET"):
        print("\n  NONE — no components built yet this session")
    else:
        for line in components_built.splitlines():
            print(f"\n  {line}")

    print(f"\n{SEPARATOR}")
    print("  ACTIVE DESIGN SYSTEM STATE")
    print(SEPARATOR)
    print(f"\n  COLOR:       {color_decisions}")
    print(f"  TYPOGRAPHY:  {type_decisions}")
    print(f"  LAYOUT:      {layout_decisions}")

    print(f"\n{SEPARATOR}")
    print("  OPEN THREADS")
    print(SEPARATOR)
    if open_threads in ("NONE", "NOT SET"):
        print("\n  NONE")
    else:
        for line in open_threads.splitlines():
            print(f"\n  {line}")

    print(f"\n{SEPARATOR}")
    print("  FILE MANIFEST")
    print(SEPARATOR)
    if file_manifest in ("NONE", "NOT SET"):
        print("\n  NOT SET — populate before first session close")
    else:
        for line in file_manifest.splitlines():
            print(f"\n  {line}")

    print(f"\n{SEPARATOR}")
    print("  THIS SESSION OPENS WITH")
    print(SEPARATOR)
    print(f"\n  {next_task}")
    print(f"\n{SEPARATOR}\n")

if __name__ == "__main__":
    main()
