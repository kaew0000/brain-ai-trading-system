"""world/workspace/operations_dashboard.py — Phase W12, Feature 3.

Top-strip summary. Every field comes from `WorldState` — this module
never imports Track A.

**Documented gap, not papered over** (same discipline Phase W11's own
SEPARATION_POLICY amendment used for the event->room mapping): no
verified Track B-visible signal distinguishes Paper vs. Live trading
mode. `world.runtime`'s `engineStatus` vocabulary (idle/active/
recovering/halted) doesn't encode it either. `mode` is therefore
`"emergency"` when `engine_status` is `halted`/`recovering` (a real,
meaningful signal), and `"unknown"` otherwise — never a guessed
paper/live label. A verified accessor for this would be a natural
addition to a future telemetry export.
"""

from world.runtime.models import WorldState
from world.workspace.models import OperationsSummary

_EMERGENCY_STATUSES = frozenset({"halted", "recovering"})


def _telemetry(state: WorldState, *needles: str) -> float | None:
    needles_lower = [n.lower() for n in needles]
    for t in state.telemetry:
        name_lower = t.name.lower()
        if all(n in name_lower for n in needles_lower):
            return t.value
    return None


def build_operations_summary(state: WorldState) -> OperationsSummary:
    mode = "emergency" if state.engine_status in _EMERGENCY_STATUSES else "unknown"
    account_equity = None  # no verified Track B-visible accessor yet — see module docstring
    drawdown = state.portfolio_summary.drawdown if state.portfolio_summary else None
    active_missions = sum(1 for m in state.missions if m.status == "active")
    heartbeat_ages = [t.value for t in state.telemetry if t.name.startswith("heartbeat.") and t.name.endswith(".age_s")]
    exchange_connected = any(t.name.startswith("heartbeat.") for t in state.telemetry)

    return OperationsSummary(
        mode=mode,
        engine_status=state.engine_status,
        account_equity=account_equity,
        drawdown=drawdown,
        active_mission_count=active_missions,
        exchange_connected=exchange_connected,
        heartbeat_age_s=min(heartbeat_ages) if heartbeat_ages else None,
        cpu_percent=_telemetry(state, "cpu_percent"),
        ram_percent=_telemetry(state, "ram_percent"),
        clock=state.captured_at,
        # Phase W13-1/W13-4 — additive, sourced from the new
        # WorldState.orders/.reconciliation fields; both simply
        # empty/None when orders.json has no data yet, never fabricated.
        active_orders_count=len(state.orders),
        reconciliation_last_result=state.reconciliation.last_result if state.reconciliation else None,
        reconciliation_event_count=state.reconciliation.event_count if state.reconciliation else None,
    )
