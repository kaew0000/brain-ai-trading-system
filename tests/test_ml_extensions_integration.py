"""
Tests for the remaining ML Extensions Integration Layer pieces:
  - ml/extensions_integration/config_bridge.py (ConfigBridge)
  - ml/extensions_integration/system_integrator.py (SystemIntegrator)
  - ml/extensions_integration/portfolio_adapter.py (PortfolioStateAdapter)
  - api/ml_extensions_api.py (the REST read layer)

Save/restore ML_EXTENSIONS_ENABLED around every test that touches it —
same pattern conftest.py's _default_auth_disabled_for_tests fixture and
tests/test_api_auth.py's auth_client() already use for
API_AUTH_ENABLED, so this composes correctly regardless of test order.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from ml.extensions_integration.config_bridge import ConfigBridge
from ml.extensions_integration.portfolio_adapter import PortfolioStateAdapter
from ml.extensions_integration.system_integrator import SystemIntegrator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_event_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


@pytest.fixture()
def ml_extensions_flag():
    """Save/restore ML_EXTENSIONS_ENABLED around a test."""
    orig = settings.ML_EXTENSIONS_ENABLED
    yield
    settings.ML_EXTENSIONS_ENABLED = orig


class TestConfigBridge:
    def test_is_enabled_reflects_settings_flag(self, ml_extensions_flag):
        settings.ML_EXTENSIONS_ENABLED = False
        assert ConfigBridge.is_enabled() is False
        settings.ML_EXTENSIONS_ENABLED = True
        assert ConfigBridge.is_enabled() is True

    def test_default_symbols_reuses_canonical_symbol_list(self):
        # Reuses settings.symbol_list — the ONE canonical
        # SYMBOL/SYMBOLS fallback, not a re-derived copy of it.
        assert ConfigBridge.default_symbols() == settings.symbol_list

    def test_build_extensions_config_uses_real_symbols(self):
        # ExtensionsConfig is defined in ml/extensions/orchestrator.py,
        # which — despite being a plain dataclass with zero RL logic of
        # its own — is only importable via ml/extensions/'s package
        # __init__.py, which eagerly imports RLAdapter and therefore
        # gymnasium (see ml/extensions_integration/__init__.py's module
        # docstring for the full story). Skips cleanly in any
        # environment without ml/extensions/requirements.txt installed
        # — e.g. CI, which correctly only installs the base
        # requirements.txt — rather than failing.
        pytest.importorskip("gymnasium")
        cfg = ConfigBridge.build_extensions_config()
        assert cfg.symbols == ConfigBridge.default_symbols()
        assert cfg.mode == "paper"

    def test_build_extensions_config_accepts_overrides(self):
        pytest.importorskip("gymnasium")
        cfg = ConfigBridge.build_extensions_config(rl_algorithm="SAC", hpo_n_trials=5)
        assert cfg.rl_algorithm == "SAC"
        assert cfg.hpo_n_trials == 5


class TestSystemIntegratorWiring:
    def test_disabled_by_default_returns_enabled_false(self, ml_extensions_flag):
        settings.ML_EXTENSIONS_ENABLED = False
        result = SystemIntegrator(ceo_agent=None).wire_all()
        assert result == {"enabled": False}

    def test_enabled_without_data_source_still_wires_agent(self, ml_extensions_flag):
        # No data_provider/historical_ohlcv — data_adapter ends up None,
        # but wiring itself must not fail (MLExtensionsAgent handles a
        # missing data_adapter gracefully, per its own tests). Requires
        # ExtensionsOrchestrator to actually construct, hence gymnasium
        # — see test_build_extensions_config_uses_real_symbols' comment
        # for why.
        pytest.importorskip("gymnasium")
        settings.ML_EXTENSIONS_ENABLED = True
        result = SystemIntegrator(ceo_agent=None).wire_all()
        assert result["enabled"] is True
        assert result["data_adapter"] is None
        assert result["agent"] is not None

    def test_enabled_registers_agent_with_ceo(self, ml_extensions_flag):
        pytest.importorskip("gymnasium")
        from agents import build_agent_layer

        settings.ML_EXTENSIONS_ENABLED = True
        layer = build_agent_layer()
        ceo = layer["ceo"]
        result = SystemIntegrator(ceo_agent=ceo).wire_all()
        assert result["enabled"] is True
        assert "ml_extensions" in ceo._agents
        assert ceo._agents["ml_extensions"] is result["agent"]

    def test_never_raises_on_internal_failure(self, ml_extensions_flag, monkeypatch):
        settings.ML_EXTENSIONS_ENABLED = True

        class BrokenDataProvider:
            def get_ohlcv(self, *a, **kw):
                raise RuntimeError("simulated exchange failure")

        result = SystemIntegrator(ceo_agent=None, data_provider=BrokenDataProvider()).wire_all()
        assert result["enabled"] is False
        assert "error" in result

    def test_degrades_gracefully_when_gymnasium_not_installed(self, ml_extensions_flag, monkeypatch):
        # Regression test for the exact bug CI caught on this phase's
        # first delivery: with ML_EXTENSIONS_ENABLED=true but the
        # optional ml/extensions/requirements.txt stack not installed,
        # wire_all() must return enabled=False with a clear error, never
        # raise. Doesn't need pytest.importorskip — it should PASS
        # specifically in an environment WITHOUT gymnasium, and is
        # written to still pass even if gymnasium happens to be present
        # (by forcing the import to fail via monkeypatch either way).
        settings.ML_EXTENSIONS_ENABLED = True
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "ml.extensions.orchestrator" or name.startswith("ml.extensions.orchestrator"):
                raise ModuleNotFoundError("No module named 'gymnasium'")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = SystemIntegrator(ceo_agent=None).wire_all()
        assert result["enabled"] is False
        assert "error" in result


class TestPortfolioStateAdapter:
    def test_no_sources_returns_safe_zeroed_defaults(self):
        adapter = PortfolioStateAdapter(portfolio_state=None, data_provider=None)
        state = adapter.get_state_for_rl()
        assert state["equity"] == 0.0
        assert state["balance"] == 0.0
        assert state["position"] == 0.0

    def test_reads_real_fields_when_sources_present(self):
        class FakeDataProvider:
            def get_account_balance(self):
                return 1000.0

        class FakePortfolioState:
            floating_pnl = 25.0
            risk_used = 0.4
            position_count = 2

            def portfolio_drawdown(self, balance):
                return 0.05

        adapter = PortfolioStateAdapter(portfolio_state=FakePortfolioState(), data_provider=FakeDataProvider())
        state = adapter.get_state_for_rl()
        assert state["balance"] == 1000.0
        assert state["equity"] == 1025.0
        assert state["position"] == 0.4
        assert state["unrealized_pnl"] == 25.0
        assert state["position_count"] == 2.0
        assert state["current_drawdown"] == 0.05

    def test_never_raises_when_a_source_errors(self):
        class BrokenDataProvider:
            def get_account_balance(self):
                raise RuntimeError("boom")

        adapter = PortfolioStateAdapter(portfolio_state=None, data_provider=BrokenDataProvider())
        state = adapter.get_state_for_rl()  # must not raise
        assert state["balance"] == 0.0


class TestMLExtensionsAPI:
    @pytest.fixture()
    def client(self):
        from api.app import app, set_state

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        set_state("ml_extensions", None)

    def test_status_honest_disabled_when_never_wired(self, client):
        r = client.get("/api/ml_extensions/status")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["enabled"] is False

    def test_status_enabled_when_wired(self, client):
        from api.app import set_state

        set_state("ml_extensions", {"enabled": True, "agent": object()})
        r = client.get("/api/ml_extensions/status")
        assert r.json()["data"]["enabled"] is True
        assert r.json()["data"]["agent_registered"] is True

    def test_rl_status_not_ready_when_no_orchestrator(self, client):
        r = client.get("/api/ml_extensions/rl/status")
        assert r.status_code == 200
        assert r.json()["data"]["ready"] is False

    def test_online_metrics_not_ready_when_no_orchestrator(self, client):
        r = client.get("/api/ml_extensions/online/metrics")
        assert r.status_code == 200
        assert r.json()["data"]["ready"] is False

    def test_hpo_status_not_ready_when_no_orchestrator(self, client):
        r = client.get("/api/ml_extensions/hpo/status")
        assert r.status_code == 200
        assert r.json()["data"]["ready"] is False

    def test_agent_last_report_not_ready_when_never_run(self, client):
        r = client.get("/api/ml_extensions/agent/last-report")
        assert r.status_code == 200
        assert r.json()["data"]["ready"] is False

    def test_agent_last_report_returns_real_report_after_run(self, client):
        from api.app import set_state
        from ml.extensions_integration.ml_extensions_agent import MLExtensionsAgent

        agent = MLExtensionsAgent(orchestrator=None, data_adapter=None)
        agent.run({"symbol": "BTCUSDT"})
        set_state("ml_extensions", {"enabled": True, "agent": agent})

        r = client.get("/api/ml_extensions/agent/last-report")
        body = r.json()["data"]
        assert body["ready"] is True
        assert body["report"]["agent"] == "ML_EXTENSIONS"
        assert body["report"]["symbol"] == "BTCUSDT"

    def test_status_endpoints_covered_by_default_viewer_auth(self, client):
        # /api/ml_extensions/* is not in _AUTH_PUBLIC_PATHS and not in
        # _AUTH_OPERATOR_ROUTES — confirms it's covered by the same
        # prefix-generic VIEWER-role _auth_middleware as every other
        # /api/* route, same claim api/execution_api.py's own docstring
        # makes for itself.
        import api.app as api_module

        assert ("GET", "/api/ml_extensions/status") not in api_module._AUTH_OPERATOR_ROUTES
        assert "/api/ml_extensions/status" not in api_module._AUTH_PUBLIC_PATHS
