# scripts/verify_packet_manifest.py
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Tuple


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(packet_dir: Path) -> Dict:
    mf = packet_dir / "packet_manifest.json"
    if not mf.exists():
        raise SystemExit(f"FAIL: manifest not found: {mf}")
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"FAIL: could not parse manifest: {mf} err={e}")


def newest_packet_dir(packets_dir: Path) -> Path:
    if not packets_dir.exists():
        raise SystemExit(f"FAIL: packets dir not found: {packets_dir}")
    dirs = sorted(
        [p for p in packets_dir.iterdir() if p.is_dir() and p.name.startswith("packet_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        raise SystemExit(f"FAIL: no packet_* directories found in {packets_dir}")
    return dirs[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify packet_manifest.json hashes for a snapshot packet directory.")
    ap.add_argument("--packet-dir", type=str, default=None, help="Path to packet dir. If omitted, uses newest packet_* under exports/packets.")
    ap.add_argument("--latest", type=int, default=0, choices=[0, 1], help="Verify exports/packets/LATEST (ignores --packet-dir).")
    args = ap.parse_args()

    root = Path.cwd()
    packets_dir = root / "exports" / "packets"

    if args.latest == 1:
        packet_dir = packets_dir / "LATEST"
        if not packet_dir.exists():
            raise SystemExit(f"FAIL: LATEST dir not found: {packet_dir}")
    else:
        packet_dir = Path(args.packet_dir) if args.packet_dir else newest_packet_dir(packets_dir)

    manifest = load_manifest(packet_dir)
    files = manifest.get("files", [])
    if not isinstance(files, list) or not files:
        raise SystemExit(f"FAIL: invalid/empty manifest files list in {packet_dir / 'packet_manifest.json'}")

    missing: List[str] = []
    mismatched: List[Tuple[str, str, str]] = []  # (rel, expected, got)

    for entry in files:
        rel = entry.get("path", "")
        exp = entry.get("sha256", "")
        size = entry.get("size", None)

        if not rel or not exp:
            raise SystemExit(f"FAIL: malformed manifest entry: {entry}")

        p = packet_dir / rel
        if not p.exists() or not p.is_file():
            missing.append(rel)
            continue

        got = sha256_file(p)
        if got != exp:
            mismatched.append((rel, exp, got))

        if isinstance(size, int):
            got_size = p.stat().st_size
            if got_size != size:
                mismatched.append((rel, f"size:{size}", f"size:{got_size}"))

    if missing or mismatched:
        print(f"PACKET_VERIFY: FAIL dir={packet_dir}")
        if missing:
            print(f"MISSING_FILES: {len(missing)}")
            for x in missing[:50]:
                print("  -", x)
        if mismatched:
            print(f"MISMATCHED: {len(mismatched)}")
            for rel, exp, got in mismatched[:50]:
                print(f"  - {rel} expected={exp} got={got}")
        raise SystemExit("FAIL: packet verification failed")

    print(f"PACKET_VERIFY: OK dir={packet_dir} files={len(files)}")


if __name__ == "__main__":
    main()
