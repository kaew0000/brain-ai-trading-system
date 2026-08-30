"""training_lane/training_lane_runner.py — V16 Phase 4C Track C:
Background Paper-Training Engine.

Runs a fully independent, always-on paper-execution loop on a daemon
thread, started at every main.py boot when
config/settings.py::BACKGROUND_PAPER_TRAINING_ENABLED is True.
Completely isolated from whatever the primary execution_lane
(LIVE/TRAINING) is doing — its own $100 PaperAccount, its own
PaperExecutionEngine, its own thread.

Multi-symbol rotation (V16 Phase 4C Track C addition)
-------------------------------------------------------
Originally traded settings.SYMBOL only, forever. When
config/settings.py::BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED is True and
an opportunity_ranker was supplied at construction, this lane instead
round-robins entries across that ranker's top-N scanner-ranked
candidates (see TrainingLaneRunner._select_symbol()) — so the training
dataset reflects the same multi-symbol universe the live
portfolio_signal_provider lane actually trades, rather than a single
hardcoded symbol the live lane may rarely even select. Off by default;
with it off (or no ranker supplied), behavior is unchanged from before
this addition.

Restore-on-restart (V16 Phase 4C §49 addition)
-------------------------------------------------------
Originally, every process restart threw this lane's whole state away —
fresh $100 PaperAccount, and any genuinely-open position simply
vanished (its eventual WIN/LOSS outcome never captured at all). Now
saves a full snapshot (training_lane/state_store.py, one row in
training_lane_state) at the end of every cycle, and attempts to restore
it at construction — see TrainingLaneRunner._restore_state(). A restore
problem of any kind (first-ever run, corrupted row, incompatible future
format) is logged and this lane simply continues with a fresh account,
exactly as it always did before this addition — restore is strictly
additive, never a precondition for this lane to run.

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
from training_lane.state_store import get_training_lane_state_store
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
        opportunity_ranker=None,
        multi_symbol_enabled: bool | None = None,
        state_store=None,
    ) -> None:
        from execution.strategy_registry import build_strategy

        self._data_provider = data_provider
        # `_fixed_symbol` is the permanent fallback (this class's original,
        # single-symbol behavior). `self.symbol` is the *currently active*
        # symbol and is mutable — it changes between trades when rotation
        # is on (see _select_symbol()), but never mid-position: a position
        # opened on one symbol is always ticked/closed on that same symbol.
        self._fixed_symbol = symbol or settings.SYMBOL
        self.symbol = self._fixed_symbol
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

        # Root-cause fix (see PATCH_NOTES.md / paper/paper_position.py's
        # TIMEOUT_BARS docstring): PaperPosition's 96-bar default assumes
        # one tick == one M15 candle. This lane ticks once per
        # self._poll_interval seconds instead (20s by default), so
        # positions were being force-closed after ~32 minutes, not the
        # intended settings.BACKGROUND_TRAINING_POSITION_TIMEOUT_HOURS.
        # Derive the real bar count from actual cadence so the intended
        # wall-clock timeout holds regardless of poll interval. Floored
        # at 1 so a very long configured poll interval can never produce
        # a zero/negative bar count.
        self._timeout_bars = max(
            1,
            int(
                (settings.BACKGROUND_TRAINING_POSITION_TIMEOUT_HOURS * 3600.0)
                / self._poll_interval
            ),
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

        # V16 Phase 4C Track C: rotate across scanner-ranked symbols
        # instead of pinning this lane to _fixed_symbol forever, so
        # training data reflects the same multi-symbol universe the live
        # portfolio_signal_provider lane actually trades. Off by default
        # (settings.BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED) — with it
        # off, or no ranker supplied, behavior is byte-for-byte identical
        # to before this phase. `opportunity_ranker` is duck-typed (needs
        # only a .rank() method returning objects with a .symbol
        # attribute) rather than requiring a real MarketScanner, so a
        # fake is trivial in tests — see main.py's wiring for how the
        # real one (ranking.opportunity_ranker.OpportunityRanker wrapping
        # the same MarketScanner instance the live scanner path uses) is
        # constructed and injected.
        self._multi_symbol_enabled = (
            multi_symbol_enabled
            if multi_symbol_enabled is not None
            else settings.BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED
        )
        self._ranker = opportunity_ranker if self._multi_symbol_enabled else None
        self._rotation_index = 0

        # V16 Phase 4C §49: restore-on-restart. Every prior restart threw
        # this lane's whole in-memory state away (fresh $100 PaperAccount,
        # any genuinely-open position silently vanishing — losing that
        # trade's eventual outcome entirely, never captured by
        # DatasetBuilder) — the exact "training resets every time the bot
        # restarts" symptom this phase closes. Attempted here,
        # unconditionally, right after constructing the fresh engine
        # above: if a prior state exists and restores cleanly, it
        # replaces the fresh engine and restores symbol/bust_count/
        # rotation_index too; if not (first-ever run, corrupted state, or
        # any other failure), the fresh engine already constructed above
        # is simply left in place — restore is additive-on-top, never a
        # precondition for this lane to run.
        self._state_store = state_store or get_training_lane_state_store()
        self.restored_from_prior_run = False
        self._restore_state()

    def _restore_state(self) -> None:
        """Never raises — a restore problem is logged and this lane
        proceeds with the fresh engine _new_engine() already built,
        exactly as if this method didn't exist. See __init__'s comment
        for why this is safe to treat as best-effort."""
        try:
            saved = self._state_store.load_state()
            if saved is None:
                return
            engine_state = saved.get("engine")
            if not engine_state:
                return
            self._engine = PaperExecutionEngine.from_state_dict(
                engine_state, timeout_bars=self._timeout_bars,
            )
            self.symbol = saved.get("symbol", self.symbol)
            self._bust_count = int(saved.get("bust_count", self._bust_count))
            self._rotation_index = int(saved.get("rotation_index", self._rotation_index))
            self.restored_from_prior_run = True
            open_count = len(self._engine.open_positions)
            logger.info(
                f"TrainingLaneRunner: restored prior state | "
                f"balance={self._engine.account.balance:.2f} "
                f"open_positions={open_count} symbol={self.symbol} "
                f"bust_count={self._bust_count}"
            )
        except Exception as exc:
            logger.error(
                f"TrainingLaneRunner: restore failed, continuing with a "
                f"fresh account: {exc}", exc_info=True,
            )

    def _save_state(self) -> None:
        """Never raises — see _restore_state()'s docstring; a failed
        save should never interrupt this lane's own trading cycle."""
        try:
            self._state_store.save_state({
                "engine":         self._engine.to_state_dict(),
                "symbol":         self.symbol,
                "bust_count":     self._bust_count,
                "rotation_index": self._rotation_index,
            })
        except Exception as exc:
            logger.error(f"TrainingLaneRunner: state save failed: {exc}", exc_info=True)

    def _select_symbol(self) -> str:
        """Picks the symbol for the *next* entry attempt. Only ever
        called when this lane is flat (no open position) — see
        _cycle() — since a position, once opened, is always ticked and
        closed on the symbol it was opened with; switching mid-position
        would corrupt PnL tracking (PaperExecutionEngine.tick() applies
        one mark price to every currently-open position).

        Round-robins through opportunity_ranker.rank()'s top-N candidates
        when multi-symbol mode is on. Falls back to _fixed_symbol —
        never raises — whenever multi-symbol mode is off, no ranker was
        supplied, ranking returns nothing (e.g. "scanner cache is empty"
        early after boot), or ranking itself raises for any reason. A
        rotation hiccup should never be able to stop this lane trading;
        it should just fall back to the one symbol it always knew how to
        trade."""
        if self._ranker is None:
            return self._fixed_symbol
        try:
            ranked = self._ranker.rank()
            if not ranked:
                return self._fixed_symbol
            symbol = ranked[self._rotation_index % len(ranked)].symbol
            self._rotation_index += 1
            return symbol
        except Exception as exc:
            logger.debug(
                f"TrainingLaneRunner: symbol rotation skipped this attempt, "
                f"falling back to {self._fixed_symbol}: {exc}"
            )
            return self._fixed_symbol

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _new_engine(self) -> PaperExecutionEngine:
        account = PaperAccount(balance=self._starting_balance)
        return PaperExecutionEngine(account=account, timeout_bars=self._timeout_bars)

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
            "multi_symbol_enabled": self._multi_symbol_enabled,
            "execution_lane": TRAINING_LANE,
            "starting_balance": self._starting_balance,
            "balance": balance,
            "bust_count": self._bust_count,
            "closed_trade_count": len(closed),
            "open_position": open_positions[0] if open_positions else None,
            "last_closed_trade": last_closed,
            "poll_interval_seconds": self._poll_interval,
            "restored_from_prior_run": self.restored_from_prior_run,
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
            self._save_state()
            return  # don't open a new position on the same cycle as a reset

        if not self._engine.open_positions:  # max_open=1 by construction
            # Reselect right before attempting an entry — covers both
            # "already flat at the top of this cycle" and "just closed a
            # position a few lines up, in this same cycle" in one place,
            # rather than only reselecting once per cycle at the top
            # (which would leave rotation lagging by a cycle after every
            # close). self.symbol is intentionally NOT touched anywhere
            # else in this method — see _select_symbol()'s docstring for
            # why mid-position symbol switches aren't safe.
            self.symbol = self._select_symbol()
            decision = _to_paper_decision(self._signal_provider(self.symbol))
            if decision is not None:
                self._engine.execute(decision, symbol=self.symbol)

        # V16 Phase 4C §49: save every cycle, unconditionally — not just
        # on a graceful stop() — so a hard kill/crash (this project's own
        # history: restarts have far more often looked like a closed
        # terminal window than a clean Ctrl+C) never loses more than one
        # cycle's worth of state. Cheap enough at this poll interval
        # (default 20s) to not bother gating on "did anything actually
        # change this cycle".
        self._save_state()

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
