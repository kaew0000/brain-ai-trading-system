"""system_health/order_state.py — V16 Phase ORDER-01: Unified Canonical
Order-State Layer (Ghost Position Elimination).

This module is a composition, not a new source of truth. Every fact it
reports is read from infrastructure that already existed before this
phase:

    exchange_state.manager.ExchangeStateManager   (C1)
        — optional, freshness/health metadata only (sync_latency_ms,
          last_exchange_update). Never used to decide exchange truth;
          that stays ReconciliationEngine._read_exchange()'s job (the
          same data_provider.get_position_info() call every other part
          of this codebase already trusts), so there is exactly one
          exchange-truth read path, not two.

    system_health.reconciliation.ReconciliationEngine
        — exchange/journal/bot comparison, mismatch classification,
          ghost/orphan detection. This phase's own investigation (see
          docs/architecture.md, Phase ORDER-01 section) found and fixed
          the actual root cause of the reported ghost-position bug here:
          ReconciliationEngine._read_bot() previously mirrored the
          exchange view in live mode instead of reading
          portfolio/portfolio_state.py's PortfolioState independently, so
          a stale PortfolioState entry (created because
          PortfolioState.remove_position() was, before this phase, only
          ever called from execution/execution_orchestrator.py's
          replacement-close path — never from a stop-loss/take-profit/
          manual close) was structurally invisible to reconciliation.

    system_health.recovery_engine.RecoveryEngine
        — automatic recovery actions, extended in this phase to clear a
          stale PortfolioState entry the same way it already cleared a
          stale journal row.

    execution.trade_lifecycle.TradeLifecycle
        — per-symbol OPENING/CLOSING granularity that reconciliation
          alone doesn't model (reconciliation only ever sees a
          before/after snapshot, not the in-flight EXECUTING/
          EXIT_EXECUTING states).

OrderStateManager's only job is mapping the above into the eight
canonical OrderState values the phase brief specifies, and publishing
canonical-STATE-TRANSITION events on the existing EventBus. It never
calls Binance itself, never places/cancels/modifies an order, and never
mutates PortfolioState/journal/TradeLifecycle directly — all mutation
continues to happen exactly where it already did, inside
RecoveryEngine, invoked via ReconciliationEngine.run().
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)

_EVENT_SOURCE = "ORDER_STATE_MANAGER"

# Canonical states considered "settled" (no active mismatch, no in-flight
# transition) for POSITION_SYNCED / POSITION_RECOVERED event purposes.
_SETTLED_STATES = frozenset({"NO_POSITION", "OPEN", "CLOSED"})


class OrderState(str, Enum):
    """The only eight runtime position states this system recognizes,
    per the phase brief. No other canonical state may exist."""
    NO_POSITION = "NO_POSITION"
    OPENING     = "OPENING"
    OPEN        = "OPEN"
    CLOSING     = "CLOSING"
    CLOSED      = "CLOSED"
    DESYNC      = "DESYNC"
    GHOST       = "GHOST"
    UNKNOWN     = "UNKNOWN"


@dataclass
class OrderStateSnapshot:
    symbol:                str
    canonical_state:        OrderState
    exchange_position:      dict
    runtime_position:       dict
    journal_position:       dict
    last_sync:               str | None
    last_exchange_update:     str | None
    sync_latency_ms:          float | None
    ghost_detected:          bool
    desync_reason:           str | None
    mismatch_type:           str | None
    recovery_attempted:      bool
    recovery_result:         str | None

    def to_dict(self) -> dict:
        return {
            "symbol":               self.symbol,
            "canonical_state":       self.canonical_state.value,
            "exchange_position":     self.exchange_position,
            "runtime_position":      self.runtime_position,
            "journal_position":      self.journal_position,
            "last_sync":             self.last_sync,
            "last_exchange_update":   self.last_exchange_update,
            "sync_latency_ms":        self.sync_latency_ms,
            "ghost_detected":        self.ghost_detected,
            "desync_reason":         self.desync_reason,
            "mismatch_type":         self.mismatch_type,
            "recovery_attempted":     self.recovery_attempted,
            "recovery_result":        self.recovery_result,
        }


class OrderStateManager:
    """Stateless w.r.t. position truth (holds no position data of its
    own — every field in OrderStateSnapshot is read fresh from the
    composed infrastructure on every call). Holds only its own
    transition-tracking and metrics counters in memory, the same
    "in-memory only, not a durability guarantee" caveat every other
    tracker in this codebase already carries (execution/execution_state.py,
    portfolio/portfolio_state.py, execution/trade_lifecycle.py)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_state: OrderState | None = None
        self._sync_count = 0
        self._desync_count = 0
        self._ghost_count = 0
        self._recovery_count = 0
        self._latency_samples: list[float] = []

    # ── Public API ───────────────────────────────────────────────────

    def get_order_state(self, sys: dict, symbol: str | None = None) -> OrderStateSnapshot:
        from config.settings import settings
        symbol = symbol or settings.SYMBOL

        # Fall back to the process-wide singleton the same way
        # api/app.py's existing /api/system/reconciliation endpoint
        # already does (get_reconciliation_engine()) — so this works
        # whether `sys` is main.py's full `components` dict (trading-loop
        # thread) or api/app.py's smaller `_state` dict (API thread);
        # both ultimately resolve to the same ReconciliationEngine
        # instance, not a second one.
        reconciliation = sys.get("reconciliation_engine")
        if reconciliation is None:
            from system_health.reconciliation import get_reconciliation_engine
            reconciliation = get_reconciliation_engine()

        try:
            # Same pipeline the 60s-scheduled run_position_reconciliation()
            # job already runs: comparison + auto-recovery + publish +
            # suppression (ReconciliationEngine._last_fired_sig). Calling
            # it again here is not a second reconciliation algorithm —
            # run() is idempotent per that suppression logic, and this is
            # the one and only comparison entrypoint in the codebase.
            reconciliation.run(sys)
        except Exception as exc:
            logger.error(f"OrderStateManager: reconciliation.run() failed: {exc}", exc_info=True)

        views = reconciliation.get_last_views()
        if views is None:
            snapshot = self._unknown_snapshot(symbol, "no reconciliation views available yet")
        else:
            snapshot = self._build_snapshot(sys, symbol, views, reconciliation)

        self._maybe_publish_transition(sys, snapshot)
        self._record_metrics(snapshot)
        return snapshot

    def status(self) -> dict:
        with self._lock:
            avg_latency = (
                sum(self._latency_samples) / len(self._latency_samples)
                if self._latency_samples else None
            )
            return {
                "sync_count":              self._sync_count,
                "desync_count":            self._desync_count,
                "ghost_count":             self._ghost_count,
                "recovery_count":          self._recovery_count,
                "average_sync_latency_ms":  avg_latency,
                "last_canonical_state":     self._last_state.value if self._last_state else None,
            }

    # ── Internal: build snapshot ────────────────────────────────────

    def _unknown_snapshot(self, symbol: str, reason: str) -> OrderStateSnapshot:
        return OrderStateSnapshot(
            symbol=symbol, canonical_state=OrderState.UNKNOWN,
            exchange_position={}, runtime_position={}, journal_position={},
            last_sync=None, last_exchange_update=None, sync_latency_ms=None,
            ghost_detected=False, desync_reason=reason, mismatch_type=None,
            recovery_attempted=False, recovery_result=None,
        )

    def _build_snapshot(self, sys: dict, symbol: str, views: dict, reconciliation) -> OrderStateSnapshot:
        ex, jv, bot = views["exchange"], views["journal"], views["bot"]
        mt, detail = views["mismatch_type"], views["detail"]

        lifecycle = sys.get("trade_lifecycle")
        lc_state = None
        if lifecycle is not None:
            try:
                lc_state = lifecycle.get_state(symbol)
            except Exception:
                lc_state = None

        state, ghost, desync_reason = self._classify(ex, jv, bot, mt, detail, lc_state)

        last_sync, last_exchange_update, sync_latency_ms = self._exchange_freshness(sys)

        recovery_attempted, recovery_result = self._recent_recovery(reconciliation, mt)

        return OrderStateSnapshot(
            symbol=symbol, canonical_state=state,
            exchange_position=ex, runtime_position=bot, journal_position=jv,
            last_sync=last_sync, last_exchange_update=last_exchange_update,
            sync_latency_ms=sync_latency_ms,
            ghost_detected=ghost, desync_reason=desync_reason, mismatch_type=mt,
            recovery_attempted=recovery_attempted, recovery_result=recovery_result,
        )

    def _classify(
        self, ex: dict, jv: dict, bot: dict, mt: str | None, detail: str, lc_state,
    ) -> tuple[OrderState, bool, str | None]:
        """Maps ReconciliationEngine's classification + TradeLifecycle's
        per-symbol state onto the eight canonical states. Exchange is the
        root authority throughout — see module docstring."""
        if ex.get("has_position") is None:
            return OrderState.UNKNOWN, False, detail or "exchange view unavailable"

        if mt == "PRESENCE_MISMATCH":
            if ex.get("has_position") is False:
                # Exchange verified flat; journal and/or the runtime
                # PortfolioState cache still claim a position — exactly
                # the ghost this phase exists to catch.
                return OrderState.GHOST, True, detail
            # Exchange holds a real position nothing else knows about
            # (the pre-existing "orphaned exchange position" case,
            # RecoveryEngine._protect_orphaned_exchange_position()).
            return OrderState.DESYNC, False, detail

        if mt in ("SIDE_MISMATCH", "QUANTITY_MISMATCH", "DUPLICATE_JOURNAL_TRADES"):
            return OrderState.DESYNC, False, detail

        if mt is not None:
            # Any future mismatch type this mapping doesn't explicitly
            # know yet — surfaced honestly rather than silently assumed
            # to be one of the above.
            return OrderState.UNKNOWN, False, detail

        # mt is None: every verifiable view agrees.
        from execution.trade_lifecycle import TradeLifecycleState as LC

        if ex.get("has_position") is True:
            if lc_state == LC.EXECUTING:
                return OrderState.OPENING, False, None
            if lc_state in (LC.EXIT_REQUESTED, LC.EXIT_EXECUTING):
                return OrderState.CLOSING, False, None
            return OrderState.OPEN, False, None

        if lc_state == LC.CLOSED:
            return OrderState.CLOSED, False, None
        return OrderState.NO_POSITION, False, None

    def _recent_recovery(self, reconciliation, mt: str | None) -> tuple[bool, str | None]:
        """Recovery attempt/result for the CURRENTLY active mismatch
        only. get_recent() is keyed off ReconciliationEngine's own
        publish-suppression buffer and can hold events for mismatches
        that no longer apply (e.g. an old, already-resolved
        QUANTITY_MISMATCH) — matched against the live `mt` so a settled
        symbol doesn't display a stale recovery verdict."""
        if mt is None:
            return False, None
        try:
            for evt in reconciliation.get_recent(limit=10):
                if evt.get("mismatch_type") == mt:
                    return bool(evt.get("recovery_attempted")), evt.get("recovery_result")
        except Exception:
            pass
        return False, None

    def _exchange_freshness(self, sys: dict) -> tuple[str | None, str | None, float | None]:
        """Best-effort observability metadata from ExchangeStateManager
        (C1) — never wired into any live component before this phase.
        Deliberately isolated in its own try/except: if this fails or C1
        is unavailable, the rest of the snapshot (canonical_state, ghost
        detection) is entirely unaffected, since exchange truth itself
        comes from ReconciliationEngine's own read, not from here."""
        dp = sys.get("data_provider")
        if dp is None:
            return None, None, None
        try:
            from exchange_state.manager import get_manager
            mgr = get_manager(dp, mode=self._resolve_mode())
            snap = mgr.get_snapshot()
            if not snap.fetched_at:
                return None, None, None
            last_sync = datetime.fromtimestamp(snap.fetched_at, tz=timezone.utc).isoformat()
            latency_ms = max(0.0, (time.time() - snap.fetched_at) * 1000)
            return last_sync, last_sync, latency_ms
        except Exception as exc:
            logger.debug(f"OrderStateManager: exchange freshness unavailable: {exc}")
            return None, None, None

    def _resolve_mode(self) -> str:
        try:
            from config.settings import EXECUTION_MODE, settings
            if EXECUTION_MODE == "paper":
                return "paper"
            return "testnet" if getattr(settings, "BINANCE_TESTNET", True) else "live"
        except Exception:
            return "live"

    # ── Internal: transitions / events / metrics ────────────────────

    def _maybe_publish_transition(self, sys: dict, snapshot: OrderStateSnapshot) -> None:
        with self._lock:
            previous = self._last_state
            changed = previous != snapshot.canonical_state
            self._last_state = snapshot.canonical_state

        if not changed:
            return

        bus = sys.get("event_bus")
        if bus is None:
            return

        payload = snapshot.to_dict()
        prev_label = previous.value if previous else "INIT"
        try:
            bus.publish(
                _EVENT_SOURCE, "ORDER_STATE_CHANGED",
                f"{snapshot.symbol}: {prev_label} -> {snapshot.canonical_state.value}",
                severity="info", payload=payload,
            )

            if snapshot.canonical_state == OrderState.GHOST:
                bus.publish(
                    _EVENT_SOURCE, "GHOST_POSITION_DETECTED",
                    snapshot.desync_reason or f"Ghost position detected for {snapshot.symbol}",
                    severity="critical", payload=payload,
                )
            elif snapshot.canonical_state == OrderState.DESYNC:
                bus.publish(
                    _EVENT_SOURCE, "POSITION_DESYNC",
                    snapshot.desync_reason or f"Position desync detected for {snapshot.symbol}",
                    severity="warning", payload=payload,
                )
            elif (previous is not None and previous.value not in _SETTLED_STATES
                    and snapshot.canonical_state.value in _SETTLED_STATES):
                bus.publish(
                    _EVENT_SOURCE, "POSITION_RECOVERED",
                    f"{snapshot.symbol} recovered to {snapshot.canonical_state.value}",
                    severity="info", payload=payload,
                )
            elif snapshot.canonical_state.value in _SETTLED_STATES:
                bus.publish(
                    _EVENT_SOURCE, "POSITION_SYNCED",
                    f"{snapshot.symbol} synced: {snapshot.canonical_state.value}",
                    severity="info", payload=payload,
                )
        except Exception as exc:
            logger.error(f"OrderStateManager: event publish failed: {exc}")

    def _record_metrics(self, snapshot: OrderStateSnapshot) -> None:
        with self._lock:
            if snapshot.canonical_state == OrderState.GHOST:
                self._ghost_count += 1
            if snapshot.canonical_state == OrderState.DESYNC:
                self._desync_count += 1
            if snapshot.canonical_state.value in _SETTLED_STATES:
                self._sync_count += 1
            if snapshot.recovery_attempted:
                self._recovery_count += 1
            if snapshot.sync_latency_ms is not None:
                self._latency_samples.append(snapshot.sync_latency_ms)
                if len(self._latency_samples) > 500:
                    self._latency_samples.pop(0)


# ── Singleton, mirrors reconciliation.py / recovery_engine.py's own pattern ──

_osm: OrderStateManager | None = None
_osm_lock = threading.Lock()


def get_order_state_manager() -> OrderStateManager:
    global _osm
    if _osm is None:
        with _osm_lock:
            if _osm is None:
                _osm = OrderStateManager()
    return _osm


def reset_order_state_manager() -> OrderStateManager:
    """Test-only: fresh instance so transition/metric state never leaks
    between tests (same convention as reset_reconciliation_engine() /
    reset_recovery_engine())."""
    global _osm
    with _osm_lock:
        _osm = OrderStateManager()
    return _osm
