from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "STATE_SNAPSHOT.md"
BOOTSTRAP_FILE = ROOT / "BOOTSTRAP_PACKET.txt"

# -- UPDATE THIS EVERY SESSION -----------------------------------------------
# Set to the session number you are currently closing.
# The validation gate uses this to detect stale milestone content.
CURRENT_SESSION = 79   # <-- change this before running end_session.py
# ----------------------------------------------------------------------------


def run(cmd: list[str]) -> str:
    try:
        result = subprocess.check_output(cmd, cwd=str(ROOT), stderr=subprocess.STDOUT)
        return result.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        print("ERROR running:", " ".join(cmd))
        print(e.output.decode("utf-8", errors="replace"))
        raise SystemExit(1)


def print_pre_run_checklist() -> None:
    """
    Print a pre-close checklist and pause 5 seconds to give the developer
    a chance to abort (Ctrl+C) if STATE_SNAPSHOT.md has not been updated.
    """
    border = "+" + "=" * 62 + "+"
    mid    = "+" + "-" * 62 + "+"

    def row(text: str = "") -> str:
        return f"|  {text:<58}  |"

    lines = [
        border,
        row("DraftOS SESSION CLOSE -- PRE-RUN CHECKLIST".center(58)),
        mid,
        row("Before this script will pass, STATE_SNAPSHOT.md MUST have:"),
        row(),
        row(f"1. ## Last Completed Milestone"),
        row(f"   Updated to describe Session {CURRENT_SESSION} work"),
        row(f"   (not a prior session)"),
        row(),
        row("2. ## Next Milestone (Single Target)"),
        row("   Updated to the NEXT actionable milestone"),
        row("   (not a stale placeholder)"),
        row(),
        row("3. All Layer Status counts reflect current DB state"),
        row(),
        row("If you haven't done this yet -- stop now and update the"),
        row("file before re-running end_session.py."),
        border,
    ]
    print()
    print("\n".join(lines))
    print()
    print("Continuing in 5 seconds... (Ctrl+C to abort)")
    time.sleep(5)


def ensure_clean_git() -> None:
    status = run(["git", "status", "--porcelain"]).strip()
    if status:
        print("Git working directory not clean. Commit before ending session.")
        print(status)
        raise SystemExit(1)


def validate_state_snapshot_content() -> None:
    """
    Gate: refuse to close if STATE_SNAPSHOT.md looks like it hasn't
    been updated this session.

    Checks:
    1. ## Last Completed Milestone section exists and is non-empty
    2. ## Next Milestone (Single Target) section exists and is not the
       generic placeholder text ("Additional source ingest..." or "UNKNOWN")
    3. The file is more than 500 characters (not a stub)
    4. ## Last Completed Milestone does not reference a session number
       older than CURRENT_SESSION (stale content guard)

    If any check fails: print a descriptive error and raise SystemExit(1).
    The analyst must update STATE_SNAPSHOT.md before session close will
    proceed.
    """
    if not STATE_FILE.exists():
        print("FAIL: STATE_SNAPSHOT.md not found.")
        raise SystemExit(1)

    content = STATE_FILE.read_text(encoding="utf-8")

    if len(content.strip()) < 500:
        print("FAIL: STATE_SNAPSHOT.md looks like a stub (< 500 chars).")
        print("Update it with this session's work before closing.")
        raise SystemExit(1)

    if "## Last Completed Milestone" not in content:
        print("FAIL: STATE_SNAPSHOT.md missing '## Last Completed Milestone' section.")
        raise SystemExit(1)

    # Extract next milestone text
    m = re.search(
        r"^##\s*Next Milestone\s*\(Single Target\)\s*$",
        content, flags=re.MULTILINE
    )
    if not m:
        print("FAIL: STATE_SNAPSHOT.md missing '## Next Milestone (Single Target)' heading.")
        raise SystemExit(1)

    after = content[m.end():]
    stop = re.search(r"^\s*##\s+", after, flags=re.MULTILINE)
    block = (after[: stop.start()] if stop else after).strip()

    stale_markers = [
        "Additional source ingest (source universe stable",
        "UNKNOWN",
        "Full clean weekly pipeline run",
    ]
    for marker in stale_markers:
        if block.startswith(marker):
            print(f"FAIL: Next Milestone appears to be the default placeholder text.")
            print(f"  Found: {block[:80]}")
            print("Update STATE_SNAPSHOT.md with this session's actual next milestone.")
            raise SystemExit(1)

    # Check that Last Completed Milestone references current session
    last_m = re.search(
        r"^##\s*Last Completed Milestone\s*$",
        content, flags=re.MULTILINE
    )
    if last_m:
        after_last = content[last_m.end():]
        stop_last = re.search(r"^\s*##\s+", after_last, re.MULTILINE)
        last_block = (after_last[:stop_last.start()] if stop_last else after_last).strip()
        # If the block starts with "Session N" where N < CURRENT_SESSION, flag as stale.
        session_match = re.match(r"Session\s+(\d+)", last_block)
        if session_match:
            found_session = int(session_match.group(1))
            if found_session < CURRENT_SESSION:
                print(
                    f"FAIL: Last Completed Milestone still describes Session "
                    f"{found_session}, but CURRENT_SESSION={CURRENT_SESSION}."
                )
                print(
                    "  Update STATE_SNAPSHOT.md '## Last Completed Milestone' "
                    "to reflect this session's work."
                )
                raise SystemExit(1)

    print("OK: STATE_SNAPSHOT.md content validated.")


