"""
execution/execution_scheduler.py — V16 Phase 2F: Execution Scheduler +
Multi-Symbol Signals

CLAUDE.md's own priority list has "Execution Scheduler" as Priority 5 —
directly after Portfolio Manager/Capital Allocation/Correlation/Sector
Engine (Priorities 1-4, all done) — and docs/architecture.md §23's own
"Next up" named it explicitly as the piece still missing to make
Phase 2A-2E's work actually run in production: "PortfolioManager.decide()
and ExecutionOrchestrator.execute() work correctly and are fully tested,
but nothing calls them on a cadence."

This class is that caller. One cycle (run_once()):
  1. candidates = OpportunityRanker.rank()[:SCHEDULER_CANDIDATE_LIMIT]
  2. balance = data_provider.get_account_balance()
  3. decision = PortfolioManager.decide(candidates, risk_engine, state, balance)
  4. batch = ExecutionOrchestrator.execute(decision, state, balance)

Threading model mirrors scanner/market_scanner.py's MarketScanner
exactly (daemon threading.Thread + threading.Event for stop, same
start()/stop()/is_running() shape) — not a new pattern. run_once() is
a public method specifically so tests (and any future caller) can drive
one cycle synchronously without touching threading at all.

Scope boundary (mirrors execution_orchestrator.py's own "Scope
boundary" section — same discipline, same reasons):

  - This does NOT read real exchange/journal state into the
    PortfolioState it owns. That's reconciliation's job
    (system_health/reconciliation.py) — and reading that module's own
    code confirms it is a MISMATCH-DETECTION engine (exchange vs. bot
    vs. journal views), not a "construct a PortfolioState from real
    positions" utility, so this genuinely isn't solved elsewhere yet
    either. The PortfolioState this class owns starts empty and is
    built up ONLY from this scheduler's own executions — a position
    opened before this scheduler started, or by the legacy
    single-symbol loop, or manually on the exchange, will NOT be
    reflected. Documented here rather than silently assumed away;
    real reconciliation-fed PortfolioState is listed as follow-up work
    in docs/architecture.md.
  - This does NOT change PortfolioManager, CapitalManager, RiskEngine,
    OpportunityRanker, or ExecutionOrchestrator — it only calls them,
    exactly as already built and tested.
"""
from __future__ import annotations

import threading
from typing import Optional

from execution.execution_orchestrator import ExecutionBatch, ExecutionOrchestrator
from portfolio.portfolio_state import PortfolioState
from utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionScheduler:
    """Owns one PortfolioState for its lifetime and drives
    decide() -> execute() on a timer. See module docstring for the
    scope boundary (what real state it does and doesn't track)."""

    def __init__(
        self,
        opportunity_ranker,               # ranking.opportunity_ranker.OpportunityRanker
        portfolio_manager,                # portfolio.portfolio_manager.PortfolioManager
        risk_engine,                      # risk.risk_engine.RiskEngine
        execution_orchestrator: ExecutionOrchestrator,
        data_provider,                    # data.binance_provider.BinanceDataProvider — for get_account_balance()
        portfolio_state: Optional[PortfolioState] = None,
        interval_seconds: Optional[int] = None,
        candidate_limit: Optional[int] = None,
    ) -> None:
        from config.settings import settings

        self.opportunity_ranker = opportunity_ranker
        self.portfolio_manager = portfolio_manager
        self.risk_engine = risk_engine
        self.execution_orchestrator = execution_orchestrator
        self.data_provider = data_provider
        self.portfolio_state = portfolio_state or PortfolioState()
        self.interval_seconds = (
            interval_seconds if interval_seconds is not None else settings.SCHEDULER_INTERVAL_SECONDS
        )
        self.candidate_limit = (
            candidate_limit if candidate_limit is not None else settings.SCHEDULER_CANDIDATE_LIMIT
        )

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cycle_count = 0
        self._last_error: Optional[str] = None

        logger.info(
            f"ExecutionScheduler ready | interval={self.interval_seconds}s "
            f"candidate_limit={self.candidate_limit}"
        )

    # ── Lifecycle (mirrors scanner/market_scanner.py's MarketScanner) ─────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("ExecutionScheduler.start() called but already running — ignoring")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="execution-scheduler")
        self._thread.start()
        logger.info(f"ExecutionScheduler started | interval={self.interval_seconds}s")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("ExecutionScheduler stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self.interval_seconds)

    # ── One cycle ───────────────────────────────────────────────────────

    def run_once(self) -> Optional[ExecutionBatch]:
        """Run exactly one decide()->execute() cycle. Never raises — any
        failure anywhere in the cycle is logged and the cycle is treated
        as a no-op, matching this project's "safety wrapping at every
        touchpoint" rule (the scheduler thread must never die from an
        auxiliary failure). Returns None if nothing was executed (no
        candidates, decision blocked, or an error occurred) — check
        `.last_error` after a None return to distinguish "genuinely
        nothing to do" from "something failed"."""
        self._cycle_count += 1
        self._last_error = None
        try:
            candidates = self.opportunity_ranker.rank()
            if self.candidate_limit:
                candidates = candidates[: self.candidate_limit]
            if not candidates:
                logger.debug("ExecutionScheduler: no candidates this cycle")
                return None

            balance = self.data_provider.get_account_balance()
            decision = self.portfolio_manager.decide(candidates, self.risk_engine, self.portfolio_state, balance)

            if decision.blocked:
                logger.info(f"ExecutionScheduler: decision blocked ({decision.block_reason})")
                return None

            batch = self.execution_orchestrator.execute(decision, self.portfolio_state, balance)
            summary = batch.summary()
            logger.info(
                f"ExecutionScheduler: cycle #{self._cycle_count} complete | "
                f"candidates={len(candidates)} completed={summary.completed} "
                f"failed={summary.failed} cancelled={summary.cancelled}"
            )
            return batch
        except Exception as exc:
            self._last_error = str(exc)
            logger.error(f"ExecutionScheduler: cycle #{self._cycle_count} failed: {exc}")
            return None

    # ── Observability ────────────────────────────────────────────────────

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def to_dict(self) -> dict:
        return {
            "running":          self.is_running(),
            "cycle_count":      self._cycle_count,
            "last_error":       self._last_error,
            "interval_seconds": self.interval_seconds,
            "candidate_limit":  self.candidate_limit,
            "tracked_positions": self.portfolio_state.position_count,
        }
