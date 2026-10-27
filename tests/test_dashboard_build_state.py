"""
tests/test_dashboard_build_state.py — V16 §84

Regression coverage for the stale-dashboard-build gap: PR #116's launcher only
built dashboard_src/dist when it was MISSING, so after `git pull` an old build
(made before §81-§83) kept being served and the World page ran stale code.

scripts/dashboard_build_state.py decides fresh / build / install_build from file
mtimes (stdlib only, read-only). scripts/ensure_dashboard.bat consumes it; the
.bat itself cannot be executed on non-Windows CI, so it is checked statically.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "scripts" / "dashboard_build_state.py"
BAT = REPO / "scripts" / "ensure_dashboard.bat"


def _load():
    spec = importlib.util.spec_from_file_location("dashboard_build_state", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _touch(path: Path, mtime: float, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def dash(tmp_path):
    """A dashboard_src layout whose dist and node_modules are newer than sources."""
    d = tmp_path / "dashboard_src"
    _touch(d / "index.html", 1000)
    _touch(d / "package.json", 1000)
    _touch(d / "package-lock.json", 1000)
    _touch(d / "src" / "main.tsx", 1000)
    _touch(d / "node_modules" / ".package-lock.json", 2000)
    _touch(d / "dist" / "index.html", 3000)
    return d


class TestState:
    def test_missing_dist_is_install_build(self, tmp_path):
        d = tmp_path / "dashboard_src"
        _touch(d / "src" / "main.tsx", 1000)
        assert mod.dashboard_build_state(d) == "install_build"

    def test_fresh_when_dist_newer_than_all_inputs(self, dash):
        assert mod.dashboard_build_state(dash) == "fresh"

    def test_stale_source_triggers_build_only(self, dash):
        _touch(dash / "src" / "pages" / "world" / "WorldPage.tsx", 4000)
        assert mod.dashboard_build_state(dash) == "build"

    def test_stale_lockfile_triggers_install_build(self, dash):
        _touch(dash / "package-lock.json", 4000)
        assert mod.dashboard_build_state(dash) == "install_build"

    def test_missing_node_modules_triggers_install_build_when_stale(self, dash):
        _touch(dash / "src" / "main.tsx", 4000)
        (dash / "node_modules" / ".package-lock.json").unlink()
        assert mod.dashboard_build_state(dash) == "install_build"

    def test_missing_node_modules_alone_is_not_a_rebuild_when_fresh(self, dash):
        (dash / "node_modules" / ".package-lock.json").unlink()
        assert mod.dashboard_build_state(dash) == "fresh"

    def test_test_files_do_not_mark_build_stale(self, dash):
        _touch(dash / "src" / "pages" / "world" / "tests" / "world.test.ts", 4000)
        _touch(dash / "src" / "lib" / "api.spec.ts", 4000)
        _touch(dash / "src" / "lib" / "tests" / "api.test.ts", 4000)
        assert mod.dashboard_build_state(dash) == "fresh"

    def test_node_modules_and_dist_changes_are_ignored(self, dash):
        _touch(dash / "node_modules" / "pkg" / "index.js", 4000)
        _touch(dash / "dist" / "assets" / "app.js", 2500)
        assert mod.dashboard_build_state(dash) == "fresh"

    def test_equal_mtime_counts_as_fresh(self, dash):
        _touch(dash / "src" / "main.tsx", 3000)
        assert mod.dashboard_build_state(dash) == "fresh"

    def test_public_assets_count_as_inputs(self, dash):
        _touch(dash / "public" / "favicon.svg", 4000)
        assert mod.dashboard_build_state(dash) == "build"


class TestCli:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(HELPER), *args], capture_output=True, text=True, timeout=30
        )

    def test_prints_single_token_and_exits_zero(self, dash):
        _touch(dash / "src" / "main.tsx", 4000)
        r = self._run(str(dash))
        assert r.returncode == 0
        assert r.stdout.strip() == "build"

    def test_nonexistent_dir_does_not_crash(self, tmp_path):
        r = self._run(str(tmp_path / "nope"))
        assert r.returncode == 0
        assert r.stdout.strip() == "install_build"  # dist missing -> legacy build path

    def test_real_repo_dashboard_returns_known_token(self):
        r = self._run()
        assert r.returncode == 0
        assert r.stdout.strip() in {"fresh", "build", "install_build", "error"}

    def test_helper_is_read_only(self, dash):
        before = sorted((p, p.stat().st_mtime) for p in dash.rglob("*") if p.is_file())
        mod.dashboard_build_state(dash)
        after = sorted((p, p.stat().st_mtime) for p in dash.rglob("*") if p.is_file())
        assert before == after


@pytest.fixture(scope="module")
def bat():
    return BAT.read_text(encoding="utf-8")


class TestLauncherStatic:
    """ensure_dashboard.bat can't run on Linux CI; guard the contract instead."""

    def test_uses_helper_and_handles_all_states(self, bat):
        assert "dashboard_build_state.py" in bat
        for token in ("fresh", "build", "install_build"):
            assert token in bat

    def test_keeps_legacy_missing_dist_fallback(self, bat):
        # helper unavailable -> still builds when dist is missing (PR #116 behaviour)
        assert 'if exist "%DIST_INDEX%" exit /b 0' in bat
        assert 'set "STATE=install_build"' in bat

    def test_never_fatal_for_the_launchers(self, bat):
        assert "exit /b 1" not in bat
        assert bat.rstrip().endswith("exit /b 0")

    def test_restores_previous_build_when_rebuild_fails(self, bat):
        assert "BAK" in bat and "restored the previous build" in bat

    def test_opt_out_env_var_documented_and_honoured(self, bat):
        assert bat.count("BRAIN_DASHBOARD_AUTOREBUILD") >= 2

    @pytest.mark.parametrize(
        "launcher", ["run.bat", "run_live.bat", "run_paper.bat", "run_testnet.bat"]
    )
    def test_every_launcher_still_calls_ensure_dashboard(self, launcher):
        text = (REPO / launcher).read_text(encoding="utf-8")
        assert "scripts\\ensure_dashboard.bat" in text
