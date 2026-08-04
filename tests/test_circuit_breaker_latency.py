"""tests/test_circuit_breaker_latency.py — Phase W11

Covers the one change made to system_health/circuit_breaker.py: call()
now records wall-clock latency for read-only observability via
snapshot(). Every assertion here is about the *addition* — existing
behavior (return value, exceptions, state transitions) is asserted
unchanged alongside it, not just the new field in isolation.
"""
from __future__ import annotations

import time

import pytest

from system_health.circuit_breaker import CircuitBreaker

pytestmark = pytest.mark.unit


def test_call_returns_value_unchanged():
    cb = CircuitBreaker("test_returns_value")
    result = cb.call(lambda x: x * 2, 21)
    assert result == 42


def test_call_records_latency_on_success():
    cb = CircuitBreaker("test_latency_success")
    assert cb.snapshot()["last_latency_ms"] is None  # nothing recorded yet

    def _slow():
        time.sleep(0.01)
        return "ok"

    cb.call(_slow)
    snap = cb.snapshot()
    assert snap["last_latency_ms"] is not None
    assert snap["last_latency_ms"] >= 9.0  # allow scheduler jitter under 10ms sleep


def test_call_records_latency_on_failure_too():
    """Latency must be recorded even when fn raises — a slow failing
    call is exactly the case this instrumentation exists to surface."""
    cb = CircuitBreaker("test_latency_failure", failure_threshold=5)

    def _slow_fail():
        time.sleep(0.01)
        raise ValueError("boom")

    with pytest.raises(ValueError):
        cb.call(_slow_fail)

    snap = cb.snapshot()
    assert snap["last_latency_ms"] is not None
    assert snap["last_latency_ms"] >= 9.0


def test_call_still_raises_and_still_counts_failures():
    """The exact pre-W11 contract: call() propagates fn's exception and
    the breaker still counts it as a failure toward opening."""
    cb = CircuitBreaker("test_failure_counting", failure_threshold=2)

    for _ in range(2):
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))

    assert cb.state == "OPEN"


def test_latency_updates_on_every_call():
    cb = CircuitBreaker("test_latency_updates")
    cb.call(lambda: time.sleep(0.005))
    first = cb.snapshot()["last_latency_ms"]
    cb.call(lambda: time.sleep(0.02))
    second = cb.snapshot()["last_latency_ms"]
    assert second > first


def test_all_snapshots_includes_last_latency_ms_key():
    from system_health.circuit_breaker import all_snapshots, get_breaker

    get_breaker("test_all_snapshots_latency").call(lambda: "ok")
    snaps = all_snapshots()
    assert "last_latency_ms" in snaps["test_all_snapshots_latency"]
    assert snaps["test_all_snapshots_latency"]["last_latency_ms"] is not None
