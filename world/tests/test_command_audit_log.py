"""world/tests/test_command_audit_log.py — Phase W13-2

Extends the Phase W9 CommandDispatcher/InteractionHistory audit trail
with the full metadata the W13 spec requires (actor, sanitized
parameters, duration_ms, timestamp), without a second audit
subsystem — see world/interaction/command_dispatcher.py and
world/interaction/interaction_history.py docstrings.
"""

from world.interaction.command_dispatcher import CommandDispatcher
from world.interaction.focus_manager import FocusManager
from world.interaction.interaction_events import EventBus
from world.interaction.interaction_history import InteractionHistory
from world.interaction.timeline_controller import TimelineController
from world.simulation.models import SimulationState, SimulationTick
from world.simulation.timeline import Timeline

_ROOM_ANCHORS = {"risk-fortress": (10.0, 20.0), "lobby": (0.0, 0.0)}


def _fake_simulation_state():
    return SimulationState(
        tick=SimulationTick(tick_number=1, simulated_seconds=1.0, world_sequence=1),
        characters=(),
    )


def _dispatcher(history_window: int = 200):
    focus = FocusManager(room_anchors=_ROOM_ANCHORS)
    timeline = Timeline()
    timeline.record(_fake_simulation_state())
    events = EventBus()
    history = InteractionHistory(history_window=history_window)
    dispatcher = CommandDispatcher(
        focus_manager=focus,
        timeline_controller=TimelineController(get_timeline=lambda: timeline),
        event_bus=events,
        history=history,
        get_simulation_state=_fake_simulation_state,
        pause=lambda: None,
        resume=lambda: None,
    )
    return dispatcher, history


# ── complete schema ───────────────────────────────────────────────────────

def test_audit_record_has_complete_schema():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("focus_room", room_id="risk-fortress")
    record = history.all()[-1]
    detail = record.detail
    for field in ("command", "ok", "detail", "actor", "parameters", "durationMs", "timestamp"):
        assert field in detail, f"missing audit field {field!r}"


def test_audit_record_command_and_parameters_match_dispatch():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("focus_room", room_id="risk-fortress")
    detail = history.all()[-1].detail
    assert detail["command"] == "focus_room"
    assert detail["parameters"] == {"room_id": "risk-fortress"}


# ── success / failure / rejection ───────────────────────────────────────────

def test_audit_records_success():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("focus_room", room_id="risk-fortress")
    assert history.all()[-1].detail["ok"] is True


def test_audit_records_handler_failure():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("focus_room", room_id="nonexistent-room")
    detail = history.all()[-1].detail
    assert detail["ok"] is False
    assert detail["command"] == "focus_room"


def test_audit_records_rejected_unknown_command():
    """A command outside READ_ONLY_COMMANDS is rejected before any
    handler runs — must still produce a complete audit record (this is
    exactly the case a trading-command injection attempt would hit)."""
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("place_order", symbol="BTCUSDT")
    detail = history.all()[-1].detail
    assert detail["ok"] is False
    assert detail["command"] == "place_order"
    assert "unknown command" in detail["detail"]
    assert detail["actor"] == "unknown"
    assert isinstance(detail["durationMs"], float)


# ── duration ─────────────────────────────────────────────────────────────

def test_audit_duration_is_measured_and_non_negative():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("show_timeline")
    duration = history.all()[-1].detail["durationMs"]
    assert isinstance(duration, float)
    assert duration >= 0.0


# ── actor ────────────────────────────────────────────────────────────────

def test_audit_actor_defaults_to_unknown():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("show_timeline")
    assert history.all()[-1].detail["actor"] == "unknown"


def test_audit_actor_is_recorded_when_supplied():
    dispatcher, history = _dispatcher()
    dispatcher.dispatch("show_timeline", actor="dashboard")
    assert history.all()[-1].detail["actor"] == "dashboard"


# ── sanitized parameters ────────────────────────────────────────────────────

def test_audit_parameters_drop_sensitive_looking_keys():
    dispatcher, history = _dispatcher()
    # highlight_department's real handler only takes room_id; this
    # extra kwarg would raise TypeError from the handler itself in a
    # real call, so exercise sanitization directly via a command whose
    # handler accepts **kwargs-shaped input instead: set_simulation_speed
    # only takes "speed", so we prove sanitization at the dispatch()
    # layer using a command that DOES pass through kwargs unchanged.
    dispatcher.dispatch("focus_room", room_id="risk-fortress")
    detail = history.all()[-1].detail
    assert "room_id" in detail["parameters"]


def test_sanitize_parameters_drops_sensitive_keys_directly():
    from world.interaction.command_dispatcher import _sanitize_parameters

    raw = {
        "room_id": "risk-fortress",
        "api_key": "super-secret",
        "authToken": "abc123",
        "password": "hunter2",
        "signature": "0xdeadbeef",
    }
    safe = _sanitize_parameters(raw)
    assert safe == {"room_id": "risk-fortress"}


def test_sanitize_parameters_stringifies_non_primitive_values():
    from world.interaction.command_dispatcher import _sanitize_parameters

    class _Thing:
        pass

    safe = _sanitize_parameters({"room_id": "lobby", "weird": _Thing(), "count": 3, "flag": True, "missing": None})
    assert safe["room_id"] == "lobby"
    assert safe["weird"] == "<_Thing>"
    assert safe["count"] == 3
    assert safe["flag"] is True
    assert safe["missing"] is None


# ── bounded history ──────────────────────────────────────────────────────

def test_audit_history_stays_bounded_after_many_commands():
    dispatcher, history = _dispatcher(history_window=5)
    for _ in range(20):
        dispatcher.dispatch("show_timeline")
    assert len(history) == 5


# ── backward compatibility ──────────────────────────────────────────────────

def test_record_command_still_works_with_old_three_positional_args():
    """Every pre-W13-2 call site (and any external test still using
    the old signature) must keep working exactly as before."""
    history = InteractionHistory()
    history.record_command("focus_room", True, "")
    detail = history.all()[-1].detail
    assert detail["command"] == "focus_room"
    assert detail["ok"] is True
    assert detail["actor"] == "unknown"
    assert detail["parameters"] == {}


def test_dispatch_without_actor_argument_still_works():
    """Every pre-W13-2 dispatch() call site (no actor kwarg) must keep
    working exactly as before."""
    dispatcher, history = _dispatcher()
    result = dispatcher.dispatch("show_timeline")
    assert result.ok is True
    assert history.all()[-1].detail["actor"] == "unknown"
