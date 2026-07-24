#!/usr/bin/env python3
"""
Brain Bot – Installation Script
================================
Run once before first use:

    python install.py

Steps:
  1. Install Python packages from requirements.txt
  2. Clone vendor repositories into vendors/
  3. Copy .env.example → .env  (if not already present)
  4. Verify all critical imports
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENDORS = os.path.join(ROOT, "vendors")
LOGS    = os.path.join(ROOT, "logs")

# Repos that are NOT available on PyPI and must be cloned
VENDOR_REPOS: dict[str, str] = {
    "binance_futures_bot": "https://github.com/conor19w/Binance-Futures-Trading-Bot.git",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: str | None = None, check: bool = True) -> bool:
    print(f"  $ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=cwd, check=check)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  [ERROR] command failed (exit {exc.returncode})")
        return False
    except FileNotFoundError as exc:
        print(f"  [ERROR] executable not found: {exc}")
        return False


def _section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Steps ─────────────────────────────────────────────────────────────────────

def step_pip() -> bool:
    _section("1 / 4  Installing Python packages")
    req = os.path.join(ROOT, "requirements.txt")
    return _run([sys.executable, "-m", "pip", "install", "-r", req, "--upgrade"])


def step_clone() -> None:
    _section("2 / 4  Cloning vendor repositories")
    os.makedirs(VENDORS, exist_ok=True)

    git_ok = shutil.which("git") is not None
    if not git_ok:
        print("  [WARNING] git not found on PATH – skipping repo clone.")
        print("  Install git from https://git-scm.com/ and re-run install.py")
        return

    for name, url in VENDOR_REPOS.items():
        dest = os.path.join(VENDORS, name)
        if os.path.isdir(dest):
            print(f"  {name}: already present – pulling latest …")
            _run(["git", "-C", dest, "pull"], check=False)
        else:
            print(f"  {name}: cloning …")
            _run(["git", "clone", "--depth", "1", url, dest], check=False)


def step_env() -> None:
    _section("3 / 4  Environment file")
    env_src = os.path.join(ROOT, ".env.example")
    env_dst = os.path.join(ROOT, ".env")
    if os.path.exists(env_dst):
        print("  .env already exists – leaving it untouched.")
    elif os.path.exists(env_src):
        shutil.copy(env_src, env_dst)
        print("  Created .env from .env.example")
        print("  >>> Edit .env and fill in BINANCE_API_KEY / BINANCE_API_SECRET <<<")
    else:
        print("  .env.example not found – create .env manually.")


def step_verify() -> bool:
    _section("4 / 4  Verifying imports")
    checks = [
        ("smartmoneyconcepts", "smc"),
        ("binance.um_futures",  "UMFutures"),
        ("pandas",              "pd"),
        ("numpy",               "np"),
        ("hmmlearn",            "hmm"),
        ("ta",                  "ta"),
        ("sklearn",             "sklearn"),
        ("colorlog",            "colorlog"),
        ("schedule",            "schedule"),
        ("dotenv",              "dotenv"),
        ("pydantic_settings",   "pydantic_settings"),
    ]
    all_ok = True
    for module, _ in checks:
        try:
            __import__(module)
            print(f"  ✓  {module}")
        except ImportError as exc:
            print(f"  ✗  {module}  –  {exc}")
            all_ok = False
    return all_ok


def step_dirs() -> None:
    """Ensure runtime directories exist."""
    for d in (VENDORS, LOGS):
        os.makedirs(d, exist_ok=True)
    # Create .gitkeep so git tracks the directories
    for d in (VENDORS, LOGS):
        gk = os.path.join(d, ".gitkeep")
        if not os.path.exists(gk):
            open(gk, "w").close()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Brain Bot BTCUSDT Futures – Installation")
    print("=" * 60)

    step_dirs()
    pip_ok     = step_pip()
    step_clone()
    step_env()
    import_ok  = step_verify()

    print("\n" + "=" * 60)
    if pip_ok and import_ok:
        print("  INSTALLATION COMPLETE")
        print()
        print("  Next steps:")
        print("    1.  Edit .env  →  add your Binance API keys")
        print("    2.  Set BINANCE_TESTNET=true for testing first")
        print("    3.  Run the bot:  python main.py")
        print("        or Windows:   run.bat / run_testnet.bat")
    else:
        print("  INSTALLATION HAD ERRORS – review output above")
    print("=" * 60)
