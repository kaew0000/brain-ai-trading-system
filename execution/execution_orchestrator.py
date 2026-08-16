"""
execution/execution_orchestrator.py — V16 Phase 2E: Execution Wiring &
Live Orchestrator

docs/architecture.md §20 ("Next up") names this piece explicitly:
"reading real exchange/journal state into a PortfolioState each cycle,
driving the position state machine, calling ExecutionCoordinator's
per-symbol TradeManager with an OrchestratedDecision's allocations, and
actually acting on (or discarding) a ReplacementProposal — including
feeding real closures back through PortfolioManager.notify_position_closed()".
This module builds the "calling ... with an OrchestratedDecision's
allocations" and "acting on a ReplacementProposal" pieces. It
deliberately does NOT build the other two things §20 lists in the same
breath:

  - "reading real exchange/journal state into a PortfolioState each
    cycle" is reconciliation (system_health/reconciliation.py already
    exists for this concern) — ExecutionOrchestrator is handed a
    PortfolioState by its caller and updates it as executions complete;
    it does not construct one from scratch.
  - A scheduler that calls PortfolioManager.decide() then
    ExecutionOrchestrator.execute() on a timer. CLAUDE.md's own
    priority list has "Execution Scheduler" as a distinct, later
    priority after Portfolio Manager/Capital Allocation/Correlation/
    Sector Engine — treating it as part of *this* phase would be
    starting a future phase early. ExecutionOrchestrator.execute() is a
    plain method any scheduler can call once one exists; nothing here
    assumes or builds the calling loop.

Signal boundary
------------------------------------------------------------------------
portfolio/portfolio_models.py's PortfolioAllocation carries capital_amount/
risk_pct/leverage but explicitly NO entry/stop-loss/take-profit price —
"those come from the per-symbol Strategy/Decision layer at execution
time, which is out of scope here" (that module's own docstring).
execution/strategy.py's SMC_OI_Regime_Strategy is that layer today, but
it is single-symbol-shaped (reads one global data_provider, no symbol
parameter) — reshaping it into a per-arbitrary-symbol signal source
would be redesigning existing execution/decision logic, which this
phase's brief explicitly rules out. ExecutionOrchestrator instead takes
a `signal_provider: Callable[[str], Optional[ExecutionSignal]]` as a
constructor dependency — the same dependency-injection idiom
TradeManager(data_provider)/CapitalManager(correlation_engine=...)/
SMC_OI_Regime_Strategy(decision_engine, ...) already use throughout this
codebase. Whatever future phase adapts per-symbol signal generation for
the portfolio (in-scope work explicitly deferred here) plugs in as this
callable; ExecutionOrchestrator does not know or care how it is
implemented.

Replacement handling
------------------------------------------------------------------------
portfolio/portfolio_models.py's ReplacementProposal docstring is explicit
that a proposal is "a RECOMMENDATION, not an action" and is "deliberately
NOT merged into OrchestratedDecision.selected/total_capital_allocated:
there is no entry/stop-loss price at this decision layer to size a
not-yet-open replacement position with". This phase acts on the
CLOSE side only (closing `outgoing_symbol`, then calling
PortfolioManager.notify_position_closed() so cooldown/min-hold
bookkeeping reflects the real closure) — the freed capacity naturally
lets `incoming_symbol` (or whatever ranks highest next cycle) be
selected as an ordinary allocation on a subsequent decide() call,
already fully specified with capital/risk/leverage. Attempting to open
`incoming_symbol` directly from a ReplacementProposal here would mean
inventing sizing data that structurally doesn't exist at this layer.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from collections.abc import Callable

from execution.execution_events import (
    ExecutionEventType,
    publish_execution_event,
)
from execution.execution_metrics import ExecutionMetricsSnapshot, compute_metrics
from execution.execution_state import ExecutionState, ExecutionStatus, get_execution_state
from execution.trade_lifecycle import CloseSource
from portfolio.portfolio_models import (
    OrchestratedDecision,
    PortfolioAllocation,
    ReplacementProposal,
)
from portfolio.portfolio_models import PortfolioPosition, PositionState
from portfolio.portfolio_state import PortfolioState
from utils.logger import get_logger

logger = get_logger(__name__)

# Error substrings that mean "do not retry" — matches the phase brief's
# explicit "Never retry: risk rejection, insufficient capital, duplicate
# order, manual cancel" list. Anything NOT matching one of these is
# treated as recoverable (network/timeout/rate-limit-shaped failures)
# and retried up to max_retries — trade_manager.py's own
# @retry_api_call decorator has already exhausted ITS retries for
# ordinary transient API errors by the time execute_trade() returns
# success=False, so what reaches here is either a genuine business
# rejection (below) or a fully-exhausted transient failure (worth one
# more attempt at this higher orchestration layer, since a fresh
# attempt re-fetches leverage/margin/qty from scratch rather than
# resuming mid-sequence).
_NON_RECOVERABLE_MARKERS = (
    "rejected by exchange",   # entry/SL order rejected — exchange-level business rejection
    "invalid qty",            # sizing / insufficient capital
    "duplicate",               # duplicate order / duplicate clientOrderId unresolved
    "manual_cancel",           # explicit external cancel — never auto-retried
    "not configured on this coordinator",  # programming/config error, not transient
)


def _is_recoverable_error(error: str | None) -> bool:
    if not error:
        return True  # e.g. close_position() returning None with no message — no
                      # evidence it's a permanent rejection; treat as retryable.
    lowered = error.lower()
    return not any(marker in lowered for marker in _NON_RECOVERABLE_MARKERS)


def _compute_slippage(direction: int, requested_price: float, entry_order: dict) -> float | None:
    """V16 Phase 4B Step 2: entry slippage = actual fill price minus the
    requested price, direction-adjusted so a POSITIVE number always
    means "cost more than intended" (paid more on a LONG entry, or sold
    for less on a SHORT entry) regardless of side — the conventional
    meaning of slippage. Returns None (not 0.0) when there's no usable
    fill price to compare against, e.g. paper mode's order dicts don't
    carry `avgPrice`/`price` at all — None means "not computable", not
    "zero slippage".
    """
    if not isinstance(entry_order, dict) or not requested_price:
        return None
    fill = entry_order.get("avgPrice") or entry_order.get("price")
    try:
        fill = float(fill)
    except (TypeError, ValueError):
        return None
    if not fill:
        return None
    raw = fill - requested_price
    return round(raw if direction == 1 else -raw, 6)


@dataclass(frozen=True)
class ExecutionSignal:
    """The per-symbol trade signal ExecutionOrchestrator needs but
    PortfolioAllocation deliberately doesn't carry (see module
    docstring's "Signal boundary" section). `direction` follows the
    same 1/-1/0 convention execution/strategy.py's generate_signal()
    already uses (1=LONG, -1=SHORT, 0=no trade)."""

    direction:   int
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    # V16 Phase 4C Step 7C: optional shared signal_id carried from a
    # signal-layer provider (e.g. execution/ceo_gated_signal_provider.py)
    # that already journaled a CEO decision cycle's signal row. Default
    # None preserves every pre-existing positional/keyword construction
    # site unchanged (execution/portfolio_signal_provider.py,
    # execution/strategy_registry.py, every test file's ExecutionSignal(...)
    # literal) — see _record_trade_opened() below for how this is
    # consumed at trade-open time.
    signal_id:   int | None = None
    # V16 W14-2A: optional per-agent attribution list carried from a
    # CEO-gated signal-layer provider (execution/ceo_gated_signal_provider.py)
    # that already ran agents/ceo_agent.py's CEOAgent for this cycle —
    # see journal/trade_attribution.py's agent_attribution_from_ceo_decision()
    # for the shape. Default None preserves every pre-existing
    # positional/keyword construction site unchanged (same rationale as
    # signal_id above). Consumed at trade-open time by
    # _record_trade_opened() below.
    agent_attribution: list[dict] | None = None


SignalProvider = Callable[[str], ExecutionSignal | None]


@dataclass
class ExecutionResult:
    """Outcome of one execution attempt — either opening an allocation
    or closing a replacement's outgoing side (see `is_replacement`)."""

    execution_id:   str
    symbol:         str
    status:         ExecutionStatus
    success:        bool
    retries:        int
    error:          str | None
    order_result:   dict | None
    is_replacement: bool = False

    def to_dict(self) -> dict:
        return {
            "execution_id":   self.execution_id,
            "symbol":         self.symbol,
            "status":         self.status.value,
            "success":        self.success,
            "retries":        self.retries,
            "error":          self.error,
            "is_replacement": self.is_replacement,
        }


