"""
tests/test_v15_production.py — Brain Bot V15 Production Regression Suite

Covers every bug listed in the V15 audit:
  BUG-V15-DB-01..05   Database layer
  BUG-V15-RETRY-01..04 Retry decorator
  BUG-V15-CB-*        Circuit breaker
  BUG-V15-EB-*        Event bus
  BUG-V15-BP-*        Binance provider (mocked)
  BUG-V15-API-*       API endpoints
  BUG-V15-STRESS-*    Long-run / concurrency

All tests use in-memory SQLite (:memory:) or mocks — no real network calls.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# v16 fix: every other test file in this suite has `pytestmark =
# pytest.mark.unit` (or per-class @pytest.mark.unit) at module scope.
# This file never did, and pytest.ini's `addopts = ... -m "unit"` means
# unmarked tests are silently deselected from the default `pytest tests/`
# run — so all 61 tests in this file (now +12 with the v16 watchdog/
# sd_notify additions) never actually executed as part of the project's
# regression bar, despite the file's own docstring describing itself as
# exactly that ("Brain Bot V15 Production Regression Suite"). Confirmed
# via mocks-only content (in-memory SQLite / MagicMock, no live network)
# that this belongs under "unit", matching pytest.ini's own definition.
pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Database Layer Tests (BUG-V15-DB-*)
# ---------------------------------------------------------------------------

class TestDatabaseLayer:
    """Covers BUG-V15-DB-01 through BUG-V15-DB-05."""

    def test_wal_mode_enabled(self):
        """BUG-V15-DB-01: WAL journal mode must be set on new file connections."""
        from database.db import _new_file_conn
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            conn = _new_file_conn(path)
            row = conn.execute("PRAGMA journal_mode").fetchone()
            conn.close()
            assert row[0] == "wal", f"Expected WAL, got {row[0]}"
        finally:
            os.unlink(path)

    def test_busy_timeout_set(self):
        """BUG-V15-DB-03: busy_timeout must be configured to avoid instant lock failures."""
        from database.db import _new_file_conn
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            conn = _new_file_conn(path)
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            conn.close()
            assert int(row[0]) >= 5000, f"busy_timeout too low: {row[0]}"
        finally:
            os.unlink(path)

    def test_managed_conn_write_serialization(self):
        """BUG-V15-DB-02: Concurrent writes must be serialised without corruption."""
        from database.db import ManagedConn, _get_write_lock
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Create the table
            lock = _get_write_lock(db_path)
            with lock:
                conn = sqlite3.connect(db_path)
                conn.execute("CREATE TABLE IF NOT EXISTS counter (n INTEGER)")
                conn.execute("INSERT INTO counter VALUES (0)")
                conn.commit()
                conn.close()

            errors = []
            completed = []

            def increment(idx: int):
                try:
                    with ManagedConn(db_path) as c:
                        row = c.execute("SELECT n FROM counter").fetchone()
                        new_val = row[0] + 1
                        time.sleep(0.001)   # simulate work
                        c.execute("UPDATE counter SET n = ?", (new_val,))
                        c.commit()
                    completed.append(idx)
                except Exception as exc:
                    errors.append(str(exc))

            threads = [threading.Thread(target=increment, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert not errors, f"Write errors: {errors}"
            assert len(completed) == 10

        finally:
            os.unlink(db_path)

    def test_memory_connection_reused(self):
        """BUG-V15-DB-05: :memory: connections must be the same object."""
        from database.db import get_connection
        c1 = get_connection(":memory:")
        c2 = get_connection(":memory:")
        assert c1 is c2, "Expected the same :memory: connection object"

    def test_schema_not_applied_twice(self):
        """BUG-V15-DB-04: Schema must only be applied once per path."""
        from database.db import ManagedConn, _initialized_paths
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name

        # Remove from initialized so we can test fresh
        _initialized_paths.discard(path)
        try:
            with ManagedConn(path) as c:
                c.execute("SELECT 1")
            with ManagedConn(path) as c:
                # Should not fail with "table already exists"
                c.execute("SELECT 1")
        finally:
            _initialized_paths.discard(path)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Retry Decorator Tests (BUG-V15-RETRY-*)
# ---------------------------------------------------------------------------

class TestRetryDecorator:
    """Covers BUG-V15-RETRY-01 through BUG-V15-RETRY-04."""

    def test_exponential_backoff(self):
        """BUG-V15-RETRY-01: Retry delays must grow exponentially."""
        from utils.retry import retry_api_call
        sleep_calls: List[float] = []

        call_count = 0

        @retry_api_call(retries=3, delay=1.0, backoff=2.0, jitter=False)
        def failing_fn():
            nonlocal call_count
            call_count += 1
            raise ConnectionResetError("test")

        with patch("utils.retry.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            with pytest.raises(ConnectionResetError):
                failing_fn()

        assert call_count == 3
        # Delays: 1.0^0 * 1.0 = 1.0, 1.0^1 * 2.0 = 2.0
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == pytest.approx(1.0, abs=0.01)
        assert sleep_calls[1] == pytest.approx(2.0, abs=0.01)

    def test_jitter_applied(self):
        """BUG-V15-RETRY-02: Jitter must spread delays to avoid thundering herd."""
        from utils.retry import _jitter
        # Run 50 samples; none should equal the exact base value
        base = 2.0
        results = [_jitter(base) for _ in range(50)]
        unique = set(round(r, 8) for r in results)
        # With true randomness, virtually all 50 should be unique
        assert len(unique) > 40, "Jitter appears deterministic or missing"
        # All must be within ±25% of base
        for r in results:
            assert base * 0.75 <= r <= base * 1.25, f"Jitter out of range: {r}"

    def test_max_delay_cap(self):
        """BUG-V15-RETRY-03: Sleep time must not exceed max_delay."""
        from utils.retry import retry_api_call
        sleep_calls: List[float] = []

        @retry_api_call(retries=4, delay=10.0, backoff=10.0, max_delay=20.0, jitter=False)
        def failing_fn():
            raise ConnectionResetError("test")

        with patch("utils.retry.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            with pytest.raises(ConnectionResetError):
                failing_fn()

        for s in sleep_calls:
            assert s <= 20.0, f"Delay exceeded max_delay: {s}"

    def test_non_retryable_error_raised_immediately(self):
        """Non-retryable Binance errors must not consume retry budget."""
        from utils.retry import retry_api_call
        from binance.error import ClientError
        call_count = 0

        @retry_api_call(retries=5, delay=0.1)
        def bad_key_fn():
            nonlocal call_count
            call_count += 1
            raise ClientError(
                status_code=401, error_code=-2015,
                error_message="Invalid API key", header={}
            )

        with patch("utils.retry.time.sleep"):
            with pytest.raises(ClientError):
                bad_key_fn()

        assert call_count == 1, "Non-retryable error consumed retries"

    def test_circuit_breaker_fast_fail(self):
        """BUG-V15-CB-01: Open circuit must raise CircuitBreakerOpen without sleeping.

        Behaviour: breaker opens after the first failure (threshold=1). The retry
        decorator's SECOND attempt within the SAME call hits the open breaker and
        raises CircuitBreakerOpen immediately (no sleep). The NEXT outer call is
        also fast-failed by the open breaker.
        """
        from system_health.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
        from utils.retry import retry_api_call

        cb = CircuitBreaker("test_fast_fail_v2", failure_threshold=1, recovery_timeout=60)
        sleep_calls: List[float] = []

        @retry_api_call(retries=3, delay=1.0, breaker=cb)
        def failing_fn():
            raise ConnectionResetError("net")

        with patch("utils.retry.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            # First call: attempt 1 fails → breaker OPENS;
            # attempt 2 hits open breaker → CircuitBreakerOpen raised
            with pytest.raises((ConnectionResetError, CircuitBreakerOpen)):
                failing_fn()

        # Breaker is now OPEN — next call fast-fails with no sleep
        sleep_before = len(sleep_calls)
        with pytest.raises(CircuitBreakerOpen):
            failing_fn()
        assert len(sleep_calls) == sleep_before, "Open circuit must not sleep"


# ---------------------------------------------------------------------------
# Circuit Breaker Tests (BUG-V15-CB-*)
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    def test_closed_to_open_after_threshold(self):
        from system_health.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
        cb = CircuitBreaker("test_open", failure_threshold=3, recovery_timeout=60)
        assert cb.state == "CLOSED"

        for _ in range(3):
            try:
                with cb:
                    raise ValueError("fail")
            except ValueError:
                pass

        assert cb.state == "OPEN"
        with pytest.raises(CircuitBreakerOpen):
            with cb:
                pass

    def test_open_to_half_open_after_timeout(self):
        from system_health.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_half_open", failure_threshold=1, recovery_timeout=0.1)
        try:
            with cb:
                raise ValueError("fail")
        except ValueError:
            pass
        assert cb.state == "OPEN"
        time.sleep(0.15)
        # Next call should be let through (probe)
        with cb:
            pass  # success
        assert cb.state in ("CLOSED", "HALF_OPEN")

    def test_half_open_success_closes(self):
        from system_health.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_close", failure_threshold=1, recovery_timeout=0.05, success_threshold=1)
        try:
            with cb:
                raise ValueError("fail")
        except ValueError:
            pass
        time.sleep(0.1)
        with cb:
            pass  # probe success
        assert cb.state == "CLOSED"

    def test_manual_reset(self):
        from system_health.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_reset", failure_threshold=1, recovery_timeout=999)
        try:
            with cb:
                raise ValueError("fail")
        except ValueError:
            pass
        assert cb.state == "OPEN"
        cb.reset()
        assert cb.state == "CLOSED"

    def test_snapshot_format(self):
        from system_health.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_snapshot", failure_threshold=5, recovery_timeout=60)
        snap = cb.snapshot()
        required_keys = {"name", "state", "failure_count", "success_count",
                         "last_failure", "state_age_s", "recovery_in_s", "timestamp"}
        assert required_keys.issubset(snap.keys()), f"Missing keys: {required_keys - snap.keys()}"

    def test_global_registry(self):
        from system_health.circuit_breaker import get_breaker, all_snapshots
        cb1 = get_breaker("registry_test_A")
        cb2 = get_breaker("registry_test_A")
        assert cb1 is cb2

        snaps = all_snapshots()
        assert "registry_test_A" in snaps


# ---------------------------------------------------------------------------
# Event Bus Tests (BUG-V15-EB-*)
# ---------------------------------------------------------------------------

class TestEventBus:

    def test_publish_and_get_recent(self):
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        bus.publish("TEST_AGENT", "TEST_EVENT", "hello")
        recent = bus.get_recent(limit=10)
        assert any(e["agent"] == "TEST_AGENT" for e in recent)

    def test_ring_buffer_bounded(self):
        """BUG-V15-EB-01: Ring buffer must not grow unboundedly."""
        from events.event_bus import reset_event_bus, _RING_BUFFER_SIZE
        bus = reset_event_bus(persist=False)
        for i in range(_RING_BUFFER_SIZE + 50):
            bus.publish("A", "E", f"msg {i}")
        recent = bus.get_recent(limit=10000)
        assert len(recent) <= _RING_BUFFER_SIZE

    def test_bad_subscriber_isolated(self):
        """BUG-V15-EB-02: A crashing subscriber must not affect other subscribers."""
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        good_calls: List[str] = []

        def bad_cb(evt):
            raise RuntimeError("subscriber crash")

        def good_cb(evt):
            good_calls.append(evt.message)

        bus.subscribe("*", bad_cb)
        bus.subscribe("*", good_cb)

        # Must not raise
        bus.publish("X", "Y", "test message")
        assert "test message" in good_calls

    def test_subscriber_filter(self):
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        received_agent1: List[str] = []
        received_agent2: List[str] = []

        bus.subscribe("AGENT_1", lambda e: received_agent1.append(e.message))
        bus.subscribe("AGENT_2", lambda e: received_agent2.append(e.message))

        bus.publish("AGENT_1", "E", "msg_1")
        bus.publish("AGENT_2", "E", "msg_2")

        assert received_agent1 == ["msg_1"]
        assert received_agent2 == ["msg_2"]

    def test_wildcard_subscriber(self):
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        all_msgs: List[str] = []
        bus.subscribe("*", lambda e: all_msgs.append(e.message))

        bus.publish("A", "E", "one")
        bus.publish("B", "F", "two")

        assert "one" in all_msgs
        assert "two" in all_msgs

    def test_unsubscribe(self):
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        calls: List[int] = []
        cb = lambda e: calls.append(1)

        bus.subscribe("Z", cb)
        bus.publish("Z", "E", "m1")
        assert len(calls) == 1

        removed = bus.unsubscribe("Z", cb)
        assert removed is True
        bus.publish("Z", "E", "m2")
        assert len(calls) == 1   # no new call

    def test_seq_monotonically_increasing(self):
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        for _ in range(20):
            bus.publish("S", "E", "m")
        recent = bus.get_recent(limit=100)
        seqs = [e["seq"] for e in recent]
        # reversed (newest-first), so seqs should be descending
        assert seqs == sorted(seqs, reverse=True)

    def test_thread_safe_concurrent_publish(self):
        """BUG-V15-EB-04: Concurrent publishes must not corrupt the ring buffer."""
        from events.event_bus import reset_event_bus
        bus = reset_event_bus(persist=False)
        errors: List[str] = []

        def publish_many():
            for i in range(100):
                try:
                    bus.publish("T", "E", f"msg {i}")
                except Exception as exc:
                    errors.append(str(exc))

        threads = [threading.Thread(target=publish_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        # Buffer should be bounded
        recent = bus.get_recent(limit=10000)
        assert len(recent) <= 1000


# ---------------------------------------------------------------------------
# Binance Provider Tests (BUG-V15-BP-*)
# ---------------------------------------------------------------------------

class TestBinanceProvider:

    def test_time_drift_ms_property(self):
        """BUG-V15-BP-01: _time_drift_ms must alias _time_offset_ms_market."""
        with patch("data.binance_provider.UMFutures") as MockClient:
            inst = MockClient.return_value
            inst.time.return_value = {"serverTime": int(time.time() * 1000)}
            inst.mark_price.return_value = {"markPrice": "50000.0", "lastFundingRate": "0.0001"}
            from data.binance_provider import BinanceDataProvider
            dp = BinanceDataProvider()
            dp._time_offset_ms_market = 123
            assert dp._time_drift_ms == 123

    def test_circuit_breaker_opens_on_repeated_failures(self):
        """BUG-V15-BP-03: Circuit breaker must open after 5 consecutive failures."""
        from system_health.circuit_breaker import get_breaker, CircuitBreakerOpen
        cb = get_breaker("test_bp_circuit", failure_threshold=3, recovery_timeout=999)
        cb.reset()

        for _ in range(3):
            try:
                with cb:
                    raise ConnectionResetError("fake net error")
            except ConnectionResetError:
                pass

        assert cb.state == "OPEN"
        with pytest.raises(CircuitBreakerOpen):
            with cb:
                pass


# ---------------------------------------------------------------------------
# Stress / Long-run Tests (BUG-V15-STRESS-*)
# ---------------------------------------------------------------------------

class TestLongRunBehavior:

    def test_event_bus_no_memory_growth_1000_cycles(self):
        """Simulates 1000 trading cycles; ring buffer must stay bounded."""
        from events.event_bus import reset_event_bus, _RING_BUFFER_SIZE
        bus = reset_event_bus(persist=False)
        for cycle in range(1000):
            for agent in ["SMC_ANALYST", "VOLUME_ANALYST", "BRAIN_BOT", "RISK_MANAGER"]:
                bus.publish(agent, "CYCLE_EVENT", f"cycle {cycle}")
        recent = bus.get_recent(limit=100000)
        assert len(recent) <= _RING_BUFFER_SIZE
        assert len(recent) > 0

    def test_db_write_lock_no_deadlock_under_load(self):
        """30 concurrent threads writing to the same DB must all complete."""
        from database.db import ManagedConn, _initialized_paths
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        _initialized_paths.discard(db_path)

        errors: List[str] = []
        completed = []

        def write_row(idx: int):
            try:
                with ManagedConn(db_path) as c:
                    c.execute(
                        "CREATE TABLE IF NOT EXISTS stress (id INTEGER, val TEXT)"
                    )
                    c.execute("INSERT INTO stress VALUES (?, ?)", (idx, f"v{idx}"))
                    c.commit()
                completed.append(idx)
            except Exception as exc:
                errors.append(f"{idx}: {exc}")

        threads = [threading.Thread(target=write_row, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        os.unlink(db_path)

        assert not errors, f"Errors: {errors[:5]}"
        assert len(completed) == 30

    def test_circuit_breaker_recovers_after_outage(self):
        """Simulate API outage → breaker opens → API recovers → breaker closes."""
        from system_health.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            "outage_recovery_test",
            failure_threshold=3,
            recovery_timeout=0.1,
            success_threshold=2,
        )

        # Fail 3 times → OPEN
        for _ in range(3):
            try:
                with cb:
                    raise ConnectionResetError("down")
            except ConnectionResetError:
                pass
        assert cb.state == "OPEN"

        # Wait for recovery window
        time.sleep(0.15)

        # Probe succeeds twice → CLOSED
        with cb:
            pass  # probe 1
        if cb.state != "CLOSED":
            with cb:
                pass  # probe 2
        assert cb.state == "CLOSED"

        # Normal operation resumes
        with cb:
            result = 42
        assert result == 42

    def test_retry_with_circuit_breaker_integration(self):
        """Full integration: retry + circuit breaker working together.

        With failure_threshold=2 and retries=5: the first 2 attempts fail,
        the breaker opens, then attempt 3 hits the open breaker and raises
        CircuitBreakerOpen. After that, a fresh call also fast-fails.
        """
        from system_health.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
        from utils.retry import retry_api_call

        cb = CircuitBreaker("integration_test_v2", failure_threshold=2, recovery_timeout=999)
        cb.reset()
        sleep_calls: List[float] = []
        call_count = 0

        @retry_api_call(retries=5, delay=0.01, backoff=2.0, jitter=False, breaker=cb)
        def unstable_api():
            nonlocal call_count
            call_count += 1
            raise ConnectionResetError("network")

        with patch("utils.retry.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            # First outer call: 2 real attempts open the breaker, 3rd attempt
            # raises CircuitBreakerOpen from _pre_call
            with pytest.raises((ConnectionResetError, CircuitBreakerOpen)):
                unstable_api()

        assert cb.state == "OPEN"
        call_count_before_open = call_count

        # Second outer call — circuit is OPEN, fast-fail, no extra calls
        sleep_before = len(sleep_calls)
        with pytest.raises(CircuitBreakerOpen):
            unstable_api()

        assert call_count == call_count_before_open, "Open circuit must not invoke the function"
        assert len(sleep_calls) == sleep_before, "Open circuit must not sleep"


# ---------------------------------------------------------------------------
# API Endpoint Smoke Tests
# ---------------------------------------------------------------------------

class TestAPIEndpoints:
    """Fast smoke tests using TestClient — no real Binance/DB connections."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Prepare a minimal API app for testing with full state isolation."""
        from fastapi.testclient import TestClient
        import api.app as app_module

        # Reset ALL shared state before each test (V15: isolation fix)
        with app_module._state_lock:
            app_module._state.clear()
            app_module._state.update({
                "latest_decision": None,
                "latest_context":  None,
                "paper_engine":    None,
                "journal_v2":      None,
            })

        # Patch journal and bus with mocks
        mock_journal = MagicMock()
        mock_journal.get_performance_summary.return_value = {}
        mock_journal.get_daily_stats.return_value = []
        mock_journal.get_open_trades.return_value = []
        mock_journal.get_explanations.return_value = []
        mock_journal.get_agent_messages.return_value = []
        mock_journal.get_signals.return_value = []
        mock_journal.get_oi_history.return_value = []
        mock_journal.get_funding_history.return_value = []
        mock_journal.get_market_regimes.return_value = []
        mock_journal.get_latest_signal.return_value = None
        mock_journal.get_latest_explanation.return_value = None

        app_module._JOURNAL_INSTANCE = mock_journal
        from events.event_bus import reset_event_bus
        app_module._BUS_INSTANCE = reset_event_bus(persist=False)

        self.client = TestClient(app_module.app, raise_server_exceptions=False)
        yield

        # Teardown: reset state after test
        app_module._JOURNAL_INSTANCE = None
        app_module._BUS_INSTANCE     = None
        with app_module._state_lock:
            app_module._state["paper_engine"] = None

    def test_health_endpoint_returns_200(self):
        r = self.client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "uptime_s" in data["data"]

    def test_system_health_returns_200(self):
        r = self.client.get("/api/system/health")
        assert r.status_code == 200

    def test_system_reconciliation_returns_200(self):
        r = self.client.get("/api/system/reconciliation")
        assert r.status_code == 200

    def test_decision_no_decision_yet(self):
        r = self.client.get("/api/decision")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_signals_endpoint(self):
        r = self.client.get("/api/signals?limit=10")
        assert r.status_code == 200

    def test_journal_endpoint(self):
        r = self.client.get("/api/journal")
        assert r.status_code == 200

    def test_paper_not_running(self):
        r = self.client.get("/api/paper")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is False

    def test_paper_metrics_not_running(self):
        r = self.client.get("/api/paper/metrics")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is False

    def test_events_endpoint(self):
        r = self.client.get("/api/events?limit=20")
        assert r.status_code == 200

    def test_missions_endpoint(self):
        r = self.client.get("/api/missions")
        assert r.status_code == 200

    def test_config_endpoint_no_secrets(self):
        r = self.client.get("/api/config")
        assert r.status_code == 200
        data = r.json()["data"]
        # Must not leak API keys
        assert "BINANCE_API_KEY" not in str(data)
        assert "BINANCE_API_SECRET" not in str(data)

    def test_ml_status_endpoint(self):
        r = self.client.get("/api/ml/status")
        assert r.status_code == 200

    def test_forward_test_endpoint(self):
        r = self.client.get("/api/forward_test")
        assert r.status_code == 200

    def test_command_state_endpoint(self):
        r = self.client.get("/api/command/state")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Recovery Engine Tests
