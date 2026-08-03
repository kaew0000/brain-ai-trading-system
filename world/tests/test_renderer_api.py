"""Phase W10: world.frontend.renderer.api — the additive facade."""
from world.frontend.renderer.api import get_render_frame, known_room_ids


def test_known_room_ids_matches_real_room_count():
    assert len(known_room_ids()) == 17


def test_get_render_frame_returns_frame_for_requested_room():
    frame = get_render_frame("ceo-tower")
    assert frame.room_id == "ceo-tower"
    assert len(frame.commands) > 0


def test_switching_rooms_rebuilds_the_frame():
    first = get_render_frame("ceo-tower")
    second = get_render_frame("risk-fortress")
    assert first.room_id != second.room_id
    assert second.room_id == "risk-fortress"


def test_frame_is_json_serializable():
    import json
    frame = get_render_frame("data-center")
    json.dumps(frame.to_dict())


def test_every_real_room_renders_without_error():
    for room_id in known_room_ids():
        frame = get_render_frame(room_id)
        assert frame.room_id == room_id
