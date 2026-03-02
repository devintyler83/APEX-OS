from __future__ import annotations

import shutil
from pathlib import Path

from draftos.config import PATHS


def main() -> None:
    exports = PATHS.root / "exports"
    packets = exports / "packets"

    if not packets.exists():
        raise SystemExit("FAIL: no packets directory found")

    packet_dirs = sorted(
        [p for p in packets.iterdir() if p.is_dir() and p.name.startswith("packet_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not packet_dirs:
        raise SystemExit("FAIL: no packet_* directories found")

    latest_packet = packet_dirs[0]
    latest_dir = packets / "LATEST"

    if latest_dir.exists():
        shutil.rmtree(latest_dir)

    shutil.copytree(latest_packet, latest_dir)

    print(f"OK: LATEST packet published from {latest_packet.name}")


if __name__ == "__main__":
    main()