# ---------------------------------------------------------------------------

class TestRecoveryEngine:

    def test_cooldown_prevents_rapid_retries(self):
        from system_health.recovery_engine import RecoveryEngine
        engine = RecoveryEngine()
        sys_ctx = {}

        result1 = engine.attempt_reconnect_data_provider(sys_ctx)
        result2 = engine.attempt_reconnect_data_provider(sys_ctx)

        assert result1 != "skipped_cooldown"  # first call proceeds
        assert result2 == "skipped_cooldown"  # second call blocked by cooldown

    def test_attempt_log_bounded(self):
        from system_health.recovery_engine import RecoveryEngine
        engine = RecoveryEngine()
        # Inject more than 200 log entries directly
        for i in range(250):
            engine._record("test_action", f"target_{i}", "ok")
        log = engine.get_attempt_log(limit=10000)
        assert len(log) <= 200


# ---------------------------------------------------------------------------
# Watchdog Tests
# ---------------------------------------------------------------------------

class TestWatchdog:

    def test_fresh_subsystem_is_dead(self):
        """Watchdog reports DEAD for subsystems that have never beaten."""
        from system_health.watchdog import Watchdog
        from system_health.heartbeat import reset_heartbeat
        reset_heartbeat()
        wd = Watchdog(subsystems={"never_beaten": 10.0})
        snap = wd.snapshot()
        assert snap["subsystems"]["never_beaten"]["status"] == "DEAD"

    def test_recent_heartbeat_is_alive(self):
        from system_health.watchdog import Watchdog
        from system_health.heartbeat import reset_heartbeat
        hb = reset_heartbeat()
        hb.beat("test_sub")
        wd = Watchdog(subsystems={"test_sub": 60.0})
        snap = wd.snapshot()
        assert snap["subsystems"]["test_sub"]["status"] == "ALIVE"

    def test_stale_heartbeat_degraded(self):
        from system_health.watchdog import Watchdog
        from system_health.heartbeat import reset_heartbeat
        import datetime as _dt
        hb = reset_heartbeat()
        # Manually inject a stale timestamp (6 minutes ago)
        stale_time = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=360)
        ).isoformat()
        with hb._lock:
            hb._beats["stale_sub"] = {"timestamp": stale_time, "meta": {}}
        wd = Watchdog(subsystems={"stale_sub": 60.0})
        snap = wd.snapshot()
        assert snap["subsystems"]["stale_sub"]["status"] in ("STALE", "DEAD")


