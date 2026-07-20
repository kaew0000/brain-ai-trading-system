"""
execution/execution_state.py — V16 Phase 2E: Execution Wiring & Live
Orchestrator

Pure in-memory state container — no exchange calls, no database, no
network. Mirrors portfolio/portfolio_state.py's own philosophy ("this
class just tracks numbers") and events/event_bus.py's ring-buffer
pattern (bounded history, not unbounded growth) rather than inventing a
third state-tracking idiom for this one package.

ExecutionState answers two questions ExecutionOrchestrator itself is not
responsible for computing on every call:
  1. "Has this (execution_batch_id, symbol) pair already been executed?"
     — the idempotency ledger. Keyed on (batch_id, symbol) rather than
     symbol alone, because the same symbol legitimately gets executed
     again in a later, distinct decision cycle (batch) — idempotency
     here means "don't execute the same decision's allocation twice",
     not "never trade this symbol twice, ever".
  2. "What is currently pending/running/completed/failed/cancelled?" —
     for observability (api/execution_api.py, tests), not for control
     flow; ExecutionOrchestrator decides what to do next from the
     OrchestratedDecision/ExecutionCoordinator results it already has in
     hand, not by re-reading this container.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

_HISTORY_SIZE = 500  # ring buffer, mirrors events/event_bus.py's _RING_BUFFER_SIZE choice


class ExecutionStatus(str, Enum):
    PENDING   = "PENDING"
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ExecutionRecord:
    """One allocation's execution lifecycle. Mutable in place (unlike
    portfolio/'s frozen dataclasses) because a single record transitions
    PENDING -> RUNNING -> {COMPLETED|FAILED|CANCELLED} over its own
    lifetime and ExecutionState owns that transition, not the caller
    reconstructing a new record each time."""

    execution_id:   str
    batch_id:       str
    symbol:         str
    status:         ExecutionStatus = ExecutionStatus.PENDING
    retry_count:    int = 0
    created_at:     float = field(default_factory=time.time)
    started_at:     Optional[float] = None
    finished_at:    Optional[float] = None
    error:          Optional[str] = None
    result:         Optional[dict] = None

    @property
    def latency_seconds(self) -> Optional[float]:
        if self.started_at is None or self.finished_at is None:
            return None
        return max(0.0, self.finished_at - self.started_at)

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "batch_id":     self.batch_id,
            "symbol":       self.symbol,
            "status":       self.status.value,
            "retry_count":  self.retry_count,
            "created_at":   self.created_at,
            "started_at":   self.started_at,
            "finished_at":  self.finished_at,
            "latency_seconds": self.latency_seconds,
            "error":        self.error,
        }


class ExecutionState:
    """Thread-safe tracker for one running process's execution history.
    One instance is meant to be shared by every ExecutionOrchestrator
    call for the life of the process (constructor-injected, same as
    ExecutionCoordinator's _managers cache) — see get_execution_state()
    below for the process-wide singleton accessor api/execution_api.py
    reads from."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, ExecutionRecord] = {}
        self._order: deque[str] = deque(maxlen=_HISTORY_SIZE)  # eviction order
        self._executed_keys: Set[Tuple[str, str]] = set()  # (batch_id, symbol)

    # ── Idempotency ──────────────────────────────────────────────────────

    def already_executed(self, batch_id: str, symbol: str) -> bool:
        with self._lock:
            return (batch_id, symbol) in self._executed_keys

    def mark_executed(self, batch_id: str, symbol: str) -> None:
        with self._lock:
            self._executed_keys.add((batch_id, symbol))

    # ── Lifecycle ────────────────────────────────────────────────────────

    def enqueue(self, execution_id: str, batch_id: str, symbol: str) -> ExecutionRecord:
        """Register a PENDING record before any engine call is made — the
        real window request_cancel() needs to exist during (a caller
        checking for a cancel request between enqueue-time and the actual
        execute_trade()/close_position() call)."""
        record = ExecutionRecord(execution_id=execution_id, batch_id=batch_id, symbol=symbol)
        record.status = ExecutionStatus.PENDING
        with self._lock:
            if len(self._order) == self._order.maxlen:
                evicted = self._order[0]
                self._records.pop(evicted, None)
            self._order.append(execution_id)
            self._records[execution_id] = record
        return record

    def start(self, execution_id: str) -> Optional[ExecutionRecord]:
        """Transition an enqueued PENDING record to RUNNING. Returns None
        (and does nothing) if the record was cancelled while pending, or
        doesn't exist — callers must check for None and skip the engine
        call rather than executing anyway."""
        with self._lock:
            record = self._records.get(execution_id)
            if record is None or record.status != ExecutionStatus.PENDING:
                return None
            record.status = ExecutionStatus.RUNNING
            record.started_at = time.time()
            return record

    def request_cancel(self, execution_id: str, reason: str = "manual_cancel") -> bool:
        """Cancel a still-PENDING record. Returns False (no-op) if the
        record is already RUNNING/COMPLETED/FAILED/CANCELLED or doesn't
        exist — matches real-world 'can't cancel something already
        executing or done'."""
        with self._lock:
            record = self._records.get(execution_id)
            if record is None or record.status != ExecutionStatus.PENDING:
                return False
            record.status = ExecutionStatus.CANCELLED
            record.finished_at = time.time()
            record.error = reason
            return True

    def complete(self, execution_id: str, result: dict) -> None:
        with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return
            record.status = ExecutionStatus.COMPLETED
            record.finished_at = time.time()
            record.result = result

    def fail(self, execution_id: str, error: str) -> None:
        with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return
            record.status = ExecutionStatus.FAILED
            record.finished_at = time.time()
            record.error = error

    def cancel(self, execution_id: str, reason: str) -> None:
        with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return
            record.status = ExecutionStatus.CANCELLED
            record.finished_at = record.finished_at or time.time()
            record.error = reason

    def record_retry(self, execution_id: str) -> int:
        with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return 0
            record.retry_count += 1
            return record.retry_count

    # ── Query ────────────────────────────────────────────────────────────

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        with self._lock:
            return self._records.get(execution_id)

    def all_records(self) -> List[ExecutionRecord]:
        with self._lock:
            return list(self._records.values())

    def by_status(self, status: ExecutionStatus) -> List[ExecutionRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.status == status]

    @property
    def pending_count(self) -> int:
        return len(self.by_status(ExecutionStatus.PENDING))

    @property
    def running_count(self) -> int:
        return len(self.by_status(ExecutionStatus.RUNNING))

    @property
    def completed_count(self) -> int:
        return len(self.by_status(ExecutionStatus.COMPLETED))

    @property
    def failed_count(self) -> int:
        return len(self.by_status(ExecutionStatus.FAILED))

    @property
    def cancelled_count(self) -> int:
        return len(self.by_status(ExecutionStatus.CANCELLED))

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "pending":   self.pending_count,
                "running":   self.running_count,
                "completed": self.completed_count,
                "failed":    self.failed_count,
                "cancelled": self.cancelled_count,
                "total_tracked": len(self._records),
            }

    def clear(self) -> None:
        """Test-only reset — mirrors EventBus.clear()/clear_subscribers()."""
        with self._lock:
            self._records.clear()
            self._order.clear()
            self._executed_keys.clear()


# ── Singleton ────────────────────────────────────────────────────────────
# Mirrors events/event_bus.py's get_event_bus()/reset_event_bus() pattern
# exactly — same problem (one process-wide instance, but tests need a
# fresh one), same solution, no new idiom invented.

_global_state: Optional[ExecutionState] = None
_state_lock = threading.Lock()


def get_execution_state() -> ExecutionState:
    global _global_state
    if _global_state is None:
        with _state_lock:
            if _global_state is None:
                _global_state = ExecutionState()
    return _global_state


def reset_execution_state() -> ExecutionState:
    global _global_state
    with _state_lock:
        _global_state = ExecutionState()
    return _global_state
