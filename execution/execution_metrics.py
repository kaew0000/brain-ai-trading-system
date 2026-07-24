"""
execution/execution_metrics.py — V16 Phase 2E: Execution Wiring & Live
Orchestrator

Pure computation over execution_state.ExecutionState's tracked records —
no independent counters, no separate storage. Mirrors
portfolio/sector_engine.py's SectorEngine.diversification_score_from_exposure()
pattern: a static-ish function that derives a metric from data another
module already owns, rather than a second module quietly re-counting the
same executions.

ExecutionMetricsSnapshot is frozen/immutable (like portfolio/'s
dataclasses) because it is a point-in-time computed view, not something
any caller should mutate — every ExecutionOrchestrator.execute() call
that changes counts publishes a NEW snapshot via
execution_events.ExecutionEventType.METRICS_UPDATED rather than anyone
mutating an old one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from execution.execution_state import ExecutionState, ExecutionStatus


@dataclass(frozen=True)
class ExecutionMetricsSnapshot:
    total:                 int
    completed:              int
    failed:                 int
    cancelled:              int
    pending:                int
    running:                int
    success_rate:           float   # completed / (completed + failed), 0.0 if none finished
    failure_rate:            float   # failed / (completed + failed), 0.0 if none finished
    retry_rate:              float   # fraction of finished executions that needed >=1 retry
    average_latency_seconds: float   # mean latency_seconds across finished records with a latency
    per_symbol_counts:        dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total":                    self.total,
            "completed":                self.completed,
            "failed":                   self.failed,
            "cancelled":                self.cancelled,
            "pending":                  self.pending,
            "running":                  self.running,
            "success_rate":             round(self.success_rate, 4),
            "failure_rate":             round(self.failure_rate, 4),
            "retry_rate":               round(self.retry_rate, 4),
            "average_latency_seconds":  round(self.average_latency_seconds, 4),
            "per_symbol_counts":        dict(self.per_symbol_counts),
        }


def compute_metrics(state: ExecutionState) -> ExecutionMetricsSnapshot:
    """Derive a snapshot from whatever `state` currently holds. Safe to
    call at any time (e.g. mid-batch) — pending/running records simply
    don't contribute to success/failure/retry/latency rates yet, exactly
    as their status implies."""
    records = state.all_records()

    finished = [r for r in records if r.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED)]
    completed = [r for r in records if r.status == ExecutionStatus.COMPLETED]
    failed    = [r for r in records if r.status == ExecutionStatus.FAILED]
    cancelled = [r for r in records if r.status == ExecutionStatus.CANCELLED]
    pending   = [r for r in records if r.status == ExecutionStatus.PENDING]
    running   = [r for r in records if r.status == ExecutionStatus.RUNNING]

    finished_n = len(finished)
    success_rate = (len(completed) / finished_n) if finished_n else 0.0
    failure_rate = (len(failed) / finished_n) if finished_n else 0.0
    retried = [r for r in finished if r.retry_count > 0]
    retry_rate = (len(retried) / finished_n) if finished_n else 0.0

    latencies = [r.latency_seconds for r in finished if r.latency_seconds is not None]
    average_latency = (sum(latencies) / len(latencies)) if latencies else 0.0

    per_symbol: dict[str, int] = {}
    for r in records:
        per_symbol[r.symbol] = per_symbol.get(r.symbol, 0) + 1

    return ExecutionMetricsSnapshot(
        total=len(records),
        completed=len(completed),
        failed=len(failed),
        cancelled=len(cancelled),
        pending=len(pending),
        running=len(running),
        success_rate=success_rate,
        failure_rate=failure_rate,
        retry_rate=retry_rate,
        average_latency_seconds=average_latency,
        per_symbol_counts=per_symbol,
    )