def update_state_timestamp() -> None:
    if not STATE_FILE.exists():
        print("STATE_SNAPSHOT.md missing.")
        raise SystemExit(1)

    content = STATE_FILE.read_text(encoding="utf-8")
    lines = content.splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith("Last Updated (UTC):"):
            lines[i] = f"Last Updated (UTC): {datetime.now(timezone.utc).isoformat()}"
            updated = True
            break

    if not updated:
        # If header line is missing, prepend a standard one.
        header = f"Last Updated (UTC): {datetime.now(timezone.utc).isoformat()}"
        lines.insert(1, header)

    STATE_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def extract_next_milestone(state_text: str) -> str:
    """
    Extracts the Next Milestone from STATE_SNAPSHOT.md.

    Expected format (recommended):
      ## Next Milestone (Single Target)
      - <milestone text>

    Also supports:
      ## Next Milestone (Single Target)
      <milestone text>
    """
    # Find the heading
    m = re.search(r"^##\s*Next Milestone\s*\(Single Target\)\s*$", state_text, flags=re.MULTILINE)
    if not m:
        return "UNKNOWN (Next Milestone heading not found in STATE_SNAPSHOT.md)"

    # Slice everything after the heading
    after = state_text[m.end():]

    # Stop at the next heading or end of file
    stop = re.search(r"^\s*##\s+", after, flags=re.MULTILINE)
    block = after[: stop.start()] if stop else after

    # Pull the first non-empty line
    for line in block.splitlines():
        s = line.strip()
        if not s:
            continue
        # handle bullet form: "- something"
        if s.startswith("-"):
            s = s.lstrip("-").strip()
        return s

    return "UNKNOWN (Next Milestone block was empty in STATE_SNAPSHOT.md)"


def commit_session_artifacts() -> None:
    """
    Stage STATE_SNAPSHOT.md and BOOTSTRAP_PACKET.txt, commit, and push.
    Called after both files are written. This is the ONLY git write
    in the script -- all work-in-progress must be committed before
    end_session.py is invoked.
    """
    run(["git", "add", "STATE_SNAPSHOT.md", "BOOTSTRAP_PACKET.txt"])
    run(["git", "commit", "-m", "session close: update STATE_SNAPSHOT + BOOTSTRAP_PACKET"])
    run(["git", "push", "origin", "main"])
    print("OK: STATE_SNAPSHOT.md + BOOTSTRAP_PACKET.txt committed and pushed.")


def main() -> None:
    print("=== END SESSION ORCHESTRATOR ===")

    print_pre_run_checklist()

    ensure_clean_git()

    print("Running migrate.py...")
    run(["python", "-m", "draftos.db.migrate"])

    print("Running doctor.py...")
    run(["python", "scripts/doctor.py"])

    print("Running scripts/doctor_snapshot.py...")
    snapshot_output = run(["python", "scripts/doctor_snapshot.py"])

    validate_state_snapshot_content()

    update_state_timestamp()

    state_content = STATE_FILE.read_text(encoding="utf-8")
    next_milestone = extract_next_milestone(state_content)

    print("Building BOOTSTRAP_PACKET.txt...")

    packet = f"""DRAFTOS CONTINUATION

Non-negotiables:
- Deterministic only
- Additive migrations only
- Season scoped
- Active sources only
- Idempotent scripts
- Full file replacements only
- Provide run order + verification commands

Goal for this chat:
{next_milestone}

Authoritative State:

1) STATE_SNAPSHOT.md
{state_content}
2) System Snapshot Output
{snapshot_output}

Instructions:
Reconstruct system truth from artifacts only.
Do not infer from prior chats.
Implement the next milestone cleanly.
Respect architectural layers.
Ensure idempotency.
Include verification commands.
"""

    BOOTSTRAP_FILE.write_text(packet.rstrip() + "\n", encoding="utf-8")

    print("BOOTSTRAP_PACKET.txt ready.")

    print("\n" + "=" * 60)
    print("BOOTSTRAP_PACKET.txt -- Next Milestone written as:")
    print(f"  {next_milestone}")
    print("=" * 60)
    print("Verify this is correct before the commit lands.")
    print("Ctrl+C now to abort if the Next Milestone is wrong.")
    time.sleep(3)

    commit_session_artifacts()

    # -- REMINDER FOR NEXT SESSION -------------------------------------------
    # Before running end_session.py next time:
    #   1. Increment CURRENT_SESSION at the top of this file.
    #   2. Update STATE_SNAPSHOT.md ## Last Completed Milestone.
    #   3. Update STATE_SNAPSHOT.md ## Next Milestone (Single Target).
    #   4. Then run: python scripts/end_session.py
    # ------------------------------------------------------------------------
    print("=== SESSION CLOSED CLEANLY ===")


if __name__ == "__main__":
    main()
