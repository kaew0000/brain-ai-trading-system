"""system_health/ghost_reconciliation.py — Track C3 Phase 2: Ghost
Detection + Runtime Validation + Reconciliation Metrics + Recovery
Observability.

This module is a composition, not a new source of truth — same posture
as system_health/order_state.py (V16 Phase ORDER-01), which this phase
sits directly on top of and does not replace. Every fact reported here
is read from infrastructure that already existed before this phase:

    system_health.order_state.OrderStateManager   (V16 Phase ORDER-01)
        — the canonical eight-state (NO_POSITION/OPENING/OPEN/CLOSING/
          CLOSED/DESYNC/GHOST/UNKNOWN) classification, itself composed
          from ReconciliationEngine + RecoveryEngine + TradeLifecycle.
          C3-2 calls OrderStateManager.get_order_state() exactly once
          per check() and never re-derives exchange/journal/runtime
          truth itself.

    execution.order_timeline.OrderTimeline         (Track C3 Phase 1)
        — the ONE genuinely new signal this phase adds: OrderTimeline's
          last-known composite state gives temporal context
          (ReconciliationEngine/OrderStateManager only ever compare a
          single current snapshot). Consumed strictly read-only via
          current_state()/recent() — never run_once()'d, never
          started/stopped, never mutated.

    system_health.reconciliation.ReconciliationEngine
    system_health.recovery_engine.RecoveryEngine
        — untouched. Recovery already happens automatically inside
          OrderStateManager.get_order_state() -> ReconciliationEngine
          .run() -> RecoveryEngine.attempt_reconciliation_recovery().
          This module never calls either directly and never invents a
          new recovery action; it only OBSERVES the attempt/result
          OrderStateManager already surfaced (see _classify_recovery())
          to produce success/failure metrics and one new event
          (RECONCILIATION_FAILED) for a case that was previously only
          logged, never published.

Why this phase exists (root cause, not a rewrite)
--------------------------------------------------
Inspection of the current repository (see docs/architecture/
GHOST_RECONCILIATION.md for the full record) found that
system_health/order_state.py already implements most of what a naive
"C3-2 ghost detection" brief would ask for: GHOST/DESYNC states, an
event on every transition, and sync/desync/ghost/recovery counters.
Duplicating that would violate this repository's own "never create
duplicate modules / parallel implementations" rule. What is genuinely
missing, and what this module adds, is narrow:

  1. OrderTimeline (Track C3 Phase 1) was never wired into any
     consumer — this phase is its first real reader. Cross-checking it
     against exchange truth catches a case OrderStateManager's own
     classification cannot: exchange verified flat, journal/runtime
     agree it's flat too, but the timeline's last recorded composite
     state still looks in-flight (e.g. a missed CLOSED transition).
     New status: TIMELINE_DESYNC.

  2. OrderStateManager's GHOST state doesn't say *which* source (the
     runtime PortfolioState cache, the journal, or both) was stale —
     RecoveryEngine's own recovery_result string encodes this
     (cleared_runtime_ghost / closed_ghost_row) but it isn't exposed as
     a queryable classification. New: GHOST_RUNTIME / GHOST_JOURNAL.

  3. OrderStateManager's DESYNC state lumps ORPHAN_EXCHANGE,
     SIDE_MISMATCH, QUANTITY_MISMATCH, and DUPLICATE_JOURNAL_TRADES
     together. New: a proper sub-classification, read directly off the
     mismatch_type + exchange_position ReconciliationEngine already
     computed (no new decision logic).

  4. A silent gap: RecoveryEngine logs a failed automatic recovery
     attempt but never publishes it as its own event. New: the
     RECONCILIATION_FAILED event (see _events_for()).

  5. The brief's own metric vocabulary (ghost_detected_count,
     orphan_exchange_count, recovery_success_count, ...) doesn't map
     1:1 onto OrderStateManager.status()'s existing counters
     (sync_count/desync_count/ghost_count/recovery_count) — this
     module keeps its own counters under the requested names rather
     than repurposing OrderStateManager's, so neither module's
     behavior/tests change.

Event vocabulary — reuse first
-------------------------------
Per this phase's own brief ("inspect the existing event vocabulary;
if equivalent events already exist, reuse them"): OrderStateManager
already publishes ORDER_STATE_CHANGED / GHOST_POSITION_DETECTED /
POSITION_DESYNC / POSITION_RECOVERED / POSITION_SYNCED on every
transition, and RecoveryEngine already publishes GHOST_POSITION_REMOVED
/ ORPHAN_POSITION_HOLD when it acts. This module does NOT re-publish
duplicates of any of those for the same finding. It publishes exactly
three event types, each covering a gap nothing else fills:

  - RUNTIME_POSITION_MISMATCH — SIDE_MISMATCH/QUANTITY_MISMATCH
    specifically (POSITION_DESYNC alone doesn't distinguish these).
  - ORDER_TIMELINE_DESYNC — the new OrderTimeline cross-check finding.
  - RECONCILIATION_FAILED — a recovery attempt that did not clear the
    condition (previously logged only, never published).

Dedup: publishes only on a DETECTION_STATUS transition for that symbol
(mirrors OrderStateManager._maybe_publish_transition's own "changed
only" rule), with an additional wall-clock re-arm window
(config.settings.ORDER_RECONCILIATION_DEDUP_SECONDS) so a rapidly
flapping condition cannot re-fire the same event pair many times a
minute even across repeated transitions.

Real-money safety
------------------
This module places no orders, cancels no orders, and calls no recovery
action of its own — every mutation it could ever reflect already
happened inside RecoveryEngine (existing, unchanged, conservative:
ghost runtime/journal state is cleared only after exchange
verification; an orphaned real exchange position is protected with an
SL and held for human acknowledgement, never auto-closed — see
recovery_engine.py's own docstring). TIMELINE_DESYNC in particular
triggers NO automatic recovery in this phase — it is a weaker,
second-order signal not yet backed by a proven recovery policy, and is
intentionally detection-only (documented as a C3-3 candidate).

No new Binance polling. check() reads OrderStateManager (which reads
ReconciliationEngine, which reads data_provider.get_position_info() —
the same one call every other consumer already trusts) and
OrderTimeline (a pull from its own in-memory/DB state, never a
Binance call). Nothing here calls refresh(force=True) or queries
Binance independently.

Persistence: metrics and findings history are in-memory only (not
persisted across restart) — the same caveat OrderStateManager.status()
carries for its own counters. Documented as a known limitation.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)

_EVENT_SOURCE = "GHOST_RECONCILIATION_MONITOR"

# OrderTimeline composite states (execution/order_timeline.py's
# TimelineState) that represent an in-flight-or-open-looking order/
# trade. If the exchange is independently verified FLAT while the
# timeline's last recorded state is still one of these, the timeline
# itself has desynced from reality (a missed CLOSED transition, a
# dropped event, etc.) — distinct from, and detectable even when,
# every other source (exchange/journal/runtime) already agrees flat.
_ACTIVE_TIMELINE_STATES = frozenset({
    "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED",
    "OPEN", "REDUCING", "CLOSING",
})

_MAX_LATENCY_SAMPLES = 500
_MAX_FINDINGS = 200


class DetectionStatus(str, Enum):
    """This phase's own read-only classification vocabulary — NOT a
    replacement for system_health.order_state.OrderState (the
    canonical position-lifecycle state). This is a finer-grained label
    for *what kind of truth-mismatch, if any* was found, derived from
    an already-computed OrderStateSnapshot. See module docstring."""
    NO_POSITION            = "NO_POSITION"
    REAL_POSITION          = "REAL_POSITION"
    GHOST_RUNTIME          = "GHOST_RUNTIME"
    GHOST_JOURNAL          = "GHOST_JOURNAL"
    ORPHAN_EXCHANGE        = "ORPHAN_EXCHANGE"
    SIDE_MISMATCH          = "SIDE_MISMATCH"
    QUANTITY_MISMATCH      = "QUANTITY_MISMATCH"
    DUPLICATE_JOURNAL_TRADES = "DUPLICATE_JOURNAL_TRADES"
    TIMELINE_DESYNC        = "TIMELINE_DESYNC"
    UNKNOWN                = "UNKNOWN"


_SEVERITY_MAP: dict[str, str] = {
    DetectionStatus.GHOST_RUNTIME.value:            "critical",
    DetectionStatus.GHOST_JOURNAL.value:             "critical",
    DetectionStatus.ORPHAN_EXCHANGE.value:           "critical",
    DetectionStatus.SIDE_MISMATCH.value:             "critical",
    DetectionStatus.DUPLICATE_JOURNAL_TRADES.value:  "critical",
    DetectionStatus.QUANTITY_MISMATCH.value:         "warning",
    DetectionStatus.TIMELINE_DESYNC.value:           "warning",
    DetectionStatus.REAL_POSITION.value:             "info",
    DetectionStatus.NO_POSITION.value:               "info",
    DetectionStatus.UNKNOWN.value:                   "info",
}

# Recovery-result substrings that mean "attempted, did not fix it".
# Everything else that isn't a recognized no-op (see
# _NEUTRAL_RECOVERY_RESULTS) counts as success. See _classify_recovery().
_FAILURE_MARKERS = ("error", "failed", "missing_")
_NEUTRAL_RECOVERY_RESULTS = frozenset({
    "no_safe_auto_action", "position_no_longer_open", "skipped_cooldown",
})


@dataclass
class RuntimeValidationResult:
    symbol:             str
    status:              str    # DetectionStatus value
    severity:            str    # info | warning | critical
    canonical_state:      str    # system_health.order_state.OrderState value
    exchange_state:       dict
    runtime_state:        dict
    journal_state:        dict
    timeline_state:        str | None
    timeline_desync:       bool
    ghost_detected:        bool
    mismatch_type:         str | None
    recovery_attempted:     bool
    recovery_result:        str | None
    detected_at:            str
    reason:                 str | None

    def to_dict(self) -> dict:
        return asdict(self)


class GhostReconciliationMonitor:
    """Stateless w.r.t. position truth — every field in
    RuntimeValidationResult is read fresh from OrderStateManager +
    OrderTimeline on every check() call (same convention
    OrderStateManager itself documents for its own snapshots). Holds
    only its own transition-tracking, event-dedup, findings ring
    buffer, and metrics counters in memory — in-memory only, not a
    durability guarantee, matching every other tracker in this
    codebase (event_bus, execution_state, order_state, ...)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_status: dict[str, str] = {}
        self._last_event_ts: dict[tuple[str, str], float] = {}
        self._findings: list[dict] = []

        self._metrics: dict[str, int | str | None] = {
            "reconciliation_count":         0,
            "ghost_detected_count":         0,
            "runtime_mismatch_count":       0,
            "orphan_exchange_count":        0,
            "recovery_success_count":       0,
            "recovery_failure_count":       0,
            "timeline_desync_count":        0,
            "last_reconciliation_timestamp": None,
            "last_recovery_timestamp":       None,
        }
        self._reconciliation_latency_samples: list[float] = []
        self._timeline_latency_samples: list[float] = []

    # ── Public API ───────────────────────────────────────────────────

    def check(self, sys: dict, symbol: str | None = None) -> RuntimeValidationResult:
        """One validation cycle for one symbol. Safe to call directly
        (tests, an API request handler, or a scheduled job) — never
        starts a thread of its own. Never raises: any internal failure
        degrades to an UNKNOWN result, same posture as
        OrderStateManager._unknown_snapshot()."""
        from config.settings import settings
        symbol = symbol or settings.SYMBOL

        mgr = sys.get("order_state_manager")
        if mgr is None:
            from system_health.order_state import get_order_state_manager
            mgr = get_order_state_manager()

        started = time.monotonic()
        try:
            snapshot = mgr.get_order_state(sys, symbol=symbol)
        except Exception as exc:
            logger.error(f"GhostReconciliationMonitor: get_order_state failed: {exc}", exc_info=True)
            return self._unknown_result(symbol, f"order_state_error: {exc}")
        reconciliation_latency_ms = (time.monotonic() - started) * 1000.0

        timeline = self._resolve_timeline(sys)
        timeline_desync, timeline_state = self._check_timeline_desync(snapshot, timeline, symbol)
        timeline_latency_ms = self._timeline_latency_ms(timeline, symbol)

        status = self._classify_detection(snapshot, timeline_desync)
        severity = _SEVERITY_MAP.get(status, "info")

        now = datetime.now(timezone.utc).isoformat()
        result = RuntimeValidationResult(
            symbol=symbol,
            status=status,
            severity=severity,
            canonical_state=snapshot.canonical_state.value,
            exchange_state=snapshot.exchange_position,
            runtime_state=snapshot.runtime_position,
            journal_state=snapshot.journal_position,
            timeline_state=timeline_state,
            timeline_desync=timeline_desync,
            ghost_detected=snapshot.ghost_detected,
            mismatch_type=snapshot.mismatch_type,
            recovery_attempted=snapshot.recovery_attempted,
            recovery_result=snapshot.recovery_result,
            detected_at=now,
            reason=snapshot.desync_reason,
        )

        self._record_metrics(status, timeline_desync, reconciliation_latency_ms, timeline_latency_ms, now, result)
        self._maybe_publish(sys, symbol, status, result)
        return result

    def status(self) -> dict:
        """C3-2's own metrics — distinct names from, and additive to,
        OrderStateManager.status()'s counters (see module docstring
        point 5)."""
        with self._lock:
            out = dict(self._metrics)
            out["reconciliation_latency_ms"] = self._avg(self._reconciliation_latency_samples)
            out["timeline_sync_latency_ms"] = self._avg(self._timeline_latency_samples)
            return out

    def get_recent_findings(self, limit: int = 50) -> list[dict]:
        """Bounded, in-memory, most-recent-first. A 'finding' is
        appended only on a DETECTION_STATUS transition for that symbol
        (not on every poll) — same convention as OrderTimeline's
        history()/recent()."""
        with self._lock:
            return list(self._findings[-limit:][::-1])

    # ── Internal: OrderTimeline consumption (read-only) ────────────────

    def _resolve_timeline(self, sys: dict):
        timeline = sys.get("order_timeline")
        if timeline is not None:
            return timeline
        try:
            from execution.order_timeline import get_order_timeline
            return get_order_timeline()
        except Exception as exc:
            logger.debug(f"GhostReconciliationMonitor: OrderTimeline unavailable: {exc}")
            return None

    def _check_timeline_desync(self, snapshot, timeline, symbol: str) -> tuple[bool, str | None]:
        if timeline is None:
            return False, None
        try:
            info = timeline.current_state(symbol)
            t_state = info.get("state") if info else None
        except Exception as exc:
            logger.debug(f"GhostReconciliationMonitor: OrderTimeline.current_state failed: {exc}")
            return False, None
        if not t_state:
            return False, None

        ex = snapshot.exchange_position or {}
        exchange_flat = ex.get("has_position") is False
        desync = exchange_flat and t_state in _ACTIVE_TIMELINE_STATES
        return desync, t_state

    def _timeline_latency_ms(self, timeline, symbol: str) -> float | None:
        if timeline is None:
            return None
        try:
            recent = timeline.recent(symbol=symbol, limit=1)
        except Exception:
            return None
        if not recent:
            return None
        ts = recent[0].get("timestamp")
        if not ts:
            return None
        try:
            t = datetime.fromisoformat(ts)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() * 1000.0)
        except Exception:
            return None

    # ── Internal: classification (reads already-computed data only) ────

    def _classify_detection(self, snapshot, timeline_desync: bool) -> str:
        from system_health.order_state import OrderState

        ex = snapshot.exchange_position or {}
        jv = snapshot.journal_position or {}
        bot = snapshot.runtime_position or {}
        mt = snapshot.mismatch_type

        if snapshot.canonical_state == OrderState.UNKNOWN:
            return DetectionStatus.UNKNOWN.value

        if snapshot.canonical_state == OrderState.GHOST:
            # PRESENCE_MISMATCH, exchange verified flat. Which source(s)
            # are stale is read directly off the same ex/jv/bot views
            # RecoveryEngine._clear_runtime_ghost()/_clear_ghost_journal_row()
            # already act on independently — no new decision logic.
            runtime_stale = bot.get("has_position") is True and bot.get("source") == "portfolio_state"
            journal_stale = jv.get("has_position") is True
            if runtime_stale:
                return DetectionStatus.GHOST_RUNTIME.value
            if journal_stale:
                return DetectionStatus.GHOST_JOURNAL.value
            # Defensive fallback: GHOST implies at least one of the above
            # per ReconciliationEngine._classify()'s own PRESENCE_MISMATCH
            # branch; report the general finding rather than mis-sorting
            # it as something else if that invariant ever changes.
            return DetectionStatus.GHOST_RUNTIME.value

        if snapshot.canonical_state == OrderState.DESYNC:
            if mt == "PRESENCE_MISMATCH" and ex.get("has_position") is True:
                return DetectionStatus.ORPHAN_EXCHANGE.value
            if mt == "SIDE_MISMATCH":
                return DetectionStatus.SIDE_MISMATCH.value
            if mt == "QUANTITY_MISMATCH":
                return DetectionStatus.QUANTITY_MISMATCH.value
            if mt == "DUPLICATE_JOURNAL_TRADES":
                return DetectionStatus.DUPLICATE_JOURNAL_TRADES.value
            # A future mismatch_type this mapping doesn't know yet —
            # surfaced honestly, matching OrderStateManager._classify()'s
            # own "unknown mismatch type" fallback.
            return DetectionStatus.UNKNOWN.value

        if timeline_desync:
            return DetectionStatus.TIMELINE_DESYNC.value

        if snapshot.canonical_state in (OrderState.OPEN, OrderState.OPENING, OrderState.CLOSING):
            return DetectionStatus.REAL_POSITION.value

        # NO_POSITION / CLOSED, and every check above found nothing.
        return DetectionStatus.NO_POSITION.value

    def _classify_recovery(self, recovery_attempted: bool, recovery_result: str | None) -> str | None:
        """'success' | 'failure' | None (no attempt, or a neutral no-op
        like no_safe_auto_action that isn't meaningfully either)."""
        if not recovery_attempted or not recovery_result:
            return None
        r = recovery_result.lower()
        if r in _NEUTRAL_RECOVERY_RESULTS or r.startswith("no_auto_recovery_for"):
            return None
        if any(marker in r for marker in _FAILURE_MARKERS):
            return "failure"
        return "success"

    # ── Internal: metrics ────────────────────────────────────────────

    def _record_metrics(
        self, status: str, timeline_desync: bool,
        reconciliation_latency_ms: float, timeline_latency_ms: float | None,
        now: str, result: RuntimeValidationResult,
    ) -> None:
        recovery_verdict = self._classify_recovery(result.recovery_attempted, result.recovery_result)
        with self._lock:
            self._metrics["reconciliation_count"] += 1
            self._metrics["last_reconciliation_timestamp"] = now

            self._reconciliation_latency_samples.append(reconciliation_latency_ms)
            if len(self._reconciliation_latency_samples) > _MAX_LATENCY_SAMPLES:
                self._reconciliation_latency_samples.pop(0)
            if timeline_latency_ms is not None:
                self._timeline_latency_samples.append(timeline_latency_ms)
                if len(self._timeline_latency_samples) > _MAX_LATENCY_SAMPLES:
                    self._timeline_latency_samples.pop(0)

            if status in (DetectionStatus.GHOST_RUNTIME.value, DetectionStatus.GHOST_JOURNAL.value):
                self._metrics["ghost_detected_count"] += 1
            if status in (
                DetectionStatus.GHOST_RUNTIME.value, DetectionStatus.GHOST_JOURNAL.value,
                DetectionStatus.SIDE_MISMATCH.value, DetectionStatus.QUANTITY_MISMATCH.value,
            ):
                self._metrics["runtime_mismatch_count"] += 1
            if status == DetectionStatus.ORPHAN_EXCHANGE.value:
                self._metrics["orphan_exchange_count"] += 1
            if timeline_desync:
                self._metrics["timeline_desync_count"] += 1

            if recovery_verdict == "success":
                self._metrics["recovery_success_count"] += 1
                self._metrics["last_recovery_timestamp"] = now
            elif recovery_verdict == "failure":
                self._metrics["recovery_failure_count"] += 1
                self._metrics["last_recovery_timestamp"] = now

    def _avg(self, samples: list[float]) -> float | None:
        return (sum(samples) / len(samples)) if samples else None

    # ── Internal: findings ring buffer + events (transition-only) ──────

    def _maybe_publish(self, sys: dict, symbol: str, status: str, result: RuntimeValidationResult) -> None:
        with self._lock:
            previous = self._last_status.get(symbol)
            changed = previous != status
            self._last_status[symbol] = status
            if changed:
                self._findings.append(result.to_dict())
                overflow = len(self._findings) - _MAX_FINDINGS
                if overflow > 0:
                    del self._findings[:overflow]

        if not changed:
            # Identical finding as the last check for this symbol — no
            # duplicate event, no duplicate findings-buffer entry. This
            # alone satisfies "repeated identical findings must not
            # generate unlimited duplicate events" (brief §9/§16.H); the
            # per-event dedup window below is an additional guard against
            # a rapidly flapping condition re-firing on every transition.
            return

        bus = sys.get("event_bus")
        if bus is None:
            return

        from config.settings import settings
        dedup_seconds = getattr(settings, "ORDER_RECONCILIATION_DEDUP_SECONDS", 30.0)

        for event_name, message, severity in self._events_for(symbol, status, result):
            key = (symbol, event_name)
            now_m = time.monotonic()
            with self._lock:
                last = self._last_event_ts.get(key)
                if last is not None and (now_m - last) < dedup_seconds:
                    continue
                self._last_event_ts[key] = now_m
            try:
                bus.publish(_EVENT_SOURCE, event_name, message, severity=severity, payload=result.to_dict())
            except Exception as exc:
                logger.warning(f"GhostReconciliationMonitor: event publish failed (non-fatal): {exc}")

    def _events_for(self, symbol: str, status: str, result: RuntimeValidationResult) -> list[tuple[str, str, str]]:
        """New events only — see module docstring's 'Event vocabulary —
        reuse first' section for why GHOST_* and ORPHAN_EXCHANGE findings
        do NOT get a duplicate event published here."""
        events: list[tuple[str, str, str]] = []

        if status in (DetectionStatus.SIDE_MISMATCH.value, DetectionStatus.QUANTITY_MISMATCH.value):
            events.append((
                "RUNTIME_POSITION_MISMATCH",
                f"{symbol}: {status} — {result.reason or 'see mismatch_type'}",
                _SEVERITY_MAP.get(status, "warning"),
            ))

        if status == DetectionStatus.TIMELINE_DESYNC.value:
            events.append((
                "ORDER_TIMELINE_DESYNC",
                f"{symbol}: exchange verified flat but OrderTimeline's last state was {result.timeline_state}",
                "warning",
            ))

        recovery_verdict = self._classify_recovery(result.recovery_attempted, result.recovery_result)
        if recovery_verdict == "failure":
            events.append((
                "RECONCILIATION_FAILED",
                f"{symbol}: recovery attempt did not clear the condition ({result.recovery_result})",
                "critical",
            ))

        return events

    def _unknown_result(self, symbol: str, reason: str) -> RuntimeValidationResult:
        now = datetime.now(timezone.utc).isoformat()
        return RuntimeValidationResult(
            symbol=symbol, status=DetectionStatus.UNKNOWN.value, severity="info",
            canonical_state="UNKNOWN", exchange_state={}, runtime_state={}, journal_state={},
            timeline_state=None, timeline_desync=False, ghost_detected=False, mismatch_type=None,
            recovery_attempted=False, recovery_result=None, detected_at=now, reason=reason,
        )


# ── Singleton, mirrors order_state.py / reconciliation.py / recovery_engine.py ──

_grm: GhostReconciliationMonitor | None = None
_grm_lock = threading.Lock()


def get_ghost_reconciliation_monitor() -> GhostReconciliationMonitor:
    global _grm
    if _grm is None:
        with _grm_lock:
            if _grm is None:
                _grm = GhostReconciliationMonitor()
    return _grm


def reset_ghost_reconciliation_monitor() -> GhostReconciliationMonitor:
    """Test-only: fresh instance so metrics/transition/dedup state never
    leaks between tests (same convention as reset_order_state_manager()
    / reset_reconciliation_engine() / reset_recovery_engine())."""
    global _grm
    with _grm_lock:
        _grm = GhostReconciliationMonitor()
    return _grm
