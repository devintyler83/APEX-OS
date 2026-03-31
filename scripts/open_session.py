#!/usr/bin/env python3
"""
APEX OS Session Briefing -- Mode 2 Build Planning.
Run at the start of every Mode 2 Claude Code session.
Usage: python scripts/open_session.py
"""

from pathlib import Path
from datetime import date
import re
import sys

STATE_FILE = Path("SESSION_STATE.md")
SEPARATOR = "=" * 60

def read_state():
    if not STATE_FILE.exists():
        print("\n[ERROR] SESSION_STATE.md not found in project root.")
        print("Create it from the Mode 2 SESSION_STATE template before proceeding.")
        sys.exit(1)
    return STATE_FILE.read_text(encoding="utf-8")

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
            return "[NOTE] SESSION_STATE.md last updated " + str(delta) + " day(s) ago -- verify accuracy."
        else:
            return "[WARNING] SESSION_STATE.md is " + str(delta) + " days old -- update before proceeding."
    except ValueError:
        return "[WARNING] Last Updated date is not valid ISO format -- check SESSION_STATE.md."

def main():
    content = read_state()

    last_updated     = extract_field(content, "Last Updated")
    session_baseline = extract_field(content, "Session Baseline")
    last_migration   = extract_field(content, "Last Migration Completed")
    next_migration   = extract_field(content, "Next Migration")
    pending          = extract_section(content, "MIGRATIONS PENDING")
    schema_modified  = extract_field(content, "Tables Modified This Session")
    schema_added     = extract_field(content, "Tables Added This Session")
    schema_pending   = extract_field(content, "Pending Schema Decisions")
    open_threads     = extract_section(content, "OPEN BUILD THREADS")
    blockers         = extract_section(content, "BLOCKERS")
    next_task        = extract_field(content, "Next Session Opens With")

    stale = staleness_warning(last_updated)

    print("")
    print(SEPARATOR)
    print("  DRAFTOS -- MODE 2 SESSION BRIEFING")
    print("  " + date.today().strftime("%A, %B %d, %Y"))
    print(SEPARATOR)

    if stale:
        print("")
        print("  " + stale)

    print("")
    print("  SESSION BASELINE:       " + session_baseline)
    print("  STATE FILE DATE:        " + last_updated)

    print("")
    print(SEPARATOR)
    print("  MIGRATION STATUS")
    print(SEPARATOR)
    print("")
    print("  LAST COMPLETED:  " + last_migration)
    print("  NEXT BUILD:      " + next_migration)

    if pending and pending not in ("NONE", "NOT SET"):
        print("")
        print("  PENDING QUEUE:")
        for line in pending.splitlines():
            print("    " + line)

    print("")
    print(SEPARATOR)
    print("  SCHEMA STATE")
    print(SEPARATOR)
    print("")
    print("  MODIFIED:  " + schema_modified)
    print("  ADDED:     " + schema_added)

    if schema_pending and schema_pending not in ("NONE", "NOT SET"):
        print("")
        print("  PENDING DECISION:")
        print("  " + schema_pending)

    print("")
    print(SEPARATOR)
    print("  OPEN THREADS")
    print(SEPARATOR)
    if open_threads in ("NONE", "NOT SET"):
        print("")
        print("  NONE")
    else:
        for line in open_threads.splitlines():
            print("")
            print("  " + line)

    print("")
    print(SEPARATOR)
    print("  BLOCKERS")
    print(SEPARATOR)
    if blockers in ("NONE", "NOT SET"):
        print("")
        print("  NONE -- cleared to build")
    else:
        for line in blockers.splitlines():
            print("")
            print("  [BLOCKED] " + line)

    print("")
    print(SEPARATOR)
    print("  THIS SESSION OPENS WITH")
    print(SEPARATOR)
    print("")
    print("  " + next_task)
    print("")
    print(SEPARATOR)
    print("")

if __name__ == "__main__":
    main()