from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """
    Deterministically locate repo root by walking upward until pyproject.toml is found.
    This avoids relying on CWD, which is not stable across entrypoints.
    """
    cur = start.resolve()
    for _ in range(20):
        if (cur / "pyproject.toml").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError("DraftOS repo root not found (pyproject.toml missing in parent chain).")


@dataclass(frozen=True)
class Paths:
    root: Path
    db: Path
    imports: Path
    exports: Path


def _build_paths() -> Paths:
    env_root = os.environ.get("DRAFTOS_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
    else:
        # config.py lives at draftos/config.py, so repo root is 1 level above /draftos
        root = _find_repo_root(Path(__file__).parent)

    db = root / "data" / "edge" / "draftos.sqlite"
    imports = root / "data" / "imports"
    exports = root / "data" / "exports"
    return Paths(root=root, db=db, imports=imports, exports=exports)


PATHS = _build_paths()