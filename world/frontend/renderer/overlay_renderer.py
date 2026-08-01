"""OverlayRenderer — Phase W8.

No dedicated ABC exists for overlays in
`world/frontend/interfaces/` (only `LayerRenderer` covers a whole
layer generically) — this is a new, freestanding concrete class
rather than an implementation of an existing interface, following the
same accumulate-then-drain shape as `character_renderer` and
`room_renderer` for consistency with the rest of this package.

Scope note: "Clock" / "simulation speed" overlays are built from
`WorldState.sequence` (the Phase W7 tick number) only. The richer
Phase W7 `SimulationTick` fields (`simulated_seconds`,
`SimulationState.running`) are not part of the Phase W3
`WorldState` shape `Renderer.render(world_state)` receives, and
adding them would mean changing that already-shipped frozen
dataclass's schema — out of scope for a renderer-integration phase
that was asked not to touch Phase W3's contracts. Documented here
rather than silently reading `world.simulation.api` a second time
from inside this class (which would duplicate
`world_state_provider.RenderWorldStateProvider`'s one read path and
risk the two going out of sync within a single frame).
"""

from world.frontend.renderer.render_state import RenderCommand
from world.frontend.renderer.world_state import WorldState
from world.frontend.scene.layer import LayerType


class OverlayRenderer:
    def __init__(self) -> None:
        self._commands: list[RenderCommand] = []

    def render_room_overlays(self, room_id: str, world_state: WorldState) -> None:
        """Department label + room status indicator (busy/quiet/alert/
        critical/meeting/celebration, per
        `world.simulation.models.ROOM_ACTIVITIES`) for one room."""
        status = world_state.district_status.get(room_id, {})
        self._commands.append(RenderCommand(
            command_type="overlay",
            entity_id=f"room-label-{room_id}",
            layer=LayerType.UI_OVERLAY.value,
            z_order=5,
            screen_x=0.0,
            screen_y=0.0,
            metadata={"kind": "department_label", "text": status.get("name", room_id)},
        ))
        self._commands.append(RenderCommand(
            command_type="overlay",
            entity_id=f"room-status-{room_id}",
            layer=LayerType.UI_OVERLAY.value,
            z_order=5,
            screen_x=0.0,
            screen_y=0.0,
            metadata={
                "kind": "room_status",
                "activity": status.get("activity", "quiet"),
                "occupantCount": status.get("occupantCount", 0),
                "isMeeting": status.get("activity") == "meeting",
                "isEmergency": status.get("activity") == "critical",
            },
        ))

    def render_character_overlay(self, character_id: str, behavior: str) -> None:
        """Per-character status indicator — only emitted for the two
        behaviours worth flagging above the base sprite/animation
        (`meeting`, `emergency`); `idle`/`walking`/`working`/
        `celebration`/`resting` are fully conveyed by the sprite
        animation state itself."""
        if behavior not in ("meeting", "emergency"):
            return
        self._commands.append(RenderCommand(
            command_type="overlay",
            entity_id=f"char-status-{character_id}",
            layer=LayerType.UI_OVERLAY.value,
            z_order=5,
            screen_x=0.0,
            screen_y=0.0,
            metadata={"kind": "character_status", "behavior": behavior},
        ))

    def render_global_overlays(self, world_state: WorldState) -> None:
        """Clock/tick overlay — one per frame, not per room. See
        module docstring for why this is tick-number-only."""
        self._commands.append(RenderCommand(
            command_type="overlay",
            entity_id="global-clock",
            layer=LayerType.UI_OVERLAY.value,
            z_order=5,
            screen_x=0.0,
            screen_y=0.0,
            metadata={"kind": "clock", "tick": world_state.sequence},
        ))

    def take_commands(self) -> list[RenderCommand]:
        commands, self._commands = self._commands, []
        return commands
