"""
DraftOS — export_png.py
PNG renderer for DraftOS share cards via Playwright (headless Chromium).

Usage:
    from scripts.export_png import export_from_prospect_dict
    png_path = export_from_prospect_dict(prospect_dict, output_dir="reports/")

    # CLI:
    python scripts/export_png.py /tmp/card.html /tmp/card.png

Requires:
    pip install playwright
    playwright install chromium
"""

import asyncio
import os
import sys
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

# Playwright requires ProactorEventLoop on Windows (SelectorEventLoop has no subprocess transport)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ── Card dimensions (match CSS .card width + body padding) ───────────────────
_CARD_WIDTH_PX  = 800   # viewport width — card is 720px + body padding
_CARD_HEIGHT_PX = 600   # initial viewport; Playwright clips to actual content
_DEVICE_SCALE   = 2     # 2× for retina-quality PNG


# ── Core render function ──────────────────────────────────────────────────────

def render_html_to_png(html_str: str, output_path: str | Path) -> Path:
    """
    Render an HTML string to a PNG file using Playwright headless Chromium.

    Args:
        html_str:    Complete HTML string (self-contained, no external deps).
        output_path: Destination file path for the PNG.

    Returns:
        Path to the written PNG file.

    Raises:
        RuntimeError: If Playwright is not installed or Chromium launch fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write HTML to a temp file so Playwright can load it via file:// URI
    # (avoids any CSP issues with data URIs and embedded fonts)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(html_str)
        tmp_path = tmp.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            page = browser.new_page(
                viewport={"width": _CARD_WIDTH_PX, "height": _CARD_HEIGHT_PX},
                device_scale_factor=_DEVICE_SCALE,
            )

            # Load HTML from temp file path
            page.goto(f"file:///{tmp_path.replace(os.sep, '/')}")

            # Wait for fonts and layout to settle
            page.wait_for_load_state("networkidle", timeout=10_000)

            # Clip screenshot to the .card element for pixel-perfect output
            card = page.query_selector(".card")
            if card:
                card.screenshot(path=str(output_path), type="png")
            else:
                # Fallback: full-page screenshot
                page.screenshot(path=str(output_path), full_page=True, type="png")

            browser.close()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

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
    # Late import — keeps this module importable without the full DraftOS tree
    try:
        # Try scripts-relative import first (C:\DraftOS\scripts\)
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
        # Self-test with mock prospect
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