"""CommandDispatcher — Command Dispatch section. Every command below is
one of the brief's named, read-only verbs; no trading commands exist
here, and nothing here calls into `agents/`, `execution/`, `portfolio/`,
`learning/`, `risk/`, or `exchange/` — only `FocusManager`,
`TimelineController`, and `world.simulation.api`'s existing
`pause`/`resume` (both already read-only from the trading engine's
perspective per that module's own docstring).

Every successful command publishes the matching `interaction_events.
EventBus` event (`CameraMoved`, `TimelineChanged`,
`SimulationPaused`/`SimulationResumed`) and is recorded into an
`InteractionHistory` if one is supplied — matches the Event Bus and
History sections of the brief, which name these as consequences of
dispatching a command, not separate manual steps a caller must remember.

`set_simulation_speed` is the one command with no real backend effect to
wrap: `world.simulation.scheduler.SimulationScheduler.fps_target` is a
fixed, descriptive design constant (see that module's docstring — "not
enforced by this class"), and Phase W7 has no polling loop for a "speed"
to govern in the first place (ticks only ever happen when something
external calls `step()`). Rather than inventing an effect that doesn't
exist anywhere in this codebase, this stores the requested rate as a
plain preference value a future Phase W10 UI could read and interpret
for its own playback loop; it is documented here as a preference, not a
simulation control.

Phase W13-2 extends `_record()` with the full command-audit metadata
the W13 spec requires (actor/parameters/duration_ms/timestamp), on top
of the Phase W9 command/ok/detail fields — entirely via
`InteractionHistory.record_command()`'s new keyword-only arguments
(see that module), so no second audit subsystem, no schema break for
existing callers. `kwargs` — the command's own call arguments — are
sanitized before being handed to history: any key that looks like it
could hold a secret (name containing "key"/"secret"/"token"/
"password"/"credential"/"auth"/"signature") is dropped outright, and
any non-primitive value is replaced with its type name rather than the
object itself, so nothing this dispatcher wasn't explicitly built to
recognize as safe can ever reach persisted history — belt-and-braces
given every real command here only ever takes plain str/float
arguments (room_id, character_id, event_id, speed) anyway.
"""

import time
from datetime import UTC, datetime

from world.interaction.focus_manager import FocusManager
from world.interaction.interaction_events import EventBus
from world.interaction.interaction_history import InteractionHistory
from world.interaction.models import CommandResult
from world.interaction.timeline_controller import TimelineController
from world.simulation import api as simulation_api

READ_ONLY_COMMANDS = (
    "focus_room", "follow_character", "center_camera", "highlight_department",
    "show_timeline", "jump_to_event", "pause_simulation", "resume_simulation",
    "set_simulation_speed",
)

# Phase W13-2 — dropped outright from audit `parameters`, never stored
# even redacted, on the chance a future command is added that takes
# one of these names. Checked as a substring of the (lowercased)
# kwarg name, not an exact match, to catch e.g. "apiKey"/"auth_token".
_SENSITIVE_PARAM_MARKERS = ("key", "secret", "token", "password", "credential", "auth", "signature")


