"""tests/test_hft_ws_app_wiring.py — V16 Phase 4C Track B, HFT-1.

Covers api/app.py's get_hft_ws_client() singleton accessor and its use in
lifespan(): must return None (and start no background task) when
settings.HFT_WS_ENABLED is False (the default), and must construct exactly
one BinanceWSClient, wired to config.settings.settings.symbol_list, when
enabled. Does not test actual network connectivity — that's
data.binance_ws_client's own concern, covered in
tests/test_binance_ws_client.py.
"""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_singleton():
    """get_hft_ws_client() caches its result in a module-level global —
    reset it around every test so tests don't leak state into each other."""
    import api.app as app_module
    app_module._hft_ws_client = None
    yield
    app_module._hft_ws_client = None


def test_get_hft_ws_client_returns_none_when_flag_disabled(monkeypatch):
    from config.settings import settings
    import api.app as app_module
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", False)
    assert app_module.get_hft_ws_client() is None


def test_get_hft_ws_client_constructs_client_when_flag_enabled(monkeypatch):
    from config.settings import settings
    import api.app as app_module
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", True)
    monkeypatch.setattr(settings, "BINANCE_TESTNET", True)
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": 1_700_000_000_000},
    )
    client = app_module.get_hft_ws_client()
    from data.binance_ws_client import BinanceWSClient
    assert isinstance(client, BinanceWSClient)
    assert set(client._states.keys()) == set(settings.symbol_list)


def test_get_hft_ws_client_is_a_singleton_across_calls(monkeypatch):
    from config.settings import settings
    import api.app as app_module
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", True)
    monkeypatch.setattr(settings, "BINANCE_TESTNET", True)
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": 1_700_000_000_000},
    )
    first = app_module.get_hft_ws_client()
    second = app_module.get_hft_ws_client()
    assert first is second


def test_app_starts_and_serves_health_with_flag_disabled(monkeypatch):
    """Regression guard: importing/starting the app with the default
    (flag-off) config must behave exactly as before this phase — no HFT
    task, no HFT-related error, /api/health still responds."""
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", False)
    from api.app import app
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
