"""tests/test_hft_shadow_mode.py — V16 Phase 4C Track B, HFT-4.

The single most important test in this phase: proves that wiring a real,
extreme, non-neutral HFT flow snapshot all the way through
MarketContextBuilder.build() -> market_context["futures"]["hft_flow"]
produces a BYTE-IDENTICAL ConfidenceEngine.score() result compared to
building the exact same context with no ws_snapshot at all. This is the
mechanical verification of "shadow mode: NO trading impact" — not just an
absence of wiring into ConfidenceEngine (which would be a weaker,
implementation-detail claim), but a direct assertion on the actual
decision-relevant output.

Also covers: backward compatibility (main.py's _get_hft_ws_snapshot()
never raises, even with the flag on and no client/snapshot available),
and that a valid snapshot's data really does reach
market_context["futures"]["hft_flow"] (i.e. the wiring isn't a no-op that
would make the "no impact" test vacuously true).
"""
import pytest

from data.binance_ws_client import SymbolWSSnapshot, TradeEvent
from decision.confidence_engine import ConfidenceEngine
from intelligence.market_context_builder import MarketContextBuilder

pytestmark = pytest.mark.unit


def _market_data():
    return {
        "mark_price":       67000.0,
        "prev_mark_price":  67000.0 * 0.999,
        "funding_rate":     0.0001,
        "oi_delta":         0.015,
        "open_interest":    15000.0,
        "long_short_ratio": {"longShortRatio": "1.05"},
        "taker_ratio":      {"buySellRatio": "1.10"},
    }


def _smc_signals(bullish=True):
    from features.smc_engine import SMCSignals
    sig = SMCSignals()
    sig.bos = True
    sig.bos_direction = "Bullish" if bullish else "Bearish"
    sig.trend_bias = "Bullish" if bullish else "Bearish"
    sig.choch = True
    sig.choch_direction = "Bullish" if bullish else "Bearish"
    return sig


def _regime():
    from regime.regime_engine import RegimeResult
    r = RegimeResult()
    r.regime = "TREND"
    r.confidence = 0.85
    r.adx = 32.0
    r.bb_width = 0.003
    r.atr_normalized = 0.002
    r.probabilities = {"TREND": 0.85, "RANGE": 0.10, "HIGH_VOLATILITY": 0.05}
    return r


def _volume_signals(spike=True):
    from features.volume_engine import VolumeSignals
    v = VolumeSignals()
    v.volume_spike = spike
    v.volume_ratio = 2.1 if spike else 0.8
    v.obv_direction = "bullish"
    v.score = 2
    return v


def _extreme_bullish_ws_snapshot():
    """Deliberately extreme, one-sided book + trade flow, designed to
    produce the largest possible non-neutral hft_flow.score/.state — if
    THIS doesn't move ConfidenceEngine's output, nothing subtler would
    either."""
    now_ms = int(__import__("time").time() * 1000)
    return SymbolWSSnapshot(
        symbol="BTCUSDT",
        best_bid=67000.0,
        best_ask=67000.5,
        bid_levels=[(67000.0, 500.0)],
        ask_levels=[(67000.5, 1.0)],
        recent_trades=[TradeEvent(67000.0, 50.0, is_buyer_maker=False, trade_time_ms=now_ms)],
        book_valid=True,
        sequence_valid=True,
        stream_connected=True,
        data_age_ms=10,
    )


def _build_context(ws_snapshot=None):
    builder = MarketContextBuilder()
    return builder.build(
        market_data=_market_data(),
        smc_signals={"h4": _smc_signals(), "h1": _smc_signals(), "m15": _smc_signals()},
        volume_signals=_volume_signals(),
        regime_result=_regime(),
        ws_snapshot=ws_snapshot,
    )


# ── The core "no trading impact" proof ────────────────────────────────────