@dataclass
class ExecutionBatch:
    """The full outcome of one ExecutionOrchestrator.execute() call —
    one batch per OrchestratedDecision acted on."""

    batch_id:             str
    decision_generated_at: float
    results:               list[ExecutionResult] = field(default_factory=list)
    started_at:             float = 0.0
    finished_at:            float = 0.0

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    def summary(self) -> ExecutionSummary:
        completed = [r for r in self.results if r.status == ExecutionStatus.COMPLETED]
        failed    = [r for r in self.results if r.status == ExecutionStatus.FAILED]
        cancelled = [r for r in self.results if r.status == ExecutionStatus.CANCELLED]
        return ExecutionSummary(
            batch_id=self.batch_id,
            total=len(self.results),
            completed=len(completed),
            failed=len(failed),
            cancelled=len(cancelled),
            duration_seconds=self.duration_seconds,
        )

    def to_dict(self) -> dict:
        return {
            "batch_id":              self.batch_id,
            "decision_generated_at": self.decision_generated_at,
            "results":               [r.to_dict() for r in self.results],
            "duration_seconds":      self.duration_seconds,
            "summary":               self.summary().to_dict(),
        }


@dataclass(frozen=True)
class ExecutionSummary:
    """Batch-scoped aggregate — contrast with ExecutionMetricsSnapshot
    (execution/execution_metrics.py), which is process-wide/cumulative
    across every batch this orchestrator has ever run. Both are real,
    non-redundant views: this answers "how did THIS decision's
    execution go", that answers "how is execution doing overall"."""

    batch_id:          str
    total:             int
    completed:         int
    failed:            int
    cancelled:         int
    duration_seconds:   float

    def to_dict(self) -> dict:
        return {
            "batch_id":          self.batch_id,
            "total":             self.total,
            "completed":         self.completed,
            "failed":            self.failed,
            "cancelled":         self.cancelled,
            "duration_seconds":  round(self.duration_seconds, 4),
        }


