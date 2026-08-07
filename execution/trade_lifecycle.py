"""
execution/trade_lifecycle.py — V16 Phase 4B Step 3D: Unified Trade
Lifecycle & Trade Attribution

Single source of truth for "where is this trade right now" and the one
orchestration point every close path — regardless of source — reports
through, so journal/trade_attribution.py's record_trade_outcome() has
exactly one caller in the entire codebase (Part C: "becomes the only
write path"). Pure lifecycle orchestration only: no strategy logic, no
business decisions about WHEN or WHY to close (that judgment still
belongs entirely to each close source — e.g. main.py's own SL/TP
monitor still decides WIN vs LOSS; this module only records the
transition and performs the one write once that decision has already
been made elsewhere).

State machine
-------------
This phase's brief shows:

    OPEN -> EXECUTING -> OPEN -> MONITORING -> EXIT_REQUESTED
         -> EXIT_EXECUTING -> CLOSED (or FAILED)

"OPEN" appears twice in that diagram (once before EXECUTING, once
after) — an enum can't have two members with the same name, so the
FIRST one is named PENDING here (a trade that's been decided but whose
entry order hasn't been placed yet). Documented explicitly rather than
silently renamed without comment:

    PENDING -> EXECUTING -> OPEN -> MONITORING -> EXIT_REQUESTED
             -> EXIT_EXECUTING -> CLOSED
    (FAILED reachable from EXECUTING or EXIT_EXECUTING)

Known granularity limitation, stated rather than hidden: every real
open/close path in this codebase as of this phase calls
execute_trade()/close_position() SYNCHRONOUSLY and only learns
success-or-failure after the call returns — there is no mid-flight hook
anywhere in execution/trade_manager.py today that would let this module
observe EXECUTING (or EXIT_EXECUTING) as a state that persists for any
observable duration. Every real call site below transitions straight
through EXECUTING/EXIT_EXECUTING in the same breath as the transition
on either side of it. The states exist in this module (so a FUTURE
async/two-phase execution engine has somewhere to report progress
into) even though nothing observes them mid-flight today.
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from journal.trade_attribution import record_trade_outcome
from utils.logger import get_logger

logger = get_logger("execution.trade_lifecycle")


class TradeLifecycleState(str, Enum):
    PENDING         = "PENDING"
    EXECUTING       = "EXECUTING"
    OPEN            = "OPEN"
    MONITORING      = "MONITORING"
    EXIT_REQUESTED  = "EXIT_REQUESTED"
    EXIT_EXECUTING  = "EXIT_EXECUTING"
    CLOSED          = "CLOSED"
    FAILED          = "FAILED"


# Valid forward transitions only — no back-transitions. This table IS
# the entire "no duplicate closes" enforcement mechanism (Part H/I):
# a second exit request against a handle already in EXIT_REQUESTED,
# EXIT_EXECUTING, CLOSED, or FAILED has no allowed transition to move
# to, so request_exit() below rejects it deterministically — no
# separate lock, no race window, because the check-and-transition is
# one dict lookup plus one assignment, not a read-then-later-write
# sequence (see TradeLifecycle's own module-level note on why this is
# safe under concurrency without an explicit threading.Lock).
_TRANSITIONS: dict[TradeLifecycleState, frozenset[TradeLifecycleState]] = {
    TradeLifecycleState.PENDING:        frozenset({TradeLifecycleState.EXECUTING, TradeLifecycleState.FAILED}),
    TradeLifecycleState.EXECUTING:      frozenset({TradeLifecycleState.OPEN, TradeLifecycleState.FAILED}),
    TradeLifecycleState.OPEN:           frozenset({TradeLifecycleState.MONITORING}),
    TradeLifecycleState.MONITORING:     frozenset({TradeLifecycleState.EXIT_REQUESTED}),
    TradeLifecycleState.EXIT_REQUESTED: frozenset({TradeLifecycleState.EXIT_EXECUTING, TradeLifecycleState.FAILED}),
    TradeLifecycleState.EXIT_EXECUTING: frozenset({TradeLifecycleState.CLOSED, TradeLifecycleState.FAILED}),
    TradeLifecycleState.CLOSED:         frozenset(),
    TradeLifecycleState.FAILED:         frozenset(),
}


class CloseSource(str, Enum):
    """Every close source named in this phase's brief (Part B). Each is
    a value TradeLifecycle will accept and route through the same
    single pipeline — but listing a name here is NOT a claim that this
    codebase currently has a real, automatic trigger for it. See
    docs/architecture.md's Phase 4B Step 3D section, "Part B — close-
    source inventory", for exactly which of these map to real existing
    code today (STOP_LOSS/TAKE_PROFIT via main.py's legacy monitor,
    REPLACEMENT via execution_orchestrator.py, RECONCILIATION via
    system_health/recovery_engine.py, EMERGENCY_CLOSE via
    execution/trade_manager.py's in-flight abort) vs. which are
    supported-but-not-yet-triggered-by-anything (MANUAL_CLOSE,
    LIQUIDATION, EXCHANGE_CLOSE as a distinct close-side event,
    RISK_CLOSE, CEO_BLOCKED as a CLOSE rather than a pre-open veto).
    """
    STOP_LOSS           = "SL"
    TAKE_PROFIT         = "TP"
    CEO_BLOCKED         = "CEO_BLOCKED"
    REPLACEMENT         = "REPLACEMENT"
    PORTFOLIO_ROTATION  = "PORTFOLIO_ROTATION"  # same mechanism as REPLACEMENT in this codebase today
    RISK_CLOSE          = "RISK_CLOSE"
    RECOVERY            = "RECOVERY"
    MANUAL_CLOSE        = "MANUAL_CLOSE"
    EXCHANGE_CLOSE      = "EXCHANGE_CLOSE"
    RECONCILIATION      = "RECONCILIATION"
    LIQUIDATION         = "LIQUIDATION"
    EMERGENCY_CLOSE     = "EMERGENCY_CLOSE"


class TradeLifecycleError(Exception):
    """Raised only for a genuinely invalid transition request (a
    programming error at the call site, not a normal runtime
    condition). request_exit() specifically catches this itself and
    turns a duplicate-close attempt into a logged no-op rather than
    letting it propagate — see request_exit()'s own docstring."""


@dataclass
class TradeHandle:
    """One trade's in-process lifecycle state, held by whichever close
    source eventually needs it. NOT persisted itself — PortfolioState
    and the journal remain the actual source of truth for position
    existence across a process restart, same "in-memory only" caveat
    execution/execution_state.py's own module docstring already states
    for ExecutionState. TradeLifecycle.snapshot() (Part G) is a
    point-in-time read of this in-memory state, not a durability
    guarantee."""
    symbol:       str
    state:        TradeLifecycleState = TradeLifecycleState.PENDING
    trade_id:     Optional[int] = None
    opened_at:    Optional[float] = None
    exit_reason:  Optional[str] = None
    exit_source:  Optional[CloseSource] = None
    confidence:   Optional[float] = None


class TradeLifecycle:
    """Part A. Single source of truth for state transitions,
    validation, journal routing, portfolio notifications, and trade
    attribution. No business logic, no strategy logic — every decision
    about WHAT to do (open this symbol, close that one, for this
    reason) is made by the caller; this class only enforces that the
    resulting transition is valid and, on a terminal transition, writes
    the outcome exactly once.

    `journal`: anything record_trade_outcome() accepts (in production,
    journal.journal_v2.TradeJournalV2). `portfolio_manager`: anything
    exposing notify_position_closed(..., record_attribution=...) (in
    production, portfolio.portfolio_manager.PortfolioManager). Both
    optional — a TradeLifecycle constructed with neither still enforces
    the state machine and can be used in isolation (see Part H's tests),
    it just has nothing to write to.
    """

    def __init__(self, journal=None, portfolio_manager=None) -> None:
        self.journal = journal
        self.portfolio_manager = portfolio_manager
        self._handles: dict[str, TradeHandle] = {}

    # ── internal ─────────────────────────────────────────────────────

    def _transition(self, handle: TradeHandle, new_state: TradeLifecycleState) -> None:
        allowed = _TRANSITIONS.get(handle.state, frozenset())
        if new_state not in allowed:
            raise TradeLifecycleError(
                f"{handle.symbol}: invalid transition {handle.state.value} -> {new_state.value}"
            )
        handle.state = new_state

    # ── open side ────────────────────────────────────────────────────

    def open_pending(self, symbol: str) -> TradeHandle:
        """New candidate about to be executed. Overwrites any existing
        handle for this symbol (a fresh PENDING always means a fresh
        attempt — e.g. a re-selected symbol after a prior close)."""
        handle = TradeHandle(symbol=symbol)
        self._handles[symbol] = handle
        return handle

    def open_executing(self, handle: TradeHandle) -> None:
        self._transition(handle, TradeLifecycleState.EXECUTING)

    def open_confirmed(
        self,
        handle: TradeHandle,
        trade_id: int | None,
        *,
        execution_id: str | None = None,
        order_id: str | None = None,
        slippage: float | None = None,
        fees: float | None = None,
        latency_seconds: float | None = None,
        agent_attribution: list[dict] | None = None,
        confidence: float | None = None,
        source: str = "EXECUTION_ORCHESTRATOR",
    ) -> None:
        """Entry order filled. Transitions OPEN then immediately
        MONITORING (nothing in this codebase distinguishes "just opened,
        not yet watched" from "being watched" as separate observable
        states today — see module docstring's granularity note) and
        records the open-side attribution via record_trade_outcome(),
        the same single write path the close side uses."""
        self._transition(handle, TradeLifecycleState.OPEN)
        handle.trade_id  = trade_id
        handle.opened_at = time.time()
        handle.confidence = confidence
        self._transition(handle, TradeLifecycleState.MONITORING)

        if self.journal is not None and trade_id is not None:
            try:
                record_trade_outcome(
                    self.journal, trade_id,
                    execution_id=execution_id, order_id=order_id,
                    slippage=slippage, fees=fees, latency_seconds=latency_seconds,
                    agent_attribution=agent_attribution, confidence=confidence,
                    source=source, symbol=handle.symbol,
                )
            except Exception as exc:
                logger.error(f"TradeLifecycle: open-side record failed for {handle.symbol}: {exc}")

    def open_failed(self, handle: TradeHandle, reason: str, source: str = "EXECUTION_ORCHESTRATOR") -> None:
        """Entry never confirmed (rejected, or — execution/trade_manager.py's
        EMERGCLOSE case — filled then immediately had to be closed again
        because SL placement failed, before any journal row existed to
        attach a close outcome to). Modeled as an open-side FAILURE
        rather than a close, since there is no trade_id to write a close
        outcome against — see docs/architecture.md's Phase 4B Step 3D
        section for why EMERGCLOSE specifically is handled this way.

        The handle is kept (not removed) in a terminal FAILED state —
        see exit_confirmed()'s own docstring below for why that matters:
        it's what lets a later duplicate call against the same symbol
        be correctly rejected instead of silently treated as a
        brand-new position."""
        self._transition(handle, TradeLifecycleState.FAILED)
        handle.exit_reason = reason

    # ── close side ───────────────────────────────────────────────────

    def request_exit(
        self,
        symbol: str,
        source: CloseSource,
        reason: str,
        *,
        trade_id: int | None = None,
    ) -> TradeHandle | None:
        """Entry point every close source calls. Returns None (logged,
        not raised) if this symbol already has a close in flight or
        completed — the entire duplicate-close guard (Part H/I) is this
        one check, backed by _TRANSITIONS above.

        If no handle exists for this symbol (a position that was opened
        before this lifecycle tracked it — e.g. anything opened through
        the legacy single-symbol path, which does not yet call
        open_confirmed(); see "Known limitation" in the phase's own
        design notes), a synthetic MONITORING handle is constructed on
        the fly so the close can still be unified through this same
        pipeline rather than being rejected outright."""
        handle = self._handles.get(symbol)
        if handle is None:
            handle = TradeHandle(symbol=symbol, state=TradeLifecycleState.MONITORING, trade_id=trade_id)
            self._handles[symbol] = handle
        elif trade_id is not None and handle.trade_id is None:
            handle.trade_id = trade_id

        try:
            self._transition(handle, TradeLifecycleState.EXIT_REQUESTED)
        except TradeLifecycleError as exc:
            logger.warning(f"TradeLifecycle: duplicate/invalid close request for {symbol} ignored ({exc})")
            return None

        handle.exit_reason = reason
        handle.exit_source = source
        return handle

    def exit_executing(self, handle: TradeHandle) -> None:
        self._transition(handle, TradeLifecycleState.EXIT_EXECUTING)

    def exit_confirmed(
        self,
        handle: TradeHandle,
        *,
        result: str | None = None,
        exit_price: float | None = None,
        pnl: float | None = None,
        execution_id: str | None = None,
        order_id: str | None = None,
        fees: float | None = None,
        slippage: float | None = None,
        latency_seconds: float | None = None,
        agent_attribution: list[dict] | None = None,
        confidence: float | None = None,
        notify_portfolio: bool = True,
    ) -> None:
        """Close order filled (or, for a bookkeeping-only close like
        RECONCILIATION's ghost-row cleanup, the correction was applied).
        Writes the outcome via record_trade_outcome() exactly once
        (Part C), then notifies PortfolioManager for cooldown/
        PortfolioState bookkeeping ONLY — record_attribution=False is
        passed so notify_position_closed() does not write to the
        journal a second time (Part D: "PortfolioManager must never
        mutate journal directly").

        The handle is kept (not removed) in a terminal CLOSED state,
        deliberately — this is what lets a SECOND close attempt against
        the same symbol be correctly rejected by request_exit()'s
        transition check (CLOSED has no allowed outgoing transitions)
        instead of being silently mistaken for "a position this
        lifecycle never saw open" and allowed through as a fresh
        synthetic close. This is the actual mechanism behind Part I's
        "no duplicate closes" requirement — verified directly by a
        dedicated test. Terminal handles are excluded from snapshot()
        (Part G) so the dashboard view stays limited to what's
        genuinely open or in flight, and are naturally replaced (not
        leaked) the next time open_pending() is called for that same
        symbol."""
        self._transition(handle, TradeLifecycleState.CLOSED)
        duration_seconds = (time.time() - handle.opened_at) if handle.opened_at else None

        if self.journal is not None and handle.trade_id is not None:
            try:
                record_trade_outcome(
                    self.journal, handle.trade_id,
                    result=result, exit_price=exit_price, pnl=pnl,
                    execution_id=execution_id, order_id=order_id,
                    fees=fees, slippage=slippage, latency_seconds=latency_seconds,
                    agent_attribution=agent_attribution,
                    confidence=confidence if confidence is not None else handle.confidence,
                    reason=handle.exit_reason,
                    source=handle.exit_source.value if handle.exit_source else None,
                    symbol=handle.symbol, duration_seconds=duration_seconds,
                )
            except Exception as exc:
                logger.error(f"TradeLifecycle: close-side record failed for {handle.symbol}: {exc}")

        if notify_portfolio and self.portfolio_manager is not None:
            try:
                self.portfolio_manager.notify_position_closed(
                    handle.symbol, trade_id=handle.trade_id, record_attribution=False,
                )
            except Exception as exc:
                logger.error(f"TradeLifecycle: portfolio notify failed for {handle.symbol}: {exc}")

    def exit_failed(self, handle: TradeHandle, reason: str) -> None:
        """Close order failed (e.g. Exchange Reject on the close side).
        Same "keep the terminal handle, don't pop it" reasoning as
        exit_confirmed() above — FAILED also has no allowed outgoing
        transitions, so a retry attempt against the same symbol is
        rejected the same way a duplicate CLOSED attempt is, rather
        than silently retried as if nothing had happened."""
        self._transition(handle, TradeLifecycleState.FAILED)
        handle.exit_reason = reason

    # ── Part G: read-only state for the dashboard ──────────────────────

    def get_state(self, symbol: str) -> TradeLifecycleState | None:
        handle = self._handles.get(symbol)
        return handle.state if handle else None

    def get_handle_snapshot(self, symbol: str) -> dict | None:
        """Same row shape as one entry of snapshot() below, but for
        exactly one symbol AND including terminal CLOSED/FAILED handles.
        snapshot() deliberately excludes terminal handles (see its own
        docstring — it's a "what's live right now" view for the
        dashboard). A read-model that needs to observe the FINAL
        transition into CLOSED/FAILED — e.g. execution/order_timeline.py
        (Track C3), which persists every observed state change including
        the terminal one — would otherwise lose exit_reason/trade_id the
        same poll cycle the symbol drops out of snapshot(). Read-only;
        does not affect snapshot(), __len__, or any transition method."""
        handle = self._handles.get(symbol)
        if handle is None:
            return None
        return {
            "symbol":      handle.symbol,
            "state":       handle.state.value,
            "trade_id":    handle.trade_id,
            "exit_reason": handle.exit_reason,
            "exit_source": handle.exit_source.value if handle.exit_source else None,
            "confidence":  handle.confidence,
        }

    def known_symbols(self) -> list[str]:
        """Every symbol this TradeLifecycle currently holds ANY handle
        for, live or terminal — a superset of snapshot()'s symbols.
        Lets a poll-based read-model (execution/order_timeline.py,
        Track C3) discover a symbol that went all the way to
        CLOSED/FAILED between two of the read-model's OWN poll cycles
        (or before its very first one) — get_handle_snapshot(symbol)
        alone cannot do this since it requires already knowing the
        symbol to look up. Read-only; does not affect snapshot(),
        __len__, or any transition method."""
        return list(self._handles.keys())

    def snapshot(self) -> list[dict]:
        """Every symbol currently open or in the middle of opening/
        closing — i.e. everything EXCEPT terminal CLOSED/FAILED handles,
        which are kept internally (see exit_confirmed()'s docstring for
        why) but deliberately excluded here so this stays "what's live
        right now", not a growing-forever history."""
        return [
            {
                "symbol":      h.symbol,
                "state":       h.state.value,
                "trade_id":    h.trade_id,
                "exit_reason": h.exit_reason,
                "exit_source": h.exit_source.value if h.exit_source else None,
                "confidence":  h.confidence,
            }
            for h in self._handles.values()
            if h.state not in (TradeLifecycleState.CLOSED, TradeLifecycleState.FAILED)
        ]

    def __len__(self) -> int:
        """Count of LIVE handles only (matches snapshot()'s own
        filter) — used by Part I's stress tests to assert no orphan
        positions are left behind after a batch of opens+closes."""
        return sum(
            1 for h in self._handles.values()
            if h.state not in (TradeLifecycleState.CLOSED, TradeLifecycleState.FAILED)
        )

    def __bool__(self) -> bool:
        """Always True, deliberately — without this, defining __len__
        above makes Python treat a freshly-constructed (empty, 0 live
        handles) TradeLifecycle as falsy, which silently breaks any
        `some_lifecycle or TradeLifecycle(...)` fallback pattern
        anywhere a caller passes in an empty-but-valid instance (this
        phase's own execution/execution_orchestrator.py constructor
        had exactly this bug — found by this phase's own integration
        tests, fixed there to use an explicit `is not None` check
        instead, and fixed here too so the mistake can't silently
        recur anywhere else this class is used the same way)."""
        return True


# ── Process-wide default instance ───────────────────────────────────────
#
# Mirrors execution/execution_state.py's get_execution_state() exactly
# (same double-checked-locking pattern) — for the same reason: most
# callers (main.py's bootstrap, api/lifecycle_api.py's dashboard read
# layer, Part G) want ONE well-known TradeLifecycle they can all reach,
# not each constructing their own isolated instance. A caller that DOES
# want an isolated instance (tests, anything in this phase's own
# tests/test_trade_lifecycle.py) constructs TradeLifecycle(...) directly
# instead of calling this — both are always valid, this is a default,
# not the only way to get one.
_global_lifecycle: TradeLifecycle | None = None
_lifecycle_lock = threading.Lock()


def get_default_trade_lifecycle(journal=None, portfolio_manager=None) -> TradeLifecycle:
    """Returns the process-wide default TradeLifecycle, constructing it
    on first call. `journal`/`portfolio_manager` are only used for that
    first construction (matches ExecutionState's own "configuration
    only matters on first call" convention) — a later call with
    different arguments does NOT reconfigure the existing instance, it
    just returns it unchanged; construct a fresh TradeLifecycle(...)
    directly if you need a differently-configured one."""
    global _global_lifecycle
    if _global_lifecycle is None:
        with _lifecycle_lock:
            if _global_lifecycle is None:
                _global_lifecycle = TradeLifecycle(journal=journal, portfolio_manager=portfolio_manager)
    return _global_lifecycle


def reset_default_trade_lifecycle() -> None:
    """Test-only: clear the process-wide singleton between test cases —
    same purpose as events/event_bus.py's own reset_event_bus()."""
    global _global_lifecycle
    with _lifecycle_lock:
        _global_lifecycle = None
