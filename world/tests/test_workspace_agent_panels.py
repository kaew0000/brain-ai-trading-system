"""Phase W12: agent_workspace — 7 named panels, real WorldState."""
from world.runtime.api import get_world_state
from world.workspace.agent_workspace import build_agent_panels


def test_builds_exactly_seven_panels():
    panels = build_agent_panels(get_world_state())
    assert len(panels) == 7


def test_panel_labels_match_the_required_set():
    panels = build_agent_panels(get_world_state())
    labels = {p.panel_label for p in panels}
    assert labels == {"CEO", "Risk", "Execution", "Market", "Regime", "Portfolio", "Learning"}


def test_ceo_panel_maps_to_primus_and_ceo_tower():
    panels = build_agent_panels(get_world_state())
    ceo = next(p for p in panels if p.panel_label == "CEO")
    assert ceo.agent_id == "primus"
    assert ceo.room_id == "ceo-tower"


def test_every_panel_has_a_status_from_the_real_seven_behaviors():
    panels = build_agent_panels(get_world_state())
    valid = {"idle", "walking", "working", "meeting", "emergency", "celebration", "resting"}
    for p in panels:
        assert p.status in valid


def test_missing_telemetry_is_none_not_fabricated():
    """This test environment's telemetry.json is empty (no DataSource
    points at a real engine path yet, per every prior phase) — heartbeat
    and latency must honestly be None, never a fabricated number."""
    panels = build_agent_panels(get_world_state())
    for p in panels:
        assert p.heartbeat_age_s is None
        assert p.latency_ms is None


def test_every_panel_serializes_to_dict():
    import json
    panels = build_agent_panels(get_world_state())
    json.dumps([p.to_dict() for p in panels])