class ExecutionOrchestrator:
    """Connects PortfolioManager's decisions to the existing execution
    layer. See module docstring for exact scope boundaries."""

    def __init__(
        self,
        execution_engine,           # whatever execution.execution_factory.build_execution_engine() returned
        portfolio_manager,          # portfolio.portfolio_manager.PortfolioManager
        signal_provider: SignalProvider,
        execution_lane: str,        # W14-2D-1: required, no default — see docs/architecture.md's W14-2D-1 section
        state: ExecutionState | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        journal=None,                # V16 Phase 4B Step 2: TradeJournalV2-compatible; None = attribution inert
        lifecycle=None,              # V16 Phase 4B Step 3D: execution.trade_lifecycle.TradeLifecycle
    ) -> None:
        from config.settings import settings
        from execution.trade_lifecycle import TradeLifecycle
        from journal.journal_v2 import VALID_EXECUTION_LANES

        if execution_lane not in VALID_EXECUTION_LANES:
            raise ValueError(
                f"ExecutionOrchestrator: execution_lane must be one of "
                f"{VALID_EXECUTION_LANES}, got {execution_lane!r}"
            )
        self.execution_lane = execution_lane

        self.execution_engine = execution_engine
        self.portfolio_manager = portfolio_manager
        self.signal_provider = signal_provider
        self.state = state or get_execution_state()
        self.journal = journal
        # Not passed by any caller as of this phase — auto-constructed
        # from the same journal/portfolio_manager this orchestrator
        # already has, so a fresh TradeLifecycle wraps exactly the same
        # record_trade_outcome()/notify_position_closed() calls this
        # class already made directly before this phase — same
        # arguments, same order, just routed through one more layer.
        # Every existing test/caller that constructs ExecutionOrchestrator
        # without knowing `lifecycle` exists gets identical journal/
        # portfolio output to before this phase (see
        # docs/architecture.md's Phase 4B Step 3D compatibility report).
        # V16 Phase 4B Step 3D: explicit `is not None` check — NOT
        # `lifecycle or TradeLifecycle(...)`. TradeLifecycle defines
        # __len__ (for Part I's "no orphan positions" assertions), which
        # makes a freshly-constructed, EMPTY TradeLifecycle instance
        # falsy in a plain `or` check — `lifecycle or default` would
        # silently discard any caller-supplied lifecycle that happened
        # to have zero open positions at construction time (exactly
        # main.py's bootstrap ordering: trade_lifecycle is empty when
        # first passed here). Found by this phase's own integration
        # tests before it reached anywhere near production — see
        # docs/architecture.md's Phase 4B Step 3D section.
        self.lifecycle = lifecycle if lifecycle is not None else TradeLifecycle(journal=journal, portfolio_manager=portfolio_manager)
        self.max_retries = (
            max_retries if max_retries is not None else settings.EXECUTION_MAX_RETRIES
        )
        self.retry_delay_seconds = (
            retry_delay_seconds if retry_delay_seconds is not None
            else settings.EXECUTION_RETRY_DELAY_SECONDS
        )
        logger.info(
            f"ExecutionOrchestrator ready | max_retries={self.max_retries} "
            f"retry_delay_seconds={self.retry_delay_seconds}"
        )

    # ── Main entry point ─────────────────────────────────────────────────

    def execute(
        self,
        decision: OrchestratedDecision,
        portfolio_state: PortfolioState,
        balance: float,
        batch_id: str | None = None,
    ) -> ExecutionBatch:
        """Act on one OrchestratedDecision. Idempotent across repeated
        calls with the SAME decision object (default batch_id is derived
        from decision.generated_at) — re-calling execute() on a decision
        already fully processed returns a batch of all-CANCELLED
        (reason="already_executed") results rather than placing orders
        twice. Note the idempotency ledger is in-memory only (see
        execution_state.py's own module docstring) — it protects against
        accidental double-calls within this process's lifetime, not
        across a restart."""
        batch_id = batch_id or f"decision-{decision.generated_at}"
        started_at = time.time()
        results: list[ExecutionResult] = []

        if decision.blocked:
            logger.info(f"ExecutionOrchestrator: decision blocked ({decision.block_reason}); nothing to execute")
            batch = ExecutionBatch(
                batch_id=batch_id, decision_generated_at=decision.generated_at,
                results=results, started_at=started_at, finished_at=time.time(),
            )
            self._publish_metrics(batch_id, decision)
            return batch

        seen_symbols: set = set()
        for alloc in decision.selected:
            if alloc.symbol in seen_symbols:
                results.append(self._skip(batch_id, alloc.symbol, "duplicate_symbol_in_batch"))
                continue
            seen_symbols.add(alloc.symbol)

            if self.state.already_executed(batch_id, alloc.symbol):
                results.append(self._skip(batch_id, alloc.symbol, "already_executed"))
                continue

            results.append(self._execute_allocation(batch_id, alloc, balance, portfolio_state))

        for proposal in decision.replacements:
            close_key = f"close:{proposal.outgoing_symbol}"
            if self.state.already_executed(batch_id, close_key):
                results.append(self._skip(batch_id, proposal.outgoing_symbol, "already_executed", is_replacement=True))
                continue
            results.append(self._execute_replacement_close(batch_id, proposal, portfolio_state))

        finished_at = time.time()
        batch = ExecutionBatch(
            batch_id=batch_id, decision_generated_at=decision.generated_at,
            results=results, started_at=started_at, finished_at=finished_at,
        )
        self._publish_metrics(batch_id, decision)
        return batch

    def cancel(self, execution_id: str, reason: str = "manual_cancel") -> bool:
        """External hook: cancel a still-PENDING execution before it
        reaches the exchange. Returns False if it's already
        running/finished (see ExecutionState.request_cancel)."""
        cancelled = self.state.request_cancel(execution_id, reason=reason)
        if cancelled:
            publish_execution_event(
                ExecutionEventType.CANCELLED, execution_id=execution_id,
                message=reason, severity="warning",
            )
        return cancelled

    def metrics(self) -> ExecutionMetricsSnapshot:
        return compute_metrics(self.state)

    # ── Allocation execution (open) ──────────────────────────────────────

    def _execute_allocation(
        self, batch_id: str, alloc: PortfolioAllocation, balance: float, portfolio_state: PortfolioState,
    ) -> ExecutionResult:
        execution_id = f"{batch_id}:{alloc.symbol}"
        if self._already_cancelled(execution_id, batch_id, alloc.symbol):
            existing = self.state.get(execution_id)
            return ExecutionResult(
                execution_id, alloc.symbol, ExecutionStatus.CANCELLED, False, 0,
                existing.error if existing else "cancelled", None,
            )
        self.state.enqueue(execution_id, batch_id, alloc.symbol)

        signal = self.signal_provider(alloc.symbol)
        if signal is None or signal.direction == 0:
            self.state.cancel(execution_id, "no_signal")
            self.state.mark_executed(batch_id, alloc.symbol)
            publish_execution_event(
                ExecutionEventType.CANCELLED, execution_id=execution_id, symbol=alloc.symbol,
                message="no_signal", severity="info",
            )
            return ExecutionResult(execution_id, alloc.symbol, ExecutionStatus.CANCELLED, False, 0, "no_signal", None)

        record = self.state.start(execution_id)
        if record is None:
            # Cancelled between enqueue() and here (e.g. via cancel()).
            self.state.mark_executed(batch_id, alloc.symbol)
            existing = self.state.get(execution_id)
            return ExecutionResult(
                execution_id, alloc.symbol, ExecutionStatus.CANCELLED, False, 0,
                existing.error if existing else "cancelled", None,
            )

        publish_execution_event(
            ExecutionEventType.STARTED, execution_id=execution_id, symbol=alloc.symbol,
            payload={"leverage": alloc.leverage, "risk_pct": alloc.risk_pct, "capital_amount": alloc.capital_amount},
        )

        direction_str = "LONG" if signal.direction == 1 else "SHORT"
        attempts = 0
        result: dict = {"success": False, "error": "not_attempted"}
        while True:
            result = self.execution_engine.execute_trade(
                direction=direction_str,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                balance=balance,
                risk_pct=alloc.risk_pct,
                leverage=alloc.leverage,
                symbol=alloc.symbol,
            )
            if result.get("success"):
                break
            if attempts >= self.max_retries or not _is_recoverable_error(result.get("error")):
                break
            attempts += 1
            self.state.record_retry(execution_id)
            logger.warning(
                f"ExecutionOrchestrator: retrying {alloc.symbol} "
                f"(attempt {attempts}/{self.max_retries}) after: {result.get('error')}"
            )
            if self.retry_delay_seconds:
                time.sleep(self.retry_delay_seconds)

        self.state.mark_executed(batch_id, alloc.symbol)

        if result.get("success"):
            self.state.complete(execution_id, result)
            trade_id = self._record_trade_opened(execution_id, alloc, signal, result)
            self._apply_opened_position(portfolio_state, alloc, result, direction_str, trade_id=trade_id)
            publish_execution_event(
                ExecutionEventType.COMPLETED, execution_id=execution_id, symbol=alloc.symbol,
                payload={"quantity": result.get("quantity"), "entry_price": result.get("entry_price")},
            )
            return ExecutionResult(execution_id, alloc.symbol, ExecutionStatus.COMPLETED, True, attempts, None, result)

        self.state.fail(execution_id, result.get("error"))
        publish_execution_event(
            ExecutionEventType.FAILED, execution_id=execution_id, symbol=alloc.symbol,
            severity="error", payload={"error": result.get("error")},
        )
        return ExecutionResult(execution_id, alloc.symbol, ExecutionStatus.FAILED, False, attempts, result.get("error"), result)

    def _record_trade_opened(
        self, execution_id: str, alloc: PortfolioAllocation, signal: ExecutionSignal, result: dict,
    ) -> int | None:
        """V16 Phase 4B Step 2 (docs/architecture.md §29): persist this
        open to the journal so it's attributable at close time. No-op
        (returns None) when self.journal isn't configured. On ANY
        failure, logs and returns None rather than raising — `result`
        here already has success=True, meaning the trade has ALREADY
        been placed on the exchange; attribution bookkeeping must never
        be able to make a real trade look like it failed (same rule as
        agents/ceo_agent.py's dynamic-weight fallback and main.py's
        per-agent try/except around save_agent_decision()).

        V16 W14-2A: agent_attribution is recorded here ONLY when
        `signal` already carries one (i.e. signal.agent_attribution is
        not None) — set by execution/ceo_gated_signal_provider.py when
        it ran agents/ceo_agent.py's CEOAgent for this cycle (see
        journal/trade_attribution.py's agent_attribution_from_ceo_decision()).
        For every other caller (the plain execution/portfolio_signal_provider.py
        path above, strategy_registry.py, every pre-W14-2A test's
        ExecutionSignal(...) literal — none of which run CEOAgent),
        signal.agent_attribution defaults to None and nothing changes:
        get_trade_attribution() still honestly returns an empty
        agent_participation list for those trades rather than this
        method fabricating one.

        V16 Phase 4C Step 7C: when `signal` already carries a signal_id
        (e.g. execution/ceo_gated_signal_provider.py already journaled a
        CEO decision cycle — CEO_AGENT row + every participating
        sub-agent row — and threaded that same id onto the
        ExecutionSignal it returned), this trade is saved under THAT id
        instead of minting a second, unrelated one. This is what makes
        `trades.signal_id == agent_decisions.signal_id` hold end to end
        (journal_v2.get_trade_attribution()'s join). When `signal`
        carries no id (every pre-Step-7C caller — the plain
        portfolio_signal_provider.py path above, strategy_registry.py,
        every existing test's ExecutionSignal(...) literal), behavior is
        byte-identical to before: a fresh signal row is minted here,
        exactly as it always was.
        """
        if self.journal is None:
            return None
        try:
            from datetime import datetime, timezone

            from analytics.trade_journal import TradeRecord

            direction_str = "LONG" if signal.direction == 1 else "SHORT"
            now_iso = datetime.now(timezone.utc).isoformat()

            if signal.signal_id is not None:
                # Reuse the CEO-cycle (or other upstream) signal_id —
                # never mint a second, unrelated one for the same trade.
                sig_id = signal.signal_id
            else:
                sig_id = self.journal.save_signal(
                    {
                        "timestamp":   now_iso,
                        "action":      direction_str,
                        "direction":   direction_str,
                        "confidence":  0.0,
                        "entry_price": signal.entry_price,
                        "stop_loss":   signal.stop_loss,
                        "take_profit": signal.take_profit,
                    },
                    execution_lane=self.execution_lane,
                    symbol=alloc.symbol,
                )

            entry_order = result.get("entry_order") or {}
            order_id = str(entry_order.get("orderId", "")) if isinstance(entry_order, dict) else ""

            rec = TradeRecord()
            rec.timestamp   = now_iso
            rec.symbol      = alloc.symbol
            rec.direction   = direction_str
            rec.entry_price = result.get("entry_price") or signal.entry_price
            rec.stop_loss   = signal.stop_loss
            rec.take_profit = signal.take_profit
            rec.quantity    = result.get("quantity") or 0.0
            rec.order_id    = order_id
            trade_id = self.journal.save_trade(rec, execution_lane=self.execution_lane, signal_id=sig_id)

            # V16 Phase 4B Step 3D: routed through TradeLifecycle instead
            # of calling record_trade_outcome() directly — same fields,
            # same one journal write, now also enforcing the state
            # machine (Part A) and adding +source/+symbol (previously
            # not passed at all). PENDING/EXECUTING collapse into this
            # same call because execute_trade() above already completed
            # synchronously by the time this method runs — see
            # trade_lifecycle.py's own module docstring for why that's a
            # documented limitation, not new to this phase.
            slippage = _compute_slippage(signal.direction, signal.entry_price, entry_order)
            handle = self.lifecycle.open_pending(alloc.symbol)
            self.lifecycle.open_executing(handle)
            self.lifecycle.open_confirmed(
                handle, trade_id,
                execution_id=execution_id,
                order_id=order_id or None,
                slippage=slippage,
                agent_attribution=signal.agent_attribution,
                source="EXECUTION_ORCHESTRATOR",
                # fees: not recorded — Binance Futures' market-order
                # response doesn't include commission; that requires a
                # separate userTrades/account API call this codebase
                # doesn't make anywhere today. The field exists on
                # TradeLifecycle.open_confirmed()/record_trade_outcome()/
                # save_execution_attribution() so a future caller that
                # DOES fetch it can pass it straight in with zero API
                # changes — see docs/architecture.md §29 "Scope boundary".
            )
            return trade_id
        except Exception as exc:
            logger.error(f"ExecutionOrchestrator: attribution open-record failed for {alloc.symbol}: {exc}")
            return None

    def _apply_opened_position(
        self, portfolio_state: PortfolioState, alloc: PortfolioAllocation, result: dict, direction_str: str,
        trade_id: int | None = None,
    ) -> None:
        entry_price = result.get("entry_price") or 0.0
        quantity    = result.get("quantity") or 0.0
        portfolio_state.add_position(PortfolioPosition(
            symbol=alloc.symbol,
            direction=direction_str,
            entry_price=entry_price,
            quantity=quantity,
            leverage=alloc.leverage,
            # Same notional-equivalent formula PortfolioManager.decide()
            # already uses for not-yet-open picks (capital_amount *
            # leverage) — see portfolio_manager.py's projected_exposure
            # comment — kept identical here for consistency once the
            # position actually opens.
            notional=alloc.capital_amount * alloc.leverage,
            margin_used=alloc.capital_amount,
            unrealized_pnl=0.0,
            state=PositionState.OPEN,
            opened_at=time.time(),
            trade_id=trade_id,
        ))

    # ── Replacement execution (close outgoing side only) ─────────────────

    def _execute_replacement_close(
        self, batch_id: str, proposal: ReplacementProposal, portfolio_state: PortfolioState,
    ) -> ExecutionResult:
        symbol = proposal.outgoing_symbol
        close_key = f"close:{symbol}"
        execution_id = f"{batch_id}:{close_key}"
        if self._already_cancelled(execution_id, batch_id, close_key):
            existing = self.state.get(execution_id)
            return ExecutionResult(
                execution_id, symbol, ExecutionStatus.CANCELLED, False, 0,
                existing.error if existing else "cancelled", None, is_replacement=True,
            )
        self.state.enqueue(execution_id, batch_id, symbol)

        position = portfolio_state.get_position(symbol)
        if position is None:
            self.state.cancel(execution_id, "outgoing_position_not_found")
            self.state.mark_executed(batch_id, close_key)
            return ExecutionResult(
                execution_id, symbol, ExecutionStatus.CANCELLED, False, 0,
                "outgoing_position_not_found", None, is_replacement=True,
            )

        if not hasattr(self.execution_engine, "close_position"):
            # e.g. paper-mode _PaperAdapter — multi-symbol targeted close
            # is a documented, pre-existing limitation of paper mode
            # (execution/execution_factory.py's own docstring), not
            # something this phase redesigns.
            self.state.cancel(execution_id, "execution_engine_does_not_support_close")
            self.state.mark_executed(batch_id, close_key)
            logger.warning(
                f"ExecutionOrchestrator: cannot close replacement outgoing "
                f"position {symbol} — current execution engine has no "
                f"close_position()"
            )
            return ExecutionResult(
                execution_id, symbol, ExecutionStatus.CANCELLED, False, 0,
                "execution_engine_does_not_support_close", None, is_replacement=True,
            )

        record = self.state.start(execution_id)
        if record is None:
            self.state.mark_executed(batch_id, close_key)
            existing = self.state.get(execution_id)
            return ExecutionResult(
                execution_id, symbol, ExecutionStatus.CANCELLED, False, 0,
                existing.error if existing else "cancelled", None, is_replacement=True,
            )

        publish_execution_event(
            ExecutionEventType.STARTED, execution_id=execution_id, symbol=symbol,
            payload={"reason": proposal.reason, "replacement": True},
        )

        attempts = 0
        order: dict | None = None
        error: str | None = None
        while True:
            order = self.execution_engine.close_position(
                direction=position.direction, quantity=position.quantity, symbol=symbol,
            )
            if order is not None:
                break
            error = "close_position_returned_none"
            if attempts >= self.max_retries:
                break
            attempts += 1
            self.state.record_retry(execution_id)
            if self.retry_delay_seconds:
                time.sleep(self.retry_delay_seconds)

        self.state.mark_executed(batch_id, close_key)

        if order is not None:
            self.state.complete(execution_id, order)
            removed_position = portfolio_state.remove_position(symbol)
            close_outcome = self._compute_close_outcome(removed_position, order)
            record = self.state.get(execution_id)
            # V16 Phase 4B Step 3D: routed through TradeLifecycle (Part
            # C: "the only write path"). TradeLifecycle itself calls
            # notify_position_closed(..., record_attribution=False)
            # afterward — same cooldown/PortfolioState bookkeeping as
            # before this phase, journal write now owned by the
            # lifecycle instead of by PortfolioManager directly writing
            # it as a side effect (Part D). EXIT_REQUESTED/EXIT_EXECUTING
            # collapse into this same call because close_position() above
            # already completed synchronously — same documented
            # limitation as the open side (trade_lifecycle.py's module
            # docstring).
            handle = self.lifecycle.request_exit(
                symbol, CloseSource.REPLACEMENT, proposal.reason or "replacement",
                trade_id=removed_position.trade_id if removed_position else None,
            )
            if handle is not None:
                self.lifecycle.exit_executing(handle)
                self.lifecycle.exit_confirmed(
                    handle,
                    execution_id=execution_id,
                    latency_seconds=record.latency_seconds if record else None,
                    **close_outcome,
                )
            else:
                # Duplicate-close guard fired (Part I) — this symbol was
                # already closed through TradeLifecycle by another path
                # in this same cycle. The exchange close order above
                # still succeeded (order is not None), so this remains a
                # COMPLETED ExecutionResult — only the redundant
                # attribution write is skipped, exactly what Part C's
                # "no duplicated writes" asks for.
                logger.warning(
                    f"ExecutionOrchestrator: replacement-close attribution skipped for "
                    f"{symbol} — TradeLifecycle already has a terminal handle for it"
                )
            publish_execution_event(
                ExecutionEventType.COMPLETED, execution_id=execution_id, symbol=symbol,
                payload={"replacement": True},
            )
            return ExecutionResult(execution_id, symbol, ExecutionStatus.COMPLETED, True, attempts, None, order, is_replacement=True)

        # V16 Phase 4B Step 3D (Part B: "Exchange Reject" close source):
        # the exchange rejected the close order (order is None) — no
        # PortfolioState mutation happened above (remove_position() is
        # only called in the order-is-not-None branch), so the position
        # is STILL genuinely open; this is not a real close, just a
        # failed attempt at one. Modeled as EXIT_EXECUTING -> FAILED —
        # honestly documented rather than left implicit: FAILED here
        # means "this close ATTEMPT failed", not "the position no
        # longer exists" — PortfolioState remains the actual source of
        # truth for that. A retry needs a fresh close attempt (this
        # method's pre-existing behavior — it already didn't auto-retry
        # before this phase either; the caller decides what to do with
        # a FAILED ExecutionResult next cycle, unchanged).
        try:
            handle = self.lifecycle.request_exit(
                symbol, CloseSource.EXCHANGE_CLOSE, proposal.reason or "replacement",
                trade_id=position.trade_id if position else None,
            )
            if handle is not None:
                self.lifecycle.exit_executing(handle)
                self.lifecycle.exit_failed(handle, reason=f"exchange_rejected_close: {error}")
        except Exception as exc:
            logger.error(f"ExecutionOrchestrator: lifecycle notify failed for rejected close of {symbol}: {exc}")

        self.state.fail(execution_id, error)
        publish_execution_event(
            ExecutionEventType.FAILED, execution_id=execution_id, symbol=symbol,
            severity="error", payload={"error": error, "replacement": True},
        )
        return ExecutionResult(execution_id, symbol, ExecutionStatus.FAILED, False, attempts, error, None, is_replacement=True)

    # ── Close-side attribution (V16 Phase 4B Step 2) ───────────────────────

    def _compute_close_outcome(self, position: PortfolioPosition | None, order: dict) -> dict:
        """Derive exit_price/pnl/result/order_id from the raw close
        order response plus the position being closed. Returns None for
        any field that can't be honestly computed (e.g. no position was
        tracked, or the order response doesn't carry a fill price)
        rather than guessing — see docs/architecture.md §29 "Scope
        boundary". A pnl of exactly 0.0 is classified WIN (breakeven
        counted as a win) — a deliberate, documented convention, not an
        accident.
        """
        if position is None or not isinstance(order, dict):
            return {"exit_price": None, "pnl": None, "result": None, "order_id": None}

        order_id = order.get("orderId")
        exit_price = order.get("avgPrice") or order.get("price")
        try:
            exit_price = float(exit_price) if exit_price else None
        except (TypeError, ValueError):
            exit_price = None

        pnl = None
        result = None
        if exit_price:
            if position.direction == "LONG":
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity
            result = "WIN" if pnl >= 0 else "LOSS"

        return {
            "exit_price": exit_price,
            "pnl": round(pnl, 4) if pnl is not None else None,
            "result": result,
            "order_id": str(order_id) if order_id is not None else None,
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    def _already_cancelled(self, execution_id: str, batch_id: str, key: str) -> bool:
        """True if execution_id already has a CANCELLED record — e.g. a
        caller predicted this deterministic execution_id and called
        cancel() on it before this batch's loop reached it (a real,
        useful window: execute() processes allocations one at a time,
        so a concurrent caller CAN cancel allocation N+1 while
        allocation N is still in flight). Also marks it executed so a
        later call with the same batch_id doesn't re-attempt it."""
        existing = self.state.get(execution_id)
        if existing is not None and existing.status == ExecutionStatus.CANCELLED:
            self.state.mark_executed(batch_id, key)
            return True
        return False

    def _skip(self, batch_id: str, symbol: str, reason: str, is_replacement: bool = False) -> ExecutionResult:
        execution_id = f"{batch_id}:{'close:' if is_replacement else ''}{symbol}:{uuid.uuid4().hex[:8]}"
        publish_execution_event(
            ExecutionEventType.CANCELLED, execution_id=execution_id, symbol=symbol,
            message=reason, severity="info",
        )
        return ExecutionResult(execution_id, symbol, ExecutionStatus.CANCELLED, False, 0, reason, None, is_replacement)

    def _publish_metrics(self, batch_id: str, decision: OrchestratedDecision) -> None:
        snapshot = compute_metrics(self.state)
        publish_execution_event(
            ExecutionEventType.METRICS_UPDATED,
            execution_id=batch_id,
            decision_id=str(decision.generated_at),
            payload=snapshot.to_dict(),
        )
