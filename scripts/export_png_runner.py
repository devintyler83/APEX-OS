"""
Standalone PNG export runner. Called via subprocess from app.py context.
Reads prospect JSON from stdin, writes PNG to path passed as argv[1].
"""
import sys
import json
from pathlib import Path

def main():
    output_path = Path(sys.argv[1])
    prospect = json.loads(sys.stdin.read())

    # Import here — this runs in a clean process, no event loop conflict
    from scripts.export_png import export_from_prospect_dict
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = export_from_prospect_dict(prospect, output_dir=tmpdir)
        import shutil
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result, output_path)
    print(f"OK:{output_path}")

if __name__ == "__main__":
    main()
