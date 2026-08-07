"""world/workspace/agent_workspace.py — Phase W12, Feature 2.

Seven named panels (CEO/Risk/Execution/Market/Regime/Portfolio/Learning),
mapped onto the stable Phase W1 character/district codenames rather than
Phase W11's dynamically-registered telemetry keys — those keys come from
wherever the trading engine happens to call `agent_telemetry.register()`
at runtime, with no documented, verified mapping to these 7 business
names (the same category of gap Phase W11's own amendment documents for
event->room). Status/behavior comes straight from Phase W7
(`world.simulation.api.get_character_activity`), which is already
reliable regardless of whether telemetry is populated.

`heartbeat_age_s` / `latency_ms` are deliberately best-effort: they scan
`WorldState.telemetry` for a name containing the panel's agent_ref or
room_id, and are `None` (never a fabricated 0) when nothing matches.
"""

from world.runtime.models import WorldState
from world.simulation import api as simulation_api
from world.workspace.models import AgentPanelState

# (panel label, character id, agentRef used in telemetry name matching, room id)
_PANELS = (
    ("CEO", "primus", "PRIMUS", "ceo-tower"),
    ("Risk", "bastion", "BASTION", "risk-fortress"),
    ("Execution", "forge", "FORGE", "execution-forge"),
    ("Market", "watcher", "WATCHER", "market-intelligence-center"),
    ("Regime", "chameleon", "CHAMELEON", "ai-council"),
    ("Portfolio", "gardener", "GARDENER", "portfolio-garden"),
    ("Learning", "oracle", "ORACLE", "research-district"),
)


def _find_telemetry_value(state: WorldState, *needles: str) -> float | None:
    needles_lower = [n.lower() for n in needles]
    for t in state.telemetry:
        name_lower = t.name.lower()
        if all(n in name_lower for n in needles_lower):
            return t.value
    return None


def _last_decision(state: WorldState, room_id: str) -> str | None:
    room_events = [e for e in state.events if e.district == room_id]
    if not room_events:
        return None
    return sorted(room_events, key=lambda e: e.timestamp)[-1].message or None


def _current_task(state: WorldState, room_id: str) -> str | None:
    active = [m for m in state.missions if m.district == room_id and m.status == "active"]
    return active[0].title if active else None


def build_agent_panels(state: WorldState) -> tuple[AgentPanelState, ...]:
    panels = []
    for label, char_id, agent_ref, room_id in _PANELS:
        agent = next((a for a in state.agents if a.agent_id == char_id), None)
        activity = simulation_api.get_character_activity(char_id)
        status = activity.behavior if activity else (agent.status if agent else "idle")

        panels.append(AgentPanelState(
            panel_label=label,
            agent_id=char_id,
            room_id=room_id,
            status=status,
            heartbeat_age_s=_find_telemetry_value(state, "heartbeat", agent_ref) or
            _find_telemetry_value(state, "heartbeat", room_id),
            latency_ms=_find_telemetry_value(state, agent_ref, "latency"),
            last_decision=_last_decision(state, room_id),
            current_task=_current_task(state, room_id),
            last_update=state.captured_at,
        ))
    return tuple(panels)
