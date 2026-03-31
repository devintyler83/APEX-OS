#!/usr/bin/env python3
"""
DraftOS SESSION_STATE.md auto-updater.
Run at close of every migration.
Usage: python scripts/update_session_state.py --migration 0046 --description "Added APEX score index to prospects table" --next 0047 --next-description "Build divergence flag materialized view"
"""

import argparse
import re
from datetime import date
from pathlib import Path

STATE_FILE = Path("SESSION_STATE.md")

def read_state():
    if not STATE_FILE.exists():
        raise FileNotFoundError("SESSION_STATE.md not found in project root.")
    return STATE_FILE.read_text()

def update_field(content, label, new_value):
    pattern = rf"({re.escape(label)}: )(.+)"
    replacement = rf"\g<1>{new_value}"
    updated = re.sub(pattern, replacement, content)
    if updated == content:
        raise ValueError(f"Field not found in SESSION_STATE.md: {label}")
    return updated

def append_migration_log(content, migration, description):
    log_line = f"Last Migration Completed: {migration} — {description}"
    pattern = r"(Last Migration Completed: )(.+)"
    return re.sub(pattern, log_line, content)

def update_next_migration(content, next_num, next_desc):
    next_line = f"Next Migration: {next_num} — {next_desc}"
    pattern = r"(Next Migration: )(.+)"
    return re.sub(pattern, next_line, content)

def clear_blockers(content):
    pattern = r"(## BLOCKERS\n)([\s\S]*?)(\n## )"
    return re.sub(pattern, r"\1NONE\3", content)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--migration", required=True, help="Completed migration number e.g. 0046")
    parser.add_argument("--description", required=True, help="One-line description of what was built")
    parser.add_argument("--next", required=True, help="Next migration number e.g. 0047")
    parser.add_argument("--next-description", required=True, help="One-line description of next build")
    parser.add_argument("--schema-modified", nargs="*", default=[], help="Tables modified this migration")
    parser.add_argument("--schema-added", nargs="*", default=[], help="Tables added this migration")
    parser.add_argument("--blocker", default=None, help="Active blocker if any — omit if none")
    args = parser.parse_args()

    content = read_state()

    # Update date and migration log
    content = update_field(content, "Last Updated", str(date.today()))
    content = append_migration_log(content, args.migration, args.description)
    content = update_next_migration(content, args.next, args.next_description)

    # Schema state
    modified = ", ".join(args.schema_modified) if args.schema_modified else "NONE"
    added = ", ".join(args.schema_added) if args.schema_added else "NONE"
    content = update_field(content, "Tables Modified This Session", modified)
    content = update_field(content, "Tables Added This Session", added)

    # Blockers
    if args.blocker:
        content = update_field(content, "## BLOCKERS", f"\n{args.blocker}")
    else:
        content = clear_blockers(content)

    # Next session opens with
    next_task = f"Execute Migration {args.next} — {args.next_description}"
    content = update_field(content, "Next Session Opens With", next_task)

    STATE_FILE.write_text(content)
    print(f"SESSION_STATE.md updated. Migration {args.migration} closed. Next: {args.next}.")

if __name__ == "__main__":
    main()