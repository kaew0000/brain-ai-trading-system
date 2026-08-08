"""telemetry/world_export.py — Phase W11 Track A -> World bridge.

Purely additive, read-only, one-way. Calls ONLY existing, already-
tested Track A accessors and writes their output as plain JSON into a
staging directory (`world/data/runtime_input/` by default) that
`world/readers/*.py`'s `JSONFileSource` instances then read exactly
like any other file source — this module never imports anything from
`world/`, and never writes into `world/data/runtime/` itself (that
directory remains `RuntimeManager`'s/`SnapshotBuilder`'s exclusively).

Every accessor used here, and exactly where it lives, was confirmed by
reading the source before this file was written (see
docs/architecture/SEPARATION_POLICY.md "Phase W11 amendment" and
world/docs/LIVE_OPERATIONS_CENTER.md for the full inventory + data-flow
diagram):

  - telemetry.agent_telemetry.get_telemetry_registry().snapshot()
  - system_health.heartbeat.get_heartbeat().get_all()
  - system_health.circuit_breaker.all_snapshots()
  - missions.mission_tracker.get_mission_tracker().get_active()
  - portfolio.portfolio_history.get_latest_decisions(limit=1)
  - a provided journal_v2.TradeJournalV2 instance's .get_daily_stats()
    and .get_trades()
  - events.event_bus.get_event_bus().get_recent()
  - psutil, for CPU/RAM only (the one genuinely new data source)

Nothing here recomputes anything the trading engine already computes.
RuntimeManager (Phase W4), which reads what this module writes, only
ever exports snapshots — it has no path back into any Track A module
and cannot influence a trading decision.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_THIS_DIR)
DEFAULT_STAGING_DIR = os.path.join(REPO_ROOT, "world", "data", "runtime_input")

# events/event_bus.py publishers use real subsystem names (SMC_ANALYST,
# RISK_MANAGER, CONFIDENCE_ENGINE, BRAIN_BOT, ...) that do NOT
# correspond to the Phase W1 district "assignedAgents" codename scheme
# (PRIMUS, FORGE, BASTION, ...) - confirmed during W11 investigation;
# no mapping between the two schemes exists anywhere in the codebase.
# Building one is out of scope for this bundle (see the W11 report's
# "Known Gaps" section). Every bus-sourced event is placed in this one
# neutral, always-valid district rather than a guessed per-agent room;
# the real publishing agent name is preserved as-is in the "agent"
# field, so notifications/timeline still label it correctly.
_EVENT_FALLBACK_DISTRICT = "command-hall"

# events/event_bus.py's BusEvent.severity vocabulary (debug/info/
# warning/error - see EventBus.publish()'s _log() level selection) does
# not exactly match world/readers/event_reader.py's VALID_SEVERITIES
# (info/success/warning/critical). This is the one explicit translation
# between the two, read from both sources before writing it - never a
# guess. Any value not listed here defaults to "info" (safe, never
# silently dropped).
_SEVERITY_MAP = {
    "debug": "info",
    "info": "info",
    "warning": "warning",
    "error": "critical",
}

# missions/mission_tracker.py's Mission.stage vocabulary (SIGNAL_FOUND
# / VALIDATION / RISK_CHECK / EXECUTION / MONITORING / CLOSED) does not
# match world/readers/mission_reader.py's VALID_STATUSES (proposed /
# active / complete / aborted). get_active() already excludes CLOSED,
# so only the first five ever need mapping here; SIGNAL_FOUND is the
# only stage that isn't yet an active effort, so it maps to "proposed"
# and everything else maps to "active" - a deliberate simplification,
# documented rather than silently guessed.
_STAGE_TO_STATUS = {
    "SIGNAL_FOUND": "proposed",
    "VALIDATION": "active",
    "RISK_CHECK": "active",
    "EXECUTION": "active",
    "MONITORING": "active",
}

# Real district ids (world/districts/definitions/*.json) chosen for
# each mission stage by what that stage represents, not guessed:
# research/validation work -> research-district, the risk gate ->
# risk-fortress, execution/monitoring -> execution-forge (Trading
# Floor).
_STAGE_TO_DISTRICT = {
    "SIGNAL_FOUND": "research-district",
    "VALIDATION": "research-district",
    "RISK_CHECK": "risk-fortress",
    "EXECUTION": "execution-forge",
    "MONITORING": "execution-forge",
}


def _safe(fn, default, label: str):
    """Call fn() and return its result, or `default` (logged at debug
    level only) on any exception. Every accessor this module calls is
    already documented read-only/side-effect-free; this just makes
    sure a problem in *one* of them (stale registry, closed DB handle,
    empty table, psutil unavailable, etc.) can never stop the others
    from exporting — matches world.adapter.adapter's own "a missing
    source is fine, not fatal" convention."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        logger.debug(f"world_export: {label} unavailable this capture: {exc}")
        return default


