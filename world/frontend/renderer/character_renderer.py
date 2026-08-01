"""SpriteCharacterRenderer — Phase W8.

Concrete `world.frontend.interfaces.character_renderer.CharacterRenderer`.

That ABC's `render_character(character_id, character_data, state) ->
None` is a void, side-effecting draw call — written for a direct
engine binding (call it once per character per frame, it draws
immediately). This repository ships no pixel-drawing engine (see
`renderer.py`'s module docstring), so this implementation honors the
`-> None` contract literally and *accumulates* a `render_state.RenderCommand`
into an internal buffer instead of drawing one; `renderer.SceneGraphRenderer`
drains that buffer once per frame via `take_commands()` to build the
`RenderFrame` it returns from `render()` — the same buffer-then-drain
shape `render()` itself uses for the same reason.

Per the ABC docstring, `state` here must already be one of
`world.frontend.interfaces.animation_controller.STANDARD_ANIMATION_STATES`
(the five states every character actually has a sprite for) — the
caller (`renderer.SceneGraphRenderer`) is responsible for resolving a
Phase W7 `CHARACTER_BEHAVIORS` label down to one of those five via
`sprite_mapper.SpriteMapper.animation_state_for` *before* calling
`render_character`. This class does not know about the seven-state
behaviour vocabulary at all — kept as a narrow, ABC-faithful
implementation.
"""

from typing import Any

from world.frontend.interfaces.character_renderer import CharacterRenderer
from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.render_state import RenderCommand
from world.frontend.scene.layer import LayerType
from world.frontend.viewport.viewport import ViewportState, world_to_screen


class SpriteCharacterRenderer(CharacterRenderer):
    """`origin_x`/`origin_y` is the *room's* global office-unit anchor
    (`room_renderer.load_room_anchors()`), not the camera position —
    the two happen to be equal whenever the camera is simply focused
    on this room (`renderer.SceneGraphRenderer` always focuses the
    camera on the loaded room today), but keeping them as separate
    parameters here means this class still projects correctly if a
    future phase pans/zooms the camera away from room-center while
    keeping this room loaded, without any change to this file.
    `world.simulation.api.get_simulation_state()` character positions
    are room-local (see `room_renderer`'s module docstring for the
    verified coordinate-system finding this corrects for); this class
    adds the room origin before projecting to screen space so a
    character lands in the same global position furniture in the same
    room does.
    """

    def __init__(
        self, asset_locator: AssetLocator, viewport: ViewportState,
        camera_x: float, camera_y: float, origin_x: float = 0.0, origin_y: float = 0.0,
    ) -> None:
        self._asset_locator = asset_locator
        self._viewport = viewport
        self._camera_x = camera_x
        self._camera_y = camera_y
        self._origin_x = origin_x
        self._origin_y = origin_y
        self._commands: list[RenderCommand] = []

    def render_character(self, character_id: str, character_data: dict[str, Any], state: str) -> None:
        sprite_entry = self._asset_locator.character_sprite(character_id, state)
        asset_id = sprite_entry["id"] if sprite_entry is not None else None

        local_x = character_data.get("x", 0.0)
        local_y = character_data.get("y", 0.0)
        screen_x, screen_y = world_to_screen(
            self._viewport, self._camera_x, self._camera_y,
            self._origin_x + local_x, self._origin_y + local_y,
        )

        self._commands.append(RenderCommand(
            command_type="sprite",
            entity_id=character_id,
            layer=LayerType.CHARACTERS.value,
            z_order=3,
            screen_x=screen_x,
            screen_y=screen_y,
            asset_id=asset_id,
            metadata={
                "animationState": state,
                "roomId": character_data.get("room_id"),
                "resolved": asset_id is not None,
            },
        ))

    def take_commands(self) -> list[RenderCommand]:
        """Drain and return every command accumulated since the last
        `take_commands()` call (or since construction)."""
        commands, self._commands = self._commands, []
        return commands
