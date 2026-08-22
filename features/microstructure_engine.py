"""features/microstructure_engine.py — V16 Phase 4C Track B, HFT-2:
microstructure feature computation from a WS-derived order-book/trade-flow
snapshot (data.binance_ws_client.SymbolWSSnapshot).

Scope discipline (HFT-2 only — see the Phase 4C Track B design review §5/§6):
  This module computes the MVP feature set the design review locked in —
  depth_imbalance, aggressive_buy_volume/aggressive_sell_volume, delta,
  CVD + CVD-slope, trade_intensity, spread/mid_price, and the
  feature_confidence validity gate. It deliberately does NOT compute
  HFT_FLOW_SCORE or HFT_FLOW_STATE (design review §4/§13's -100..+100
  score and 5-state enum) — that combination step is HFT-3, a separate,
  not-yet-approved phase. HFTFlowSignal.score/.state stay at their
  dataclass defaults (0.0 / "NEUTRAL") here, unused by anything, so this
  module cannot influence any trading decision by itself.

  Deferred features (design review §5/§6, not built here): microprice,
  average_trade_size, large_trade_ratio, liquidity_addition/removal/
  replenishment/pull, absorption/spoof-like detection. None of these are
  referenced anywhere in this file.

Why stateful (unlike FuturesIntelEngine, which is stateless per-call):
  CVD is a genuinely cumulative statistic (running sum of signed trade
  volume), not something derivable from a single snapshot. Recomputing it
  fresh from SymbolWSSnapshot.recent_trades every call would only ever see
  the WS client's fixed retention window (HFT_WS_TRADE_BUFFER_SECONDS),
  not the true since-connection cumulative figure. This engine instead
  tracks, per symbol, the last trade timestamp it has already counted, and
  only folds NEW trades into the running total on each compute() call —
  avoiding both double-counting and unbounded memory growth (no raw trade
  history is retained here beyond what SymbolWSSnapshot already buffers).

Architectural isolation: no import of execution.* or risk.risk_engine
anywhere in this file, matching HFT-1's same constraint — this module
only ever returns a value object to its caller, it holds no reference to
anything that can place an order.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.settings import settings
from utils.logger import get_logger

if TYPE_CHECKING:
    from data.binance_ws_client import SymbolWSSnapshot  # noqa

logger = get_logger(__name__)


@dataclass
class HFTFlowSignal:
    """V16 Phase 4C Track B design review §13's snapshot contract, added to
    futures.futures_intel_engine.FuturesIntelResult in place of the old
    orderbook_imbalance/cvd extension stubs. `score`/`state` are populated
    by HFT-3, not this module (see module docstring) — they stay at their
    defaults here.
    """
    score:                 float = 0.0     # -100..+100, set by HFT-3 only
    state:                 str   = "NEUTRAL"  # set by HFT-3 only
    depth_imbalance:       float = 0.0
    delta:                 float = 0.0
    cvd:                   float = 0.0
    cvd_slope:             float = 0.0
    aggressive_buy_volume:  float = 0.0
    aggressive_sell_volume: float = 0.0
    trade_intensity:        float = 0.0     # trades/sec over HFT_FLOW_TRADE_WINDOW_SECONDS
    spread:                 float = 0.0
    mid_price:              float = 0.0
    data_age_ms:            int   = 0
    book_valid:             bool  = False
    sequence_valid:         bool  = False
    stream_connected:       bool  = False
    # Deterministic function of the four flags above (design review §10) —
    # 0.0 means "contribute nothing", not "contribute a neutral score".
    # HFT-3's _score_hft_flow() must treat 0.0 as fully inert.
    feature_confidence:     float = 0.0


class MicrostructureEngine:
    """Computes HFTFlowSignal for one or more symbols. One instance is
    meant to live for the lifetime of the process (same lifecycle as
    FuturesIntelEngine) so its per-symbol CVD accumulators persist across
    calls — a fresh instance per call would make cvd/cvd_slope meaningless.
    """

    def __init__(
        self,
        depth_levels: int | None = None,
        trade_window_seconds: int | None = None,
        cvd_ema_alpha: float | None = None,
    ) -> None:
        self._depth_levels = depth_levels if depth_levels is not None else settings.HFT_FLOW_DEPTH_LEVELS
        self._trade_window_seconds = (
            trade_window_seconds if trade_window_seconds is not None else settings.HFT_FLOW_TRADE_WINDOW_SECONDS
        )
        self._cvd_ema_alpha = cvd_ema_alpha if cvd_ema_alpha is not None else settings.HFT_FLOW_CVD_EMA_ALPHA

        self._cvd: dict[str, float] = {}
        self._delta_ema: dict[str, float] = {}
        self._last_counted_trade_ms: dict[str, int] = {}
        logger.info(
            f"MicrostructureEngine ready | depth_levels={self._depth_levels} "
            f"trade_window_s={self._trade_window_seconds} cvd_ema_alpha={self._cvd_ema_alpha}"
        )

    def compute(self, symbol: str, snapshot: "SymbolWSSnapshot", now_ms: int | None = None) -> HFTFlowSignal:
        """Pure with respect to `snapshot` (does not mutate it), but DOES
        mutate this engine's own per-symbol CVD/EMA state — calling this
        twice with the same snapshot for the same symbol will double-count
        nothing (the trade-dedup logic is keyed by trade_time_ms already
        counted, not by call count), but callers should still call this
        once per symbol per decision cycle, matching the "read once,
        reuse" discipline the design review requires (§16) for whatever
        later phase consumes this alongside ML feature capture.
        """
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)

        sig = HFTFlowSignal(
            data_age_ms=snapshot.data_age_ms,
            book_valid=snapshot.book_valid,
            sequence_valid=snapshot.sequence_valid,
            stream_connected=snapshot.stream_connected,
        )
        sig.feature_confidence = 1.0 if (sig.book_valid and sig.sequence_valid and sig.stream_connected) else 0.0

        sig.spread, sig.mid_price = self._spread_and_mid(snapshot)
        sig.depth_imbalance = self._depth_imbalance(snapshot)

        buy_vol, sell_vol, intensity = self._trade_window_stats(snapshot, now_ms)
        sig.aggressive_buy_volume = buy_vol
        sig.aggressive_sell_volume = sell_vol
        sig.trade_intensity = intensity
        sig.delta = buy_vol - sell_vol

        sig.cvd, sig.cvd_slope = self._update_cvd(symbol, snapshot)

        return sig

    # ── Spread / mid_price ───────────────────────────────────────────────

    @staticmethod
    def _spread_and_mid(snapshot: "SymbolWSSnapshot") -> tuple[float, float]:
        if snapshot.best_bid is None or snapshot.best_ask is None:
            return 0.0, 0.0
        return snapshot.best_ask - snapshot.best_bid, (snapshot.best_bid + snapshot.best_ask) / 2.0

    # ── Depth imbalance ──────────────────────────────────────────────────

    def _depth_imbalance(self, snapshot: "SymbolWSSnapshot") -> float:
        bid_depth = sum(qty for _, qty in snapshot.bid_levels[: self._depth_levels])
        ask_depth = sum(qty for _, qty in snapshot.ask_levels[: self._depth_levels])
        total = bid_depth + ask_depth
        if total <= 0:
            return 0.0
        return (bid_depth - ask_depth) / total

    # ── Trade-flow window stats (aggressive buy/sell, intensity) ─────────

    def _trade_window_stats(self, snapshot: "SymbolWSSnapshot", now_ms: int) -> tuple[float, float, float]:
        cutoff = now_ms - self._trade_window_seconds * 1000
        window_trades = [t for t in snapshot.recent_trades if t.trade_time_ms >= cutoff]
        # Per Binance aggTrade semantics: is_buyer_maker=True means the
        # resting order was a bid, i.e. the AGGRESSOR was a seller.
        buy_vol = sum(t.qty for t in window_trades if not t.is_buyer_maker)
        sell_vol = sum(t.qty for t in window_trades if t.is_buyer_maker)
        intensity = len(window_trades) / self._trade_window_seconds if self._trade_window_seconds > 0 else 0.0
        return buy_vol, sell_vol, intensity

    # ── CVD (cumulative, incremental across calls) + slope ──────────────

    def _update_cvd(self, symbol: str, snapshot: "SymbolWSSnapshot") -> tuple[float, float]:
        """Deliberately uses its own trade-cutoff logic (last_counted_trade_ms),
        independent of _trade_window_stats()'s fixed window — CVD needs to
        see every trade exactly once since this engine started, not a
        rolling window, so it cannot reuse the windowed delta computed
        above (see module docstring's "Why stateful" section)."""
        last_counted = self._last_counted_trade_ms.get(symbol, 0)
        new_trades = [t for t in snapshot.recent_trades if t.trade_time_ms > last_counted]
        if new_trades:
            self._last_counted_trade_ms[symbol] = max(t.trade_time_ms for t in new_trades)

        incremental_delta = sum(
            t.qty if not t.is_buyer_maker else -t.qty for t in new_trades
        )
        prev_cvd = self._cvd.get(symbol, 0.0)
        cvd = prev_cvd + incremental_delta
        self._cvd[symbol] = cvd

        # cvd_slope = short EMA of the (incremental) delta measurement,
        # per design review §5 — NOT an EMA of the cumulative CVD value
        # itself, which would behave very differently (near-monotonic).
        prev_ema = self._delta_ema.get(symbol, incremental_delta)
        ema = self._cvd_ema_alpha * incremental_delta + (1 - self._cvd_ema_alpha) * prev_ema
        self._delta_ema[symbol] = ema

        return cvd, ema

    # ── Reset (testing / explicit session restart only) ─────────────────

    def reset_symbol(self, symbol: str) -> None:
        """Not called anywhere in production code — provided so tests (and
        any future explicit 'start a new HFT session' operator action) can
        clear one symbol's cumulative CVD state without restarting the
        whole engine."""
        self._cvd.pop(symbol, None)
        self._delta_ema.pop(symbol, None)
        self._last_counted_trade_ms.pop(symbol, None)
