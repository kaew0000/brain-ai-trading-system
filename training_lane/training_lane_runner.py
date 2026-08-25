"""training_lane/training_lane_runner.py — V16 Phase 4C Track C:
Background Paper-Training Engine.

Runs a fully independent, always-on paper-execution loop on a daemon
thread, started at every main.py boot when
config/settings.py::BACKGROUND_PAPER_TRAINING_ENABLED is True.
Completely isolated from whatever the primary execution_lane
(LIVE/TRAINING) is doing — its own $100 PaperAccount, its own
PaperExecutionEngine, its own thread.

Purpose
-------
Continuously generate execution_lane="PAPER" trade outcomes against
real market data, and feed every closed trade into the existing
FeatureStore/DatasetBuilder ML pipeline. This closes a real gap found
during the pre-implementation audit: research/dataset_builder.py::
DatasetBuilder.capture_closed_mission() has exactly ONE call site in
the whole repo (main.py's legacy single-symbol monitor_open_trades()
loop) — even today's multi-symbol ExecutionOrchestrator path does not
feed the ML pipeline. This module adds its own explicit call at
trade-close; it does not assume or rely on any existing hook firing on
its behalf.

execution_lane value
---------------------
Uses "PAPER", not "TRAINING". config/settings.py's
_EXECUTION_LANE_BY_MODE already maps EXECUTION_MODE=paper (a person
manually running main.py in paper mode) to execution_lane="TRAINING".
Reusing "TRAINING" here would make a person-initiated manual paper
session and this always-on background engine indistinguishable in the
database. "PAPER" is the only one of the three schema-reserved
execution_lane values (LIVE/TRAINING/PAPER — see
database/migrations/migration_001_execution_lane_backfill.py's CHECK
constraint) with zero existing writers, confirmed by grepping every
runtime assignment site in the repo. Decided explicitly by the person
this was built for; do not change without the same sign-off.

Safety — why no path here can ever reach a real Binance order
----------------------------------------------------------------
- Signal generation reuses execution/strategy_registry.py::build_strategy(),
  the SAME decision pipeline (MarketContextBuilder → ConfidenceEngine →
  SignalProvider) the primary lane uses — never
  execution/execution_coordinator.py or any order-placing client.
- Every decision is routed through paper/paper_execution.py::
  PaperExecutionEngine, whose full import graph (paper_execution.py,
  paper_account.py, paper_position.py) contains no exchange client —
  verified directly during the design review, not assumed.
- Owns its OWN PaperAccount/PaperExecutionEngine pair, constructed
  fresh in this module — never touches main.py's `trade_manager`
  (the primary lane's execution engine).
- Reads market data via the SAME data_provider the primary lane already
  uses (data/binance_provider.py), which is read-only for this purpose
  (get_mark_price) and already circuit-breaker/retry wrapped with
  multiple existing concurrent readers (legacy loop + MarketScanner) —
  this is one more reader, not a new write path.

Independent of lifecycle_state
--------------------------------
commander/control_state.py documents lifecycle_state as a SOFT gate
that "only matters once lifecycle_state == RUNNING", governing
live-order call sites specifically. This runner's boot condition is
purely BACKGROUND_PAPER_TRAINING_ENABLED — independent of
lifecycle_state and independent of the primary lane's balance, per the
person's explicit request that this run "even when the real account
balance is 0".

Bust handling
-------------
Per the person's explicit decision: when the $100 training account's
balance reaches zero, reset it back to $100 AND record why it busted
(recent trade results/close-reasons) as its own labelled row in
FeatureStore, so the ML pipeline can learn from the bust itself, not
just from individual trade outcomes. See _handle_bust() below.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from config.settings import settings
from paper.paper_account import PaperAccount
from paper.paper_execution import PaperExecutionEngine
from utils.logger import get_logger

logger = get_logger(__name__)

# See module docstring's "execution_lane value" section for why this is
# "PAPER" and not "TRAINING".
TRAINING_LANE = "PAPER"

# How many of the most recent closed trades to summarise into the bust
# event's log line and training row (bounded so a very long losing
# streak before a bust doesn't produce an unbounded log/row payload).
_BUST_HISTORY_WINDOW = 10


@dataclass
class _PaperDecision:
    """Adapts execution/execution_orchestrator.py::ExecutionSignal
    (direction: 1=LONG / -1=SHORT / 0=no trade) to the `decision` shape
    paper/paper_execution.py::PaperExecutionEngine.execute() expects
    (decision.action: "LONG"/"SHORT"). PaperExecutionEngine reads any
    other decision fields (confidence, regime, oi_delta, funding_rate)
    via getattr(decision, name, default) — see its own class docstring
    — so this deliberately only carries the fields it actually has;
    leaving the rest unset is within PaperExecutionEngine's documented
    contract, not a workaround."""

    action: str
    entry_price: float
    stop_loss: float
    take_profit: float


def _to_paper_decision(signal) -> _PaperDecision | None:
    """signal is an execution.execution_orchestrator.ExecutionSignal or
    None (SignalProvider's documented return type)."""
    if signal is None or signal.direction == 0:
        return None
    action = "LONG" if signal.direction == 1 else "SHORT"
    return _PaperDecision(
        action=action,
        entry_price=float(signal.entry_price),
        stop_loss=float(signal.stop_loss),
        take_profit=float(signal.take_profit),
    )


class TrainingLaneRunner:
    """Owns one independent, always-on paper-training pipeline.

    Construct once at boot (see main.py's wiring block) and call
    .start() — runs until .stop() is called or the process exits
    (daemon thread). Safe to construct even if the primary lane never
    starts or has zero balance; this class never reads or writes
    anything belonging to the primary lane.
    """

    def __init__(
        self,
        data_provider,
        regime_engine,
        smc_engine,
        volume_engine,
        context_builder,
        confidence_engine,
        symbol: str | None = None,
        starting_balance: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        from execution.strategy_registry import build_strategy

        self._data_provider = data_provider
        self.symbol = symbol or settings.SYMBOL
        self._starting_balance = (
            starting_balance
            if starting_balance is not None
            else settings.BACKGROUND_TRAINING_STARTING_BALANCE
        )
        self._poll_interval = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS
        )

        # Person's explicit decision: same strategy/thresholds as live,
        # no exploratory bias — reuses settings.STRATEGY_NAME, the exact
        # same knob the primary/multi-symbol lane resolves through
        # execution/strategy_registry.py::build_strategy().
        self._signal_provider = build_strategy(
            settings.STRATEGY_NAME,
            data_provider=data_provider,
            regime_engine=regime_engine,
            smc_engine=smc_engine,
            volume_engine=volume_engine,
            context_builder=context_builder,
            confidence_engine=confidence_engine,
        )

        self._engine = self._new_engine()
        self._bust_count = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _new_engine(self) -> PaperExecutionEngine:
        account = PaperAccount(balance=self._starting_balance)
        return PaperExecutionEngine(account=account)

    def start(self) -> None:
        """Idempotent — calling twice is a no-op, matching the pattern
        every other optional subsystem in main.py follows."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="training-lane-runner",
        )
        self._thread.start()
        logger.info(
            f"TrainingLaneRunner started | symbol={self.symbol} "
            f"balance={self._starting_balance:.2f} lane={TRAINING_LANE} "
            f"poll={self._poll_interval}s"
        )

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Status (read-only, for API/dashboard visibility) ───────────────────────

    def status(self) -> dict:
        """Plain-dict snapshot for GET /api/training-lane/status (added
        alongside the Train Monitor visibility panel). Reads only
        already-lock-protected properties (PaperAccount.balance,
        PaperExecutionEngine.open_positions/.closed_trades all take
        their own internal lock — see paper/paper_account.py and
        paper/paper_execution.py) — no new locking needed here, and
        this never mutates anything, so it's safe to call from the API
        thread while the runner thread is mid-cycle.

        Deliberately returns primitives/plain dicts only, never a
        reference to internal engine/account/position objects, so a
        caller can't accidentally mutate training state through the
        status surface.
        """
        engine = self._engine
        balance = engine.account.balance
        open_positions = [p.to_dict() for p in engine.open_positions]
        closed = engine.closed_trades
        last_closed = closed[-1].to_dict() if closed else None
        return {
            "enabled": True,
            "is_running": self.is_running,
            "symbol": self.symbol,
            "execution_lane": TRAINING_LANE,
            "starting_balance": self._starting_balance,
            "balance": balance,
            "bust_count": self._bust_count,
            "closed_trade_count": len(closed),
            "open_position": open_positions[0] if open_positions else None,
            "last_closed_trade": last_closed,
            "poll_interval_seconds": self._poll_interval,
        }

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._cycle()
            except Exception as exc:
                logger.error(
                    f"TrainingLaneRunner cycle error (non-fatal, continuing): {exc}",
                    exc_info=True,
                )
            self._stop_event.wait(self._poll_interval)

    def _cycle(self) -> None:
        mark = self._data_provider.get_mark_price(self.symbol)
        if mark is None:
            return

        for closed_trade in self._engine.tick(float(mark)):
            self._capture_closed_trade(closed_trade)

        if self._engine.account.balance <= 0:
            self._handle_bust()
            return  # don't open a new position on the same cycle as a reset

        if not self._engine.open_positions:  # max_open=1 by construction
            decision = _to_paper_decision(self._signal_provider(self.symbol))
            if decision is not None:
                self._engine.execute(decision)

    # ── ML pipeline feed ─────────────────────────────────────────────────────

    def _capture_closed_trade(self, closed_trade) -> None:
        """Fires the same DatasetBuilder hook the legacy single-symbol
        loop uses (main.py's monitor_open_trades()) — see module
        docstring for why this call is required here rather than
        assumed to already happen."""
        try:
            from research.dataset_builder import get_dataset_builder

            trade_row = closed_trade.to_dict()
            trade_row["timestamp"] = closed_trade.opened_at
            trade_row["closed_at"] = closed_trade.closed_at
            get_dataset_builder().capture_closed_mission(
                execution_lane=TRAINING_LANE,
                mission=None,
                trade_row=trade_row,
                market_context=None,
                intelligence=None,
            )
        except Exception as exc:
            logger.debug(f"TrainingLaneRunner: dataset capture skipped: {exc}")

    # ── Bust handling ────────────────────────────────────────────────────────

    def _handle_bust(self) -> None:
        self._bust_count += 1
        closed = self._engine.closed_trades
        recent = closed[-_BUST_HISTORY_WINDOW:]
        summary = {
            "bust_number": self._bust_count,
            "trades_since_last_reset": len(closed),
            "recent_results": [t.result for t in recent],
            "recent_close_reasons": [t.close_reason for t in recent],
        }
        logger.warning(f"TrainingLaneRunner: PAPER account busted — resetting. {summary}")

        # Person's explicit decision: record why the account busted AND
        # feed that as its own labelled training row — not just a log
        # line. Reuses the last closed trade's real feature vector
        # (build_feature_vector only returns FEATURE_COLUMNS-shaped
        # keys — see research/trade_snapshot.py — so the bust marker is
        # added directly to the features dict rather than smuggled
        # through trade_row/market_context, which build_feature_vector
        # would silently drop) and lets FeatureStore.save_row's existing
        # extra_json mechanism (any features key outside FEATURE_COLUMNS)
        # carry the marker — no schema change, no change to
        # research/feature_store.py or research/trade_snapshot.py.
        if recent:
            try:
                from research.dataset_builder import get_dataset_builder
                from research.trade_snapshot import build_feature_vector, build_outcome

                last = recent[-1]
                trade_row = last.to_dict()
                trade_row["timestamp"] = last.opened_at
                trade_row["closed_at"] = last.closed_at

                features = build_feature_vector(None, trade_row, None, None)
                features["account_busted"] = True
                features["bust_number"] = self._bust_count
                features["recent_results"] = summary["recent_results"]
                features["recent_close_reasons"] = summary["recent_close_reasons"]

                # Reuse the SAME FeatureStore instance capture_closed_mission()
                # writes through (get_dataset_builder()._store), not a fresh
                # FeatureStore() pointed at the default db path — keeps every
                # row from this runner (normal trades + bust events) in one
                # database regardless of how the process was configured/tested.
                store = get_dataset_builder()._store
                row_id = store.save_row(
                    features,
                    execution_lane=TRAINING_LANE,
                    trade_id=None,
                    symbol=last.symbol,
                )
                result, pnl, ht = build_outcome(trade_row)
                if result is not None:
                    store.update_outcome(row_id, result, pnl, ht)
                logger.info(f"TrainingLaneRunner: bust event captured as row #{row_id}")
            except Exception as exc:
                logger.debug(f"TrainingLaneRunner: bust-event capture skipped: {exc}")

        self._engine = self._new_engine()
