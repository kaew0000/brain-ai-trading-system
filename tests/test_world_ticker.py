"""tests/test_world_ticker.py — V16 §82

Dedicated World simulation clock: lifecycle, failure backoff / recovery,
health reporting, the Timeline rolling-window resize it relies on, and the
read-only /api/world/ticker endpoint. No network, no Binance.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from world.simulation import ticker as ticker_module
from world.simulation.engine import SimulationEngine
from world.simulation.ticker import WorldSimulationTicker
from world.simulation.timeline import Timeline

pytestmark = pytest.mark.unit


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


@pytest.fixture(autouse=True)
def _clear_registered_ticker():
    ticker_module.set_ticker(None)
    yield
    ticker_module.set_ticker(None)


class TestConstruction:
    def test_rejects_non_positive_interval(self):
        with pytest.raises(ValueError):
            WorldSimulationTicker(step_fn=lambda: None, interval_seconds=0)
        with pytest.raises(ValueError):
            WorldSimulationTicker(step_fn=lambda: None, interval_seconds=-1)

    def test_rejects_backoff_below_interval(self):
        with pytest.raises(ValueError):
            WorldSimulationTicker(step_fn=lambda: None, interval_seconds=5, max_backoff_seconds=1)


class TestTickOnce:
    def test_success_updates_counters_and_health(self):
        calls = []
        t = WorldSimulationTicker(step_fn=lambda: calls.append(1), interval_seconds=2.0)
        assert t.tick_once() is True
        h = t.health()
        assert calls == [1]
        assert h["tickCount"] == 1
        assert h["consecutiveFailures"] == 0
        assert h["lastTickAt"] is not None
        assert h["lastError"] is None

    def test_failure_is_counted_never_raised(self):
        def boom():
            raise RuntimeError("sim exploded")

        t = WorldSimulationTicker(step_fn=boom, interval_seconds=2.0)
        assert t.tick_once() is False  # must not raise
        h = t.health()
        assert h["failureCount"] == 1
        assert h["consecutiveFailures"] == 1
        assert "sim exploded" in h["lastError"]
        assert h["tickCount"] == 0

    def test_recovery_resets_consecutive_failures(self):
        state = {"fail": True}

        def flaky():
            if state["fail"]:
                raise ValueError("transient")

        t = WorldSimulationTicker(step_fn=flaky, interval_seconds=2.0)
        t.tick_once()
        t.tick_once()
        assert t.health()["consecutiveFailures"] == 2
        state["fail"] = False
        assert t.tick_once() is True
        h = t.health()
        assert h["consecutiveFailures"] == 0
        assert h["failureCount"] == 2  # lifetime total is kept
        assert h["lastError"] is None


class TestBackoff:
    def test_delay_is_interval_when_healthy(self):
        t = WorldSimulationTicker(step_fn=lambda: None, interval_seconds=2.0, max_backoff_seconds=30.0)
        assert t.next_delay() == 2.0

    def test_delay_grows_exponentially_and_is_capped(self):
        def boom():
            raise RuntimeError("x")

        t = WorldSimulationTicker(step_fn=boom, interval_seconds=2.0, max_backoff_seconds=30.0)
        delays = []
        for _ in range(8):
            t.tick_once()
            delays.append(t.next_delay())
        assert delays[0] == 4.0
        assert delays[1] == 8.0
        assert delays == sorted(delays)  # never shrinks while failing
        assert max(delays) == 30.0  # capped


class TestThreadLifecycle:
    def test_runs_periodically_and_stops(self):
        count = {"n": 0}
        t = WorldSimulationTicker(step_fn=lambda: count.__setitem__("n", count["n"] + 1), interval_seconds=0.01)
        assert t.health()["status"] == "stopped"
        t.start()
        try:
            assert _wait_for(lambda: count["n"] >= 5)
            assert t.is_running
            assert t.health()["status"] == "ok"
        finally:
            t.stop()
        assert not t.is_running
        frozen = count["n"]
        time.sleep(0.05)
        assert count["n"] == frozen  # really stopped
        assert t.health()["status"] == "stopped"

    def test_start_is_idempotent(self):
        t = WorldSimulationTicker(step_fn=lambda: None, interval_seconds=0.01)
        t.start()
        try:
            first = t._thread
            t.start()
            assert t._thread is first
            assert sum(1 for th in threading.enumerate() if th.name == "WorldSimulationTicker") == 1
        finally:
            t.stop()

    def test_thread_survives_failures_and_recovers(self):
        state = {"calls": 0}

        def flaky():
            state["calls"] += 1
            if state["calls"] <= 2:
                raise RuntimeError("boom")

        # tiny interval + tiny cap so the test does not wait on real backoff
        t = WorldSimulationTicker(step_fn=flaky, interval_seconds=0.005, max_backoff_seconds=0.02)
        t.start()
        try:
            assert _wait_for(lambda: t.health()["tickCount"] >= 3)
            h = t.health()
            assert h["failureCount"] == 2
            assert h["consecutiveFailures"] == 0
            assert t.is_running
        finally:
            t.stop()

    def test_degraded_status_while_failing(self):
        def boom():
            raise RuntimeError("x")

        t = WorldSimulationTicker(step_fn=boom, interval_seconds=0.005, max_backoff_seconds=0.02)
        t.start()
        try:
            assert _wait_for(lambda: t.health()["status"] == "degraded")
        finally:
            t.stop()

    def test_stalled_status_when_last_tick_is_too_old(self):
        t = WorldSimulationTicker(step_fn=lambda: None, interval_seconds=0.05)
        t.start()
        try:
            assert _wait_for(lambda: t.health()["tickCount"] >= 1)
            t._stop_event.set()  # park the loop without marking the thread stopped yet
            t._thread.join(timeout=2)
            assert not t.is_running
            # emulate "thread alive but no tick for 5+ intervals"
            t._thread = threading.Thread(target=time.sleep, args=(0.5,), daemon=True)
            t._thread.start()
            t._last_tick_monotonic = time.monotonic() - 10 * 0.05
            assert t.health()["status"] == "stalled"
        finally:
            t.stop()


class TestDefaultStepFunction:
    def test_default_step_advances_the_real_simulation(self):
        from world.simulation import api as simulation_api

        before = simulation_api.get_simulation_state().tick.tick_number
        t = WorldSimulationTicker(interval_seconds=2.0)  # step_fn=None -> world.simulation.api.step
        assert t.tick_once() is True
        assert simulation_api.get_simulation_state().tick.tick_number == before + 1


class TestTimelineHistoryWindow:
    def _states(self, n):
        engine = SimulationEngine(history_window=None)
        return [engine.step(force=True) for _ in range(n)]

    def test_shrinking_trims_oldest_and_keeps_cursor_on_latest(self):
        tl = Timeline(history_window=None)
        states = self._states(10)
        for s in states:
            tl.record(s)
        tl.set_history_window(4)
        assert len(tl._records) == 4
        assert tl._records[-1].tick.tick_number == states[-1].tick.tick_number
        assert tl._cursor == 3

    def test_growing_does_not_drop_anything(self):
        tl = Timeline(history_window=3)
        for s in self._states(5):
            tl.record(s)
        assert len(tl._records) == 3
        tl.set_history_window(10)
        assert len(tl._records) == 3

    def test_none_means_unbounded_and_invalid_is_rejected(self):
        tl = Timeline(history_window=2)
        tl.set_history_window(None)
        for s in self._states(6):
            tl.record(s)
        assert len(tl._records) == 6
        with pytest.raises(ValueError):
            tl.set_history_window(0)

    def test_engine_and_api_passthrough(self):
        engine = SimulationEngine(history_window=500)
        engine.set_history_window(3)
        for _ in range(8):
            engine.step(force=True)
        assert len(engine._timeline._records) == 3


class TestTickerEndpoint:
    @pytest.fixture()
    def client(self):
        from api.app import app

        return TestClient(app, raise_server_exceptions=False)

    def test_disabled_when_no_ticker_registered(self, client):
        r = client.get("/api/world/ticker")
        assert r.status_code == 200
        assert r.json()["data"] == {"status": "disabled", "running": False}

    def test_reports_registered_ticker_health(self, client):
        t = WorldSimulationTicker(step_fn=lambda: None, interval_seconds=2.0)
        t.tick_once()
        ticker_module.set_ticker(t)
        r = client.get("/api/world/ticker")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["intervalSeconds"] == 2.0
        assert data["tickCount"] == 1
        assert data["status"] == "stopped"  # registered but its thread was never started


class TestEndToEndWithRealSimulation:
    """Real ticker thread + real simulation + real REST layer (no mocks)."""

    @pytest.fixture(autouse=True)
    def _clean_simulation(self):
        # The shared simulation engine is process-global. Other tests pause or
        # seek its timeline (the renderer follows the timeline cursor, by
        # design), so start from a freshly reset, playing engine.
        from world.simulation import api as simulation_api

        simulation_api.reset()
        simulation_api.resume()
        yield
        simulation_api.reset()

    def test_running_ticker_advances_the_world_and_reports_ok(self):
        from api.app import app
        from world.simulation import api as simulation_api

        client = TestClient(app, raise_server_exceptions=False)
        t = WorldSimulationTicker(interval_seconds=0.02)
        ticker_module.set_ticker(t)
        start_tick = simulation_api.get_simulation_state().tick.tick_number
        t.start()
        try:
            assert _wait_for(lambda: simulation_api.get_simulation_state().tick.tick_number >= start_tick + 5)
            body = client.get("/api/world/ticker").json()["data"]
            assert body["status"] == "ok"
            assert body["running"] is True
            assert body["tickCount"] >= 5
            # the frame endpoint serves the live state the ticker is advancing
            room = client.get("/api/world/rooms").json()["data"][0]["roomId"]
            assert client.get(f"/api/world/rooms/{room}/frame").status_code == 200
        finally:
            t.stop()
        assert client.get("/api/world/ticker").json()["data"]["status"] == "stopped"

    def test_characters_actually_move_between_ticks(self):
        from world.frontend.renderer import api as renderer_api
        from world.simulation import api as simulation_api

        def positions(room_id):
            f = renderer_api.get_render_frame(room_id)
            return {c.entity_id: (c.screen_x, c.screen_y) for c in f.commands if c.layer == "characters"}

        state = simulation_api.get_simulation_state()
        room = next(c.room_id for c in state.characters if c.behavior != "idle")
        seen = [positions(room)]
        for _ in range(12):
            simulation_api.step()
            seen.append(positions(room))
        assert any(a != b for a, b in zip(seen, seen[1:])), "no character moved across 12 ticks"
