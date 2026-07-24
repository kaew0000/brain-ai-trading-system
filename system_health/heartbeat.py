"""system_health/heartbeat.py — Per-subsystem liveness pings"""
from __future__ import annotations
import threading
from datetime import datetime, timezone
from utils.logger import get_logger
logger = get_logger(__name__)

class Heartbeat:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._beats: dict[str, dict] = {}

    def beat(self, name: str, meta: dict | None = None) -> None:
        try:
            with self._lock:
                self._beats[name] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "meta": meta or {},
                }
        except Exception as exc:
            logger.debug(f"Heartbeat.beat({name}) failed: {exc}")

    def get(self, name: str) -> dict | None:
        with self._lock:
            b = self._beats.get(name)
            return dict(b) if b else None

    def get_all(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._beats.items()}

    def clear(self) -> None:
        with self._lock:
            self._beats.clear()

_hb: Heartbeat | None = None
_hb_lock = threading.Lock()

def get_heartbeat() -> Heartbeat:
    global _hb
    if _hb is None:
        with _hb_lock:
            if _hb is None:
                _hb = Heartbeat()
    return _hb

def reset_heartbeat() -> Heartbeat:
    global _hb
    with _hb_lock:
        _hb = Heartbeat()
    return _hb
