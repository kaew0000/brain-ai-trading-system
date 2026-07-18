"""
utils/retry.py — Retry decorator with exponential backoff + jitter (V15)

V14 bugs fixed
--------------
BUG-V15-RETRY-01: backoff parameter defaulted to 1.0 — no actual exponential
  growth; all retries fired with constant delay.
  Fix: Default changed to 2.0; delay scales as delay * 2^(attempt-1).

BUG-V15-RETRY-02: No jitter — parallel retry storms when many calls fail
  simultaneously (e.g. Binance rate-limit hit by multiple threads).
  Fix: Added ±25% random jitter to each sleep interval.

BUG-V15-RETRY-03: No max_delay cap — on high backoff values the final
  attempt could sleep for minutes.
  Fix: max_delay parameter (default 60s).

BUG-V15-RETRY-04: No request timeout — if the underlying TCP connection
  hangs, the retry logic is never reached.
  Fix: Callers should pass timeout=10 to requests; documented here.

New: circuit_breaker integration — pass breaker=get_breaker("name") to
  wrap the entire function inside the circuit breaker on each attempt.
"""

from __future__ import annotations

import functools
import random
import time
from typing import Callable, Optional, TypeVar

from requests.exceptions import ConnectionError as ReqConnectionError, Timeout
from binance.error import ClientError

from utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable)

_RETRYABLE_EXCEPTIONS = (ReqConnectionError, Timeout, ConnectionResetError, OSError)

# Binance error codes that are transient (V15: expanded set)
_RETRYABLE_CODES = {
    -1007,   # Timeout waiting for response from backend
    -1021,   # Timestamp outside recvWindow (clock drift)
    -1015,   # Too many requests (rate limit)
}


def _is_retryable_client_error(exc: ClientError) -> bool:
    status     = getattr(exc, "status_code", None)
    error_code = getattr(exc, "error_code",  None)

    if error_code in _RETRYABLE_CODES:
        return True
    if status == 408:
        return True
    if status is None:
        return True
    return status == 429 or status >= 500


# Public alias — V16: execution/trade_manager.py needs this same
# classification to decide whether to re-raise a ClientError it caught
# internally (so @retry_api_call actually gets a chance to retry it)
# instead of duplicating the rate-limit/5xx code list a second time.
is_retryable_client_error = _is_retryable_client_error


def _jitter(delay: float, jitter_factor: float = 0.25) -> float:
    """Add ±jitter_factor random spread to avoid retry thundering herds."""
    spread = delay * jitter_factor
    return delay + random.uniform(-spread, spread)


def retry_api_call(
    retries:   int            = 3,
    delay:     float          = 2.0,
    backoff:   float          = 2.0,   # V15: was 1.0 — now truly exponential
    max_delay: float          = 60.0,  # V15: new cap
    jitter:    bool           = True,  # V15: new
    breaker                   = None,  # optional CircuitBreaker instance
):
    """
    Decorator factory.

    Retries up to `retries` times with exponential backoff:
        sleep_time = min(delay × backoff^(attempt-1), max_delay)
        with ±25% jitter if jitter=True

    Parameters
    ----------
    retries   : Max retry attempts (default 3).
    delay     : Initial sleep before first retry in seconds (default 2.0).
    backoff   : Exponential factor; 2.0 means 2s → 4s → 8s (default 2.0).
    max_delay : Cap on any single sleep duration (default 60s).
    jitter    : Add ±25% random spread to prevent thundering herds (default True).
    breaker   : Optional CircuitBreaker; if OPEN, raises CircuitBreakerOpen
                immediately without consuming a retry attempt.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from system_health.circuit_breaker import CircuitBreakerOpen

            last_exc: Optional[Exception] = None

            for attempt in range(1, retries + 1):
                # Circuit breaker check (fast-fail without sleeping)
                if breaker is not None:
                    try:
                        breaker._pre_call()
                    except CircuitBreakerOpen:
                        raise

                try:
                    result = func(*args, **kwargs)
                    # Record success with circuit breaker
                    if breaker is not None:
                        breaker._on_success()
                    return result

                except _RETRYABLE_EXCEPTIONS as exc:
                    last_exc = exc
                    if breaker is not None:
                        breaker._on_failure(str(exc))

                except ClientError as exc:
                    if not _is_retryable_client_error(exc):
                        if breaker is not None:
                            breaker._on_failure(str(exc))
                        raise
                    last_exc = exc
                    if breaker is not None:
                        breaker._on_failure(str(exc))

                if attempt < retries:
                    raw_wait = min(delay * (backoff ** (attempt - 1)), max_delay)
                    wait = _jitter(raw_wait) if jitter else raw_wait
                    logger.warning(
                        f"{func.__name__}: attempt {attempt}/{retries} failed "
                        f"({last_exc!r}) — retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"{func.__name__}: all {retries} attempts failed ({last_exc!r})"
                    )

            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