# ── Individual accessors ────────────────────────────────────────────────────

def _agent_telemetry_rows() -> list[dict[str, Any]]:
    from telemetry.agent_telemetry import get_telemetry_registry

    rows: list[dict[str, Any]] = []
    for agent, data in get_telemetry_registry().snapshot().items():
        rows.append({
            "name": f"{agent}.latency_ms", "value": data.get("latency_ms", 0.0),
            "unit": "ms", "district": "",
        })
        rows.append({
            "name": f"{agent}.confidence", "value": data.get("confidence", 0.0),
            "unit": "%", "district": "",
        })
    return rows


def _heartbeat_rows() -> list[dict[str, Any]]:
    from system_health.heartbeat import get_heartbeat

    rows: list[dict[str, Any]] = []
    now = time.time()
    for name, beat in get_heartbeat().get_all().items():
        ts = beat.get("timestamp")
        age_s = None
        if ts:
            try:
                from datetime import datetime
                age_s = round(now - datetime.fromisoformat(ts).timestamp(), 1)
            except (ValueError, TypeError):
                age_s = None
        if age_s is not None:
            rows.append({
                "name": f"heartbeat.{name}.age_s", "value": age_s,
                "unit": "s", "district": "",
            })
    return rows


def _breaker_rows() -> list[dict[str, Any]]:
    from system_health.circuit_breaker import all_snapshots

    rows: list[dict[str, Any]] = []
    for name, snap in all_snapshots().items():
        latency = snap.get("last_latency_ms")
        if latency is not None:
            rows.append({
                "name": f"breaker.{name}.latency_ms", "value": latency,
                "unit": "ms", "district": "",
            })
        rows.append({
            "name": f"breaker.{name}.failure_count", "value": snap.get("failure_count", 0),
            "unit": "count", "district": "",
        })
    return rows


def _system_resource_rows() -> list[dict[str, Any]]:
    """The one genuinely new data source added by Phase W11 — CPU/RAM
    via psutil. Never touches trading logic; a missing/failing psutil
    call is handled by the _safe() wrapper around this whole
    function, same as every other source."""
    import psutil

    return [
        {"name": "system.cpu_percent", "value": psutil.cpu_percent(interval=None), "unit": "%", "district": "data-center"},
        {"name": "system.ram_percent", "value": psutil.virtual_memory().percent, "unit": "%", "district": "data-center"},
    ]


def telemetry_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows += _safe(_agent_telemetry_rows, [], "agent telemetry")
    rows += _safe(_heartbeat_rows, [], "heartbeat")
    rows += _safe(_breaker_rows, [], "circuit breaker latency")
    rows += _safe(_system_resource_rows, [], "CPU/RAM (psutil)")
    return rows


def event_rows(limit: int = 100) -> list[dict[str, Any]]:
    from events.event_bus import get_event_bus

    def _load() -> list[dict[str, Any]]:
        out = []
        for e in get_event_bus().get_recent(limit=limit):
            out.append({
                "id": str(e.get("seq", e.get("timestamp", ""))),
                "timestamp": str(e.get("timestamp", "")),
                "type": str(e.get("event", "")),
                "district": _EVENT_FALLBACK_DISTRICT,
                "severity": _SEVERITY_MAP.get(str(e.get("severity", "info")), "info"),
                "agent": str(e.get("agent", "")),
                "message": str(e.get("message", "")),
            })
        return out

    return _safe(_load, [], "events (EventBus)")


def mission_rows() -> list[dict[str, Any]]:
    from missions.mission_tracker import get_mission_tracker

    def _load() -> list[dict[str, Any]]:
        out = []
        for m in get_mission_tracker().get_active():
            stage = str(m.get("stage", "SIGNAL_FOUND"))
            status = _STAGE_TO_STATUS.get(stage, "active")
            district = _STAGE_TO_DISTRICT.get(stage, "execution-forge")
            out.append({
                "id": str(m.get("id", "")),
                "title": f"{m.get('direction', '')} {m.get('symbol', '')}".strip(),
                "district": district,
                "status": status,
                "description": f"{stage.replace('_', ' ').title()} — confidence {float(m.get('confidence', 0.0)):.0f}%",
            })
        return out

    return _safe(_load, [], "missions")