def test_extreme_hft_flow_produces_identical_confidence_result():
    ctx_without = _build_context(ws_snapshot=None)
    ctx_with = _build_context(ws_snapshot=_extreme_bullish_ws_snapshot())

    # Sanity precondition: the wiring actually did something — otherwise
    # this whole test would be proving nothing. See the next test too.
    assert ctx_without["futures"]["hft_flow"]["feature_confidence"] == 0.0
    assert ctx_with["futures"]["hft_flow"]["feature_confidence"] == 1.0
    assert ctx_with["futures"]["hft_flow"]["score"] != 0.0

    ce = ConfidenceEngine()
    direction = ctx_without.get("mtf_direction", "") or "LONG"

    result_without = ce.score(market_context=ctx_without, direction=direction,
                               entry_price=67000.0, stop_loss=66000.0, take_profit=69000.0)
    result_with = ce.score(market_context=ctx_with, direction=direction,
                            entry_price=67000.0, stop_loss=66000.0, take_profit=69000.0)

    # The decision-relevant outputs must be identical regardless of the
    # extreme HFT flow reading — this is the actual "no trading impact"
    # claim (updated for HFT-5: with the default weight of 0.0, breakdown
    # legitimately GAINS a diagnostic "hft_flow": 0 entry whenever real WS
    # data is present, per design — that's intended visibility, not a
    # trading-relevant difference, so it's checked separately below rather
    # than folded into a blanket dict-equality assertion).
    assert result_without.action == result_with.action
    assert result_without.confidence == result_with.confidence
    assert "hft_flow" not in result_without.breakdown
    assert result_with.breakdown.get("hft_flow") == 0
    # Every other category's points must be byte-identical too.
    shared_keys = set(result_without.breakdown) & set(result_with.breakdown)
    assert shared_keys == set(result_without.breakdown)   # nothing else differs
    for key in shared_keys:
        assert result_without.breakdown[key] == result_with.breakdown[key]


def test_extreme_bearish_hft_flow_also_produces_identical_result():
    """Same proof, opposite direction — confirms the null result above
    isn't an artifact of one particular score sign."""
    now_ms = int(__import__("time").time() * 1000)
    bearish_snapshot = SymbolWSSnapshot(
        symbol="BTCUSDT", best_bid=67000.0, best_ask=67000.5,
        bid_levels=[(67000.0, 1.0)], ask_levels=[(67000.5, 500.0)],
        recent_trades=[TradeEvent(67000.0, 50.0, is_buyer_maker=True, trade_time_ms=now_ms)],
        book_valid=True, sequence_valid=True, stream_connected=True, data_age_ms=10,
    )
    ctx_without = _build_context(ws_snapshot=None)
    ctx_with = _build_context(ws_snapshot=bearish_snapshot)
    assert ctx_with["futures"]["hft_flow"]["score"] < 0

    ce = ConfidenceEngine()
    direction = ctx_without.get("mtf_direction", "") or "LONG"
    result_without = ce.score(market_context=ctx_without, direction=direction)
    result_with = ce.score(market_context=ctx_with, direction=direction)
    assert result_without.action == result_with.action
    assert result_without.confidence == result_with.confidence


# ── Confirm the wiring actually reaches market_context (not a silent no-op) ─

def test_ws_snapshot_flows_through_to_market_context():
    ctx = _build_context(ws_snapshot=_extreme_bullish_ws_snapshot())
    hft = ctx["futures"]["hft_flow"]
    assert hft["feature_confidence"] == 1.0
    assert hft["depth_imbalance"] > 0.9   # near-total bid-side dominance
    assert hft["score"] > 0


def test_omitting_ws_snapshot_leaves_market_context_hft_flow_inert():
    ctx = _build_context(ws_snapshot=None)
    hft = ctx["futures"]["hft_flow"]
    assert hft["feature_confidence"] == 0.0
    assert hft["score"] == 0.0
    assert hft["state"] == "NEUTRAL"


# ── main.py's _get_hft_ws_snapshot() safety wrapper ──────────────────────

def test_get_hft_ws_snapshot_returns_none_when_flag_disabled(monkeypatch):
    from config.settings import settings
    import main
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", False)
    assert main._get_hft_ws_snapshot("BTCUSDT") is None


def test_get_hft_ws_snapshot_never_raises_when_client_unavailable(monkeypatch):
    """Flag on, but api.app.get_hft_ws_client() raises (e.g. mid-startup,
    or a genuine bug in that path) — this helper must swallow it and
    return None, never propagate into the trading cycle."""
    from config.settings import settings
    import main
    import api.app
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", True)

    def _raise():
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(api.app, "get_hft_ws_client", _raise)
    assert main._get_hft_ws_snapshot("BTCUSDT") is None


def test_get_hft_ws_snapshot_returns_none_when_client_returns_none(monkeypatch):
    from config.settings import settings
    import main
    import api.app
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", True)
    monkeypatch.setattr(api.app, "get_hft_ws_client", lambda: None)
    assert main._get_hft_ws_snapshot("BTCUSDT") is None


def test_get_hft_ws_snapshot_returns_real_snapshot_when_available(monkeypatch):
    from config.settings import settings
    import main
    import api.app
    monkeypatch.setattr(settings, "HFT_WS_ENABLED", True)
    expected = _extreme_bullish_ws_snapshot()

    class _FakeClient:
        @staticmethod
        def get_snapshot(symbol):
            assert symbol == "BTCUSDT"
            return expected

    monkeypatch.setattr(api.app, "get_hft_ws_client", lambda: _FakeClient())
    result = main._get_hft_ws_snapshot("BTCUSDT")
    assert result is expected
