#!/usr/bin/env python3
"""
DraftOS SESSION_STATE_MODE3.md auto-updater.
Run at close of every Mode 3 session.

Usage:
python scripts/update_session_state_mode3.py `
  --color "Added --accent-gold var for APEX tier badges" `
  --typography "No changes" `
  --layout "No changes" `
  --components "APEX Score Card -- displays tier, score, and confidence band" `
  --manifest "draftos_cards_v1.html -- active" `
  --threads "NONE"
"""

import argparse
import re
from datetime import date
from pathlib import Path
import sys

STATE_FILE = Path("SESSION_STATE_MODE3.md")

def read_state():
    if not STATE_FILE.exists():
        print("[ERROR] SESSION_STATE_MODE3.md not found in project root.")
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
    parser.add_argument("--color", default="NONE", help="Color decisions made this session")
    parser.add_argument("--typography", default="NONE", help="Typography decisions made this session")
    parser.add_argument("--layout", default="NONE", help="Layout decisions made this session")
    parser.add_argument("--components", nargs="*", default=[], help="Components built this session -- one string per component")
    parser.add_argument("--manifest", nargs="*", default=[], help="Active file manifest entries -- one string per file")
    parser.add_argument("--threads", nargs="*", default=[], help="Open threads -- one string per thread")
    parser.add_argument("--next", default="NOT SET", help="One sentence describing what the next session opens with")
    args = parser.parse_args()

    content = read_state()

    # Date
    content = update_field(content, "Last Updated", str(date.today()))

    # Design system state
    content = update_field(content, "Color decisions", args.color)
    content = update_field(content, "Typography decisions", args.typography)
    content = update_field(content, "Layout decisions", args.layout)

    # Components built
    components_block = "\n".join(args.components) if args.components else "NONE"
    content = update_section(content, "COMPONENTS BUILT THIS SESSION", components_block)

    # File manifest
    manifest_block = "\n".join(args.manifest) if args.manifest else "NONE"
    content = update_section(content, "FILE MANIFEST", manifest_block)

    # Open threads
    threads_block = "\n".join(args.threads) if args.threads else "NONE"
    content = update_section(content, "OPEN THREADS", threads_block)

    # Next session opens with
    content = update_section(content, "NEXT SESSION OPENS WITH", args.next)

    STATE_FILE.write_text(content, encoding="utf-8")
    print("SESSION_STATE_MODE3.md updated. Session closed.")
    print("Next session opens with: " + args.next)

if __name__ == "__main__":
    main()