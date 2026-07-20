"""
Execution Layer: ExecutionCoordinator  (V16 Phase 1 — Multi-Symbol Foundation)

Architecture only. This class does NOT decide what to trade, when, or how
much — that remains entirely with the decision/risk layers upstream. It
exists solely to own the symbol → TradeManager mapping so that adding a
second, third, or Nth symbol later (Portfolio Manager, Scanner, Correlation
Risk — all explicitly future work, not built here) doesn't require touching
TradeManager or main.py again.

    BrainBot
       |
    ExecutionCoordinator   <- this file. Routing only.
       |
       +-- TradeManager(BTCUSDT)
       +-- TradeManager(ETHUSDT)
       +-- TradeManager(SOLUSDT)
       ...

Design constraints (see docs/architecture.md §13 for the full writeup):
  - Each TradeManager owns exactly one symbol and is never shared between
    symbols — no mutable state crosses the symbol boundary.
  - TradeManagers ARE allowed to share the same `data_provider` instance
    and the SAME module-level circuit breaker (utils.retry / trade_manager
    already pool that correctly across instances) — those are read-only /
    infrastructure-level sharing, not the "shared mutable state" the
    multi-symbol brief warns against, which means per-symbol business
    state like positions, cached exchange filters, or order tracking.
  - `execute_trade(...)` intentionally mirrors TradeManager.execute_trade's
    exact positional/keyword signature plus one new optional trailing
    `symbol=` kwarg, so every existing single-symbol call site (currently
    only main.py's `tm.execute_trade(...)`) keeps working with ZERO changes
    when only one symbol is configured — see migration notes.
  - No new third-party dependencies.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from execution.trade_manager import TradeManager
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionCoordinator:

    def __init__(self, data_provider, symbols: Optional[List[str]] = None) -> None:
        """
        Parameters
        ----------
        data_provider : BinanceDataProvider
            Shared across every TradeManager this coordinator creates —
            safe because TradeManager only ever reads `.client` off it
            (see TradeManager.__init__ docstring).
        symbols : list[str], optional
            Symbols this coordinator is responsible for. Defaults to
            settings.symbol_list, which itself falls back to [settings.SYMBOL]
            — so `ExecutionCoordinator(data_provider)` with no symbols arg
            behaves exactly like today's single-symbol setup.
        """
        self._data_provider = data_provider
        self._symbols: List[str] = list(symbols) if symbols else list(settings.symbol_list)
        if not self._symbols:
            raise ValueError("ExecutionCoordinator requires at least one symbol")

        self._default_symbol: str = self._symbols[0]
        self._managers: Dict[str, TradeManager] = {}
        # Guards _managers. main.py's trading loop and api/app.py's dashboard
        # thread can both reach a coordinator instance (e.g. via a future
        # health/status endpoint) — cheap insurance against two threads
        # racing to construct the same symbol's manager.
        self._lock = threading.RLock()
        self._shutdown = False

        logger.info(
            f"ExecutionCoordinator ready | symbols={self._symbols} "
            f"default={self._default_symbol}"
        )

    # ── Manager lifecycle ────────────────────────────────────────────────

    def get_manager(self, symbol: Optional[str] = None) -> TradeManager:
        """
        Return the TradeManager for `symbol` (default symbol if omitted),
        creating and caching it on first use. O(1) dict lookup on the
        cache-hit path; construction only happens once per symbol for the
        life of this coordinator (singleton-per-symbol, no duplicates).
        """
        if self._shutdown:
            raise RuntimeError("ExecutionCoordinator has been shut down")

        symbol = symbol or self._default_symbol
        if symbol not in self._symbols:
            raise ValueError(
                f"Symbol '{symbol}' is not configured on this coordinator "
                f"(configured: {self._symbols})"
            )

        manager = self._managers.get(symbol)
        if manager is not None:
            return manager

        with self._lock:
            # re-check inside the lock in case another thread won the race
            manager = self._managers.get(symbol)
            if manager is None:
                manager = TradeManager(self._data_provider, symbol=symbol)
                self._managers[symbol] = manager
        return manager

    def initialize(
        self, leverage: Optional[int] = None, margin_type: str = "ISOLATED"
    ) -> Dict[str, bool]:
        """
        Pre-warm every configured symbol: create its TradeManager and set
        leverage + margin mode once at startup. Purely additive — existing
        behavior (TradeManager.execute_trade already sets leverage/margin
        on every call) is unchanged whether or not this is called.

        Returns {symbol: ok} so main.py can log/alert on partial failure
        without this method raising and aborting the other symbols.
        """
        results: Dict[str, bool] = {}
        for symbol in self._symbols:
            try:
                mgr = self.get_manager(symbol)
                lev_ok = mgr.set_leverage(leverage)
                margin_ok = mgr.set_margin_type(margin_type)
                results[symbol] = bool(lev_ok and margin_ok)
            except Exception as exc:
                logger.error(f"ExecutionCoordinator.initialize({symbol}) failed: {exc}")
                results[symbol] = False
        return results

    def shutdown(self) -> None:
        """
        Graceful shutdown: releases this coordinator's manager cache.
        Intentionally does NOT cancel open orders or close positions —
        that's a trading decision, not an architecture concern, and out of
        scope for this phase (no strategy logic in this class). Safe to
        call more than once.
        """
        with self._lock:
            n = len(self._managers)
            self._managers.clear()
            self._shutdown = True
        logger.info(f"ExecutionCoordinator shutdown | released {n} manager(s)")

    # ── Health ───────────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, dict]:
        """
        Per-symbol status snapshot. Does not make any network calls (that
        would belong to a monitoring/reconciliation layer, not here) —
        reports only what the coordinator itself knows: whether a manager
        has been created for the symbol yet, and which client it's bound
        to. Cheap enough to call from a request handler.
        """
        return {
            symbol: {
                "manager_created": symbol in self._managers,
                "is_default":      symbol == self._default_symbol,
            }
            for symbol in self._symbols
        }

    # ── Execution routing (NO strategy logic — pure passthrough) ──────────

    def execute_trade(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        balance: float,
        risk_pct: float = None,
        leverage: float = None,
        symbol: Optional[str] = None,
    ) -> dict:
        """
        Route to the TradeManager for `symbol` (default symbol if
        omitted). Signature is TradeManager.execute_trade's signature plus
        one trailing optional `symbol` kwarg — every existing single-symbol
        caller (main.py) needs zero changes.
        """
        return self.get_manager(symbol).execute_trade(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            balance=balance,
            risk_pct=risk_pct,
            leverage=leverage,
        )

    def close_position(
        self,
        direction: str,
        quantity: float,
        symbol: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Route to the TradeManager for `symbol` (default symbol if
        omitted) — added in V16 Phase 2E for ExecutionOrchestrator's
        replacement-close path. Deliberately NOT left to __getattr__'s
        fallback: that delegates only to the DEFAULT symbol's manager
        (see this class's own __getattr__ docstring), which would close
        the wrong symbol's position for any non-default symbol. Mirrors
        execute_trade()'s exact get_manager(symbol)-then-forward
        pattern; TradeManager.close_position's own signature/behavior is
        unchanged.
        """
        return self.get_manager(symbol).close_position(
            direction, quantity, client_order_id=client_order_id,
        )

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def symbols(self) -> List[str]:
        return list(self._symbols)

    @property
    def default_symbol(self) -> str:
        return self._default_symbol

    # ── Backward-compat safety net ──────────────────────────────────────

    def __getattr__(self, name):
        """
        Delegate any attribute this class doesn't define to the default
        symbol's TradeManager. Nothing in the current codebase relies on
        this today (main.py only ever calls .execute_trade() on the
        object build_execution_engine() returns — verified by grep across
        the codebase) — this exists purely as a safety net for any future
        or external caller that reaches for e.g. .symbol / .client /
        .cancel_all_orders() directly on what used to be a bare
        TradeManager.

        NOTE: __getattr__ is only invoked when normal attribute lookup
        fails, so it never shadows the methods/properties defined above.
        """
        if name.startswith("_"):
            # Never delegate private/dunder lookups — avoids any risk of
            # recursing back into get_manager() (which reads self._symbols
            # etc.) before __init__ has finished populating instance state.
            raise AttributeError(name)
        return getattr(self.get_manager(), name)
