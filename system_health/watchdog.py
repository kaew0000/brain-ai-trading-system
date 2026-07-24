"""system_health/watchdog.py — Dead-subsystem detection via Heartbeat staleness"""
from __future__ import annotations
import os as _os
import threading
import time as _time
from datetime import datetime, timezone
from utils.logger import get_logger
logger = get_logger(__name__)

DEFAULT_SUBSYSTEMS: dict[str, float] = {
    "main_loop": 90.0,
    "monitor_loop": 60.0,
    "dashboard_api": 30.0,
    "websocket": 15.0,
    "trade_manager": 120.0,
    "mission_tracker": 90.0,
    "telemetry": 30.0,
}
_ALIVE_MUL = 2.0
_STALE_MUL = 5.0

class Watchdog:
    def __init__(self, subsystems: dict[str, float] | None = None) -> None:
        self._lock = threading.Lock()
        self._intervals: dict[str, float] = dict(subsystems or DEFAULT_SUBSYSTEMS)
        logger.info(f"Watchdog ready | subsystems={list(self._intervals.keys())}")

    def register_subsystem(self, name: str, interval_s: float) -> None:
        with self._lock:
            self._intervals[name] = interval_s

    def _classify(self, age_s: float | None, interval_s: float) -> str:
        if age_s is None:
            return "DEAD"
        if age_s <= interval_s * _ALIVE_MUL:
            return "ALIVE"
        if age_s <= interval_s * _STALE_MUL:
            return "STALE"
        return "DEAD"

    def snapshot(self) -> dict:
        try:
            from system_health.heartbeat import get_heartbeat
            beats = get_heartbeat().get_all()
        except Exception as exc:
            logger.debug(f"Watchdog.snapshot heartbeat read failed: {exc}")
            beats = {}

        now = datetime.now(timezone.utc)
        result: dict[str, dict] = {}
        worst = "ALIVE"

        with self._lock:
            intervals = dict(self._intervals)

        for name, interval_s in intervals.items():
            beat = beats.get(name)
            age_s: float | None = None
            last_beat_iso: str | None = None
            if beat:
                try:
                    dt = datetime.fromisoformat(beat["timestamp"])
                    age_s = (now - dt).total_seconds()
                    last_beat_iso = beat["timestamp"]
                except Exception:
                    pass
            status = self._classify(age_s, interval_s)
            result[name] = {
                "status": status, "last_beat": last_beat_iso,
                "age_s": round(age_s, 2) if age_s is not None else None,
                "interval_s": interval_s,
                "meta": beat.get("meta") if beat else None,
            }
            if status == "DEAD":
                worst = "CRITICAL"
            elif status == "STALE" and worst != "CRITICAL":
                worst = "DEGRADED"

        return {"subsystems": result, "overall_status": worst,
                "timestamp": now.isoformat()}

    def is_healthy(self) -> bool:
        return self.snapshot()["overall_status"] == "ALIVE"

_wd: Watchdog | None = None
_wd_lock = threading.Lock()

def get_watchdog() -> Watchdog:
    global _wd
    if _wd is None:
        with _wd_lock:
            if _wd is None:
                _wd = Watchdog()
    return _wd

def reset_watchdog(subsystems: dict[str, float] | None = None) -> Watchdog:
    global _wd
    with _wd_lock:
        _wd = Watchdog(subsystems=subsystems)
    return _wd


# ─────────────────────────────────────────────────────────────────────────────
# WatchdogSupervisor — the active loop Watchdog/Heartbeat/RecoveryEngine were
# missing. Audit finding #5: "both are only invoked when something calls
# them (confirmed: only referenced from api/app.py's /api/system/health and
# /api/system/reconciliation routes). Nothing polls them autonomously and
# takes action if the main loop itself is the thing that's hung."
#
# main.py's scheduler (run_trading_cycle / monitor_open_trades /
# run_position_reconciliation / daily_report) all run from ONE thread via
# the `schedule` library — a hang inside any one of them blocks all the
# others too (finding #4). This supervisor runs on its OWN thread so it
# keeps polling even if that single scheduler thread is completely stuck.
# ─────────────────────────────────────────────────────────────────────────────

# Subsystems whose DEAD status means "the single-threaded scheduler is
# stuck" (they're beaten from inside run_trading_cycle / monitor_open_trades
# respectively, on every successful pass). Deliberately NOT included:
#   - "dashboard_api": beaten exactly once, at bootstrap (main.py
#     build_system()) and never again — it goes DEAD on every run
#     regardless of real health. Treating it as an exit trigger today would
#     force-restart a perfectly healthy process. Needs its own periodic
#     heartbeat before it can be trusted as a liveness signal — tracked as
#     a follow-up in docs/architecture.md, not fixed here.
#   - "websocket": nothing in this codebase calls Heartbeat.beat("websocket",
#     ...) — there is no exchange websocket (Binance access here is REST
#     only, see data/binance_provider.py). This entry is vestigial. Also
#     tracked as a follow-up rather than silently deleted from
#     DEFAULT_SUBSYSTEMS (out of scope for this pass — removing a dashboard-
#     visible key is a separate, reviewable change).
_EXIT_TRIGGER_SUBSYSTEMS = ("main_loop", "monitor_loop")

# Subsystems that, when STALE (not yet DEAD), are worth one lightweight
# proactive recovery attempt — cheap and already rate-limited by
# RecoveryEngine's own 30s cooldown per key, so polling this often is safe.
_RECOVERABLE_SUBSYSTEMS = ("main_loop", "trade_manager")


