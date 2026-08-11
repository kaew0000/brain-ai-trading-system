"""
commander/control_state.py
=============================
Trading Control State (v14 Phase 2.5 + W14-0 lifecycle control plane)

A tiny, thread-safe global flag store that the Commander Interface mutates
and that main.py's trading loop checks. Deliberately minimal — this is
NOT a general settings store, just the flags the spec's commands
actually need to control:

  paused              : bool            — "pause trader" / "resume trader"
  paper_mode_forced    : Optional[bool]  — "paper mode on" / "paper mode off"
  lifecycle_state       : str            — "start bot" / "stop bot" (W14-0)

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

W14-0 — lifecycle_state
---------------------------------
This is a SEPARATE, independent gate from `paused`. It does not replace,
rename, or get merged with the existing pause/resume flag — see this
module's own docstring in the class body and api/app.py's command
handler for the full pause-vs-stop hierarchy. Summary: `lifecycle_state`
is the OUTER gate (no trade execution at all unless RUNNING); `paused`
is a SOFT gate that only matters once lifecycle_state == RUNNING.

Legal states: STOPPED, STARTING, RUNNING, STOPPING, FAILED.
Legal transitions (enforced by _apply_transition, nothing else mutates
_lifecycle_state):

    STOPPED  -> STARTING
    STARTING -> RUNNING | FAILED | STOPPING
    RUNNING  -> STOPPING
    STOPPING -> STOPPED | FAILED
    FAILED   -> STARTING

This process is single-process/in-process (see main.py) — there is no
separate bot process to spawn or kill. "STARTING"/"STOPPING" exist as
real, testable states in this state machine, but start()/stop() resolve
them synchronously today because there is no actual async
initialization/shutdown work to await yet. The transient states remain
meaningful for: (a) tests that simulate a slower future init/shutdown
path via the low-level mark_*() primitives, and (b) the STOPPING window
during which an in-flight trading cycle is allowed to finish rather than
being interrupted (see main.py's run_trading_cycle() gate).

lifecycle_state ALWAYS initializes to STOPPED — including after a
process restart/crash. Nothing in this module persists it to disk, and
nothing should ever be added that does; this is a deliberate live-money
safety decision (see PATCH_NOTES.md / W14-0 design report), not an
oversight.

Usage
-----
from commander.control_state import get_control_state

state = get_control_state()
state.pause()
state.is_paused()              # True
state.set_paper_mode_forced(True)
result = state.start()          # LifecycleTransitionResult
result = state.stop()           # LifecycleTransitionResult
state.snapshot()                # {"paused": ..., "paper_mode_forced": ..., "lifecycle_state": ..., "updated_at": "..."}
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

# ── W14-0 lifecycle state machine ──────────────────────────────────────────

LIFECYCLE_STOPPED  = "STOPPED"
LIFECYCLE_STARTING = "STARTING"
LIFECYCLE_RUNNING  = "RUNNING"
LIFECYCLE_STOPPING = "STOPPING"
LIFECYCLE_FAILED   = "FAILED"

# Single source of truth for legal transitions — _apply_transition() is the
# only place _lifecycle_state is ever written, so this table is the whole
# state machine.
_LEGAL_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    LIFECYCLE_STOPPED:  frozenset({LIFECYCLE_STARTING}),
    LIFECYCLE_STARTING: frozenset({LIFECYCLE_RUNNING, LIFECYCLE_FAILED, LIFECYCLE_STOPPING}),
    LIFECYCLE_RUNNING:  frozenset({LIFECYCLE_STOPPING}),
    LIFECYCLE_STOPPING: frozenset({LIFECYCLE_STOPPED, LIFECYCLE_FAILED}),
    LIFECYCLE_FAILED:   frozenset({LIFECYCLE_STARTING}),
}


@dataclass
class LifecycleTransitionResult:
    """Result of a start()/stop() call — always reports the ACTUAL
    resulting state, never an assumed one (spec §10 — no pretend success).

    accepted : False only for a genuine conflict (e.g. START requested
               while STOPPING) — the caller must not treat this as
               success. True for both "applied a real transition" and
               "idempotent no-op because already in/near the target
               state" — both are legitimate non-error outcomes.
    changed  : True only if a transition actually occurred.
    """
    state:    str
    accepted: bool
    changed:  bool


@dataclass
class ControlSnapshot:
    paused:             bool
    paper_mode_forced:  bool | None
    lifecycle_state:    str
    updated_at:         str

    def to_dict(self) -> dict:
        return asdict(self)


class TradingControlState:
    """Thread-safe global control flags. One process-wide singleton."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._paper_mode_forced: bool | None = None
        self._lifecycle_state: str = LIFECYCLE_STOPPED
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

    def set_paper_mode_forced(self, value: bool | None) -> None:
        with self._lock:
            self._paper_mode_forced = value
            self._updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"TradingControlState: paper_mode_forced={value}")

    def get_paper_mode_forced(self) -> bool | None:
        with self._lock:
            return self._paper_mode_forced

    # ── W14-0 lifecycle state machine ───────────────────────────────────────
    #
    # _apply_transition() is the ONLY method that ever writes
    # self._lifecycle_state. Every other lifecycle method (mark_*(), start(),
    # stop()) goes through it, so the legal-transition table in
    # _LEGAL_LIFECYCLE_TRANSITIONS is the single source of truth — there is
    # no way to reach an illegal state from any code path in this class.

    def lifecycle_state(self) -> str:
        with self._lock:
            return self._lifecycle_state

    def _apply_transition(self, target: str) -> bool:
        """Low-level primitive: apply `target` iff legal from the current
        state. Returns True if applied, False if illegal (current state is
        left untouched — this never raises, matching the rest of this
        module's "log and stay safe" style used for paper_mode checks).
        Caller must hold self._lock.
        """
        current = self._lifecycle_state
        if target not in _LEGAL_LIFECYCLE_TRANSITIONS.get(current, frozenset()):
            logger.warning(
                f"TradingControlState: rejected illegal lifecycle transition "
                f"{current} -> {target}"
            )
            return False
        self._lifecycle_state = target
        self._updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"TradingControlState: lifecycle {current} -> {target}")
        return True

    def mark_starting(self) -> bool:
        """STOPPED|FAILED -> STARTING. Returns True if applied."""
        with self._lock:
            return self._apply_transition(LIFECYCLE_STARTING)

    def mark_running(self) -> bool:
        """STARTING -> RUNNING. Returns True if applied."""
        with self._lock:
            return self._apply_transition(LIFECYCLE_RUNNING)

    def mark_stopping(self) -> bool:
        """RUNNING|STARTING -> STOPPING. Returns True if applied."""
        with self._lock:
            return self._apply_transition(LIFECYCLE_STOPPING)

    def mark_stopped(self) -> bool:
        """STOPPING -> STOPPED. Returns True if applied."""
        with self._lock:
            return self._apply_transition(LIFECYCLE_STOPPED)

    def mark_failed(self) -> bool:
        """STARTING|STOPPING -> FAILED. Returns True if applied."""
        with self._lock:
            return self._apply_transition(LIFECYCLE_FAILED)

    def start(self) -> LifecycleTransitionResult:
        """High-level "start bot" operation — idempotent, concurrency-safe.

        - Already STARTING or RUNNING: no-op, accepted=True, changed=False.
        - Currently STOPPING: rejected — the bot must finish reaching
          STOPPED before it can be started again (accepted=False). The
          caller must NOT treat this as success.
        - STOPPED or FAILED: transitions STARTING -> RUNNING. This resolves
          synchronously today (see module docstring — single-process, no
          real async init step yet), but goes through both states so the
          state machine and its tests stay honest about the model.
        """
        with self._lock:
            current = self._lifecycle_state
            if current in (LIFECYCLE_STARTING, LIFECYCLE_RUNNING):
                return LifecycleTransitionResult(state=current, accepted=True, changed=False)
            if current == LIFECYCLE_STOPPING:
                return LifecycleTransitionResult(state=current, accepted=False, changed=False)
            # current in (STOPPED, FAILED) — the only remaining legal source states
            applied = self._apply_transition(LIFECYCLE_STARTING)
            if not applied:  # pragma: no cover - defensive, table guarantees this succeeds here
                return LifecycleTransitionResult(state=self._lifecycle_state, accepted=False, changed=False)
            self._apply_transition(LIFECYCLE_RUNNING)
            return LifecycleTransitionResult(state=self._lifecycle_state, accepted=True, changed=True)

    def stop(self) -> LifecycleTransitionResult:
        """High-level "stop bot" operation — idempotent, concurrency-safe.

        - Already STOPPING or STOPPED: no-op, accepted=True, changed=False.
        - FAILED: nothing is running to stop — treated as an accepted
          no-op (the trade-execution gate already blocks FAILED same as
          STOPPED; see main.py), state stays FAILED. Use "start bot" to
          retry from FAILED.
        - RUNNING or STARTING: transitions STOPPING -> STOPPED. See
          run_trading_cycle()'s gate for how an in-flight cycle is allowed
          to finish rather than being interrupted mid-execution.
        """
        with self._lock:
            current = self._lifecycle_state
            if current in (LIFECYCLE_STOPPING, LIFECYCLE_STOPPED, LIFECYCLE_FAILED):
                return LifecycleTransitionResult(state=current, accepted=True, changed=False)
            # current in (RUNNING, STARTING) — the only remaining legal source states
            applied = self._apply_transition(LIFECYCLE_STOPPING)
            if not applied:  # pragma: no cover - defensive, table guarantees this succeeds here
                return LifecycleTransitionResult(state=self._lifecycle_state, accepted=False, changed=False)
            self._apply_transition(LIFECYCLE_STOPPED)
            return LifecycleTransitionResult(state=self._lifecycle_state, accepted=True, changed=True)

    def snapshot(self) -> dict:
        with self._lock:
            return ControlSnapshot(
                paused=self._paused,
                paper_mode_forced=self._paper_mode_forced,
                lifecycle_state=self._lifecycle_state,
                updated_at=self._updated_at,
            ).to_dict()

    def reset(self) -> None:
        with self._lock:
            self._paused = False
            self._paper_mode_forced = None
            self._lifecycle_state = LIFECYCLE_STOPPED
            self._updated_at = datetime.now(timezone.utc).isoformat()


# ── Singleton accessor (mirrors telemetry/reasoning/mission_tracker pattern) ──

_global_state: TradingControlState | None = None
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
