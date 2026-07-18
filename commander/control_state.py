"""
commander/control_state.py
=============================
Trading Control State (v14 Phase 2.5)

A tiny, thread-safe global flag store that the Commander Interface mutates
and that main.py's trading loop checks. Deliberately minimal — this is
NOT a general settings store, just the two flags the spec's commands
actually need to control:

  paused              : bool            — "pause trader" / "resume trader"
  paper_mode_forced    : Optional[bool]  — "paper mode on" / "paper mode off"

Honesty about paper_mode_forced
---------------------------------
EXECUTION_MODE (paper/testnet/live) is fixed at process startup by
execution_factory.build_execution_engine() — hot-swapping the actual
TradeManager instance at runtime is out of scope here (would require
position reconciliation, credential validation, etc., and is too risky
to bolt on safely).

What "paper mode on" DOES do, safely and honestly: it sets a flag that
main.py's execution step checks BEFORE calling the real trade_manager.
When paper_mode_forced=True, real order placement is skipped even if
EXECUTION_MODE=testnet/live — i.e. it's an emergency safety override,
not a full engine hot-swap. "paper mode off" clears the override and lets
EXECUTION_MODE govern again. This is documented honestly rather than
silently no-op'd or overclaimed.

Usage
-----
from commander.control_state import get_control_state

state = get_control_state()
state.pause()
state.is_paused()              # True
state.set_paper_mode_forced(True)
state.snapshot()               # {"paused": True, "paper_mode_forced": True, "updated_at": "..."}
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ControlSnapshot:
    paused:             bool
    paper_mode_forced:  Optional[bool]
    updated_at:         str

    def to_dict(self) -> dict:
        return asdict(self)


class TradingControlState:
    """Thread-safe global control flags. One process-wide singleton."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._paper_mode_forced: Optional[bool] = None
        self._updated_at = datetime.now(timezone.utc).isoformat()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("TradingControlState: PAUSED")

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("TradingControlState: RESUMED")

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paper_mode_forced(self, value: Optional[bool]) -> None:
        with self._lock:
            self._paper_mode_forced = value
            self._updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"TradingControlState: paper_mode_forced={value}")

    def get_paper_mode_forced(self) -> Optional[bool]:
        with self._lock:
            return self._paper_mode_forced

    def snapshot(self) -> dict:
        with self._lock:
            return ControlSnapshot(
                paused=self._paused,
                paper_mode_forced=self._paper_mode_forced,
                updated_at=self._updated_at,
            ).to_dict()

    def reset(self) -> None:
        with self._lock:
            self._paused = False
            self._paper_mode_forced = None
            self._updated_at = datetime.now(timezone.utc).isoformat()


# ── Singleton accessor (mirrors telemetry/reasoning/mission_tracker pattern) ──

_global_state: Optional[TradingControlState] = None
_state_lock = threading.Lock()


def get_control_state() -> TradingControlState:
    global _global_state
    if _global_state is None:
        with _state_lock:
            if _global_state is None:
                _global_state = TradingControlState()
                logger.info("TradingControlState ready")
    return _global_state


def reset_control_state() -> TradingControlState:
    """Replace the global singleton (useful in tests)."""
    global _global_state
    with _state_lock:
        _global_state = TradingControlState()
    return _global_state
