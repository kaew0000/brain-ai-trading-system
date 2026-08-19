"""tests/test_microstructure_engine.py — V16 Phase 4C Track B, HFT-2.

Covers features/microstructure_engine.py: depth_imbalance, aggressive
buy/sell volume, delta, cumulative CVD (+ EMA slope), trade_intensity,
spread/mid_price, and the feature_confidence validity gate. Pure
synchronous unit tests — no network, no asyncio.
"""
import pytest

from data.binance_ws_client import SymbolWSSnapshot, TradeEvent
from features.microstructure_engine import HFTFlowSignal, MicrostructureEngine

pytestmark = pytest.mark.unit


def _trade(price, qty, is_buyer_maker, trade_time_ms):
    return TradeEvent(price=price, qty=qty, is_buyer_maker=is_buyer_maker, trade_time_ms=trade_time_ms)


def _snapshot(
    symbol="BTCUSDT",
    best_bid=100.0,
    best_ask=100.5,
    bid_levels=None,
    ask_levels=None,
    recent_trades=None,
    book_valid=True,
    sequence_valid=True,
    stream_connected=True,
    data_age_ms=50,
):
    return SymbolWSSnapshot(
        symbol=symbol,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_levels=bid_levels if bid_levels is not None else [(100.0, 2.0), (99.5, 3.0)],
        ask_levels=ask_levels if ask_levels is not None else [(100.5, 2.0), (101.0, 3.0)],
        recent_trades=recent_trades if recent_trades is not None else [],
        book_valid=book_valid,
        sequence_valid=sequence_valid,
        stream_connected=stream_connected,
        data_age_ms=data_age_ms,
    )


def _engine(depth_levels=10, trade_window_seconds=10, cvd_ema_alpha=0.3):
    return MicrostructureEngine(
        depth_levels=depth_levels, trade_window_seconds=trade_window_seconds, cvd_ema_alpha=cvd_ema_alpha
    )


# ── Spread / mid_price ────────────────────────────────────────────────────

def test_spread_and_mid_price_computed_from_best_bid_ask():
    engine = _engine()
    snap = _snapshot(best_bid=100.0, best_ask=101.0)
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.spread == 1.0
    assert sig.mid_price == 100.5


def test_spread_and_mid_price_zero_when_book_incomplete():
    engine = _engine()
    snap = _snapshot(best_bid=None, best_ask=101.0)
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.spread == 0.0
    assert sig.mid_price == 0.0


# ── Depth imbalance ──────────────────────────────────────────────────────

def test_depth_imbalance_balanced_book_is_zero():
    engine = _engine()
    snap = _snapshot(bid_levels=[(100.0, 5.0)], ask_levels=[(100.5, 5.0)])
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.depth_imbalance == pytest.approx(0.0)


def test_depth_imbalance_positive_when_bid_heavy():
    engine = _engine()
    snap = _snapshot(bid_levels=[(100.0, 8.0)], ask_levels=[(100.5, 2.0)])
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.depth_imbalance == pytest.approx(0.6)   # (8-2)/10


def test_depth_imbalance_negative_when_ask_heavy():
    engine = _engine()
    snap = _snapshot(bid_levels=[(100.0, 2.0)], ask_levels=[(100.5, 8.0)])
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.depth_imbalance == pytest.approx(-0.6)


def test_depth_imbalance_respects_depth_levels_limit():
    engine = _engine(depth_levels=1)
    snap = _snapshot(
        bid_levels=[(100.0, 5.0), (99.5, 100.0)],   # only first level counted
        ask_levels=[(100.5, 5.0), (101.0, 100.0)],
    )
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.depth_imbalance == pytest.approx(0.0)   # 5 vs 5, deep levels ignored


def test_depth_imbalance_zero_when_both_sides_empty():
    engine = _engine()
    snap = _snapshot(bid_levels=[], ask_levels=[])
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.depth_imbalance == 0.0


