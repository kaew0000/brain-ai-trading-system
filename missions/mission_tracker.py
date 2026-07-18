"""
missions/mission_tracker.py
==============================
Mission Pipeline (v14 Phase 2.5)

Tracks the lifecycle of every trade idea from signal discovery through to
close, suitable for the future Mission Board Kanban dashboard page.

Lifecycle (forward-only, per spec)
------------------------------------
SIGNAL_FOUND → VALIDATION → RISK_CHECK → EXECUTION → MONITORING → CLOSED

Any stage may transition directly to CLOSED (abort path) — e.g. a mission
blocked at the risk gate goes SIGNAL_FOUND → VALIDATION → CLOSED with a
note explaining why, without ever reaching EXECUTION. This matches real
trading behaviour: most signals never become trades.

Design
------
- Pure stdlib, thread-safe (mirrors events/event_bus.py's proven pattern)
- Bounded store (OrderedDict, maxlen via manual eviction) — old missions
  age out automatically so memory never grows unbounded over weeks of
  uptime
- Every transition is also appended to mission.history, so the full
  lifecycle timeline survives for the Trade Replay Center (Phase 8)

Usage
-----
from missions.mission_tracker import get_mission_tracker

tracker = get_mission_tracker()
mission = tracker.create(symbol="BTCUSDT", direction="LONG", confidence=78.0,
                          meta={"entry_price": 67000.0})
tracker.advance(mission.id, "VALIDATION", note="6/6 agents ran")
tracker.advance(mission.id, "RISK_CHECK", note="risk gate passed")
tracker.advance(mission.id, "EXECUTION", note="order filled",
                 meta_update={"order_id": "12345"})
tracker.advance(mission.id, "MONITORING")
tracker.advance(mission.id, "CLOSED", note="WIN", meta_update={"pnl": 42.50})
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

STAGES = ["SIGNAL_FOUND", "VALIDATION", "RISK_CHECK", "EXECUTION", "MONITORING", "CLOSED"]
_STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}
_CLOSED = "CLOSED"

_MAX_MISSIONS = 1000   # bounded store — oldest missions evicted beyond this


class InvalidTransitionError(ValueError):
    """Raised when advance() is called with an illegal backward stage jump."""


@dataclass
class Mission:
    """A single trade idea tracked through its full lifecycle."""

    id:         str
    symbol:     str
    direction:  str    # "LONG" | "SHORT"
    stage:      str = "SIGNAL_FOUND"
    confidence: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    history:    List[dict] = field(default_factory=list)
    meta:       dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class MissionTracker:
    """
    Thread-safe lifecycle tracker for trade missions.

    One process-wide singleton (see get_mission_tracker()).
    """

    def __init__(self) -> None:
        self._lock:     threading.Lock = threading.Lock()
        self._missions: "OrderedDict[str, Mission]" = OrderedDict()

    def create(
        self,
        symbol:     str,
        direction:  str,
        confidence: float = 0.0,
        meta:       Optional[dict] = None,
    ) -> Mission:
        """Create a new mission at stage=SIGNAL_FOUND. Thread-safe."""
        mission_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        mission = Mission(
            id=mission_id,
            symbol=symbol,
            direction=direction,
            stage="SIGNAL_FOUND",
            confidence=round(float(confidence), 2),
            created_at=now,
            updated_at=now,
            history=[{"stage": "SIGNAL_FOUND", "timestamp": now, "note": "Signal discovered"}],
            meta=dict(meta or {}),
        )
        with self._lock:
            self._missions[mission_id] = mission
            self._evict_if_over_capacity()
        logger.info(f"Mission created: {mission_id} {symbol} {direction} stage=SIGNAL_FOUND")
        return mission

    def advance(
        self,
        mission_id:  str,
        stage:       str,
        note:        str = "",
        meta_update: Optional[dict] = None,
    ) -> Mission:
        """
        Transition a mission to a new stage.

        Rules
        -----
        - Forward-only: new stage index must be > current stage index,
          UNLESS the new stage is CLOSED (always allowed — abort path).
        - Unknown mission_id raises KeyError.
        - Unknown stage name raises ValueError.
        - Illegal backward transition (e.g. EXECUTION → VALIDATION)
          raises InvalidTransitionError.
        """
        if stage not in _STAGE_INDEX:
            raise ValueError(f"Unknown mission stage: {stage!r}. Must be one of {STAGES}")

        with self._lock:
            mission = self._missions.get(mission_id)
            if mission is None:
                raise KeyError(f"Unknown mission_id: {mission_id!r}")

            current_idx = _STAGE_INDEX[mission.stage]
            target_idx  = _STAGE_INDEX[stage]

            if stage != _CLOSED and target_idx <= current_idx:
                raise InvalidTransitionError(
                    f"Mission {mission_id}: illegal transition "
                    f"{mission.stage} → {stage} (backward or no-op; only CLOSED may "
                    f"be reached out of order)"
                )

            now = datetime.now(timezone.utc).isoformat()
            mission.stage = stage
            mission.updated_at = now
            mission.history.append({"stage": stage, "timestamp": now, "note": note})
            if meta_update:
                mission.meta.update(meta_update)

        logger.info(f"Mission {mission_id} → {stage}" + (f" ({note})" if note else ""))
        return mission

    def get(self, mission_id: str) -> Optional[Mission]:
        with self._lock:
            return self._missions.get(mission_id)

    def list(self, stage: Optional[str] = None, limit: int = 50) -> List[dict]:
        """Return missions newest-first, optionally filtered by stage."""
        with self._lock:
            missions = list(self._missions.values())
        missions.reverse()
        if stage:
            missions = [m for m in missions if m.stage == stage]
        return [m.to_dict() for m in missions[:limit]]

    def get_active(self) -> List[dict]:
        """Return all missions not yet CLOSED, newest-first."""
        with self._lock:
            missions = [m for m in self._missions.values() if m.stage != _CLOSED]
        missions.reverse()
        return [m.to_dict() for m in missions]

    def clear(self) -> None:
        with self._lock:
            self._missions.clear()

    def _evict_if_over_capacity(self) -> None:
        """Caller must hold self._lock. Evicts oldest missions beyond _MAX_MISSIONS."""
        while len(self._missions) > _MAX_MISSIONS:
            self._missions.popitem(last=False)


# ── Singleton accessor (mirrors events.event_bus pattern) ─────────────────────

_global_tracker: Optional[MissionTracker] = None
_tracker_lock = threading.Lock()


def get_mission_tracker() -> MissionTracker:
    global _global_tracker
    if _global_tracker is None:
        with _tracker_lock:
            if _global_tracker is None:
                _global_tracker = MissionTracker()
                logger.info("MissionTracker ready")
    return _global_tracker


def reset_mission_tracker() -> MissionTracker:
    """Replace the global singleton (useful in tests)."""
    global _global_tracker
    with _tracker_lock:
        _global_tracker = MissionTracker()
    return _global_tracker
