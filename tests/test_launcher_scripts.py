"""tests/test_launcher_scripts.py — V16 Track W14-1 Item 11

.bat files can't be executed on this Linux sandbox, so these are
structural/text assertions on the canonical launcher's safety-critical
properties — guards against a future edit silently dropping the
explicit env-var set, the confirmation gate, or the crash-restart loop.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRunLiveBatIsCanonical:
    def _read(self) -> str:
        return (REPO_ROOT / "run_live.bat").read_text()

    def test_explicitly_sets_live_mode_not_relying_on_env_file(self):
        text = self._read()
        assert "set EXECUTION_MODE=live" in text
        assert "set BINANCE_TESTNET=false" in text

    def test_requires_typed_confirmation_before_starting(self):
        text = self._read()
        assert "set /p confirm=" in text
        assert 'if not "%confirm%"=="YES"' in text

    def test_has_crash_restart_loop_ported_from_run_bat(self):
        text = self._read()
        assert ":loop" in text
        assert "python main.py" in text
        assert "choice /c YN /m \"Restart bot in LIVE mode?\"" in text
        assert "goto loop" in text

    def test_env_vars_are_set_after_confirmation_not_before(self):
        # A stale .env must never be able to start LIVE trading before
        # the operator has explicitly confirmed — order matters here.
        text = self._read()
        confirm_idx = text.index('if not "%confirm%"=="YES"')
        env_idx = text.index("set EXECUTION_MODE=live")
        assert confirm_idx < env_idx


class TestRunBatNoLongerClaimsToBeTheLiveLauncher:
    def _read(self) -> str:
        return (REPO_ROOT / "run.bat").read_text()

    def test_does_not_claim_live_trading_banner(self):
        text = self._read()
        assert "LIVE TRADING" not in text

    def test_points_operators_to_run_live_bat(self):
        text = self._read()
        assert "run_live.bat" in text

    def test_still_has_its_crash_restart_loop(self):
        # Item 11 explicitly says port the loop INTO run_live.bat, not
        # remove it from run.bat — it's still useful dev/test tooling.
        text = self._read()
        assert ":loop" in text
        assert "python main.py" in text
        assert "goto loop" in text

    def test_does_not_set_execution_mode_itself(self):
        # run.bat is dev/test tooling that defers entirely to .env —
        # it must not silently override EXECUTION_MODE/BINANCE_TESTNET
        # (that would recreate two scripts independently deciding mode).
        text = self._read()
        assert "set EXECUTION_MODE=" not in text
        assert "set BINANCE_TESTNET=" not in text


class TestOtherLaunchersUntouched:
    """Item 11 hard scope: run_paper.*/run_testnet.* must not be
    deleted or have their engine-selection logic altered."""

    @pytest.mark.parametrize("name", ["run_paper.bat", "run_testnet.bat", "run_paper.sh", "run_testnet.sh"])
    def test_still_exists(self, name):
        assert (REPO_ROOT / name).exists()
