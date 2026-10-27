"""Report whether the V16 dashboard build (dashboard_src/dist) needs rebuilding.

Why this exists
---------------
``dashboard_src/dist/`` is git-ignored and is served by ``api/app.py`` as-is.
``scripts/ensure_dashboard.bat`` (PR #116) only built it when ``dist`` was
*missing*, so after ``git pull`` an old build kept being served and every new
dashboard page/fix was invisible (observed: a build from before §81-§83 served
against a repo at §83 -> the World page loaded with stale code and 401s).

This helper compares source mtimes with ``dist/index.html`` and prints exactly
one token on stdout, so the .bat launcher can branch without any PowerShell:

    fresh          dist exists and is newer than every build input
    build          sources changed -> ``npm run build`` is enough
    install_build  dist missing, or package.json / package-lock.json changed
                   (or node_modules absent) -> ``npm ci`` then build

It never raises and always exits 0; on any unexpected error it prints
``error`` so the launcher can fall back to the legacy "build only if missing"
behaviour. Standard library only; read-only (never writes or deletes).

Usage:  python scripts/dashboard_build_state.py [path/to/dashboard_src]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Launcher/tooling constants (not runtime trading config) -- kept together here.
SOURCE_DIRS: tuple[str, ...] = ("src", "public")
SOURCE_FILES: tuple[str, ...] = (
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.node.json",
    "tailwind.config.cjs",
    "postcss.config.cjs",
)
DEPS_FILES: tuple[str, ...] = ("package.json", "package-lock.json")
# Directories / files that never affect the production bundle.
IGNORED_DIR_NAMES: frozenset[str] = frozenset({"tests", "__tests__", "node_modules"})
IGNORED_FILE_MARKERS: tuple[str, ...] = (".test.", ".spec.")

STATE_FRESH = "fresh"
STATE_BUILD = "build"
STATE_INSTALL_BUILD = "install_build"
STATE_ERROR = "error"


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _is_ignored_file(name: str) -> bool:
    return any(marker in name for marker in IGNORED_FILE_MARKERS)


def newest_source_mtime(dashboard_dir: Path) -> float:
    """Newest mtime among build inputs (0.0 when none exist)."""
    newest = 0.0
    for name in SOURCE_FILES:
        m = _mtime(dashboard_dir / name)
        if m is not None and m > newest:
            newest = m
    for sub in SOURCE_DIRS:
        root = dashboard_dir / sub
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIR_NAMES]
            for fname in filenames:
                if _is_ignored_file(fname):
                    continue
                m = _mtime(Path(dirpath) / fname)
                if m is not None and m > newest:
                    newest = m
    return newest


def _deps_need_install(dashboard_dir: Path) -> bool:
    """True when node_modules is absent or older than package.json / lockfile."""
    # npm writes this marker on every successful `npm ci` / `npm install`.
    marker = _mtime(dashboard_dir / "node_modules" / ".package-lock.json")
    if marker is None:
        return True
    for name in DEPS_FILES:
        m = _mtime(dashboard_dir / name)
        if m is not None and m > marker:
            return True
    return False


def dashboard_build_state(dashboard_dir: Path) -> str:
    """Return one of fresh / build / install_build (see module docstring)."""
    dist_index = _mtime(dashboard_dir / "dist" / "index.html")
    if dist_index is None:
        return STATE_INSTALL_BUILD  # legacy behaviour: missing -> npm ci + build
    if newest_source_mtime(dashboard_dir) <= dist_index:
        return STATE_FRESH
    return STATE_INSTALL_BUILD if _deps_need_install(dashboard_dir) else STATE_BUILD


def main(argv: list[str]) -> int:
    try:
        default = Path(__file__).resolve().parent.parent / "dashboard_src"
        target = Path(argv[1]) if len(argv) > 1 else default
        print(dashboard_build_state(target))
    except Exception:  # noqa: BLE001 - launcher helper must never break startup
        print(STATE_ERROR)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