# ---------------------------------------------------------------------------
# WatchdogSupervisor Tests (v16 P0-A / P0-D)
# ---------------------------------------------------------------------------

class TestWatchdogSupervisor:
    """system_health/watchdog.py:WatchdogSupervisor — the active loop that
    was missing per audit finding #5: Watchdog/RecoveryEngine existed but
    nothing polled them autonomously. Covers the exit-trigger logic, the
    startup grace period, the recovery-attempt path, and that the sd_notify
    watchdog is only petted while genuinely healthy."""

    def _make_supervisor(self, **kwargs):
        from system_health.watchdog import WatchdogSupervisor, Watchdog
        from system_health.heartbeat import reset_heartbeat
        reset_heartbeat()
        wd = kwargs.pop("watchdog", None) or Watchdog()
        exit_fn = MagicMock()
        sup = WatchdogSupervisor(
            sys_components={}, watchdog=wd, exit_fn=exit_fn, **kwargs
        )
        return sup, exit_fn

    def _age_beat(self, name: str, seconds_ago: float) -> None:
        """Inject a heartbeat with a timestamp `seconds_ago` in the past —
        same technique as TestWatchdog.test_stale_heartbeat_degraded."""
        import datetime as _dt
        from system_health.heartbeat import get_heartbeat
        hb = get_heartbeat()
        ts = (_dt.datetime.now(_dt.timezone.utc)
              - _dt.timedelta(seconds=seconds_ago)).isoformat()
        with hb._lock:
            hb._beats[name] = {"timestamp": ts, "meta": {}}

    def test_pets_systemd_watchdog_when_healthy(self):
        from system_health.heartbeat import get_heartbeat
        sup, exit_fn = self._make_supervisor()
        get_heartbeat().beat("main_loop")
        get_heartbeat().beat("monitor_loop")
        with patch("utils.systemd_notify.notify_watchdog") as mock_notify:
            sup.tick()
        mock_notify.assert_called_once()
        exit_fn.assert_not_called()

    def test_does_not_exit_during_grace_period_even_if_dead(self):
        """Fresh process, nothing has beaten yet (age_s=None -> DEAD by
        Watchdog's own classification) — must NOT be mistaken for a hang
        within the startup grace period."""
        sup, exit_fn = self._make_supervisor(grace_period_s=120.0)
        with patch("utils.systemd_notify.notify_watchdog"):
            snap = sup.tick()
        assert snap["subsystems"]["main_loop"]["status"] == "DEAD"
        exit_fn.assert_not_called()

    def test_exits_when_main_loop_dead_after_grace_period(self):
        sup, exit_fn = self._make_supervisor(grace_period_s=0.0)
        # monitor_loop alive, main_loop never beaten -> DEAD
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("monitor_loop")
        with patch("utils.systemd_notify.notify_watchdog"), \
             patch("utils.systemd_notify.notify_status"), \
             patch("events.event_bus.get_event_bus"):
            sup.tick()
        exit_fn.assert_called_once_with(1)

    def test_exits_when_monitor_loop_dead_after_grace_period(self):
        sup, exit_fn = self._make_supervisor(grace_period_s=0.0)
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("main_loop")
        # monitor_loop never beaten -> DEAD
        with patch("utils.systemd_notify.notify_watchdog"), \
             patch("utils.systemd_notify.notify_status"), \
             patch("events.event_bus.get_event_bus"):
            sup.tick()
        exit_fn.assert_called_once_with(1)

    def test_does_not_exit_for_non_trigger_subsystems(self):
        """dashboard_api and websocket are DEAD by design in this test
        (never beaten) but must never trigger an exit — see the comment
        block above _EXIT_TRIGGER_SUBSYSTEMS in watchdog.py for why."""
        sup, exit_fn = self._make_supervisor(grace_period_s=0.0)
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("main_loop")
        get_heartbeat().beat("monitor_loop")
        # dashboard_api / websocket left un-beaten -> DEAD, but not triggers
        with patch("utils.systemd_notify.notify_watchdog") as mock_notify:
            sup.tick()
        exit_fn.assert_not_called()
        mock_notify.assert_called_once()

    def test_attempts_recovery_when_trade_manager_stale(self):
        sup, exit_fn = self._make_supervisor(grace_period_s=0.0)
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("main_loop")
        get_heartbeat().beat("monitor_loop")
        # trade_manager interval=120s -> STALE window is (240s, 600s]
        self._age_beat("trade_manager", seconds_ago=300)

        mock_recovery = MagicMock()
        mock_recovery.attempt_reconnect_data_provider.return_value = "ok"
        with patch("utils.systemd_notify.notify_watchdog"), \
             patch("system_health.recovery_engine.get_recovery_engine",
                   return_value=mock_recovery):
            sup.tick()
        mock_recovery.attempt_reconnect_data_provider.assert_called_once_with({})
        exit_fn.assert_not_called()  # STALE (not DEAD) never triggers exit

    def test_tick_is_safe_with_empty_sys_components(self):
        """Must not raise even with no real components wired in (e.g. a
        misconfigured or partial bootstrap)."""
        sup, exit_fn = self._make_supervisor(grace_period_s=120.0)
        with patch("utils.systemd_notify.notify_watchdog"):
            snap = sup.tick()  # should not raise
        assert "overall_status" in snap

    def test_start_stop_real_thread(self):
        """start()/stop() actually spins up and tears down a real daemon
        thread without error (poll interval kept tiny for test speed)."""
        from system_health.heartbeat import get_heartbeat
        sup, exit_fn = self._make_supervisor(
            poll_interval_s=0.05, grace_period_s=120.0
        )
        get_heartbeat().beat("main_loop")
        get_heartbeat().beat("monitor_loop")
        with patch("utils.systemd_notify.notify_watchdog"):
            t = sup.start()
            assert t.is_alive()
            assert t.daemon is True
            time.sleep(0.2)
            sup.stop()
            t.join(timeout=2.0)
        assert not t.is_alive()
        assert sup._tick_count >= 1
        exit_fn.assert_not_called()


