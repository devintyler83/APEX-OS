from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "STATE_SNAPSHOT.md"
BOOTSTRAP_FILE = ROOT / "BOOTSTRAP_PACKET.txt"


def run(cmd: list[str]) -> str:
    try:
        result = subprocess.check_output(cmd, cwd=str(ROOT), stderr=subprocess.STDOUT)
        return result.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        print("ERROR running:", " ".join(cmd))
        print(e.output.decode("utf-8", errors="replace"))
        raise SystemExit(1)


def ensure_clean_git() -> None:
    status = run(["git", "status", "--porcelain"]).strip()
    if status:
        print("Git working directory not clean. Commit before ending session.")
        print(status)
        raise SystemExit(1)


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


def main() -> None:
    print("=== END SESSION ORCHESTRATOR ===")

    ensure_clean_git()

    print("Running migrate.py...")
    run(["python", "-m", "draftos.db.migrate"])

    print("Running doctor.py...")
    run(["python", "scripts/doctor.py"])

    print("Running scripts/doctor_snapshot.py...")
    snapshot_output = run(["python", "scripts/doctor_snapshot.py"])

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
    print("Copy contents into next chat.")
    print("=== SESSION CLOSED CLEANLY ===")


if __name__ == "__main__":
    main()