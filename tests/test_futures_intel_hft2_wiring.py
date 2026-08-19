"""tests/test_futures_intel_hft2_wiring.py — V16 Phase 4C Track B, HFT-2.

Covers futures/futures_intel_engine.py's new optional `ws_snapshot`
parameter on analyse(): must be fully backward compatible when omitted
(existing behavior, existing tests in tests/test_phase3.py already cover
this), and must correctly populate `result.hft_flow` when passed, without
disturbing any of the existing REST-derived fields.
"""
import pytest

from data.binance_ws_client import SymbolWSSnapshot, TradeEvent
from futures.futures_intel_engine import FuturesIntelEngine

pytestmark = pytest.mark.unit


def _snapshot(symbol="BTCUSDT", best_bid=100.0, best_ask=100.5, recent_trades=None):
    return SymbolWSSnapshot(
        symbol=symbol,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_levels=[(100.0, 2.0)],
        ask_levels=[(100.5, 2.0)],
        recent_trades=recent_trades if recent_trades is not None else [],
        book_valid=True,
        sequence_valid=True,
        stream_connected=True,
        data_age_ms=50,
    )


def _market_data():
    return {
        "mark_price": 67000.0,
        "funding_rate": 0.0001,
        "oi_delta": 0.005,
        "open_interest": 1_000_000,
        "long_short_ratio": {"longShortRatio": "1.1"},
        "taker_ratio": {"buySellRatio": "1.05"},
    }


def test_omitting_ws_snapshot_leaves_hft_flow_at_default():
    engine = FuturesIntelEngine()
    result = engine.analyse(_market_data())
    assert result.hft_flow.feature_confidence == 0.0
    assert result.hft_flow.book_valid is False


def test_passing_ws_snapshot_populates_hft_flow():
    engine = FuturesIntelEngine()
    snap = _snapshot(best_bid=100.0, best_ask=101.0)
    result = engine.analyse(_market_data(), ws_snapshot=snap)
    assert result.hft_flow.feature_confidence == 1.0
    assert result.hft_flow.spread == pytest.approx(1.0)
    assert result.hft_flow.mid_price == pytest.approx(100.5)


def test_ws_snapshot_does_not_disturb_existing_rest_derived_fields():
    engine = FuturesIntelEngine()
    md = _market_data()
    result_without = engine.analyse(md)
    result_with = FuturesIntelEngine().analyse(md, ws_snapshot=_snapshot())
    assert result_without.funding == result_with.funding
    assert result_without.open_interest == result_with.open_interest
    assert result_without.long_short == result_with.long_short
    assert result_without.taker == result_with.taker
    assert result_without.extensions == result_with.extensions


def test_extensions_dict_unchanged_regardless_of_ws_snapshot():
    """Legacy extensions dict must stay exactly 'NOT_IMPLEMENTED' even when
    a ws_snapshot IS passed — the real data now lives in hft_flow, not in
    a mutated extensions dict, per the module docstring's backward-
    compatibility note."""
    engine = FuturesIntelEngine()
    result = engine.analyse(_market_data(), ws_snapshot=_snapshot())
    assert result.extensions == {
        "orderbook_imbalance": "NOT_IMPLEMENTED",
        "cvd": "NOT_IMPLEMENTED",
        "liquidation_heatmap": "NOT_IMPLEMENTED",
    }


def test_hft_flow_populated_even_when_market_data_empty():
    engine = FuturesIntelEngine()
    result = engine.analyse({}, ws_snapshot=_snapshot())
    assert result.hft_flow.feature_confidence == 1.0


def test_to_dict_includes_hft_flow_with_rounded_floats():
    engine = FuturesIntelEngine()
    now_ms = int(__import__("time").time() * 1000)
    trades = [TradeEvent(price=100.0, qty=1.23456789, is_buyer_maker=False, trade_time_ms=now_ms)]
    snap = _snapshot(recent_trades=trades)
    result = engine.analyse(_market_data(), ws_snapshot=snap)
    d = result.to_dict()
    assert "hft_flow" in d
    assert isinstance(d["hft_flow"]["aggressive_buy_volume"], float)
    # 6-decimal rounding applied, matching the rest of to_dict()'s convention
    assert d["hft_flow"]["aggressive_buy_volume"] == round(1.23456789, 6)


def test_engine_reuses_same_microstructure_state_across_analyse_calls():
    """A single FuturesIntelEngine instance must keep one persistent
    MicrostructureEngine so CVD accumulates correctly across cycles — a
    fresh MicrostructureEngine per call would make cvd meaningless."""
    engine = FuturesIntelEngine()
    t1 = [TradeEvent(price=100.0, qty=5.0, is_buyer_maker=False, trade_time_ms=1000)]
    r1 = engine.analyse(_market_data(), ws_snapshot=_snapshot(recent_trades=t1))
    t2 = t1 + [TradeEvent(price=100.0, qty=3.0, is_buyer_maker=False, trade_time_ms=1500)]
    r2 = engine.analyse(_market_data(), ws_snapshot=_snapshot(recent_trades=t2))
    assert r2.hft_flow.cvd == pytest.approx(r1.hft_flow.cvd + 3.0)
