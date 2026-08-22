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
  - fix/execution-coordinator-symbol-mismatch: `allow_dynamic_symbols`
    (opt-in, default False — see __init__) resolves a mismatch this class
    didn't anticipate when it was written: MarketScanner/OpportunityRanker
    later grew to discover candidates across the FULL ~527-symbol Binance
    universe (docs/architecture.md's Scanner/OpportunityRanker sections),
    while this class's `_symbols` allowlist still defaults to a single
    symbol. With the flag off (default), behavior is byte-for-byte
    unchanged — an unconfigured symbol still raises ValueError exactly as
    before. With it on, get_manager() registers a genuinely new symbol on
    first use instead of raising, up to `max_dynamic_symbols` additional
    symbols beyond the originally-configured list — see __init__'s
    docstring for why that cap exists even though TradeManager
    construction itself is cheap (no network call at construction time;
    see TradeManager.__init__).
"""

from __future__ import annotations

import threading

from execution.trade_manager import TradeManager
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionCoordinator:

    def __init__(
        self,
        data_provider,
        symbols: list[str] | None = None,
        lifecycle=None,
        allow_dynamic_symbols: bool = False,
        max_dynamic_symbols: int = 50,
    ) -> None:
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
        lifecycle : execution.trade_lifecycle.TradeLifecycle, optional
            V16 Phase 4B Step 3D (Part E: "ExecutionCoordinator must
            notify lifecycle"). Optional, unused by default. This class
            itself makes no lifecycle-relevant decisions — it's a pure
            per-symbol TradeManager factory/router (get_manager() below,
            close_position() forwarding) — so satisfying Part E here
            means threading this through to every TradeManager it
            constructs (get_manager()), so EMERGCLOSE reporting (see
            TradeManager.__init__) works for every coordinator-managed
            symbol, not just a manually-constructed one.
        allow_dynamic_symbols : bool, default False
            fix/execution-coordinator-symbol-mismatch. False (default):
            byte-for-byte today's behavior — get_manager() raises
            ValueError for any symbol not in `symbols` at construction
            time, with zero changes to that code path. True: a symbol
            outside the original list gets registered on first use
            instead of raising (see get_manager()), up to
            `max_dynamic_symbols` additional symbols. Wired to
            config.settings.EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS by
            execution/execution_factory.py — see that file for the
            settings-driven default (also False).
        max_dynamic_symbols : int, default 50
            Ceiling on how many symbols BEYOND the originally-configured
            list can ever be dynamically registered over this
            coordinator's lifetime (i.e. process uptime — this resets on
            restart, since `_symbols`/`_managers` are in-memory only).
            Ignored when allow_dynamic_symbols=False.

            Decision (fix/execution-coordinator-symbol-mismatch, surfaced
            explicitly per that phase's own instruction rather than
            silently picked): PORTFOLIO_MAX_POSITIONS (default 5) bounds
            CONCURRENT open positions, not the cumulative count of
            DISTINCT symbols this coordinator could ever be asked to
            manage over a long-running process — a symbol can close and a
            completely different one open on the next cycle, and
            `_symbols`/`_managers` are append-only (no eviction), so an
            unbounded scanner universe (~527 symbols, see
            scanner/market_scanner.py) feeding this over weeks/months
            could in principle accumulate a TradeManager per symbol ever
            selected, not just per symbol concurrently held.
            TradeManager construction itself is cheap — no network call
            happens until its first execute_trade() (see
            TradeManager.__init__/_symbol_info's @retry_api_call, called
            lazily) — so this cap is NOT primarily a memory/resource
            safeguard; it exists because "which symbols can the live
            executor ever place an order on" is a live-money scope-of-
            trading decision (this phase's own framing), and an explicit,
            visible ceiling is safer than an implicitly unbounded one.
            50 was chosen as well above any realistic concurrent need
            (10x PORTFOLIO_MAX_POSITIONS' default of 5) while still far
            short of the full ~527-symbol universe — a deliberately
            generous but non-infinite default. Once reached, a symbol
            beyond the cap gets EXACTLY today's ValueError (same
            exception type, same non-retryable classification in
            execution/execution_orchestrator.py's _NON_RECOVERABLE_MARKERS
            — unchanged), not a different failure mode.
        """
        self._data_provider = data_provider
        self._symbols: list[str] = list(symbols) if symbols else list(settings.symbol_list)
        if not self._symbols:
            raise ValueError("ExecutionCoordinator requires at least one symbol")

        self._default_symbol: str = self._symbols[0]
        self._managers: dict[str, TradeManager] = {}
        self._lifecycle = lifecycle
        self._allow_dynamic_symbols = allow_dynamic_symbols
        self._max_dynamic_symbols = max_dynamic_symbols
        self._dynamically_registered_count = 0
        # Guards _managers AND (when allow_dynamic_symbols=True) _symbols'
        # append below. main.py's trading loop and api/app.py's dashboard
        # thread can both reach a coordinator instance (e.g. via a future
        # health/status endpoint) — cheap insurance against two threads
        # racing to construct the same symbol's manager (or, now, racing
        # to register the same new symbol).
        self._lock = threading.RLock()
        self._shutdown = False

        logger.info(
            f"ExecutionCoordinator ready | symbols={self._symbols} "
            f"default={self._default_symbol} "
            f"allow_dynamic_symbols={self._allow_dynamic_symbols}"
            + (f" max_dynamic_symbols={self._max_dynamic_symbols}" if self._allow_dynamic_symbols else "")
        )

    # ── Manager lifecycle ────────────────────────────────────────────────

    def get_manager(self, symbol: str | None = None) -> TradeManager:
        """
        Return the TradeManager for `symbol` (default symbol if omitted),
        creating and caching it on first use. O(1) dict lookup on the
        cache-hit path; construction only happens once per symbol for the
        life of this coordinator (singleton-per-symbol, no duplicates).

        fix/execution-coordinator-symbol-mismatch: when
        allow_dynamic_symbols=True, a symbol outside the originally-
        configured list is registered here on first use (up to
        max_dynamic_symbols additional symbols) instead of raising — see
        __init__'s docstring for the full design rationale. With the flag
        at its default (False), this method's behavior is byte-for-byte
        unchanged from before this phase.
        """
        if self._shutdown:
            raise RuntimeError("ExecutionCoordinator has been shut down")

        symbol = symbol or self._default_symbol

        if symbol not in self._symbols:
            if not self._allow_dynamic_symbols:
                raise ValueError(
                    f"Symbol '{symbol}' is not configured on this coordinator "
                    f"(configured: {self._symbols})"
                )
            with self._lock:
                # Re-check inside the lock: another thread may have already
                # registered this exact symbol (or pushed the count to the
                # cap) between the membership check above and here.
                if symbol not in self._symbols:
                    if self._dynamically_registered_count >= self._max_dynamic_symbols:
                        raise ValueError(
                            f"Symbol '{symbol}' is not configured on this coordinator "
                            f"(configured: {self._symbols}) and the dynamic-symbol cap "
                            f"({self._max_dynamic_symbols}) has been reached — "
                            f"{self._dynamically_registered_count} symbols already "
                            f"registered dynamically this run"
                        )
                    logger.info(
                        f"ExecutionCoordinator: dynamically registering new symbol "
                        f"'{symbol}' (allow_dynamic_symbols=True; not in originally "
                        f"configured list {self._symbols}; "
                        f"{self._dynamically_registered_count + 1}/{self._max_dynamic_symbols} "
                        f"of this run's dynamic-symbol cap)"
                    )
                    self._symbols.append(symbol)
                    self._dynamically_registered_count += 1

        manager = self._managers.get(symbol)
        if manager is not None:
            return manager

        with self._lock:
            # re-check inside the lock in case another thread won the race
            manager = self._managers.get(symbol)
            if manager is None:
                manager = TradeManager(self._data_provider, symbol=symbol, lifecycle=self._lifecycle)
                self._managers[symbol] = manager
        return manager

    def initialize(
        self, leverage: int | None = None, margin_type: str | None = None
    ) -> dict[str, bool]:
        """
        Pre-warm every configured symbol: create its TradeManager and set
        leverage + margin mode once at startup. Purely additive — existing
        behavior (TradeManager.execute_trade already sets leverage/margin
        on every call) is unchanged whether or not this is called.

        Returns {symbol: ok} so main.py can log/alert on partial failure
        without this method raising and aborting the other symbols.
        """
        results: dict[str, bool] = {}
        effective_margin_type = margin_type or settings.MARGIN_TYPE
        for symbol in self._symbols:
            try:
                mgr = self.get_manager(symbol)
                lev_ok = mgr.set_leverage(leverage)
                margin_ok = mgr.set_margin_type(effective_margin_type)
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

    def health_check(self) -> dict[str, dict]:
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
        symbol: str | None = None,
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
        symbol: str | None = None,
        client_order_id: str | None = None,
    ) -> dict | None:
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
    def symbols(self) -> list[str]:
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
