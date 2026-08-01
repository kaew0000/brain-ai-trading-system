"""Phase W8: OverlayRenderer — room/character status, department
labels, and clock overlays."""

from world.frontend.renderer.overlay_renderer import OverlayRenderer
from world.frontend.renderer.world_state import WorldState


def _world_state():
    return WorldState(
        district_status={
            "risk-fortress": {"name": "Risk Department", "activity": "meeting", "occupantCount": 2},
            "lobby": {"name": "Lobby", "activity": "quiet", "occupantCount": 0},
        },
        sequence=99,
    )


def test_render_room_overlays_emits_label_and_status():
    overlay = OverlayRenderer()
    overlay.render_room_overlays("risk-fortress", _world_state())
    commands = overlay.take_commands()
    kinds = {c.metadata["kind"] for c in commands}
    assert kinds == {"department_label", "room_status"}


def test_room_status_flags_meeting_and_critical_correctly():
    overlay = OverlayRenderer()
    overlay.render_room_overlays("risk-fortress", _world_state())
    status_cmd = next(c for c in overlay.take_commands() if c.metadata["kind"] == "room_status")
    assert status_cmd.metadata["isMeeting"] is True
    assert status_cmd.metadata["isEmergency"] is False


def test_room_overlays_for_unknown_room_uses_defaults():
    overlay = OverlayRenderer()
    overlay.render_room_overlays("nowhere", _world_state())
    status_cmd = next(c for c in overlay.take_commands() if c.metadata["kind"] == "room_status")
    assert status_cmd.metadata["activity"] == "quiet"
    assert status_cmd.metadata["occupantCount"] == 0


def test_character_overlay_only_emitted_for_meeting_or_emergency():
    overlay = OverlayRenderer()
    overlay.render_character_overlay("bastion", "idle")
    overlay.render_character_overlay("sentinel", "walking")
    overlay.render_character_overlay("chronos", "working")
    overlay.render_character_overlay("herald", "celebration")
    overlay.render_character_overlay("primus", "resting")
    assert overlay.take_commands() == []

    overlay.render_character_overlay("bastion", "meeting")
    overlay.render_character_overlay("sentinel", "emergency")
    commands = overlay.take_commands()
    assert len(commands) == 2
    assert {c.metadata["behavior"] for c in commands} == {"meeting", "emergency"}


def test_global_overlays_emits_clock_with_tick_number():
    overlay = OverlayRenderer()
    overlay.render_global_overlays(_world_state())
    commands = overlay.take_commands()
    assert len(commands) == 1
    assert commands[0].metadata["kind"] == "clock"
    assert commands[0].metadata["tick"] == 99


def test_take_commands_drains():
    overlay = OverlayRenderer()
    overlay.render_global_overlays(_world_state())
    assert len(overlay.take_commands()) == 1
    assert overlay.take_commands() == []
