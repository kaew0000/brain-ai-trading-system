#!/usr/bin/env python3
"""
Brain Bot BTCUSDT Futures v2
============================================================
Full pipeline architecture (Phase 4A):

  Data → Feature → Regime → Intelligence → Decision → Execution → Analytics

Layer map
---------
  Layer 1  BinanceDataProvider      — raw market data
  Layer 2  MarketContextBuilder     — unified context assembly
  Layer 3  RegimeEngine             — market regime (HMM + rules)
  Layer 4  TrendEngine              — ADX / EMA trend bias (inside ContextBuilder)
  Layer 5  SMCEngine                — Smart Money Concepts (MTF)
  Layer 6  FuturesIntelEngine       — OI / funding / L/S ratio (inside ContextBuilder)
  Layer 7  VolumeEngine             — volume spike / OBV
  Layer 8  ConfidenceEngine         — weighted 0-100% confidence score
  Layer 9  CausalExplainer          — structured JSON reasoning
  Layer 10 EventBus                 — agent event stream
  Layer 11 RiskEngine               — drawdown / consecutive-loss guard
  Layer 12 TradeManager             — Binance Futures execution
  Layer 13 TradeJournal(V2)         — SQLite persistence

Run:
  python main.py
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone

import schedule
import threading
import time as _time
import webbrowser

from config.settings import settings, EXECUTION_MODE, EXECUTION_LANE
from data.binance_provider import BinanceDataProvider
from features.smc_engine import SMCEngine, SMCSignals
from features.volume_engine import VolumeEngine
from regime.regime_engine import RegimeEngine
from intelligence.market_context_builder import MarketContextBuilder
from decision.confidence_engine import ConfidenceEngine
from decision.causal_explainer import CausalExplainer
from events.event_bus import (
    EventBus, reset_event_bus,
    brain_pub, conf_pub, risk_pub, regime_pub,
)
from execution.execution_factory import build_execution_engine
from execution.trade_lifecycle import CloseSource
from analytics.trade_journal import TradeJournal, TradeRecord
from journal.journal_v2 import TradeJournalV2
from journal.trade_attribution import agent_attribution_from_ceo_decision
from risk.risk_engine import RiskEngine
from utils.logger import get_logger
from agents import build_agent_layer
from forward_test.evaluator import ForwardTestEvaluator
from system_health.heartbeat import get_heartbeat
from system_health.reconciliation import get_reconciliation_engine
from system_health.watchdog import start_watchdog_supervisor
from utils.systemd_notify import notify_ready, notify_stopping

logger = get_logger("main")

# ── Global shutdown flag ──────────────────────────────────────────────────────

_RUNNING = True


def _handle_signal(sig, frame):
    global _RUNNING
    logger.info(f"Signal {sig} received – shutting down …")
    notify_stopping()
    _RUNNING = False


# ── System bootstrap ──────────────────────────────────────────────────────────

def _initialize_world_runtime() -> bool:
    """
    Phase W10 — best-effort, non-blocking World Runtime + Simulation
    warm-up. Deliberately defensive: World (world/) is Track B
    visualization only — it must NEVER be able to prevent the trading
    bot itself from starting. Any failure here is logged and swallowed;
    the bot proceeds exactly as it would if this function didn't exist.
    """
    try:
        from world.runtime import api as _world_runtime_api
        from world.simulation import api as _world_simulation_api

        _world_runtime_api.get_world_state()
        _world_simulation_api.get_simulation_state()
        logger.info("World Runtime + Simulation initialized (Phase W5/W7).")
        return True
    except Exception as exc:
        logger.warning(f"World Runtime did not initialize (dashboard World tab will be unavailable): {exc}")
        return False


def _tick_world_simulation() -> None:
    """Phase W10 — advance the Phase W7 SimulationEngine by one tick per
    trading cycle. Read-only from the trading engine's perspective (only
    ever calls world.simulation.api.step(), which reads world.runtime's
    already-existing WorldState — never anything in components/agents/
    execution). Wrapped defensively for the same reason
    _initialize_world_runtime() is: a World failure must never affect
    the trading loop it rides alongside.
    """
    try:
        from world.simulation import api as _world_simulation_api
        _world_simulation_api.step()
    except Exception as exc:
        logger.debug(f"World simulation tick skipped: {exc}")


_world_runtime_manager = None  # Phase W11 — lazily constructed, see below


def _get_world_runtime_manager():
    """Phase W11 — lazily construct and cache the RuntimeManager wiring:
    six Phase W4/W13-1 readers, each bound to a JSONFileSource pointed at
    telemetry.world_export's staging directory. Built once per process;
    construction only wires object references together, no I/O happens
    until run_once() is actually called. Never touches agents/,
    execution/, risk/, or portfolio/ — every reader only ever reads a
    JSON file that telemetry/world_export.py already wrote."""
    global _world_runtime_manager
    if _world_runtime_manager is None:
        from telemetry.world_export import DEFAULT_STAGING_DIR
        from world.adapter.adapter import ReadOnlyIngestionAdapter
        from world.readers.base import JSONFileSource
        from world.readers.event_reader import EventReader
        from world.readers.journal_reader import JournalReader
        from world.readers.mission_reader import MissionReader
        from world.readers.order_reader import OrderReader
        from world.readers.portfolio_reader import PortfolioReader
        from world.readers.telemetry_reader import TelemetryReader
        from world.runtime.runtime_manager import RuntimeManager

        def _src(filename: str) -> JSONFileSource:
            return JSONFileSource(os.path.join(DEFAULT_STAGING_DIR, filename))

        adapter = ReadOnlyIngestionAdapter(
            journal_reader=JournalReader(_src("journal.json")),
            telemetry_reader=TelemetryReader(_src("telemetry.json")),
            portfolio_reader=PortfolioReader(_src("portfolio.json")),
            mission_reader=MissionReader(_src("missions.json")),
            event_reader=EventReader(_src("events.json")),
            order_reader=OrderReader(_src("orders.json")),
        )
        _world_runtime_manager = RuntimeManager(adapter)
    return _world_runtime_manager


def _run_world_runtime_manager(components: dict) -> None:
    """Phase W11 (extended by Phase W13-1) — capture one Track A ->
    World snapshot and write it to world/data/runtime/*.json via the
    Phase W4 pipeline. Read-only from the trading engine's perspective
    end to end: only ever calls telemetry.world_export.export_snapshot()
    (which only calls existing read-only accessors — see that module's
    own docstring for the complete, individually-verified list,
    extended by Phase W13-1 to OrderTimeline.current_state() and
    ReconciliationEngine.status()) and RuntimeManager.run_once() (which
    only ever writes to world/data/runtime/). None of this can
    influence a trading decision — there is no path from here back into
    agents/, execution/, risk/, or portfolio/, and OrderTimeline's own
    background polling loop (started/stopped independently in
    build_system()/shutdown, see components["order_timeline"]) is
    completely untouched by this function — it is only ever read from.
    Wrapped defensively for the same reason _tick_world_simulation() is:
    a World failure must never affect the trading loop it rides
    alongside."""
    try:
        from telemetry.world_export import export_snapshot
        export_snapshot(
            journal=components.get("journal_v2"),
            order_timeline=components.get("order_timeline"),
            reconciliation_engine=components.get("reconciliation_engine"),
        )
        _get_world_runtime_manager().run_once()
    except Exception as exc:
        logger.debug(f"World runtime export tick skipped: {exc}")


# ── Dashboard / API server ────────────────────────────────────────────────────

def _start_api_server(journal, bus, paper_engine=None, data_provider=None, agent_layer=None, risk_engine=None, portfolio_state=None, trade_lifecycle=None, reconciliation_engine=None, host: str = "0.0.0.0", port: int = 8000) -> None:
    """
    Start the FastAPI dashboard server in a daemon background thread.
    Runs alongside the trading loop — does not block main.
    """
    import uvicorn
    import api.app as _api_module
    # Inject live objects so API reads from same DB/EventBus as trading loop
    _api_module._JOURNAL_INSTANCE = journal
    _api_module._BUS_INSTANCE     = bus
    # Register the paper engine (if EXECUTION_MODE=paper) so /api/paper and
    # /api/paper/* report real metrics instead of "not running".
    if paper_engine is not None:
        _api_module.set_state("paper_engine", paper_engine)
    # Expose data_provider so /api/health can read time_drift_ms and the
    # Commander Interface's "show positions" can read live exchange state.
    if data_provider is not None:
        _api_module.set_state("data_provider", data_provider)
    # Expose agent layer so /api/agents and /api/chat work
    if agent_layer is not None:
        _api_module.set_state("agent_layer", agent_layer)
    # v14 Phase 2.5 — expose risk_engine so Commander's "show risk" can
    # build a live RiskEngine.report() without a circular import into main.py.
    if risk_engine is not None:
        _api_module.set_state("risk_engine", risk_engine)
    # V16 Phase ORDER-01 — expose the live runtime position cache and its
    # supporting singletons so GET /api/order-state (and any other API
    # route) reads the SAME objects the trading-loop thread's
    # reconciliation cycle already reads, not a second copy. event_bus is
    # `bus` above, already injected as _BUS_INSTANCE; also registered
    # under the "event_bus" state key since that's the key
    # system_health/reconciliation.py._read_bot() and
    # system_health/order_state.py both look for via sys.get(...).
    _api_module.set_state("portfolio_state", portfolio_state)
    _api_module.set_state("trade_lifecycle", trade_lifecycle)
    _api_module.set_state("event_bus", bus)
    if reconciliation_engine is not None:
        _api_module.set_state("reconciliation_engine", reconciliation_engine)
    from api.app import app

    config = uvicorn.Config(
        app       = app,
        host      = host,
        port      = port,
        log_level = "warning",   # suppress uvicorn noise in trading log
    )
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True, name="api-server")
    t.start()
    logger.info(f"Dashboard API started on http://localhost:{port}")
    return port


def _wait_for_health(port: int, timeout: float = 15.0, poll_interval: float = 0.25) -> bool:
    """V16 Track W14-1 Item 10 — poll GET /api/health until it answers
    200 or `timeout` elapses. Uses stdlib urllib only (no new dependency
    for main.py). Never raises — a health check that can't itself fail
    safely would defeat the point of it."""
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:{port}/api/health"
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        _time.sleep(poll_interval)
    return False


def _open_browser(port: int, timeout: float = 15.0) -> None:
    """Open the dashboard once the API server is actually answering
    /api/health, instead of assuming a fixed 1.5s sleep was always
    enough (Track W14-1 Item 10 — the fixed sleep was a real,
    confirmed gap: a slow startup, e.g. a cold ML model load, could
    open the browser before uvicorn was listening).

    Still exactly one daemon thread, same as before — this does not add
    a second polling system alongside the existing server supervision
    (_supervised_broadcast() etc. in api/app.py); it only changes what
    this one thread waits on before firing webbrowser.open().

    On timeout it does not silently give up: it logs a clear warning
    and still opens the browser once (arguably still useful — the
    operator can refresh), rather than leaving them with no browser tab
    and no explanation at all.
    """
    def _open():
        ready = _wait_for_health(port, timeout=timeout)
        url = f"http://localhost:{port}/"
        if not ready:
            logger.warning(
                f"Dashboard API did not answer /api/health within {timeout}s "
                f"— opening browser anyway ({url}); refresh if it shows an "
                "error, the server may still be starting."
            )
        try:
            webbrowser.open(url)
            logger.info(f"Browser opened: {url}" + ("" if ready else " (server readiness unconfirmed)"))
        except Exception as exc:
            logger.warning(f"Could not open browser: {exc} — open manually: {url}")
    t = threading.Thread(target=_open, daemon=True, name="browser-launch")
    t.start()


def build_system() -> dict:
    """
    Instantiate every layer and wire dependencies.
    Returns a dict of all components keyed by name.
    """
    logger.info("=" * 62)
    logger.info(" Brain Bot BTCUSDT Futures v2 – System Bootstrap")
    logger.info("=" * 62)

    logger.info("[1/9] Data Layer …")
    data_provider = BinanceDataProvider()

    # V16 Track W14-1 (Dashboard V16 real account telemetry): register
    # the C1 ExchangeStateManager singleton here, unconditionally, so it
    # exists in exchange_state.manager's process-wide registry BEFORE
    # _start_api_server() starts (main() calls build_system() then
    # _start_api_server() — build_system() always runs first). This is
    # the SAME get_manager(data_provider, mode=EXECUTION_MODE) call the
    # ORDER_TIMELINE_ENABLED block below already makes when that flag is
    # on; calling it here too is a no-op for that path — get_manager()'s
    # registry hands back the existing instance for a given (mode,
    # exchange, account_id) key, never builds a second one (see
    # exchange_state/manager.py). Construction alone makes no Binance
    # call (see ExchangeStateManager.__init__) — the first real upstream
    # call happens lazily, on the first get_snapshot(), which
    # api/account_api.py's GET /api/account/state triggers on its first
    # request. Previously this registration only happened when
    # ORDER_TIMELINE_ENABLED=True (default False), which was the actual
    # gap the read-only C1/C3 audit identified: real account telemetry
    # for the dashboard should not depend on the unrelated order-timeline
    # feature flag.
    from exchange_state.manager import get_manager as _get_exchange_state_manager
    exchange_manager = _get_exchange_state_manager(data_provider, mode=EXECUTION_MODE)

    logger.info("[2/9] Feature Layer …")
    smc_engine    = SMCEngine()
    volume_engine = VolumeEngine()

    logger.info("[3/9] Regime Layer …")
    regime_engine = RegimeEngine(use_hmm=True)

    logger.info("[4/9] Intelligence Layer …")
    context_builder = MarketContextBuilder()

    logger.info("[5/9] Decision Layer …")
    confidence_engine = ConfidenceEngine()
    causal_explainer  = CausalExplainer()

    logger.info("[6/9] Analytics / Risk Layer …")
    journal    = TradeJournal()
    journal_v2 = TradeJournalV2()
    # V16 Phase 4B Step 3D: one TradeLifecycle for the legacy
    # single-symbol loop specifically (no PortfolioState/PortfolioManager
    # involved on this path — see monitor_open_trades()'s own call site
    # below). The multi-symbol ExecutionScheduler path further down
    # constructs its own ExecutionOrchestrator, which auto-builds its
    # OWN TradeLifecycle (wired to that path's real PortfolioManager)
    # when none is passed — see execution/execution_orchestrator.py's
    # __init__. Two TradeLifecycle instances, matching this file's own
    # pre-existing two-separate-pipelines shape (main.py §1.2 in
    # docs/architecture.md's Phase 4B Step 3D section explains why one
    # shared instance was rejected — the two pipelines already track
    # completely disjoint position state (PortfolioState vs. none), so
    # a shared lifecycle would gain nothing and risks one pipeline's
    # symbol keys colliding with the other's).
    from execution.trade_lifecycle import get_default_trade_lifecycle
    trade_lifecycle = get_default_trade_lifecycle(journal=journal_v2)
    # RiskEngine only needs get_today_pnl / get_consecutive_losses / get_daily_stats,
    # all of which TradeJournalV2 implements as a drop-in superset of v1 —
    # wiring it here keeps risk gating and the dashboard reading the same store.
    risk_engine = RiskEngine(journal_v2)

    logger.info("[7/9] Event Bus …")
    # reset_event_bus wires journal_v2 into the global singleton that
    # all AgentPublisher instances (brain_pub, conf_pub, etc.) use.
    event_bus = reset_event_bus(journal=journal_v2, persist=True)

    logger.info("[8/9] Execution Layer …")
    trade_manager = build_execution_engine(data_provider)
    # When running in paper mode, trade_manager IS the paper engine adapter —
    # stash it under its own key so the API server can register it with
    # api.app's shared state (used by /api/paper, /api/paper/trades, etc.)
    paper_engine = trade_manager if EXECUTION_MODE == "paper" else None

    # V16 Phase 1 (Multi-Symbol Foundation): testnet/live now returns an
    # ExecutionCoordinator, which exposes an optional initialize() to
    # pre-warm leverage/margin for every configured symbol at boot instead
    # of relying solely on the implicit per-trade set_leverage/set_margin_type
    # inside TradeManager.execute_trade(). Purely additive/best-effort —
    # guarded so paper mode (no initialize()) and any future engine type
    # are unaffected, and a failure here never aborts startup since
    # execute_trade() still sets leverage/margin per-trade regardless.
    # Trading loop itself (below) is completely unchanged.
    if hasattr(trade_manager, "initialize"):
        try:
            init_results = trade_manager.initialize()
            logger.info(f"ExecutionCoordinator.initialize() → {init_results}")
        except Exception as exc:
            logger.warning(f"ExecutionCoordinator.initialize() failed (non-fatal): {exc}")

    # V16 Phase 2, Part 1 (Market Scanner) — off by default (see
    # config/settings.py SCANNER_ENABLED). Guarded + best-effort, same
    # pattern as the ExecutionCoordinator.initialize() call just above:
    # a failure here is logged and never aborts startup or touches the
    # single-symbol trading loop, which is completely unchanged.
    market_scanner = None
    if settings.SCANNER_ENABLED:
        try:
            from scanner.market_scanner import MarketScanner
            market_scanner = MarketScanner(data_provider)
            market_scanner.start()
        except Exception as exc:
            logger.error(f"MarketScanner failed to start (non-fatal): {exc}")
            market_scanner = None

    # V16 Phase 2F (Execution Scheduler + Multi-Symbol Signals) — off by
    # default (see config/settings.py SCHEDULER_ENABLED). Same guarded,
    # best-effort pattern as MarketScanner just above: any failure here
    # is logged and never aborts startup or touches the single-symbol
    # trading loop below, which this phase does not modify.
    #
    # Requires market_scanner (built just above) — the Scheduler's
    # OpportunityRanker needs it for candidates. If SCANNER_ENABLED is
    # False, SCHEDULER_ENABLED is silently a no-op rather than a hard
    # startup error, since a person could reasonably flip SCHEDULER_
    # ENABLED on without realizing the dependency; this logs why instead
    # of failing confusingly.
    execution_scheduler = None
    if settings.SCHEDULER_ENABLED:
        if market_scanner is None:
            logger.error(
                "SCHEDULER_ENABLED=true but SCANNER_ENABLED=false — "
                "ExecutionScheduler needs the Market Scanner for candidates. "
                "Not starting."
            )
        else:
            try:
                from execution.execution_orchestrator import ExecutionOrchestrator
                from execution.execution_scheduler import ExecutionScheduler
                from execution.strategy_registry import build_strategy
                from portfolio.portfolio_manager import PortfolioManager
                from ranking.opportunity_ranker import OpportunityRanker

                # V16 Phase 3A (Strategy Plugin System): resolves via
                # config/settings.py STRATEGY_NAME. Default value
                # "portfolio_signal_provider" builds the identical
                # PortfolioSignalProvider(...) this line constructed
                # directly before this phase — see
                # execution/strategy_registry.py module docstring.
                signal_provider = build_strategy(
                    settings.STRATEGY_NAME,
                    data_provider=data_provider,
                    regime_engine=regime_engine,
                    smc_engine=smc_engine,
                    volume_engine=volume_engine,
                    context_builder=context_builder,
                    confidence_engine=confidence_engine,
                )

                # V16 Phase 4B Step 3C (Live CEO Agent Integration) — off
                # by default (see config/settings.py
                # CEO_MULTI_SYMBOL_ENABLED). Wraps signal_provider with
                # execution/ceo_gated_signal_provider.py's
                # CEOGatedSignalProvider, which is itself a
                # SignalProvider — ExecutionOrchestrator below is handed
                # exactly one signal_provider either way and has no idea
                # whether it's gated.
                #
                # Only strategies exposing get_signal_with_context()
                # (PortfolioSignalProvider — the default STRATEGY_NAME)
                # can be CEO-gated; agents.multi_symbol_adapter.
                # MultiSymbolCEOAdapter needs that method to get the
                # already-computed market_context/confidence_result
                # without recomputing them (see that module's own
                # docstring). "smc_oi_regime" and any future strategy
                # that doesn't expose it are logged and left unwrapped
                # — CEO_MULTI_SYMBOL_ENABLED=true silently has no effect
                # for those rather than crashing startup, matching this
                # phase's "backward compatibility is mandatory" brief.
                if settings.CEO_MULTI_SYMBOL_ENABLED:
                    if hasattr(signal_provider, "get_signal_with_context"):
                        from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
                        from execution.ceo_gated_signal_provider import CEOGatedSignalProvider

                        ceo_agent_cache = CEOAgentSymbolCache(risk_engine=risk_engine, journal=journal_v2)
                        ceo_dispatcher = MultiSymbolCEODispatcher(
                            signal_provider=signal_provider, ceo_agent_cache=ceo_agent_cache,
                        )
                        # V16 Phase 4C Step 4: inject the recommendation
                        # source as a callable rather than importing
                        # api.app at module scope inside
                        # ceo_gated_signal_provider.py — keeps that
                        # module's existing dependency-injection idiom
                        # (see its own constructor docstring) and its
                        # existing testability with fakes. Import is
                        # local/deferred, same "avoid import cycles with
                        # api.app" pattern already used everywhere else
                        # in this file (e.g. _start_api_server's own
                        # `import api.app as _api_module` calls above).
                        def _get_learning_recommendations():
                            import api.app as _api_module
                            return _api_module.get_state("learning_recommendations", [])

                        # V16 Phase 4C Step 5: same idiom as
                        # _get_learning_recommendations() immediately
                        # above — run_learning_recommendation_refresh()
                        # has written this value to _state alongside
                        # "learning_recommendations" since Step 4
                        # (main.py's own set_state("learning_dataset_row_count",
                        # ...) call), but nothing ever read it back out
                        # until now, so recommendation_scoring.py's
                        # _coverage_subscore() always saw None on the
                        # live path and fell back to its existing,
                        # unchanged 0.0 default.
                        def _get_learning_dataset_row_count():
                            import api.app as _api_module
                            return _api_module.get_state("learning_dataset_row_count", None)

                        signal_provider = CEOGatedSignalProvider(
                            signal_provider=signal_provider,
                            ceo_adapter=ceo_dispatcher,
                            execution_lane=EXECUTION_LANE,
                            journal=journal_v2,
                            recommendation_provider=_get_learning_recommendations,
                            dataset_row_count_provider=_get_learning_dataset_row_count,
                        )
                        logger.info("ExecutionScheduler: CEO Agent gating ENABLED")
                    else:
                        logger.warning(
                            f"CEO_MULTI_SYMBOL_ENABLED=true but strategy "
                            f"'{settings.STRATEGY_NAME}' has no get_signal_with_context() "
                            f"— CEO gating not applied for this strategy."
                        )

                portfolio_manager = PortfolioManager(journal=journal_v2)
                # trade_lifecycle was constructed earlier (before
                # portfolio_manager existed) via get_default_trade_lifecycle(),
                # which only uses its arguments on the very FIRST call —
                # attach portfolio_manager to it now so the multi-symbol
                # close path's TradeLifecycle.exit_confirmed() can
                # actually call notify_position_closed() (Part D) instead
                # of silently no-op'ing against a None portfolio_manager.
                trade_lifecycle.portfolio_manager = portfolio_manager
                # Reuse the SAME execution engine the single-symbol loop
                # already built above (trade_manager) rather than calling
                # build_execution_engine() a second time — that would spin
                # up a second, independent PaperExecutionEngine (its own
                # separate balance) or a second ExecutionCoordinator (its
                # own separate per-symbol TradeManager cache) alongside the
                # one already in use, silently splitting execution state
                # in two.
                execution_orchestrator = ExecutionOrchestrator(
                    execution_engine=trade_manager,
                    portfolio_manager=portfolio_manager,
                    signal_provider=signal_provider,
                    execution_lane=EXECUTION_LANE,
                    journal=journal_v2,
                    lifecycle=trade_lifecycle,
                )
                execution_scheduler = ExecutionScheduler(
                    opportunity_ranker=OpportunityRanker(market_scanner),
                    portfolio_manager=portfolio_manager,
                    risk_engine=risk_engine,
                    execution_orchestrator=execution_orchestrator,
                    data_provider=data_provider,
                )
                execution_scheduler.start()
            except Exception as exc:
                logger.error(f"ExecutionScheduler failed to start (non-fatal): {exc}")
                execution_scheduler = None

    # Track C3 Phase 1 (Unified Order/Trade Timeline) — off by default
    # (see config/settings.py ORDER_TIMELINE_ENABLED). Same guarded,
    # best-effort, non-fatal pattern as MarketScanner/ExecutionScheduler
    # above. Read-only: reuses the SAME trade_lifecycle instance already
    # constructed above (not a second one) and, if EXECUTION_MODE has a
    # usable data_provider, the SAME exchange_state singleton keyed by
    # (mode, exchange, account_id) any other C1 consumer (World/
    # Dashboard/CEO context) would get from get_manager() — never a
    # second ExchangeStateManager for the same account.
    order_timeline = None
    if settings.ORDER_TIMELINE_ENABLED:
        try:
            from exchange_state.manager import get_manager as get_exchange_state_manager
            from execution.order_timeline import get_order_timeline

            exchange_manager = get_exchange_state_manager(data_provider, mode=EXECUTION_MODE)
            order_timeline = get_order_timeline(
                execution_lane=EXECUTION_LANE,
                trade_lifecycle=trade_lifecycle,
                exchange_manager=exchange_manager,
                poll_interval_seconds=settings.ORDER_TIMELINE_POLL_INTERVAL_SECONDS,
                max_history_rows=settings.ORDER_TIMELINE_HISTORY_MAX_ROWS,
            )
            order_timeline.start()
        except Exception as exc:
            logger.error(f"OrderTimeline failed to start (non-fatal): {exc}")
            order_timeline = None

    logger.info("[9/9] All components ready.")

    # ── Agent Layer ───────────────────────────────────────────────────────────
    agent_layer = build_agent_layer(
        risk_engine = risk_engine,
        journal     = journal_v2,
    )
    forward_eval = ForwardTestEvaluator()

    # v14 Phase 2.5 — Mission Pipeline tracker (singleton, shared with api.app)
    from missions.mission_tracker import get_mission_tracker
    mission_tracker = get_mission_tracker()

    # v14 Phase 3A — Stability Layer
    reconciliation_engine = get_reconciliation_engine()
    get_heartbeat().beat("dashboard_api", meta={"phase": "bootstrap"})

    # V16 Phase ORDER-01: the live runtime position cache, owned by
    # ExecutionScheduler. Threaded through `components` here so both the
    # trading-loop thread (schedule.every(60).seconds.do(
    # run_position_reconciliation, components)) and, via
    # _start_api_server()'s new portfolio_state= arg below, the API
    # thread's api/app.py._state end up reading the SAME PortfolioState
    # instance — not a second copy. See system_health/reconciliation.py
    # _read_bot() and system_health/order_state.py for why this matters.
    live_portfolio_state = execution_scheduler.portfolio_state if execution_scheduler else None

    logger.info("=" * 62)

    return {
        "data_provider":         data_provider,
        "portfolio_state":       live_portfolio_state,
        "smc_engine":            smc_engine,
        "volume_engine":         volume_engine,
        "regime_engine":         regime_engine,
        "context_builder":       context_builder,
        "confidence_engine":     confidence_engine,
        "causal_explainer":      causal_explainer,
        "journal":               journal,
        "journal_v2":            journal_v2,
        "trade_lifecycle":       trade_lifecycle,
        "risk_engine":           risk_engine,
        "event_bus":             event_bus,
        "trade_manager":         trade_manager,
        "paper_engine":          paper_engine,
        "agent_layer":           agent_layer,
        "forward_eval":          forward_eval,
        "mission_tracker":       mission_tracker,
        "reconciliation_engine": reconciliation_engine,
        "market_scanner":        market_scanner,
        "execution_scheduler":   execution_scheduler,
        "order_timeline":        order_timeline,
        "exchange_manager":      exchange_manager,
        "current_mission_id":    None,
    }


# ── Trading cycle ─────────────────────────────────────────────────────────────

def run_trading_cycle(sys: dict) -> None:
    """
    Full pipeline cycle — MarketContextBuilder → ConfidenceEngine →
    CausalExplainer → EventBus → Execution → Journal.

    Steps
    -----
    1.  Skip if already in a position.
    2.  Fetch all market data.
    3.  Classify regime.
    4.  Run SMC multi-timeframe analysis.
    5.  Run volume analysis (M15).
    6.  Build unified market context.
    7.  Determine direction from MTF consensus.
    8.  Score confidence (ConfidenceEngine).
    9.  Explain decision (CausalExplainer).
    10. Publish decision to EventBus.
    11. Risk gate.
    12. Execute trade.
    13. Journal the result.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info(f"── cycle {ts} ──")

    # v14 Phase 3A heartbeat — must be first, before any work that might fail
    try:
        get_heartbeat().beat("main_loop", meta={"cycle": sys.get("_cycle_count", 0)})
        # Beat mission_tracker and telemetry here — unconditionally, before ANY
        # early-return path — so these subsystems are never DEAD just because
        # the bot is in a position or the cycle was a WAIT.
        # Previously these beats were placed after the ML step, meaning they
        # were NEVER sent when: (a) a position was open, (b) journal had open
        # trades, (c) VOLATILE skip, (d) any exception before that line.
        get_heartbeat().beat("mission_tracker", meta={"cycle": sys.get("_cycle_count", 0)})
        get_heartbeat().beat("telemetry",       meta={"cycle": sys.get("_cycle_count", 0)})
        get_heartbeat().beat("trade_manager",   meta={"cycle": sys.get("_cycle_count", 0)})
    except Exception:
        pass

    dp   = sys["data_provider"]

    # ── Clock drift guard ─────────────────────────────────────────────────
    # Re-sync ทุก 10 cycle เพื่อป้องกัน Windows clock drift สะสม (-1021)
    sys["_cycle_count"] = sys.get("_cycle_count", 0) + 1
    if sys["_cycle_count"] % 10 == 1:   # cycle 1, 11, 21, ...
        dp._sync_time_offset()
    smc  = sys["smc_engine"]
    vol  = sys["volume_engine"]
    reg  = sys["regime_engine"]
    ctxb = sys["context_builder"]
    ce   = sys["confidence_engine"]
    expl = sys["causal_explainer"]
    jrn  = sys["journal_v2"]
    rsk  = sys["risk_engine"]
    tm   = sys["trade_manager"]
    bus  = sys["event_bus"]

    try:
        # ── v14 Phase 2.5 — Commander pause check ───────────────────────────────
        # Checked first, before any work — "pause trader" must take effect
        # immediately on the next scheduled cycle. Guarded defensively; a
        # control-state import/read failure must never block trading.
        try:
            from commander.control_state import get_control_state
            if get_control_state().is_paused():
                logger.info("Trading cycle skipped — trader is PAUSED via Commander")
                return
        except Exception as exc:
            logger.debug(f"Commander pause check skipped: {exc}")

        # ── W14-0 — Commander lifecycle gate (start bot / stop bot) ─────────────
        # Independent of the pause flag above (see commander/control_state.py
        # module docstring for the full pause-vs-stop hierarchy). Unless the
        # bot has been explicitly started ("start bot"), no new trade decision
        # is generated at all — this is the primary way STOPPED avoids running
        # the AI/CEO decision pipeline. read fresh every cycle, never cached.
        # Guarded defensively, same style as the pause check: a control-state
        # read failure must never block trading.
        try:
            from commander.control_state import get_control_state
            if get_control_state().lifecycle_state() != "RUNNING":
                logger.info(
                    "Trading cycle skipped — bot lifecycle is not RUNNING "
                    "(use 'start bot' via Commander to begin trading)"
                )
                return
        except Exception as exc:
            logger.debug(f"Commander lifecycle check skipped: {exc}")

        # ── 1. Position check ─────────────────────────────────────────────────
        pos = dp.get_position_info()
        if pos:
            logger.info(
                f"Open position: {pos['side']} "
                f"qty={pos['positionAmt']} "
                f"entry={pos['entryPrice']:.2f} "
                f"uPnL={pos['unrealizedProfit']:.2f} U"
            )
            # v14 Phase 2.5 — bump EXECUTION → MONITORING now that the
            # position confirmed open on the exchange. Guarded defensively;
            # a tracker error here must never block the position-check skip.
            mission_tracker = sys.get("mission_tracker")
            mission_id = sys.get("current_mission_id")
            if mission_tracker is not None and mission_id is not None:
                try:
                    m = mission_tracker.get(mission_id)
                    if m is not None and m.stage == "EXECUTION":
                        mission_tracker.advance(mission_id, "MONITORING",
                                                 note="Position confirmed open on exchange")
                except Exception as exc:
                    logger.debug(f"Mission tracker MONITORING advance skipped: {exc}")

            # ── Dashboard-fix: still refresh live mark price / market context
            # while a position is open instead of returning immediately.
            # Previously this `return` froze _state["latest_decision"] and
            # _state["latest_context"] at whatever they were when the
            # position opened, so /api/decision, /api/futures, /api/regime
            # and /ws/decision all went stale for the entire lifetime of the
            # trade (sometimes 10+ minutes) — this is the dashboard
            # "not updating in real-time" bug. We still skip scoring/risk/
            # execution (no new trade while one is open) but we keep the
            # live price/context flowing to the dashboard every cycle.
            try:
                import api.app as _api_module
            except Exception:
                _api_module = None

            if _api_module is not None:
                try:
                    market = dp.get_all_market_data()
                    ohlcv  = market["ohlcv"]
                    regime_live = reg.classify(ohlcv["h1"])
                    smc_signals_live = smc.analyze_mtf(ohlcv)
                    vol_signals_live = vol.analyze(ohlcv["m15"])
                    market_ctx_live = ctxb.build(
                        market_data    = market,
                        smc_signals    = smc_signals_live,
                        volume_signals = vol_signals_live,
                        regime_result  = regime_live,
                        ohlcv_h4       = ohlcv.get("h4"),
                        ohlcv_h1       = ohlcv["h1"],
                    )
                    # Attach live position info so dashboard shows real uPnL.
                    # Normalized to the direction/quantity/entry_price shape
                    # TraderAgent expects — see _normalize_open_position().
                    market_ctx_live["open_position"] = _normalize_open_position(pos, jrn, tm)
                    _api_module.set_state("latest_context", market_ctx_live)

                    # Re-score so /api/decision and /ws/decision reflect the
                    # current market read (action will simply be ignored by
                    # the risk/execution gate below since we return early).
                    direction_live = market_ctx_live.get("mtf_direction", "")
                    mark_price_live = market_ctx_live["mark_price"]
                    ep_live, sl_live, tp_live = _derive_levels(
                        direction_live, mark_price_live, market_ctx_live
                    )
                    decision_live = ce.score(
                        market_context = market_ctx_live,
                        direction      = direction_live,
                        entry_price    = ep_live,
                        stop_loss      = sl_live,
                        take_profit    = tp_live,
                        mtf_aligned    = bool(market_ctx_live.get("mtf_aligned", False)),
                    )
                    _api_module.set_state("latest_decision", decision_live)

                    # Bug fix: the main cycle path below calls
                    # agent_layer["ceo"].decide(...) every tick, which
                    # internally runs every sub-agent (smc/futures/regime/
                    # risk/trader/journal) via BaseAgent.run() and sets
                    # their .last_report. This open-position branch never
                    # did that, so GET /api/agents returned {} for the
                    # entire lifetime of any open trade — the dashboard
                    # agent cards (everything except CEO) looked frozen.
                    # Run the same agent layer here so they keep refreshing.
                    agents_live = sys.get("agent_layer", {})
                    if agents_live:
                        try:
                            pos_info_live = market_ctx_live.copy()
                            pos_info_live["_ceo_decision"] = (
                                decision_live.to_dict() if hasattr(decision_live, "to_dict") else {}
                            )
                            pos_info_live["balance"] = 0.0
                            pos_info_live["open_position"] = _normalize_open_position(pos, jrn, tm)
                            ceo_live = agents_live.get("ceo")
                            if ceo_live is not None:
                                ceo_decision_live = ceo_live.decide(
                                    pos_info_live, confidence_result=decision_live
                                )
                                _api_module.set_state("ceo_decision", ceo_decision_live)
                        except Exception as exc:
                            logger.debug(f"Agent layer refresh while position open skipped: {exc}")
                except Exception as exc:
                    logger.debug(f"Live dashboard refresh while position open skipped: {exc}")

            return

        # ── 1b. Journal-level guard (catches stale exchange state) ────────────
        open_in_journal = jrn.get_open_trades()
        if open_in_journal:
            logger.info(
                f"Journal shows {len(open_in_journal)} open trade(s) — skipping cycle. "
                f"(If exchange position is closed, monitor loop will reconcile.)"
            )
            return

        # ── 2. Market data ────────────────────────────────────────────────────
        market = dp.get_all_market_data()
        ohlcv  = market["ohlcv"]

        # ── 3. Regime (H1) ────────────────────────────────────────────────────
        regime = reg.classify(ohlcv["h1"])

        if regime.regime == "VOLATILE" and regime.confidence > 0.80:
            logger.info(f"SKIP – VOLATILE regime (conf={regime.confidence:.2f})")
            regime_pub.warning(
                "VOLATILE_SKIP",
                f"Skipping cycle: VOLATILE regime conf={regime.confidence:.2f}",
                payload={"regime": regime.regime, "confidence": regime.confidence},
            )
            return

        # ── 4. SMC MTF ────────────────────────────────────────────────────────
        smc_signals = smc.analyze_mtf(ohlcv)

        # ── 5. Volume (M15) ───────────────────────────────────────────────────
        vol_signals = vol.analyze(ohlcv["m15"])

        # ── 6. Market Context ─────────────────────────────────────────────────
        market_ctx = ctxb.build(
            market_data    = market,
            smc_signals    = smc_signals,
            volume_signals = vol_signals,
            regime_result  = regime,
            ohlcv_h4       = ohlcv.get("h4"),
            ohlcv_h1       = ohlcv["h1"],
        )

        # ── 7. Direction from MTF consensus ───────────────────────────────────
        direction = market_ctx.get("mtf_direction", "")

        # Derive entry / SL / TP from context
        mark_price  = market_ctx["mark_price"]
        entry_price, stop_loss, take_profit = _derive_levels(
            direction, mark_price, market_ctx
        )

        # ── 8. Confidence score ───────────────────────────────────────────────
        decision = ce.score(
            market_context = market_ctx,
            direction      = direction,
            entry_price    = entry_price,
            stop_loss      = stop_loss,
            take_profit    = take_profit,
            mtf_aligned    = bool(market_ctx.get("mtf_aligned", False)),
        )

        # ── 8b. ML Advisor (Phase 3C) ─────────────────────────────────────────
        # Inserted between ConfidenceEngine and CausalExplainer per spec:
        # Signal → ConfidenceEngine → MLAdvisor → CEO → RiskEngine → Execution
        # ML may adjust confidence or recommend SKIP; it cannot place orders.
        try:
            from ml.ml_advisor import get_ml_advisor
            decision = get_ml_advisor().advise(decision, market_ctx, EXECUTION_LANE)
        except Exception as exc:
            logger.debug(f"MLAdvisor skipped: {exc}")

        # ── Per-cycle heartbeats ──────────────────────────────────────────────
        # NOTE: mission_tracker and telemetry beats are now at the TOP of
        # run_trading_cycle() so they fire before any early-return path.
        # This comment is kept as a breadcrumb; do not re-add beats here.

        # ── 9. Causal explanation ─────────────────────────────────────────────
        explanation = expl.explain(decision, market_ctx)

        # ── 10. Publish to EventBus ───────────────────────────────────────────
        _publish_decision(bus, decision, explanation, market_ctx)

        # Import _api_module once per cycle (safe to call before step 11)
        try:
            import api.app as _api_module
        except Exception:
            _api_module = None

        # ── 10a. Run AI Agent Layer (CEO + all employees) ────────────────────────
        agents = sys.get("agent_layer", {})
        # Phase 4B Step 1: initialised here (not just inside the `if agents:`
        # branch below) so the persist block in 10c can safely check it even
        # on a cycle where the agent layer didn't run.
        ceo_decision = None
        if agents:
            # Build augmented context with position + CEO decision
            pos_info = market_ctx.copy()
            pos_info["_ceo_decision"] = decision.to_dict() if hasattr(decision, "to_dict") else {}
            # balance not yet fetched — provide a sentinel; agents should not trade
            pos_info["balance"] = 0.0
            # Get open position for Trader agent
            try:
                raw_pos = dp.get_position_info()
                if raw_pos and float(raw_pos.get("positionAmt", 0)) != 0:
                    pos_info["open_position"] = _normalize_open_position(raw_pos, jrn, tm)
            except Exception:
                pass
            ceo = agents.get("ceo")
            if ceo and _api_module is not None:
                ceo_decision = ceo.decide(pos_info, confidence_result=decision)
                _api_module.set_state("ceo_decision", ceo_decision)

        # ── 10b. Push to dashboard API state ──────────────────────────────────
        # Runs every cycle (including WAIT) so /api/decision, /api/futures,
        # /api/regime and /ws/decision always reflect the latest pipeline run.
        if _api_module is not None:
            try:
                _api_module.set_state("latest_decision", decision)
                _api_module.set_state("latest_context",  market_ctx)
            except Exception as exc:
                logger.debug(f"Dashboard state update skipped: {exc}")

        # ── 10c. Persist history rows for /api/signals, /api/regime, /api/futures ─
        # These were previously never written, so dashboard charts/history were
        # always empty even though the pipeline computed everything correctly.
        sig_id = None
        try:
            sig_dict = decision.to_dict()
            sig_dict["score"] = decision.raw_score  # to_dict() uses raw_score key
            sig_id = jrn.save_signal(
                sig_dict,
                execution_lane       = EXECUTION_LANE,
                symbol               = settings.SYMBOL,
                confidence_breakdown = decision.breakdown,
                raw_features         = market_ctx,
            )
            # Phase 4B Step 1 (architecture.md §27): persist each sub-agent's
            # vote for this decision cycle, tagged with this signal's id.
            # agent_decisions.signal_id / trades.signal_id already existed in
            # the V13 schema for exactly this join, but the live pipeline
            # never wrote either side. Passing signal_id into save_trade()
            # below (once a trade actually opens) is what lets a later query
            # join a closed trade back to which agents voted for its
            # direction — no new tables/columns needed.
            if ceo_decision is not None:
                _ceo_ref = agents.get("ceo") if agents else None
                _weights = getattr(_ceo_ref, "WEIGHTS", {}) if _ceo_ref else {}
                for agent_key, report in ceo_decision.agent_reports.items():
                    try:
                        jrn.save_agent_decision(
                            agent     = report.get("agent", agent_key.upper()),
                            decision  = report.get("signal", "NEUTRAL"),
                            execution_lane = EXECUTION_LANE,
                            symbol    = settings.SYMBOL,
                            score     = float(report.get("confidence", 0.0)),
                            weight    = float(_weights.get(agent_key, 0.0)),
                            details   = report.get("raw"),
                            signal_id = sig_id,
                        )
                    except Exception as exc:
                        logger.debug(f"Agent decision persist skipped for {agent_key}: {exc}")
            jrn.save_market_regime(regime.to_dict(), symbol=settings.SYMBOL)
            jrn.save_funding(
                funding_rate = market.get("funding_rate", 0.0),
                mark_price   = mark_price,
                symbol       = settings.SYMBOL,
            )
            jrn.save_oi(
                open_interest = market.get("open_interest", 0.0),
                oi_value       = market.get("open_interest", 0.0) * mark_price,
                oi_delta_pct   = market.get("oi_delta", 0.0),
                symbol         = settings.SYMBOL,
            )
        except Exception as exc:
            logger.warning(f"History persist error (signal/regime/funding/oi): {exc}")

        logger.info(
            f"Decision={decision.action} "
            f"confidence={decision.confidence}% "
            f"dir={decision.direction} "
            f"MTF={decision.mtf_aligned} "
            f"regime={market_ctx['regime']} "
            f"oi_delta={decision.oi_delta:.4f} "
            f"funding={decision.funding_rate:.5f}"
        )

        if decision.action not in ("LONG", "SHORT"):
            return

        # ── v14 Phase 2.5 — Mission Pipeline: SIGNAL_FOUND → VALIDATION ────────
        # Created only for actionable signals (LONG/SHORT) since SIGNAL_FOUND
        # is meant to represent "a real trade idea", not every WAIT cycle.
        # All mission-tracker calls are defensively guarded — a failure here
        # must never break the live trading loop.
        mission_tracker = sys.get("mission_tracker")
        mission_id = None
        if mission_tracker is not None:
            try:
                mission = mission_tracker.create(
                    symbol=settings.SYMBOL,
                    direction=decision.action,
                    confidence=decision.confidence,
                    meta={
                        "entry_price": decision.entry_price,
                        "stop_loss":   decision.stop_loss,
                        "take_profit": decision.take_profit,
                        "regime":      market_ctx.get("regime", ""),
                        # Phase 3B: capture entry-time features for ML training
                        "funding":     getattr(decision, "funding_rate", None),
                        "oi_delta":    getattr(decision, "oi_delta", None),
                        "market_context_snapshot": market_ctx,
                    },
                )
                mission_id = mission.id
                mission_tracker.advance(mission_id, "VALIDATION",
                                         note="Agent layer + confidence scoring complete")
                sys["current_mission_id"] = mission_id
            except Exception as exc:
                logger.debug(f"Mission tracker create/advance skipped: {exc}")

        # ── 11. Risk gate ─────────────────────────────────────────────────────
        balance = dp.get_account_balance()
        # Update agent context with real balance now that it's available
        if agents and "pos_info" in dir():
            pos_info["balance"] = balance
        # P1-B1: regime is computed earlier this same cycle (used already at
        # the jrn.save_market_regime() call above) — atr_normalized is the
        # ATR-as-%-of-price RegimeEngine already computes every cycle for
        # regime classification. Reusing it here rather than computing ATR
        # a second time. Defensive getattr: if `regime` is ever None on some
        # early-return path before this point, atr_pct stays None and every
        # RiskEngine method below falls back to its pre-P1-B1 behavior.
        atr_pct = getattr(regime, "atr_normalized", None)

        ok, reason = rsk.can_trade(balance)
        if not ok:
            logger.warning(f"Risk gate BLOCKED: {reason}")
            risk_pub.warning(
                "RISK_BLOCK",
                f"Trade blocked by risk engine: {reason}",
                payload={"reason": reason, "balance": balance},
            )
            if mission_tracker is not None and mission_id is not None:
                try:
                    mission_tracker.advance(mission_id, "CLOSED",
                                             note=f"Blocked at risk gate: {reason}")
                    sys["current_mission_id"] = None
                except Exception as exc:
                    logger.debug(f"Mission tracker close-on-block skipped: {exc}")
            return

        if mission_tracker is not None and mission_id is not None:
            try:
                mission_tracker.advance(mission_id, "RISK_CHECK", note="Risk gate passed")
            except Exception as exc:
                logger.debug(f"Mission tracker RISK_CHECK advance skipped: {exc}")

        risk_pct = rsk.get_risk_pct(balance, atr_pct=atr_pct)
        leverage = rsk.get_leverage(atr_pct=atr_pct)

        logger.info(
            f"EXECUTING {decision.action} | "
            f"entry={decision.entry_price:.2f} "
            f"SL={decision.stop_loss:.2f} "
            f"TP={decision.take_profit:.2f} | "
            f"balance={balance:.2f} U risk={risk_pct*100:.2f}% "
            f"leverage={leverage}x"
            + (f" (ATR%={atr_pct*100:.2f}, scaled down from {settings.LEVERAGE}x)"
               if atr_pct is not None and leverage < settings.LEVERAGE else "")
        )

        # ── v14 Phase 2.5 — Commander paper-mode safety override ───────────────
        # When forced ON, real order placement is skipped entirely regardless
        # of EXECUTION_MODE — this is an emergency safety brake, not a full
        # paper-engine hot-swap (see commander/control_state.py docstring).
        paper_forced = False
        try:
            from commander.control_state import get_control_state
            paper_forced = bool(get_control_state().get_paper_mode_forced())
        except Exception as exc:
            logger.debug(f"Commander paper-mode check skipped: {exc}")

        # ── W14-0 — Commander lifecycle gate, defense-in-depth ──────────────────
        # The primary gate is the early-return near the top of this function
        # (right after the pause check) — under normal control flow this
        # execution path is unreachable when lifecycle_state != RUNNING.
        # This second check exists so the guarantee that "no NEW order is
        # submitted while stopped" holds at the actual order-submission call
        # site itself, not only via the early-return, matching the same
        # backend-enforcement standard already used for paper_forced above.
        # Read fresh, never cached, never trusts frontend/HTTP-response state.
        lifecycle_blocks_execution = False
        try:
            from commander.control_state import get_control_state
            lifecycle_blocks_execution = get_control_state().lifecycle_state() != "RUNNING"
        except Exception as exc:
            logger.debug(f"Commander lifecycle execution-gate check skipped: {exc}")

        if lifecycle_blocks_execution:
            logger.warning(
                "Execution SKIPPED — bot lifecycle is not RUNNING "
                "(no new orders while stopped)"
            )
            if mission_tracker is not None and mission_id is not None:
                try:
                    mission_tracker.advance(
                        mission_id, "CLOSED",
                        note="Execution skipped — bot lifecycle is not RUNNING",
                    )
                    sys["current_mission_id"] = None
                except Exception as exc:
                    logger.debug(f"Mission tracker lifecycle-gate close skipped: {exc}")
            return

        if paper_forced:
            logger.warning(
                "Execution SKIPPED — paper mode safety override is active "
                "(real orders disabled via Commander)"
            )
            if mission_tracker is not None and mission_id is not None:
                try:
                    mission_tracker.advance(
                        mission_id, "CLOSED",
                        note="Execution skipped — paper mode safety override active",
                    )
                    sys["current_mission_id"] = None
                except Exception as exc:
                    logger.debug(f"Mission tracker paper-override close skipped: {exc}")
            return

        # ── 12. Execute ───────────────────────────────────────────────────────
        # Beat trade_manager BEFORE execution so the subsystem is ALIVE even
        # when the trade fails. Previously the beat was inside the success
        # check — meaning a failed order left trade_manager as DEAD until the
        # next successful trade (which might never come in paper mode).
        try:
            get_heartbeat().beat("trade_manager", meta={"attempting": True})
        except Exception:
            pass
        exec_result = tm.execute_trade(
            direction   = decision.action,
            entry_price = decision.entry_price,
            stop_loss   = decision.stop_loss,
            take_profit = decision.take_profit,
            balance     = balance,
            risk_pct    = risk_pct,
            leverage    = leverage,
        )
        try:
            get_heartbeat().beat("trade_manager", meta={"success": exec_result.get("success")})
        except Exception:
            pass

        if mission_tracker is not None and mission_id is not None:
            try:
                if exec_result["success"]:
                    mission_tracker.advance(mission_id, "EXECUTION",
                                             note="Order filled",
                                             meta_update={"quantity": exec_result.get("quantity", 0.0)})
                else:
                    mission_tracker.advance(mission_id, "CLOSED",
                                             note=f"Execution failed: {exec_result.get('error')}")
                    sys["current_mission_id"] = None
            except Exception as exc:
                logger.debug(f"Mission tracker EXECUTION advance skipped: {exc}")

        # ── 13. Journal ───────────────────────────────────────────────────────
        m15_smc = smc_signals.get("m15", SMCSignals())
        rec = TradeRecord.from_decision(
            decision  = decision,
            smc_m15   = m15_smc,
            volume    = vol_signals,
            execution = exec_result if exec_result["success"] else None,
        )
        # Phase 4B Step 1: carries this cycle's signal_id onto the trade row
        # so get_agent_performance() can join back to which agents voted for
        # the direction that was actually traded.
        tid = jrn.save_trade(rec, execution_lane=EXECUTION_LANE, signal_id=sig_id)

        # V16 W14-2A: build per-agent attribution from the SAME
        # ceo_decision this cycle already produced above (10a) — nothing
        # recalculated — and persist it against this trade row via the
        # existing save_execution_attribution() merge API (the same one
        # execution/trade_lifecycle.py's record_trade_outcome() uses for
        # the CEO-gated multi-symbol path). trade_id is the natural
        # idempotency key: save_execution_attribution() merges into
        # trades.extra_data rather than appending, so calling this twice
        # for the same tid is a no-op overwrite, not a duplicate. Never
        # allowed to affect exec_result or raise past this point —
        # attribution is diagnostic/audit data, not an execution
        # authorization, matching this file's own established
        # try/except-and-log convention around save_agent_decision() at
        # 10c above.
        if ceo_decision is not None and tid:
            try:
                attribution = agent_attribution_from_ceo_decision(ceo_decision.to_dict())
                if attribution:
                    jrn.save_execution_attribution(tid, agent_attribution=attribution)
            except Exception as exc:
                logger.debug(f"Trade attribution persist skipped for trade #{tid}: {exc}")

        if exec_result["success"]:
            logger.info(f"Trade #{tid} executed successfully")
            brain_pub.info(
                "TRADE_EXECUTED",
                f"Trade #{tid} {decision.action} executed at {decision.entry_price:.2f}",
                payload={
                    "trade_id":    tid,
                    "action":      decision.action,
                    "entry_price": decision.entry_price,
                    "stop_loss":   decision.stop_loss,
                    "take_profit": decision.take_profit,
                    "confidence":  decision.confidence,
                },
            )
        else:
            logger.error(f"Trade #{tid} FAILED: {exec_result.get('error')}")
            brain_pub.warning(
                "TRADE_FAILED",
                f"Trade #{tid} failed: {exec_result.get('error')}",
                payload={"trade_id": tid, "error": exec_result.get("error")},
            )

    except Exception as exc:
        logger.error(f"Trading cycle error: {exc}", exc_info=True)
        brain_pub.warning(
            "CYCLE_ERROR",
            f"Trading cycle error: {exc}",
            payload={"error": str(exc)},
        )


# ── Trade monitor ─────────────────────────────────────────────────────────────

def monitor_open_trades(sys: dict) -> None:
    """
    Check whether open journal records have been closed by SL/TP on the
    exchange, and update results accordingly.
    """
    try:
        get_heartbeat().beat("monitor_loop")
    except Exception:
        pass

    dp  = sys["data_provider"]
    jrn = sys["journal_v2"]
    bus = sys["event_bus"]
    # V16 Phase 4B Step 3D: optional so this function still works
    # unchanged (falls back to the pre-existing direct jrn.update_trade_result()
    # call below) against a `sys` dict built without going through
    # build_system()'s new "trade_lifecycle" key — e.g. an older test
    # harness. build_system() itself always provides it.
    lifecycle = sys.get("trade_lifecycle")

    try:
        open_trades = jrn.get_open_trades()
        if not open_trades:
            return

        pos = dp.get_position_info()
        if pos is not None:
            return   # still in a position

        # Position closed – update journal records
        mark = dp.get_mark_price()

        for trade in open_trades:
            tid       = trade["id"]
            entry     = float(trade["entry_price"])
            sl        = float(trade["stop_loss"])
            tp        = float(trade["take_profit"])
            direction = trade["direction"]
            qty       = float(trade.get("quantity", 0.0))
            symbol    = trade.get("symbol") or settings.SYMBOL

            # Signed PnL — positive for profit, negative for loss
            if direction == "LONG":
                raw_pnl = (mark - entry) * qty
                result  = "WIN" if mark >= tp * 0.995 else "LOSS"
            else:
                raw_pnl = (entry - mark) * qty
                result  = "WIN" if mark <= tp * 1.005 else "LOSS"

            # PnL is already in USDT: (price_delta) × qty
            # qty itself was sized using risk_pct and NOT pre-multiplied by leverage,
            # so we must NOT apply leverage again here — that would double-count it.
            pnl = raw_pnl

            # V16 Phase 4B Step 3D: routed through TradeLifecycle (Part
            # C: "the only write path") instead of calling
            # jrn.update_trade_result() directly. This threshold-based
            # WIN/LOSS heuristic (unchanged above) is the closest signal
            # this function has to "which close source fired" — it does
            # NOT truly distinguish a TP-hit from any other reason the
            # position closed while in profit, nor an SL-hit from any
            # other reason it closed at a loss (Binance's SL/TP orders
            # aren't individually queried here) — TAKE_PROFIT/STOP_LOSS
            # below is this function's existing implicit assumption,
            # carried forward exactly as-is, not a new claim of
            # precision this phase adds.
            source = CloseSource.TAKE_PROFIT if result == "WIN" else CloseSource.STOP_LOSS
            if lifecycle is not None:
                handle = lifecycle.request_exit(symbol, source, f"{result.lower()}_threshold_heuristic", trade_id=tid)
                if handle is not None:
                    lifecycle.exit_executing(handle)
                    lifecycle.exit_confirmed(handle, result=result, exit_price=mark, pnl=pnl)
                else:
                    # Duplicate-close guard fired (Part I) — this trade_id
                    # was already closed through the lifecycle by another
                    # path (e.g. reconciliation) between get_open_trades()
                    # and this loop iteration. Falling back to the direct
                    # write below keeps this loop's own long-standing
                    # "always close what the exchange says is closed"
                    # guarantee intact rather than silently dropping it.
                    jrn.update_trade_result(tid, result, mark, pnl)
            else:
                jrn.update_trade_result(tid, result, mark, pnl)
            logger.info(f"Trade #{tid} closed → {result} pnl={pnl:.2f} U")

            brain_pub.info(
                "TRADE_CLOSED",
                f"Trade #{tid} closed: {result} pnl={pnl:.2f} U",
                payload={"trade_id": tid, "result": result, "pnl": pnl, "exit_price": mark},
            )

        # ── v14 Phase 2.5 — Mission Pipeline: MONITORING → CLOSED ──────────────
        # Closes the mission tracked across the run_trading_cycle/monitor_open_trades
        # pair via sys["current_mission_id"]. Guarded defensively — a tracker
        # error here must never affect journal correctness (already written above).
        mission_tracker = sys.get("mission_tracker")
        mission_id = sys.get("current_mission_id")
        if mission_tracker is not None and mission_id is not None:
            mission_obj = mission_tracker.get(mission_id)
            try:
                mission_tracker.advance(
                    mission_id, "CLOSED",
                    note=f"{result} pnl={pnl:.2f} U",
                    meta_update={"pnl": pnl, "exit_price": mark, "result": result},
                )
            except Exception as exc:
                logger.debug(f"Mission tracker final CLOSED advance skipped: {exc}")
            finally:
                sys["current_mission_id"] = None

            # Phase 3B — capture resolved trade as ML training row
            try:
                from research.dataset_builder import get_dataset_builder
                resolved = dict(trade)
                resolved["result"] = result
                resolved["pnl"] = pnl
                mm = (mission_obj.meta if mission_obj else {}) or {}
                get_dataset_builder().capture_closed_mission(
                    execution_lane=EXECUTION_LANE,
                    mission=mission_obj,
                    trade_row=resolved,
                    market_context=mm.get("market_context_snapshot"),
                    intelligence=None,
                )
            except Exception as exc:
                logger.debug(f"Dataset capture skipped: {exc}")

    except Exception as exc:
        logger.error(f"monitor_open_trades error: {exc}", exc_info=True)


# ── Daily report ──────────────────────────────────────────────────────────────

def run_position_reconciliation(sys: dict) -> None:
    """Phase 3A: Compare Exchange/Bot/Journal position every 60s."""
    try:
        engine = sys.get("reconciliation_engine")
        if engine:
            engine.run(sys)
    except Exception as exc:
        logger.error(f"run_position_reconciliation error: {exc}", exc_info=True)


def run_ghost_reconciliation_check(sys: dict) -> None:
    """Track C3 Phase 2 — off by default (settings.ORDER_RECONCILIATION_
    ENABLED). system_health/ghost_reconciliation.py's
    GhostReconciliationMonitor.check() calls the SAME read path every
    other consumer of this data already uses — OrderStateManager.
    get_order_state() -> ReconciliationEngine.run() ->
    data_provider.get_position_info() (protected by the existing
    _TRADE_BREAKER circuit breaker, same as every other caller) — not a
    second, independently-polling loop with its own cadence or its own
    exchange client.

    Known, pre-existing characteristic this job does NOT change:
    ReconciliationEngine.run() has no caching of its own — the existing
    60s run_position_reconciliation() job above, EVERY GET /api/
    order-state request, and this job each cause their own live
    get_position_info() call. Enabling this job adds one more such call
    at its own configured cadence (default: matches the existing 60s
    job); it does not fan out per-consumer within a single check(), and
    it never calls refresh(force=True) or queries Binance through any
    path other than the one every existing consumer already uses. See
    docs/architecture/GHOST_RECONCILIATION.md's Known Limitations
    section for the full accounting."""
    try:
        from system_health.ghost_reconciliation import get_ghost_reconciliation_monitor
        get_ghost_reconciliation_monitor().check(sys)
    except Exception as exc:
        logger.error(f"run_ghost_reconciliation_check error: {exc}", exc_info=True)


def run_nightly_retrain_job() -> None:
    """Phase 3C: Nightly ML retrain scheduled job (no sys dict needed)."""
    try:
        from ml.learning_mode import run_nightly_retrain
        result = run_nightly_retrain()
        logger.info(f"Nightly retrain: {result.get('status')} | "
                    f"rows={result.get('rows_available')} | "
                    f"meta_promoted={result.get('meta_label',{}).get('promoted')}")
    except Exception as exc:
        logger.error(f"run_nightly_retrain_job error: {exc}", exc_info=True)


def run_learning_recommendation_refresh(sys: dict) -> None:
    """V16 Phase 4C Step 4 (live scheduler wiring): the previously-missing
    producer for `_state["learning_recommendations"]` — api/app.py's
    `/api/recommendations` endpoint and agents/multi_symbol_adapter.py's
    CEO-gated live path have both read/consumed that key since Phase 4C
    Step 3, but nothing ever wrote it (see PATCH_NOTES.md's "known
    follow-up work" and this phase's own design audit, Part C).

    Mirrors run_nightly_retrain_job()'s shape exactly: no `sys` dict
    threading beyond the journal, guarded top-to-bottom, log-and-continue
    on any failure — a broken learning pipeline must never be able to
    take down the scheduler thread (same "safety wrapping at every
    touchpoint" rule as every other scheduled job in this file).

    Gated on settings.RECOMMENDATION_APPLICATION_ENABLED (default False,
    same flag CEOAgent itself checks before ever applying a
    recommendation) rather than a new setting — if recommendations are
    not going to be applied to any live decision, there is no reason to
    spend the (non-trivial: full trade-history scan + pattern mining)
    computation generating them. Re-checked on every call (not just once
    at schedule-registration) so flipping the setting at runtime takes
    effect on the next scheduled run, same live-re-read convention
    execution/ceo_gated_signal_provider.py's `enabled` property already
    uses.

    Does not create a new persistence layer: reuses the existing
    learning/learning_report.py::LearningReportGenerator unchanged, and
    the existing api/app.py::set_state() in-memory slot — no new state
    mechanism, no new schedule library, no new file writes.
    """
    if not settings.RECOMMENDATION_APPLICATION_ENABLED:
        logger.debug("Learning recommendation refresh skipped — "
                     "RECOMMENDATION_APPLICATION_ENABLED is False")
        return
    try:
        from learning.learning_report import LearningReportGenerator

        jrn = sys["journal_v2"]
        bundle = LearningReportGenerator(jrn).generate()

        try:
            import api.app as _api_module
            _api_module.set_state("learning_recommendations", bundle.recommendations)
            _api_module.set_state("learning_dataset_row_count", bundle.dataset.row_count)
        except Exception as exc:
            logger.debug(f"Dashboard state update skipped for learning recommendations: {exc}")

        logger.info(
            f"Learning recommendation refresh complete | "
            f"rows={bundle.dataset.row_count} "
            f"recommendations={len(bundle.recommendations)}"
        )
    except Exception as exc:
        logger.error(f"run_learning_recommendation_refresh error: {exc}", exc_info=True)


def daily_report(sys: dict) -> None:
    """Print formatted daily performance summary to log."""
    dp  = sys["data_provider"]
    jrn = sys["journal_v2"]

    try:
        balance = dp.get_account_balance()
        daily   = jrn.get_daily_stats()
        overall = jrn.get_performance_summary()
        risk    = sys["risk_engine"].report(balance)

        logger.info("=" * 62)
        logger.info("  DAILY PERFORMANCE REPORT")
        logger.info(f"  Balance       : {balance:.2f} USDT")
        logger.info(f"  Today PnL     : {daily['total_pnl']:.2f} USDT")
        logger.info(
            f"  Today trades  : {daily['total_trades']} "
            f"(W={daily['wins']} L={daily['losses']})"
        )
        logger.info(f"  Today WR      : {daily['win_rate']*100:.1f}%")
        logger.info(f"  Today avg RR  : {daily['avg_rr']:.2f}")
        # overall may be {"total_trades": 0, "message": "..."} when no closed trades
        wr_str = f"{overall.get('win_rate', 0) * 100:.1f}%" if overall.get('win_rate') is not None else "N/A"
        pf_val = overall.get('profit_factor')
        pf_str = f"{pf_val:.2f}" if pf_val is not None else "N/A"
        logger.info(f"  All-time WR   : {wr_str}")
        logger.info(f"  Profit Factor : {pf_str}")
        logger.info(f"  Consec losses : {risk['consecutive_losses']}")
        logger.info(f"  Can trade     : {risk['can_trade']}")
        logger.info("=" * 62)

    except Exception as exc:
        logger.error(f"daily_report error: {exc}", exc_info=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _derive_levels(
    direction: str,
    mark_price: float,
    ctx: dict,
) -> tuple[float, float, float]:
    """
    Derive entry / stop-loss / take-profit from market context.

    Uses SMC Order Block levels when available; falls back to ATR-based
    percentage offsets so the engine always has valid levels.
    """
    if not direction or not mark_price:
        return 0.0, 0.0, 0.0

    smc_m15 = ctx.get("smc_m15", {})
    ob_top    = float(smc_m15.get("ob_top",    0.0))
    ob_bottom = float(smc_m15.get("ob_bottom", 0.0))

    # ATR-based fallback offsets (configurable in settings if needed)
    SL_PCT = 0.018     # 1.8% stop
    TP_PCT = 0.054     # 5.4% take profit  (3R)

    if direction == "LONG":
        # OB bottom must be BELOW current price and within 3% (not stale/distant)
        ob_valid = ob_bottom and 0 < ob_bottom < mark_price and (mark_price - ob_bottom) / mark_price < 0.03
        entry = ob_bottom if ob_valid else mark_price
        sl    = entry * (1 - SL_PCT)
        tp    = entry * (1 + TP_PCT)
    else:  # SHORT
        # OB top must be ABOVE current price and within 3%
        ob_valid = ob_top and ob_top > mark_price and (ob_top - mark_price) / mark_price < 0.03
        entry = ob_top if ob_valid else mark_price
        sl    = entry * (1 + SL_PCT)
        tp    = entry * (1 - TP_PCT)

    return round(entry, 2), round(sl, 2), round(tp, 2)


def _fetch_resting_sl_tp(trade_client, direction: str) -> tuple[float, float]:
    """
    Best-effort read of the actual resting STOP_MARKET / TAKE_PROFIT_MARKET
    orders on the exchange for the current symbol, for the given position
    direction. Used as a fallback when the journal has no matching OPEN
    row to enrich SL/TP from (e.g. a position that existed on the account
    before this bot session started).

    Mirrors exactly how TradeManager.place_stop_loss()/place_take_profit()
    place these orders: closing side is SELL for a LONG position and BUY
    for a SHORT position; type is STOP_MARKET for the stop-loss and
    TAKE_PROFIT_MARKET for the take-profit; trigger price is in stopPrice.

    Returns (0.0, 0.0) on any failure (no client, paper mode, no resting
    orders, API error) rather than raising — this is a display enrichment,
    never something that should be allowed to break the trading cycle.
    """
    if trade_client is None or not hasattr(trade_client, "client"):
        # paper mode / no real exchange connection — nothing to fetch
        return 0.0, 0.0

    close_side = "SELL" if direction == "LONG" else "BUY"
    sl = tp = 0.0
    try:
        orders = trade_client.client.get_orders(symbol=trade_client.symbol)
        for o in orders or []:
            if o.get("side") != close_side:
                continue
            otype = o.get("type")
            price = float(o.get("stopPrice", 0.0) or 0.0)
            if not price:
                continue
            if otype == "STOP_MARKET":
                sl = price
            elif otype == "TAKE_PROFIT_MARKET":
                tp = price
    except Exception as exc:
        logger.debug(f"Resting SL/TP exchange lookup skipped: {exc}")
        return 0.0, 0.0
    return sl, tp


def _normalize_open_position(raw_pos: dict | None, journal=None, trade_client=None) -> dict | None:
    """
    Translate the raw Binance-shaped position dict from
    BinanceDataProvider.get_position_info() — keys: symbol, positionAmt,
    entryPrice, unrealizedProfit, side — into the snake_case/British-spelling
    shape TraderAgent.analyse() and the dashboard's open-position display
    expect: direction, quantity, entry_price, unrealised_pnl, stop_loss,
    take_profit.

    Bug fix: previously the raw dict was attached to market_context/
    pos_info["open_position"] as-is. TraderAgent did `pos.get("quantity", 0.0)`
    and `pos.get("direction", "LONG")` etc., which silently matched nothing
    and fell back to 0.0 / mark_price every cycle — so any live open
    position showed up on the dashboard as "LONG 0.0000 BTC @ <mark price>"
    instead of the real quantity and entry price, no matter how big the
    actual position was.

    stop_loss / take_profit aren't part of the exchange position response
    (Binance doesn't return "the SL/TP this bot intended" — only resting
    orders), so we best-effort enrich them from the matching OPEN row in
    the trade journal when one exists. If the position was opened outside
    the bot (or the journal write failed) there may be no matching row —
    in that case we fall back to reading the actual resting STOP_MARKET /
    TAKE_PROFIT_MARKET orders straight off the exchange via trade_client
    (when one is supplied and reachable). If neither source has anything,
    we leave them at 0.0 rather than inventing values; the dashboard
    already renders 0 distances as "0.00% away" without crashing.
    """
    if not raw_pos:
        return None

    direction = raw_pos.get("side", "LONG")
    qty       = abs(float(raw_pos.get("positionAmt", 0.0)))
    entry     = float(raw_pos.get("entryPrice", 0.0))
    upnl      = float(raw_pos.get("unrealizedProfit", 0.0))

    sl = tp = 0.0
    matched_journal_row = False
    if journal is not None:
        try:
            for t in journal.get_open_trades():
                # Match on direction; symbol is already fixed to settings.SYMBOL
                # for this whole process, so direction is the only discriminator
                # needed for a single-position-at-a-time bot.
                if t.get("direction") == direction:
                    sl = float(t.get("stop_loss", 0.0) or 0.0)
                    tp = float(t.get("take_profit", 0.0) or 0.0)
                    matched_journal_row = True
                    break
        except Exception as exc:
            logger.debug(f"Open-position SL/TP journal lookup skipped: {exc}")

    # Journal had no matching row (or the row had blank SL/TP) — this is
    # the pre-existing/foreign-position case. Fall back to whatever is
    # actually resting on the exchange before giving up and showing 0/0.
    if (not matched_journal_row) or (sl == 0.0 and tp == 0.0):
        ex_sl, ex_tp = _fetch_resting_sl_tp(trade_client, direction)
        sl = sl or ex_sl
        tp = tp or ex_tp

    return {
        "direction":        direction,
        "quantity":         qty,
        "entry_price":      entry,
        "unrealised_pnl":   upnl,
        "stop_loss":        sl,
        "take_profit":      tp,
        # Keep the raw fields too in case other/future consumers want them.
        "symbol":           raw_pos.get("symbol"),
        "positionAmt":      raw_pos.get("positionAmt"),
        "entryPrice":       raw_pos.get("entryPrice"),
        "unrealizedProfit": raw_pos.get("unrealizedProfit"),
        "side":             raw_pos.get("side"),
    }


def _publish_decision(bus: EventBus, decision, explanation, ctx: dict) -> None:
    """Publish a structured TRADE_DECISION event to the bus."""
    payload = {
        "action":       decision.action,
        "direction":    decision.direction,
        "confidence":   decision.confidence,
        "breakdown":    decision.breakdown,
        "blocked":      decision.blocked,
        "blocks":       decision.block_reasons,
        "entry_price":  decision.entry_price,
        "stop_loss":    decision.stop_loss,
        "take_profit":  decision.take_profit,
        "oi_delta":     decision.oi_delta,
        "funding_rate": decision.funding_rate,
        "regime":       ctx.get("regime"),
        "trend_bias":   ctx.get("trend_bias"),
        "mtf_aligned":  decision.mtf_aligned,
        "explanation":  explanation.to_dict() if explanation else None,
    }

    if decision.blocked:
        conf_pub.warning("TRADE_DECISION",
                         f"BLOCKED confidence={decision.confidence}%", payload)
    elif decision.action in ("LONG", "SHORT"):
        conf_pub.info("TRADE_DECISION",
                      f"{decision.action} confidence={decision.confidence}%", payload)
    else:
        conf_pub.debug("TRADE_DECISION",
                       f"{decision.action} confidence={decision.confidence}%", payload)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Graceful shutdown on Ctrl-C / SIGTERM
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Brain Bot BTCUSDT Futures v2 starting …")

    # Validate critical config
    if not settings.BINANCE_API_KEY or not settings.BINANCE_API_SECRET:
        logger.critical(
            "BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env – aborting"
        )
        sys.exit(1)

    logger.info(
        f"Symbol={settings.SYMBOL} "
        f"Leverage={settings.LEVERAGE}x "
        f"Testnet={settings.BINANCE_TESTNET} "
        f"Loop={settings.LOOP_INTERVAL}s"
    )

    # Build all components
    components = build_system()

    # Phase W10 — best-effort World Runtime + Simulation warm-up. Purely
    # additive: does not affect `components`, does not block startup if
    # it fails (see _initialize_world_runtime()'s own docstring).
    _initialize_world_runtime()

    # Schedule recurring tasks
    # ── Start dashboard API + open browser ──────────────────────────────────
    api_port = _start_api_server(
        journal       = components["journal_v2"],
        bus           = components["event_bus"],
        paper_engine  = components["paper_engine"],
        data_provider = components["data_provider"],
        agent_layer   = components["agent_layer"],
        risk_engine   = components["risk_engine"],
        portfolio_state       = components["portfolio_state"],
        trade_lifecycle       = components["trade_lifecycle"],
        reconciliation_engine = components["reconciliation_engine"],
    )
    _open_browser(api_port)

    schedule.every(settings.LOOP_INTERVAL).seconds.do(run_trading_cycle,  components)
    schedule.every(30).seconds.do(monitor_open_trades, components)
    schedule.every(60).seconds.do(run_position_reconciliation, components)
    # Track C3 Phase 2 — off by default; see config/settings.py
    # ORDER_RECONCILIATION_ENABLED and run_ghost_reconciliation_check()'s
    # own docstring above.
    if settings.ORDER_RECONCILIATION_ENABLED:
        schedule.every(settings.ORDER_RECONCILIATION_INTERVAL_SECONDS).seconds.do(
            run_ghost_reconciliation_check, components
        )
    schedule.every(1).hours.do(daily_report,            components)
    schedule.every().day.at("02:00").do(run_nightly_retrain_job)
    # V16 Phase 4C Step 4 — refresh _state["learning_recommendations"]
    # daily, off-peak (same cadence class as the nightly retrain job just
    # above; recommendations carry their own RECOMMENDATION_TTL_HOURS
    # (default 24h) expiry, so a daily refresh matches their own staleness
    # window). No-ops internally when RECOMMENDATION_APPLICATION_ENABLED
    # is False (see the job's own docstring) — registering it
    # unconditionally here is safe and keeps this list of scheduled jobs
    # a complete, truthful picture of what CAN run, same as every other
    # entry in this list.
    schedule.every().day.at("02:30").do(run_learning_recommendation_refresh, components)
    # Phase W10 — advance the World Simulation once per trading cycle,
    # same cadence as run_trading_cycle above (LOOP_INTERVAL). Additive;
    # see _tick_world_simulation()'s own docstring for why this can never
    # affect the trading loop even if World is broken.
    schedule.every(settings.LOOP_INTERVAL).seconds.do(_tick_world_simulation)
    # Phase W11 — export one Track A -> World snapshot per trading
    # cycle, same cadence as the two ticks above. Additive; see
    # _run_world_runtime_manager()'s own docstring for why this can
    # never affect the trading loop even if World or the export itself
    # is broken.
    schedule.every(settings.LOOP_INTERVAL).seconds.do(_run_world_runtime_manager, components)

    # Run immediately on startup
    run_trading_cycle(components)
    monitor_open_trades(components)
    run_position_reconciliation(components)
    daily_report(components)

    # v16 P0 hardening — start the watchdog supervisor only now, after
    # main_loop/monitor_loop already have their first heartbeat from the
    # synchronous run above. Starting it any earlier would see no
    # heartbeats yet and (without the grace period) could misread a cold
    # start as a hang. See system_health/watchdog.py:WatchdogSupervisor.
    watchdog_supervisor = start_watchdog_supervisor(components)
    components["watchdog_supervisor"] = watchdog_supervisor

    notify_ready()
    logger.info("Entering main loop …  (Ctrl-C to stop)")

    global _RUNNING
    while _RUNNING:
        schedule.run_pending()
        time.sleep(1)

    watchdog_supervisor.stop()
    # Track C3 Phase 1 — graceful stop for OrderTimeline's own background
    # poller so it isn't left as an unmanaged daemon thread. Scoped to
    # this phase's own new service only: market_scanner/execution_
    # scheduler have the same "daemon thread, no explicit stop() at
    # shutdown" gap pre-existing this phase — flagged separately rather
    # than silently fixed here, since neither is part of Track C3.
    if components.get("order_timeline") is not None:
        components["order_timeline"].stop()
    logger.info("Bot stopped. Final report:")
    daily_report(components)


if __name__ == "__main__":
    main()
