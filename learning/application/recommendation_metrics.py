"""
learning/application/recommendation_metrics.py — V16 Phase 4C Step 3
Part E: Runtime Metrics.

In-process counters only — no new persistence, no new DB table.
Mirrors events/event_bus.py's own get_*()/reset_*() singleton pattern
(module-level global + lock) so this composes the same way callers
already use EventBus, both in main.py and in tests.

Tallies come from the ADVISOR's explanations list (recommendation_advisor.py),
not from Part A's RecommendationSet directly — a recommendation can pass
every Part A filter and still end up unapplied at the Part B stage
(decision was BLOCKED, or it lost out past
RECOMMENDATION_MAX_APPLIED_PER_DECISION) — explanations is the one place
that reflects what actually happened to every recommendation, end to end.
"""
from __future__ import annotations

import threading


class RecommendationApplicationMetrics:
    """One process-wide accumulator. All read/write access is lock-guarded
    — this is read from api/app.py's dashboard endpoint (Part F) while
    being written from the live decision cycle (Part B) concurrently."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.recommendations_loaded:  int = 0
        self.recommendations_applied:  int = 0
        self.recommendations_skipped:   int = 0
        self.expired:                     int = 0
        self.contradictory:                int = 0
        self.invalid:                       int = 0
        self.insufficient_sample:            int = 0
        self._score_sum:    float = 0.0
        self._score_count:   int = 0
        self._latency_sum_ms: float = 0.0
        self._latency_count:   int = 0

    def record_loaded(self, n: int) -> None:
        with self._lock:
            self.recommendations_loaded += n

    def record_explanations(self, explanations: list) -> None:
        """`explanations` is a list of
        recommendation_advisor.AppliedRecommendationExplanation."""
        with self._lock:
            for e in explanations:
                if e.applied:
                    self.recommendations_applied += 1
                    if e.score is not None:
                        self._score_sum += e.score
                        self._score_count += 1
                    continue
                self.recommendations_skipped += 1
                reason = e.skip_reason or ""
                if reason == "validator_status=expired":
                    self.expired += 1
                elif reason.startswith("contradicted_by="):
                    self.contradictory += 1
                elif reason == "validator_status=invalid":
                    self.invalid += 1
                elif reason == "validator_status=insufficient_sample":
                    self.insufficient_sample += 1

    def record_latency_ms(self, latency_ms: float) -> None:
        with self._lock:
            self._latency_sum_ms += latency_ms
            self._latency_count += 1

    def to_dict(self) -> dict:
        with self._lock:
            avg_score = (self._score_sum / self._score_count) if self._score_count else None
            avg_latency = (self._latency_sum_ms / self._latency_count) if self._latency_count else None
            return {
                "recommendations_loaded":  self.recommendations_loaded,
                "recommendations_applied":  self.recommendations_applied,
                "recommendations_skipped":   self.recommendations_skipped,
                "expired":                     self.expired,
                "contradictory":                self.contradictory,
                "invalid":                        self.invalid,
                "insufficient_sample":              self.insufficient_sample,
                "average_score":                      avg_score,
                "average_application_latency_ms":       avg_latency,
            }


_global_metrics: RecommendationApplicationMetrics | None = None
_metrics_lock = threading.Lock()


def get_recommendation_metrics() -> RecommendationApplicationMetrics:
    global _global_metrics
    if _global_metrics is None:
        with _metrics_lock:
            if _global_metrics is None:
                _global_metrics = RecommendationApplicationMetrics()
    return _global_metrics


def reset_recommendation_metrics() -> RecommendationApplicationMetrics:
    """Mirrors events/event_bus.py's reset_event_bus() — mainly for test
    isolation (a fresh process-wide accumulator between tests)."""
    global _global_metrics
    with _metrics_lock:
        _global_metrics = RecommendationApplicationMetrics()
    return _global_metrics
