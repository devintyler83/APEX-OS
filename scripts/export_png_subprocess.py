"""
Called by export_png.py via subprocess.run().
argv[1] = output PNG path
argv[2] = input HTML temp file path
Runs sync_playwright() in the main thread of a clean process.
"""
import sys
from pathlib import Path

def main():
    output_path = Path(sys.argv[1])
    html_path   = Path(sys.argv[2])
    html_str    = html_path.read_text(encoding="utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # Card dimensions — must match _CARD_WIDTH_PX / _CARD_HEIGHT_PX
        page = browser.new_page(viewport={"width": 800, "height": 1100})
        page.set_content(html_str, wait_until="networkidle")
        page.screenshot(path=str(output_path), full_page=False)
        browser.close()

    if not output_path.exists():
        print(f"ERROR: no file at {output_path}", file=sys.stderr)
        sys.exit(1)

    print(f"OK:{output_path}")
    sys.exit(0)

if __name__ == "__main__":
    main()
