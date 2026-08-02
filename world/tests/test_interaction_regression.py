"""Phase W9 regression: `world.interaction.api` against the real, live
`world.runtime`/`world.simulation` APIs end to end — no fakes injected,
matching `test_renderer_world_state_provider.
test_default_construction_uses_real_live_apis_and_does_not_raise`'s
pattern for Phase W8.
"""

from world.interaction import api as interaction_api
from world.runtime import api as runtime_api


def test_select_a_real_room_end_to_end():
    state = runtime_api.get_world_state()
    room_id = state.rooms[0].room_id
    selection = interaction_api.select("room", room_id)
    assert selection.target_id == room_id
    assert interaction_api.current_selection() == selection
    interaction_api.clear_selection()
    assert interaction_api.current_selection() is None


def test_inspect_a_real_room_end_to_end():
    state = runtime_api.get_world_state()
    room_id = state.rooms[0].room_id
    report = interaction_api.inspect("room", room_id)
    assert report.id == room_id


def test_search_and_get_notifications_do_not_raise():
    interaction_api.search_world("risk")
    interaction_api.get_notifications()


def test_dispatch_show_timeline_does_not_raise():
    result = interaction_api.dispatch("show_timeline")
    assert result.command == "show_timeline"


def test_selection_and_command_history_accumulate():
    state = runtime_api.get_world_state()
    room_id = state.rooms[0].room_id
    interaction_api.select("room", room_id)
    interaction_api.dispatch("show_timeline")
    assert len(interaction_api.get_interaction_history()) >= 2
    assert len(interaction_api.get_event_history("SelectionChanged")) >= 1