def portfolio_payload(journal=None) -> dict[str, Any]:
    """Positions list is deliberately left empty — no verified
    read-only accessor for the trading engine's currently-open
    exchange positions was found during W11 investigation (see the
    W11 report's "Known Gaps"). The `summary` object below is real:
    drawdown/capital figures come from
    portfolio.portfolio_history.get_latest_decisions(), PnL/win-rate
    from the injected journal's get_daily_stats() — Phase W11
    amendment, docs/architecture/SEPARATION_POLICY.md."""

    def _load() -> dict[str, Any]:
        summary: dict[str, Any] = {}

        from portfolio.portfolio_history import get_latest_decisions
        decisions = get_latest_decisions(limit=1)
        if decisions:
            d = decisions[0]
            if d.get("drawdown") is not None:
                summary["drawdown"] = d["drawdown"]

        if journal is not None:
            stats = journal.get_daily_stats()
            if stats.get("total_trades", 0) > 0:
                summary["winRate"] = stats.get("win_rate")
                summary["dailyPnl"] = stats.get("total_pnl")
                summary["avgRr"] = stats.get("avg_rr")

        payload: dict[str, Any] = {"positions": []}
        if summary:
            payload["summary"] = summary
        return payload

    return _safe(_load, {"positions": []}, "portfolio (drawdown/PnL/win-rate)")


def orders_payload(order_timeline=None, reconciliation_engine=None) -> dict[str, Any]:
    """Phase W13-1. `order_timeline` should be the trading engine's
    already-constructed execution.order_timeline.OrderTimeline
    instance (main.py's components["order_timeline"]);
    `reconciliation_engine` similarly components["reconciliation_engine"].
    Both optional — omitted, "states" is simply empty and
    "reconciliation" is simply absent, never fabricated.

    Calls ONLY OrderTimeline.current_state() (no symbol arg -> every
    symbol's last-known composite state) and
    ReconciliationEngine.status() — both already-existing, already-
    tested, read-only accessors (see module docstring). Never calls
    OrderTimeline.run_once(), any refresh(force=True), any exchange
    API directly, or any recovery action — this function is the only
    place in world/ or telemetry/world_export.py that imports either
    class, and it only ever reads."""

    def _load() -> dict[str, Any]:
        states: list[dict[str, Any]] = []
        if order_timeline is not None:
            states = order_timeline.current_state()

        payload: dict[str, Any] = {"states": states}

        if reconciliation_engine is not None:
            status = reconciliation_engine.status()
            reconciliation: dict[str, Any] = {}
            if status.get("last_run") is not None:
                reconciliation["lastRun"] = status["last_run"]
            if status.get("last_result") is not None:
                reconciliation["lastResult"] = status["last_result"]
            if status.get("event_count") is not None:
                reconciliation["eventCount"] = status["event_count"]
            if status.get("suppressed_repeat_count") is not None:
                reconciliation["suppressedRepeatCount"] = status["suppressed_repeat_count"]
            if reconciliation:
                payload["reconciliation"] = reconciliation

        return payload

    return _safe(_load, {"states": []}, "orders (OrderTimeline/ReconciliationEngine)")


# ── Top-level entry point ───────────────────────────────────────────────────

def _write(staging_dir: str, filename: str, content: Any) -> None:
    path = os.path.join(staging_dir, filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(content, f)
    os.replace(tmp_path, path)  # atomic on POSIX — never a half-written file


def export_snapshot(
    *,
    journal=None,
    order_timeline=None,
    reconciliation_engine=None,
    staging_dir: str = DEFAULT_STAGING_DIR,
) -> str:
    """Capture one Track A -> World snapshot and write it as the raw
    payloads world/readers/*.py's JSONFileSource instances expect, into
    `staging_dir` (created if missing). Returns staging_dir.

    `journal` should be the trading engine's already-constructed
    journal_v2.TradeJournalV2 instance (main.py's
    components["journal_v2"]) if PnL/win-rate figures are wanted;
    omitted, those two fields are simply absent from the summary, not
    fabricated as 0.

    `order_timeline` / `reconciliation_engine` (Phase W13-1) should be
    main.py's components["order_timeline"] /
    components["reconciliation_engine"]; omitted, orders.json simply
    has no states/reconciliation this capture.

    Never raises: every individual source is wrapped in _safe(), and a
    failure writing one file is logged and skipped rather than
    stopping the rest — matches Phase W10's own
    `_tick_world_simulation()` "a World-side problem must never affect
    the trading loop" contract, extended here to "one export source
    failing must never affect the others."""
    os.makedirs(staging_dir, exist_ok=True)

    _write(staging_dir, "telemetry.json", telemetry_rows())
    _write(staging_dir, "events.json", event_rows())
    _write(staging_dir, "missions.json", mission_rows())
    _write(staging_dir, "portfolio.json", portfolio_payload(journal))
    # No verified per-trade read-only accessor with a matching
    # id/timestamp/symbol/action shape was confirmed during W11
    # investigation (see report) — kept as a valid, empty payload so
    # JournalReader never errors, rather than guessing column names.
    _write(staging_dir, "journal.json", [])
    _write(staging_dir, "orders.json", orders_payload(order_timeline, reconciliation_engine))

    return staging_dir