# ── Aggressive buy/sell volume, delta, trade_intensity ───────────────────

def test_aggressive_buy_sell_volume_from_window():
    engine = _engine(trade_window_seconds=10)
    now = 1_000_000
    trades = [
        _trade(100.0, 1.0, is_buyer_maker=False, trade_time_ms=now - 1000),   # aggressor buyer
        _trade(100.0, 2.0, is_buyer_maker=True, trade_time_ms=now - 2000),    # aggressor seller
        _trade(100.0, 3.0, is_buyer_maker=False, trade_time_ms=now - 3000),   # aggressor buyer
    ]
    snap = _snapshot(recent_trades=trades)
    sig = engine.compute("BTCUSDT", snap, now_ms=now)
    assert sig.aggressive_buy_volume == pytest.approx(4.0)
    assert sig.aggressive_sell_volume == pytest.approx(2.0)
    assert sig.delta == pytest.approx(2.0)


def test_trades_outside_window_excluded_from_aggressive_volume():
    engine = _engine(trade_window_seconds=5)
    now = 1_000_000
    trades = [
        _trade(100.0, 1.0, is_buyer_maker=False, trade_time_ms=now - 1000),    # in window
        _trade(100.0, 10.0, is_buyer_maker=False, trade_time_ms=now - 60_000), # outside window
    ]
    snap = _snapshot(recent_trades=trades)
    sig = engine.compute("BTCUSDT", snap, now_ms=now)
    assert sig.aggressive_buy_volume == pytest.approx(1.0)


def test_trade_intensity_is_trades_per_second_over_window():
    engine = _engine(trade_window_seconds=10)
    now = 1_000_000
    trades = [_trade(100.0, 1.0, False, now - i * 100) for i in range(20)]   # all within 2s
    snap = _snapshot(recent_trades=trades)
    sig = engine.compute("BTCUSDT", snap, now_ms=now)
    assert sig.trade_intensity == pytest.approx(20 / 10)


def test_no_trades_gives_zero_volumes_and_intensity():
    engine = _engine()
    snap = _snapshot(recent_trades=[])
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.aggressive_buy_volume == 0.0
    assert sig.aggressive_sell_volume == 0.0
    assert sig.trade_intensity == 0.0
    assert sig.delta == 0.0


# ── CVD (cumulative across calls) + slope ────────────────────────────────

def test_cvd_accumulates_across_multiple_compute_calls():
    engine = _engine(cvd_ema_alpha=0.5)
    t1 = [_trade(100.0, 5.0, is_buyer_maker=False, trade_time_ms=1000)]   # +5
    sig1 = engine.compute("BTCUSDT", _snapshot(recent_trades=t1), now_ms=2000)
    assert sig1.cvd == pytest.approx(5.0)

    t2 = t1 + [_trade(100.0, 2.0, is_buyer_maker=True, trade_time_ms=1500)]  # new: -2
    sig2 = engine.compute("BTCUSDT", _snapshot(recent_trades=t2), now_ms=3000)
    assert sig2.cvd == pytest.approx(3.0)   # 5 - 2, not recomputed from scratch


def test_cvd_does_not_double_count_trades_seen_in_prior_call():
    engine = _engine()
    t1 = [_trade(100.0, 5.0, False, trade_time_ms=1000)]
    sig1 = engine.compute("BTCUSDT", _snapshot(recent_trades=t1), now_ms=2000)
    # Same snapshot (same trades) passed again — nothing NEW to count.
    sig2 = engine.compute("BTCUSDT", _snapshot(recent_trades=t1), now_ms=2500)
    assert sig2.cvd == pytest.approx(sig1.cvd)


def test_cvd_is_independent_per_symbol():
    engine = _engine()
    btc_trades = [_trade(100.0, 5.0, False, trade_time_ms=1000)]
    eth_trades = [_trade(50.0, 1.0, True, trade_time_ms=1000)]
    sig_btc = engine.compute("BTCUSDT", _snapshot(symbol="BTCUSDT", recent_trades=btc_trades), now_ms=2000)
    sig_eth = engine.compute("ETHUSDT", _snapshot(symbol="ETHUSDT", recent_trades=eth_trades), now_ms=2000)
    assert sig_btc.cvd == pytest.approx(5.0)
    assert sig_eth.cvd == pytest.approx(-1.0)


