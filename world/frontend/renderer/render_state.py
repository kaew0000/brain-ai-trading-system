"""RenderFrame / RenderCommand — Phase W8 renderer output.

The whole point of `Renderer.render(world_state) -> None` in
`world.frontend.interfaces.renderer` is that a `Renderer`
implementation is free to do anything with a frame internally, but
this repository ships no pixel-drawing engine (see
`world/frontend/renderer/renderer.py`'s module docstring for why) —
so `SceneGraphRenderer.render()` (the concrete `Renderer` this phase
adds) returns its frame instead of drawing it, as one of these plain,
JSON-serializable dataclasses. A browser-side Phaser 3 scene (Phase
W10) is the actual pixel renderer; these classes are the wire format
between this backend and that frontend, over whatever transport Phase
W10 chooses (the existing FastAPI/WebSocket layer per the
project's stated stack — no transport code lives here).

Deliberately NOT a dependency of anything under `world/frontend/interfaces/`
or `world/frontend/scene/` — those stay engine-and-format agnostic;
this module is one possible concrete output shape among others a
different `Renderer` implementation could choose instead.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RenderCommand:
    """One drawable instruction: "put this asset at this screen
    position, on this layer." Pure data — no drawing.

    `command_type` is one of `"tile"`, `"sprite"`, `"overlay"`;
    kept as a plain string (matching the rest of `world/simulation`'s
    convention of plain-string enums over `Enum` for wire-shaped
    data) rather than importing an enum a JS-side Phaser consumer
    would have to mirror.
    """

    command_type: str
    entity_id: str
    layer: str  # a world.frontend.scene.layer.LayerType value
    z_order: int
    screen_x: float
    screen_y: float
    asset_id: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "commandType": self.command_type,
            "entityId": self.entity_id,
            "layer": self.layer,
            "zOrder": self.z_order,
            "screenX": self.screen_x,
            "screenY": self.screen_y,
            "assetId": self.asset_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RenderFrame:
    """One complete, backend-independent frame: everything a
    consumer needs to draw one scene at one moment, already
    projected to screen space by the current camera/viewport. Layer
    order within `commands` follows
    `world.frontend.scene.layer.STANDARD_LAYER_ORDER`; a naive
    consumer can draw `commands` in list order and get correct
    back-to-front compositing without knowing anything about layers
    itself.
    """

    scene_id: str
    room_id: str
    sequence: int
    camera: dict
    viewport: dict
    commands: tuple[RenderCommand, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "sceneId": self.scene_id,
            "roomId": self.room_id,
            "sequence": self.sequence,
            "camera": dict(self.camera),
            "viewport": dict(self.viewport),
            "commands": [c.to_dict() for c in self.commands],
        }