class WatchdogSupervisor:
    """Background thread that ties Watchdog + Heartbeat + RecoveryEngine +
    systemd's sd_notify watchdog together into one autonomous loop.

    On every poll:
      1. Read Watchdog.snapshot() (fast — reads in-memory heartbeat dict).
      2. For subsystems in _RECOVERABLE_SUBSYSTEMS that are STALE, attempt
         RecoveryEngine.attempt_reconnect_data_provider() — a lightweight
         REST call that may resolve a transient network blip.
      3. If any of _EXIT_TRIGGER_SUBSYSTEMS is DEAD: log critical, publish
         a WATCHDOG_FORCED_EXIT event (journalled + telemetry via the
         event bus), and exit the process cleanly. There is no safe way to
         force a genuinely stuck synchronous call in Python to abandon
         mid-execution without risking corrupted state or leaked
         locks/connections — the production-safe recovery is a clean
         process exit, relying on systemd's `Restart=on-failure` (already
         configured in deployment/systemd/brain_bot.service) to bring up a
         fresh process. This is the design the Phase 1 audit prescribed
         (§5, P0 item 2), not a simplification made here.
      4. Otherwise, pet systemd's watchdog (sd_notify WATCHDOG=1) — but
         ONLY when step 3 didn't fire, so systemd's own WatchdogSec= layer
         is a true independent backstop, not something this supervisor can
         paper over by petting it regardless of state.
    """

    def __init__(
        self,
        sys_components: dict,
        poll_interval_s: float = 5.0,
        grace_period_s: float = 120.0,
        watchdog: Watchdog | None = None,
        exit_fn=None,
    ) -> None:
        self._sys = sys_components
        self._poll_interval_s = poll_interval_s
        self._grace_period_s = grace_period_s
        self._wd = watchdog or get_watchdog()
        self._exit_fn = exit_fn or (lambda code: _os._exit(code))
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_count = 0  # exposed for tests/introspection
        self._started_at = _time.monotonic()

    def start(self) -> threading.Thread:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="watchdog-supervisor"
        )
        self._thread.start()
        logger.info(
            f"WatchdogSupervisor started | poll={self._poll_interval_s}s | "
            f"exit_triggers={_EXIT_TRIGGER_SUBSYSTEMS}"
        )
        return self._thread

    def stop(self) -> None:
        self._stop_evt.set()

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self.tick()
            except Exception as exc:
                logger.error(f"WatchdogSupervisor tick failed: {exc}", exc_info=True)
            self._stop_evt.wait(self._poll_interval_s)

    def tick(self) -> dict:
        """Run one supervision pass. Public + returns the snapshot so tests
        can call it directly without spinning up a real thread."""
        self._tick_count += 1
        snap = self._wd.snapshot()
        subsystems = snap["subsystems"]

        for name in _RECOVERABLE_SUBSYSTEMS:
            if subsystems.get(name, {}).get("status") == "STALE":
                self._attempt_recovery(name)

        in_grace_period = (_time.monotonic() - self._started_at) < self._grace_period_s
        dead_triggers = [] if in_grace_period else [
            name for name in _EXIT_TRIGGER_SUBSYSTEMS
            if subsystems.get(name, {}).get("status") == "DEAD"
        ]
        if dead_triggers:
            self._handle_dead(dead_triggers, snap)
            return snap  # about to exit — don't pet the watchdog

        try:
            from utils.systemd_notify import notify_watchdog
            notify_watchdog()
        except Exception as exc:
            logger.debug(f"notify_watchdog failed: {exc}")

        return snap

    def _attempt_recovery(self, subsystem_name: str) -> None:
        try:
            from system_health.recovery_engine import get_recovery_engine
            result = get_recovery_engine().attempt_reconnect_data_provider(self._sys)
            logger.warning(
                f"WatchdogSupervisor: '{subsystem_name}' STALE — "
                f"attempt_reconnect_data_provider -> {result}"
            )
        except Exception as exc:
            logger.error(
                f"WatchdogSupervisor recovery attempt for '{subsystem_name}' "
                f"failed: {exc}", exc_info=True
            )

    def _handle_dead(self, dead_triggers: list, snap: dict) -> None:
        logger.critical(
            f"WatchdogSupervisor: {dead_triggers} DEAD — single-threaded "
            f"scheduler appears hung. Exiting cleanly so systemd "
            f"(Restart=on-failure) brings up a fresh process. "
            f"Snapshot: {snap}"
        )
        try:
            from utils.systemd_notify import notify_status
            notify_status(f"WATCHDOG: {dead_triggers} dead - restarting")
        except Exception as exc:
            logger.debug(f"notify_status failed: {exc}")
        try:
            from events.event_bus import get_event_bus
            get_event_bus().publish(
                "SYSTEM_HEALTH", "WATCHDOG_FORCED_EXIT",
                f"Subsystems dead, forcing restart: {dead_triggers}",
                severity="critical", payload=snap,
            )
        except Exception as exc:
            logger.debug(f"WATCHDOG_FORCED_EXIT publish failed: {exc}")
        self._exit_fn(1)


def start_watchdog_supervisor(
    sys_components: dict, poll_interval_s: float = 5.0
) -> WatchdogSupervisor:
    supervisor = WatchdogSupervisor(sys_components, poll_interval_s=poll_interval_s)
    supervisor.start()
    return supervisor
