"""V16 §88: training lane (a) wall-clock timeout for stuck positions, (b) opt-out
exploratory entries below the live confidence threshold (training lane ONLY)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config.settings import settings
from paper.paper_account import PaperAccount
from paper.paper_execution import PaperExecutionEngine
from training_lane.training_lane_runner import TrainingLaneRunner

pytestmark = pytest.mark.unit


def _engine_with_position(age_hours: float):
    eng = PaperExecutionEngine(account=PaperAccount(balance=100.0), timeout_bars=10_000)
    eng.execute(SimpleNamespace(action="SHORT", entry_price=80_000.0,
                                stop_loss=82_000.0, take_profit=76_000.0), symbol="BTCUSDT")
    eng.open_positions[0].opened_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return eng


def test_close_expired_closes_only_old_positions():
    eng = _engine_with_position(30)
    closed = eng.close_expired(80_100.0, max_age_seconds=24 * 3600)
    assert len(closed) == 1 and closed[0].close_reason == "TIMEOUT"
    assert eng.open_positions == []
    assert eng.account.margin_used == pytest.approx(0.0, abs=1e-9) if hasattr(eng.account, "margin_used") else True


def test_close_expired_keeps_young_positions():
    eng = _engine_with_position(1)
    assert eng.close_expired(80_100.0, max_age_seconds=24 * 3600) == []
    assert len(eng.open_positions) == 1


def _runner(monkeypatch, provider, *, explore=True, min_conf=55):
    monkeypatch.setattr(settings, "BACKGROUND_TRAINING_EXPLORE_ENABLED", explore)
    monkeypatch.setattr(settings, "BACKGROUND_TRAINING_EXPLORE_MIN_CONFIDENCE", min_conf)
    r = TrainingLaneRunner.__new__(TrainingLaneRunner)
    r._signal_provider = provider
    return r


def _swc(action, conf, direction="SHORT"):
    cr = SimpleNamespace(action=action, confidence=conf, direction=direction,
                         entry_price=80_000.0, stop_loss=81_000.0, take_profit=78_000.0,
                         blocked=(action == "BLOCKED"))
    return SimpleNamespace(signal=None, market_context={}, confidence_result=cr)


def _provider(swc):
    p = MagicMock()
    p.get_signal_with_context.return_value = swc
    return p


def test_wait_above_floor_becomes_exploratory_entry(monkeypatch):
    r = _runner(monkeypatch, _provider(_swc("WAIT", 60)))
    sig = r._get_entry_signal("BTCUSDT")
    assert sig is not None and sig.direction == -1


def test_below_floor_stays_no_trade(monkeypatch):
    r = _runner(monkeypatch, _provider(_swc("WAIT", 54)))
    assert r._get_entry_signal("BTCUSDT") is None


def test_blocked_and_skip_never_explored(monkeypatch):
    for action in ("BLOCKED", "SKIP"):
        r = _runner(monkeypatch, _provider(_swc(action, 90)))
        assert r._get_entry_signal("BTCUSDT") is None


def test_flag_off_matches_old_behaviour(monkeypatch):
    prov = _provider(_swc("WAIT", 70))
    prov.return_value = None          # plain strategy call: WAIT -> no signal
    r = _runner(monkeypatch, prov, explore=False)
    assert r._get_entry_signal("BTCUSDT") is None
    prov.get_signal_with_context.assert_not_called()


def test_real_signal_passes_through_untouched(monkeypatch):
    real = SimpleNamespace(direction=1, entry_price=1.0, stop_loss=0.9, take_profit=1.2)
    swc = _swc("LONG", 80)
    swc.signal = real
    r = _runner(monkeypatch, _provider(swc))
    assert r._get_entry_signal("BTCUSDT") is real


def test_provider_without_context_api_falls_back(monkeypatch):
    plain = MagicMock(spec=["__call__"])
    plain.return_value = None
    r = _runner(monkeypatch, plain)
    assert r._get_entry_signal("BTCUSDT") is None
    plain.assert_called_once_with("BTCUSDT")
