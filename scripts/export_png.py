"""
DraftOS — export_png.py
PNG renderer for DraftOS share cards via html2image (headless Chrome/Chromium).

Usage:
    from scripts.export_png import export_from_prospect_dict
    png_path = export_from_prospect_dict(prospect_dict, output_dir="reports/")

    # CLI:
    python scripts/export_png.py /tmp/card.html /tmp/card.png

Requires:
    pip install html2image
    Chrome or Chromium must be installed (Streamlit Cloud: use packages.txt)
"""

import os
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# ── Card dimensions (match CSS .card width + body padding) ───────────────────
_CARD_WIDTH_PX  = 800
_CARD_HEIGHT_PX = 600

# Browser search order for Linux/cloud environments
_BROWSER_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

_HEADLESS_FLAGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--headless",
]


def _find_browser() -> str | None:
    """
    Return the first Chrome/Chromium executable found, or None on Windows
    (html2image auto-detects on Windows).
    """
    if sys.platform == "win32":
        return None  # let html2image locate Chrome via registry/PATH
    for candidate in _BROWSER_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "No Chrome/Chromium browser found. Checked:\n" +
        "\n".join(f"  {c}" for c in _BROWSER_CANDIDATES) +
        "\nOn Streamlit Cloud add a packages.txt with: chromium"
    )


# ── Core render function ──────────────────────────────────────────────────────

def render_html_to_png(html_str: str, output_path: str | Path) -> Path:
    """
    Render an HTML string to a PNG file using html2image (headless Chrome).

    Args:
        html_str:    Complete HTML string (self-contained, no external deps).
        output_path: Destination file path for the PNG.

    Returns:
        Path to the written PNG file.

    Raises:
        RuntimeError: If html2image is not installed or no browser is found.
    """
    try:
        from html2image import Html2Image
    except ImportError:
        raise RuntimeError(
            "html2image not installed. Run:\n"
            "  pip install html2image"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    browser_exe = _find_browser()
    kwargs = dict(
        custom_flags=_HEADLESS_FLAGS,
        output_path=str(output_path.parent),
    )
    if browser_exe is not None:
        kwargs["browser_executable"] = browser_exe

    hti = Html2Image(**kwargs)
    hti.screenshot(
        html_str=html_str,
        save_as=output_path.name,
        size=(_CARD_WIDTH_PX, _CARD_HEIGHT_PX),
    )

    return output_path


# ── Prospect dict entry point ─────────────────────────────────────────────────

def export_from_prospect_dict(
    prospect: dict,
    output_dir: str | Path = "reports/",
    filename: str | None = None,
) -> Path:
    """
    Generate a PNG share card from a prospect dict.

    Imports html_page() from export_reports_html_share at call time
    so this module can be imported standalone without the full scripts package.

    Args:
        prospect:   DraftOS prospect dict (same schema as html_page()).
        output_dir: Directory to write the PNG into (created if missing).
        filename:   Override output filename. Defaults to
                    "{prospect_id}_{slug}_{timestamp}.png".

    Returns:
        Path to the written PNG file.
    """
    try:
        _scripts_dir = str(Path(__file__).parent)
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from export_reports_html_share import html_page
    except ImportError:
        raise RuntimeError(
            "Could not import html_page from export_reports_html_share.\n"
            "Ensure export_reports_html_share.py is in the same directory as export_png.py."
        )

    html_str = html_page(prospect)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if filename is None:
        pid   = prospect.get("prospect_id", "0")
        name  = prospect.get("display_name", "prospect")
        slug  = name.lower().replace(" ", "_").replace("'", "")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{pid}_{slug}_{stamp}.png"

    output_path = output_dir / filename
    return render_html_to_png(html_str, output_path)


# ── Streamlit helper ──────────────────────────────────────────────────────────

def export_png_bytes(prospect: dict) -> bytes:
    """
    Generate PNG bytes in-memory for Streamlit st.download_button().

    Args:
        prospect: DraftOS prospect dict.

    Returns:
        PNG file contents as bytes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = export_from_prospect_dict(prospect, output_dir=tmpdir)
        return png_path.read_bytes()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    CLI usage:
        python scripts/export_png.py input.html output.png
        python scripts/export_png.py --test     # renders MOCK_RUEBEN_BAIN
    """
    if len(sys.argv) == 2 and sys.argv[1] == "--test":
        _scripts_dir = str(Path(__file__).parent)
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from export_reports_html_share import html_page, MOCK_RUEBEN_BAIN

        out_path = Path("reports/test_rueben_bain.png")
        result = render_html_to_png(html_page(MOCK_RUEBEN_BAIN), out_path)
        print(f"✓ Test card written: {result}")

    elif len(sys.argv) == 3:
        html_file   = Path(sys.argv[1])
        output_file = Path(sys.argv[2])
        html_content = html_file.read_text(encoding="utf-8")
        result = render_html_to_png(html_content, output_file)
        print(f"✓ PNG written: {result}")

    else:
        print("Usage:")
        print("  python scripts/export_png.py input.html output.png")
        print("  python scripts/export_png.py --test")
        sys.exit(1)
