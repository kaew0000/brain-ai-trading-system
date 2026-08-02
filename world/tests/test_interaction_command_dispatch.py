"""Phase W9: CommandDispatcher."""

from world.interaction.command_dispatcher import CommandDispatcher, READ_ONLY_COMMANDS
from world.interaction.focus_manager import FocusManager
from world.interaction.interaction_events import EventBus
from world.interaction.interaction_history import InteractionHistory
from world.interaction.timeline_controller import TimelineController
from world.simulation.models import CharacterActivity, Position, SimulationState, SimulationTick
from world.simulation.timeline import Timeline

_ROOM_ANCHORS = {"risk-fortress": (10.0, 20.0), "lobby": (0.0, 0.0)}


def _fake_simulation_state():
    return SimulationState(
        tick=SimulationTick(tick_number=1, simulated_seconds=1.0, world_sequence=1),
        characters=(
            CharacterActivity(agent_id="bastion", agent_ref="BASTION", behavior="working",
                               room_id="risk-fortress", position=Position(10.0, 20.0)),
        ),
    )


def _dispatcher():
    focus = FocusManager(room_anchors=_ROOM_ANCHORS)
    timeline = Timeline()
    timeline.record(_fake_simulation_state())
    events = EventBus()
    history = InteractionHistory()
    dispatcher = CommandDispatcher(
        focus_manager=focus,
        timeline_controller=TimelineController(get_timeline=lambda: timeline),
        event_bus=events,
        history=history,
        get_simulation_state=_fake_simulation_state,
        pause=lambda: None,
        resume=lambda: None,
    )
    return dispatcher, events, history


def test_no_trading_commands_in_read_only_set():
    forbidden = {"buy", "sell", "trade", "execute_order", "close_position", "open_position"}
    assert forbidden.isdisjoint(READ_ONLY_COMMANDS)


def test_focus_room_moves_camera_and_publishes_event():
    dispatcher, events, _ = _dispatcher()
    result = dispatcher.dispatch("focus_room", room_id="risk-fortress")
    assert result.ok is True
    assert result.data == {"x": 10.0, "y": 20.0}
    assert len(events.history("CameraMoved")) == 1


def test_focus_unknown_room_fails_gracefully():
    dispatcher, _, _ = _dispatcher()
    result = dispatcher.dispatch("focus_room", room_id="nonexistent")
    assert result.ok is False


def test_follow_character_syncs_position_from_simulation_state():
    dispatcher, events, _ = _dispatcher()
    result = dispatcher.dispatch("follow_character", character_id="bastion")
    assert result.ok is True
    assert result.data == {"x": 10.0, "y": 20.0}
    assert len(events.history("CameraMoved")) == 1


def test_center_camera():
    dispatcher, events, _ = _dispatcher()
    result = dispatcher.dispatch("center_camera", room_id="lobby")
    assert result.ok is True
    assert len(events.history("CameraMoved")) == 1


def test_highlight_department():
    dispatcher, _, _ = _dispatcher()
    result = dispatcher.dispatch("highlight_department", room_id="risk-fortress")
    assert result.ok is True
    assert result.data == {"roomId": "risk-fortress"}


def test_show_timeline_returns_length_and_playing_state():
    dispatcher, _, _ = _dispatcher()
    result = dispatcher.dispatch("show_timeline")
    assert result.data["length"] == 1


def test_pause_and_resume_simulation_publish_events():
    dispatcher, events, _ = _dispatcher()
    pause_result = dispatcher.dispatch("pause_simulation")
    resume_result = dispatcher.dispatch("resume_simulation")
    assert pause_result.ok is True
    assert resume_result.ok is True
    assert len(events.history("SimulationPaused")) == 1
    assert len(events.history("SimulationResumed")) == 1


def test_set_simulation_speed_stores_preference_without_backend_effect():
    dispatcher, _, _ = _dispatcher()
    result = dispatcher.dispatch("set_simulation_speed", speed=2.0)
    assert result.ok is True
    assert result.data == {"speedPreference": 2.0}
    assert "does not change tick cadence" in result.detail


def test_set_simulation_speed_rejects_non_positive():
    dispatcher, _, _ = _dispatcher()
    result = dispatcher.dispatch("set_simulation_speed", speed=-1.0)
    assert result.ok is False


def test_unknown_command_fails_without_raising():
    dispatcher, _, _ = _dispatcher()
    result = dispatcher.dispatch("delete_everything")
    assert result.ok is False


def test_every_dispatch_is_recorded_in_history():
    dispatcher, _, history = _dispatcher()
    dispatcher.dispatch("pause_simulation")
    dispatcher.dispatch("resume_simulation")
    assert len(history) == 2