# ---------------------------------------------------------------------------
# sd_notify (systemd watchdog/readiness protocol) Tests (v16 P0-D)
# ---------------------------------------------------------------------------

class TestSystemdNotify:

    def test_no_notify_socket_returns_false(self, monkeypatch):
        from utils.systemd_notify import notify
        monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
        assert notify("READY=1") is False

    def test_sends_datagram_to_real_socket(self, tmp_path, monkeypatch):
        import socket as _socket
        from utils.systemd_notify import notify_ready, notify_watchdog, notify_stopping

        sock_path = str(tmp_path / "notify.sock")
        server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM)
        server.bind(sock_path)
        server.settimeout(2.0)
        monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
        try:
            assert notify_ready() is True
            data, _ = server.recvfrom(1024)
            assert data == b"READY=1"

            assert notify_watchdog() is True
            data, _ = server.recvfrom(1024)
            assert data == b"WATCHDOG=1"

            assert notify_stopping() is True
            data, _ = server.recvfrom(1024)
            assert data == b"STOPPING=1"
        finally:
            server.close()

    def test_notify_status_formats_correctly(self, tmp_path, monkeypatch):
        import socket as _socket
        from utils.systemd_notify import notify_status

        sock_path = str(tmp_path / "notify2.sock")
        server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM)
        server.bind(sock_path)
        server.settimeout(2.0)
        monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
        try:
            notify_status("all systems nominal")
            data, _ = server.recvfrom(1024)
            assert data == b"STATUS=all systems nominal"
        finally:
            server.close()

    def test_send_failure_does_not_raise(self, monkeypatch):
        """A NOTIFY_SOCKET pointing at a nonexistent path must fail closed
        (return False), never raise into the caller."""
        from utils.systemd_notify import notify
        monkeypatch.setenv("NOTIFY_SOCKET", "/nonexistent/path/notify.sock")
        assert notify("READY=1") is False
