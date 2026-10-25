"""world.simulation.ticker — dedicated clock for the World simulation.

Why this exists
---------------
The simulation used to be advanced by a `schedule` job in main.py, once per
trading cycle (`LOOP_INTERVAL`, 60 s by default). Two consequences made the
Office World unusable as a live view: NPCs moved one tiny step a minute, and
because `schedule` runs jobs synchronously on the main thread, a slow trading
cycle froze the world completely while it ran.

`WorldSimulationTicker` advances the simulation on its own daemon thread at a
configurable interval, independent of the trading loop. Real-data ingestion
(the Track A -> World snapshot export) is deliberately NOT moved: it still
runs once per trading cycle, so rooms/agents reflect real system state at the
same cadence as before; only the *animation clock* is faster.

Safety / robustness
-------------------
* Read-only with respect to trading: the only thing it calls is the
  simulation step function (`world.simulation.api.step`), the same function
  the old scheduled job called.
* A failing step never kills the thread: failures are counted, logged
  (rate-limited) and retried with exponential backoff, resetting on the
  first success (automatic recovery).
* `health()` reports status for the dashboard / monitoring. It deliberately
  does not write into the shared `system_health` heartbeat registry: that
  registry feeds `heartbeat_age_s` (min over all heartbeats), and a beat every
  couple of seconds would mask a dead trading loop in that signal.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

# The World package is kept importable on its own (it never imports the
# trading engine), so the project logger is optional: use it when present so
# ticker messages land in the shared log file, otherwise plain stdlib logging.
try:
    from utils.logger import get_logger

    logger = get_logger(__name__)
except Exception:  # pragma: no cover - only when utils/ is unavailable
    logger = logging.getLogger(__name__)

#: Backoff multiplier exponent is capped so a long outage never waits longer
#: than `max_backoff_seconds` between attempts.
_MAX_BACKOFF_EXPONENT = 5
#: Log the first failure, then only every Nth consecutive one (avoid spam).
_FAILURE_LOG_EVERY = 30


class WorldSimulationTicker:
    def __init__(
        self,
        step_fn: Callable[[], object] | None = None,
        interval_seconds: float = 2.0,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")
        if max_backoff_seconds < interval_seconds:
            raise ValueError("max_backoff_seconds must be >= interval_seconds")
        self._step_fn = step_fn
        self._interval = float(interval_seconds)
        self._max_backoff = float(max_backoff_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._tick_count = 0
        self._failure_count = 0
        self._consecutive_failures = 0
        self._last_tick_monotonic: float | None = None
        self._last_tick_at: str | None = None
        self._last_error: str | None = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="WorldSimulationTicker")
        self._thread.start()
        logger.info(f"WorldSimulationTicker started (interval={self._interval}s)")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        logger.info("WorldSimulationTicker stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── one iteration (separate so tests can drive it without a thread) ──

    def tick_once(self) -> bool:
        """Run one step. Returns True on success, False on failure; never raises."""
        step = self._step_fn
        if step is None:
            from world.simulation import api as _simulation_api

            step = _simulation_api.step
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - the clock must survive any step failure
            with self._lock:
                self._failure_count += 1
                self._consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                n = self._consecutive_failures
            if n == 1 or n % _FAILURE_LOG_EVERY == 0:
                logger.warning(f"World simulation tick failed ({n} consecutive): {exc}")
            return False
        with self._lock:
            if self._consecutive_failures:
                logger.info(f"World simulation tick recovered after {self._consecutive_failures} failure(s)")
            self._tick_count += 1
            self._consecutive_failures = 0
            self._last_error = None
            self._last_tick_monotonic = time.monotonic()
            self._last_tick_at = datetime.now(timezone.utc).isoformat()
        return True

    def next_delay(self) -> float:
        """Seconds to wait before the next attempt: the interval normally,
        exponential backoff (capped) while failing."""
        with self._lock:
            failures = self._consecutive_failures
        if failures == 0:
            return self._interval
        return min(self._interval * (2 ** min(failures, _MAX_BACKOFF_EXPONENT)), self._max_backoff)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            self.tick_once()
            remaining = self.next_delay() - (time.monotonic() - started)
            if remaining > 0:
                self._stop_event.wait(remaining)

    # ── monitoring ─────────────────────────────────────────────────────

    def health(self) -> dict:
        with self._lock:
            last = self._last_tick_monotonic
            age = None if last is None else round(time.monotonic() - last, 3)
            consecutive = self._consecutive_failures
            data = {
                "intervalSeconds": self._interval,
                "tickCount": self._tick_count,
                "failureCount": self._failure_count,
                "consecutiveFailures": consecutive,
                "lastTickAt": self._last_tick_at,
                "lastTickAgeSeconds": age,
                "lastError": self._last_error,
            }
        running = self.is_running
        if not running:
            status = "stopped"
        elif consecutive > 0:
            status = "degraded"
        elif age is not None and age > self._interval * 5:
            status = "stalled"
        else:
            status = "ok"
        data["running"] = running
        data["status"] = status
        return data


# ── process-wide registration (read by api/world_api.py) ──────────────────

_ticker: WorldSimulationTicker | None = None


def set_ticker(ticker: WorldSimulationTicker | None) -> None:
    global _ticker
    _ticker = ticker


def get_ticker() -> WorldSimulationTicker | None:
    return _ticker


def get_ticker_health() -> dict:
    """Health of the registered ticker, or a `disabled` placeholder when the
    legacy scheduled tick is in use (WORLD_SIM_TICK_INTERVAL_SECONDS <= 0)."""
    ticker = _ticker
    if ticker is None:
        return {"status": "disabled", "running": False}
    return ticker.health()
