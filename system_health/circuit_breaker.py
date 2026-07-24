"""
system_health/circuit_breaker.py — Circuit Breaker pattern (V15)

Prevents cascading failures when external services (Binance API, DB) are
unavailable. Transitions between CLOSED → OPEN → HALF_OPEN states.

States
------
CLOSED     : Normal operation. Failures are counted.
OPEN       : Service is failing. Calls are rejected immediately (fast-fail).
HALF_OPEN  : Recovery probe. One call is allowed through to test recovery.

Usage
-----
    cb = CircuitBreaker("binance_market", failure_threshold=5, recovery_timeout=60)

    try:
        with cb:
            result = api_call()
    except CircuitBreakerOpen:
        # Fast-fail path — don't wait for timeout
        use_cached_or_skip()
    except Exception as exc:
        # Real API error — breaker has already recorded it
        handle_error(exc)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)


class BreakerState(str, Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpen(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name        = name
        self.retry_after = retry_after  # seconds until HALF_OPEN probe allowed
        super().__init__(
            f"Circuit '{name}' is OPEN — retry in {retry_after:.1f}s"
        )


@dataclass
class BreakerSnapshot:
    name:             str
    state:            str
    failure_count:    int
    success_count:    int
    last_failure:     str | None
    last_state_change: str
    recovery_in_s:    float | None


class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    Parameters
    ----------
    name              : Human-readable label (logged, shown in /api/system/health).
    failure_threshold : Consecutive failures before opening (default: 5).
    recovery_timeout  : Seconds in OPEN before allowing a probe (default: 60).
    success_threshold : Consecutive successes in HALF_OPEN to re-close (default: 2).
    """

    def __init__(
        self,
        name:              str,
        failure_threshold: int   = 5,
        recovery_timeout:  float = 60.0,
        success_threshold: int   = 2,
    ) -> None:
        self.name              = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout  = recovery_timeout
        self._success_threshold = success_threshold

        self._lock             = threading.Lock()
        self._state            = BreakerState.CLOSED
        self._failure_count    = 0
        self._success_count    = 0
        self._last_failure_at: float | None = None
        self._state_changed_at = time.monotonic()
        self._last_failure_msg: str | None  = None

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> CircuitBreaker:
        self._pre_call()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        del exc_tb  # required by context-manager protocol, unused here
        if exc_type is None:
            self._on_success()
        elif exc_type is not CircuitBreakerOpen:
            self._on_failure(str(exc_val))
        return False  # never suppress exceptions

    # ── Call-wrapper API (alternative to context manager) ─────────────────────

    def call(self, fn, *args, **kwargs):
        """Execute fn(*args, **kwargs) through the breaker."""
        with self:
            return fn(*args, **kwargs)

    # ── State transitions ─────────────────────────────────────────────────────

    def _pre_call(self) -> None:
        with self._lock:
            if self._state == BreakerState.OPEN:
                elapsed = time.monotonic() - (self._last_failure_at or 0)
                if elapsed < self._recovery_timeout:
                    retry_after = self._recovery_timeout - elapsed
                    raise CircuitBreakerOpen(self.name, retry_after)
                # Recovery window reached → probe
                self._state = BreakerState.HALF_OPEN
                self._success_count = 0
                self._state_changed_at = time.monotonic()
                logger.info(f"CircuitBreaker '{self.name}': OPEN → HALF_OPEN (probe)")

    def _on_success(self) -> None:
        with self._lock:
            if self._state == BreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state         = BreakerState.CLOSED
                    self._failure_count = 0
                    self._state_changed_at = time.monotonic()
                    logger.info(
                        f"CircuitBreaker '{self.name}': HALF_OPEN → CLOSED (recovered)"
                    )
            elif self._state == BreakerState.CLOSED:
                self._failure_count = 0  # reset rolling window

    def _on_failure(self, msg: str) -> None:
        with self._lock:
            self._failure_count  += 1
            self._last_failure_at = time.monotonic()
            self._last_failure_msg = msg

            if self._state == BreakerState.HALF_OPEN:
                # Probe failed → back to OPEN
                self._state = BreakerState.OPEN
                self._success_count = 0
                self._state_changed_at = time.monotonic()
                logger.warning(
                    f"CircuitBreaker '{self.name}': HALF_OPEN → OPEN (probe failed: {msg})"
                )
            elif (
                self._state == BreakerState.CLOSED
                and self._failure_count >= self._failure_threshold
            ):
                self._state = BreakerState.OPEN
                self._state_changed_at = time.monotonic()
                logger.error(
                    f"CircuitBreaker '{self.name}': CLOSED → OPEN "
                    f"({self._failure_count} failures; last: {msg})"
                )

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._state == BreakerState.OPEN

    @property
    def state(self) -> str:
        with self._lock:
            return self._state.value

    def snapshot(self) -> dict:
        with self._lock:
            now = datetime.now(timezone.utc)
            recovery_in: float | None = None
            if self._state == BreakerState.OPEN and self._last_failure_at:
                elapsed = time.monotonic() - self._last_failure_at
                remaining = self._recovery_timeout - elapsed
                recovery_in = round(max(0.0, remaining), 1)
            age = time.monotonic() - self._state_changed_at
            return {
                "name":              self.name,
                "state":             self._state.value,
                "failure_count":     self._failure_count,
                "success_count":     self._success_count,
                "last_failure":      self._last_failure_msg,
                "state_age_s":       round(age, 1),
                "recovery_in_s":     recovery_in,
                "timestamp":         now.isoformat(),
            }

    def reset(self) -> None:
        """Manually reset to CLOSED (for admin / recovery scripts)."""
        with self._lock:
            self._state         = BreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._state_changed_at = time.monotonic()
            logger.info(f"CircuitBreaker '{self.name}': manually RESET to CLOSED")


# ── Global registry ───────────────────────────────────────────────────────────

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name:              str,
    failure_threshold: int   = 5,
    recovery_timeout:  float = 60.0,
    success_threshold: int   = 2,
) -> CircuitBreaker:
    """
    Return (or create) a named circuit breaker from the global registry.
    Thread-safe — subsequent calls with the same name return the same instance.
    """
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                success_threshold=success_threshold,
            )
        return _registry[name]


def all_snapshots() -> dict[str, dict]:
    """Return snapshots for all registered circuit breakers."""
    with _registry_lock:
        breakers = list(_registry.values())
    return {cb.name: cb.snapshot() for cb in breakers}
