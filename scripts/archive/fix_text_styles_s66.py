"""
Session 66 validation script.
Scans app/app.py and scripts/generate_prospect_pdf_2026.py for:
  - Grey hex colors: #aaa, #888, #999, #666, #bbb, #777, #cccccc, #aaaaaa, etc.
  - font-style:italic inside injected HTML strings
  - font-size below 13px for body text in app (UI chrome labels exempt — see EXEMPT_PATTERNS)
  - font-size below 8px for any text in PDF

UI chrome exemptions (intentional small typography):
  - Uppercase section header labels: lines containing text-transform:uppercase
  - Letter-spaced labels: lines containing letter-spacing
  - Pill/badge spans: lines containing border-radius:999px
  - FM secondary badge: lines containing border-radius:6px;font-size:12px;font-weight:600 (tag pills)
  - Sub-labels under large values (Base/Adjusted): lines with font-size:11px where context is a sub-label

Exits 0 if no violations; prints all violations and exits 1 if any found.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

FILES = {
    "app/app.py": {"is_pdf": False},
    "scripts/generate_prospect_pdf_2026.py": {"is_pdf": True},
}

# Grey hex patterns to flag
GREY_PATTERNS = [
    r'#aaa\b',
    r'#888\b',
    r'#999\b',
    r'#666\b',
    r'#bbb\b',
    r'#777\b',
    r'#cccccc\b',
    r'#aaaaaa\b',
    r'#888888\b',
    r'#bbbbbb\b',
    r'#999999\b',
    r'#666666\b',
    r'#777777\b',
]

ITALIC_PATTERN = re.compile(r'font-style\s*:\s*italic', re.IGNORECASE)
SMALL_FONT_PATTERN = re.compile(r'font-size\s*:\s*(\d+(?:\.\d+)?)px', re.IGNORECASE)

# Lines containing any of these patterns are UI chrome — exempt from min-font-size check in app
APP_CHROME_EXEMPTIONS = [
    re.compile(r'text-transform\s*:\s*uppercase', re.IGNORECASE),
    re.compile(r'letter-spacing', re.IGNORECASE),
    re.compile(r'border-radius\s*:\s*999px', re.IGNORECASE),
    # FM/tag badges: small-font bold colored pills
    re.compile(r'font-weight\s*:\s*600.*border-radius|border-radius.*font-weight\s*:\s*600', re.IGNORECASE),
]


def is_inside_html_string(line: str) -> bool:
    """Heuristic: line contains html markup — style= or <div or <span etc."""
    return bool(re.search(r'style\s*=|<div|<span|<p\b|<td|<th|<tr|<table|font-size|color\s*:', line))


def is_chrome_exempt(line: str) -> bool:
    """Return True if line is intentional UI chrome (section header label, badge, etc.)."""
    for pat in APP_CHROME_EXEMPTIONS:
        if pat.search(line):
            return True
    return False


def check_file(fpath: Path, is_pdf: bool) -> list[str]:
    violations: list[str] = []
    lines = fpath.read_text(encoding="utf-8").splitlines()

    grey_compiled = [re.compile(p, re.IGNORECASE) for p in GREY_PATTERNS]

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        is_comment = stripped.startswith("#")

        if not is_comment and is_inside_html_string(line):
            # Grey check
            for pat, compiled in zip(GREY_PATTERNS, grey_compiled):
                if compiled.search(line):
                    violations.append(f"{fpath.name}:{lineno}: GREY {pat!r} — {line.rstrip()}")

            # Italic check
            if ITALIC_PATTERN.search(line):
                violations.append(f"{fpath.name}:{lineno}: ITALIC — {line.rstrip()}")

            # Font-size check
            for m in SMALL_FONT_PATTERN.finditer(line):
                size = float(m.group(1))
                if is_pdf:
                    # PDF: flag below 8px
                    if size < 8:
                        violations.append(
                            f"{fpath.name}:{lineno}: TINY_FONT {size}px (PDF min 8px) — {line.rstrip()}"
                        )
                else:
                    # App: flag below 13px, but exempt UI chrome labels
                    if size < 13 and not is_chrome_exempt(line):
                        violations.append(
                            f"{fpath.name}:{lineno}: SMALL_FONT {size}px (app min 13px) — {line.rstrip()}"
                        )

    return violations


def main() -> int:
    all_violations: list[str] = []

    for rel_path, meta in FILES.items():
        fpath = ROOT / rel_path
        if not fpath.exists():
            print(f"ERROR: {fpath} not found")
            return 1
        v = check_file(fpath, meta["is_pdf"])
        all_violations.extend(v)

    if all_violations:
        print(f"\nVIOLATIONS FOUND ({len(all_violations)}):\n")
        for v in all_violations:
            print(f"  {v}")
        print(f"\nTotal violations: {len(all_violations)}")
        return 1
    else:
        print("Total violations: 0")
        return 0


if __name__ == "__main__":
    sys.exit(main())