def test_cvd_slope_is_ema_of_incremental_delta_not_of_cvd():
    engine = _engine(cvd_ema_alpha=1.0)   # alpha=1 -> EMA == latest raw delta exactly
    t1 = [_trade(100.0, 5.0, False, trade_time_ms=1000)]
    sig1 = engine.compute("BTCUSDT", _snapshot(recent_trades=t1), now_ms=2000)
    assert sig1.cvd_slope == pytest.approx(5.0)   # first incremental delta = 5

    t2 = t1 + [_trade(100.0, 5.0, False, trade_time_ms=1500)]   # new increment: +5
    sig2 = engine.compute("BTCUSDT", _snapshot(recent_trades=t2), now_ms=3000)
    # cvd rose to 10, but slope (alpha=1) tracks only the latest increment (5),
    # proving slope is not derived from the cumulative cvd value itself.
    assert sig2.cvd == pytest.approx(10.0)
    assert sig2.cvd_slope == pytest.approx(5.0)


def test_reset_symbol_clears_cumulative_state():
    engine = _engine()
    t1 = [_trade(100.0, 5.0, False, trade_time_ms=1000)]
    engine.compute("BTCUSDT", _snapshot(recent_trades=t1), now_ms=2000)
    engine.reset_symbol("BTCUSDT")
    sig = engine.compute("BTCUSDT", _snapshot(recent_trades=t1), now_ms=3000)
    # Same trade counted again post-reset -> fresh cumulative total.
    assert sig.cvd == pytest.approx(5.0)


# ── feature_confidence gate (design review §10 — hard requirement) ──────

def test_feature_confidence_one_when_fully_valid():
    engine = _engine()
    snap = _snapshot(book_valid=True, sequence_valid=True, stream_connected=True)
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.feature_confidence == 1.0


@pytest.mark.parametrize("book_valid,sequence_valid,stream_connected", [
    (False, True, True),
    (True, False, True),
    (True, True, False),
    (False, False, False),
])
def test_feature_confidence_zero_when_any_flag_invalid(book_valid, sequence_valid, stream_connected):
    engine = _engine()
    snap = _snapshot(book_valid=book_valid, sequence_valid=sequence_valid, stream_connected=stream_connected)
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.feature_confidence == 0.0


def test_validity_flags_passed_through_from_snapshot():
    engine = _engine()
    snap = _snapshot(book_valid=False, sequence_valid=True, stream_connected=True, data_age_ms=1234)
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    assert sig.book_valid is False
    assert sig.sequence_valid is True
    assert sig.stream_connected is True
    assert sig.data_age_ms == 1234


# ── HFT-2 scope discipline: score/state must NOT be computed here ───────

def test_score_and_state_stay_at_defaults_hft3_not_built_yet():
    engine = _engine()
    snap = _snapshot(
        bid_levels=[(100.0, 100.0)], ask_levels=[(100.5, 1.0)],   # extreme imbalance
        recent_trades=[_trade(100.0, 50.0, False, 999_000)],       # heavy aggressive buying
    )
    sig = engine.compute("BTCUSDT", snap, now_ms=1_000_000)
    # Even with an extreme, obviously-bullish-looking feature set, score/state
    # must remain untouched — combining features into a score is HFT-3, a
    # separate, not-yet-approved phase (design review §4/§13).
    assert sig.score == 0.0
    assert sig.state == "NEUTRAL"


def test_default_hft_flow_signal_is_fully_inert():
    sig = HFTFlowSignal()
    assert sig.feature_confidence == 0.0
    assert sig.score == 0.0
    assert sig.state == "NEUTRAL"