def _sanitize_parameters(params: dict) -> dict:
    """Phase W13-2. Every value in `params` is either a JSON-safe
    primitive (str/int/float/bool/None — every real command argument
    in this file is one of these) or, defensively, gets replaced with
    its type name rather than stored as-is."""
    safe: dict = {}
    for key, value in params.items():
        if any(marker in key.lower() for marker in _SENSITIVE_PARAM_MARKERS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = f"<{type(value).__name__}>"
    return safe


class CommandDispatcher:
    def __init__(
        self,
        focus_manager: FocusManager | None = None,
        timeline_controller: TimelineController | None = None,
        event_bus: EventBus | None = None,
        history: InteractionHistory | None = None,
        get_simulation_state=simulation_api.get_simulation_state,
        pause=simulation_api.pause,
        resume=simulation_api.resume,
    ) -> None:
        self._focus = focus_manager or FocusManager()
        self._timeline = timeline_controller or TimelineController()
        self._events = event_bus or EventBus()
        self._history = history
        self._get_simulation_state = get_simulation_state
        self._pause = pause
        self._resume = resume
        self._highlighted_department: str | None = None
        self._simulation_speed_preference: float = 1.0

    @property
    def event_bus(self) -> EventBus:
        return self._events

    def dispatch(self, command: str, actor: str = "unknown", **kwargs) -> CommandResult:
        """`actor` (Phase W13-2) identifies the audit-log source of this
        call — e.g. "dashboard" for the HTTP command endpoint (see
        api/world_api.py). Keyword-only in practice (no real command
        takes a parameter named "actor"), defaults to "unknown" so
        every pre-W13-2 call site keeps working unchanged."""
        started = time.monotonic()
        if command not in READ_ONLY_COMMANDS:
            result = CommandResult(command=command, ok=False, detail=f"unknown command {command!r}")
            self._record(result, actor=actor, parameters=kwargs, started=started)
            return result
        handler = getattr(self, f"_cmd_{command}")
        try:
            result = handler(**kwargs)
        except (KeyError, ValueError) as exc:
            result = CommandResult(command=command, ok=False, detail=str(exc))
        self._record(result, actor=actor, parameters=kwargs, started=started)
        return result

    def _record(
        self, result: CommandResult, *, actor: str = "unknown", parameters: dict | None = None, started: float | None = None,
    ) -> None:
        if self._history is not None:
            duration_ms = None
            if started is not None:
                duration_ms = round((time.monotonic() - started) * 1000, 3)
            self._history.record_command(
                result.command, result.ok, result.detail,
                actor=actor,
                parameters=_sanitize_parameters(parameters or {}),
                duration_ms=duration_ms,
                timestamp=datetime.now(UTC).isoformat(),
            )

    def _sync_character_positions(self) -> None:
        for character in self._get_simulation_state().characters:
            self._focus.update_character_position(character.agent_id, character.position.x, character.position.y)

    def _cmd_focus_room(self, room_id: str) -> CommandResult:
        state = self._focus.focus_room(room_id)
        self._events.publish("CameraMoved", {"mode": state.focus_mode.value, "target": state.focus_target})
        return CommandResult(command="focus_room", ok=True, data={"x": state.x, "y": state.y})

    def _cmd_follow_character(self, character_id: str) -> CommandResult:
        self._sync_character_positions()
        state = self._focus.follow_character(character_id)
        self._events.publish("CameraMoved", {"mode": state.focus_mode.value, "target": state.focus_target})
        return CommandResult(command="follow_character", ok=True, data={"x": state.x, "y": state.y})

    def _cmd_center_camera(self, room_id: str) -> CommandResult:
        state = self._focus.center_room(room_id)
        self._events.publish("CameraMoved", {"mode": state.focus_mode.value, "target": room_id})
        return CommandResult(command="center_camera", ok=True, data={"x": state.x, "y": state.y})

    def _cmd_highlight_department(self, room_id: str) -> CommandResult:
        self._highlighted_department = room_id
        return CommandResult(command="highlight_department", ok=True, data={"roomId": room_id})

    def _cmd_show_timeline(self) -> CommandResult:
        return CommandResult(command="show_timeline", ok=True, data={
            "length": self._timeline.length(), "isPlaying": self._timeline.is_playing(),
        })

    def _cmd_jump_to_event(self, event_id: str) -> CommandResult:
        state = self._timeline.jump_to_event(event_id)
        self._events.publish("TimelineChanged", {"tickNumber": state.tick.tick_number})
        return CommandResult(command="jump_to_event", ok=True, data={"tickNumber": state.tick.tick_number})

    def _cmd_pause_simulation(self) -> CommandResult:
        self._pause()
        self._events.publish("SimulationPaused", {})
        return CommandResult(command="pause_simulation", ok=True)

    def _cmd_resume_simulation(self) -> CommandResult:
        self._resume()
        self._events.publish("SimulationResumed", {})
        return CommandResult(command="resume_simulation", ok=True)

    def _cmd_set_simulation_speed(self, speed: float) -> CommandResult:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._simulation_speed_preference = speed
        return CommandResult(
            command="set_simulation_speed", ok=True, data={"speedPreference": speed},
            detail="stored as a UI playback preference; does not change tick cadence (see module docstring)",
        )
