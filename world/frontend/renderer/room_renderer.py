"""OfficeDistrictRenderer — Phase W8.

Concrete `world.frontend.interfaces.district_renderer.DistrictRenderer`.
Same void/accumulate-then-drain shape as `character_renderer.SpriteCharacterRenderer`,
for the same reason (the ABC's `render_district(...) -> None` is a
side-effecting draw call written for a direct engine binding; see
`renderer.py`'s module docstring).

Coordinate note (a real, verified finding, not an assumption dressed
up as one): `world/data/layout/rooms.json`'s `cameraAnchor`/
`spawnLocation` are **floor-scale** office-unit coordinates (e.g.
`ai-council`: `{"x": 2.0, "y": 16.0}`), while furniture/decoration
positions in `world/data/assets/room_assets.json` and character
positions from `world.simulation.api.get_simulation_state()` are
**room-local** (e.g. every character's position for `bastion` in
`risk-fortress` falls in the 0–4 range matching
`world/data/characters/placement.json`'s `deskAnchor`/spatial
placement positions for that same room). No document in this
repository states how the two combine, so this module makes the
simplest reading explicit rather than silently picking one:
`world_position = room_anchor + local_position`, treating one
abstract office unit as the same size in both systems. If a future
phase's art/layout work says otherwise, only `room_origin`/
`_offset_to_world` below need to change — nothing upstream of this
module encodes the assumption.

`load_room_anchors` also backs `renderer.SceneGraphRenderer`'s
`ReferenceCameraController` construction, which
(`world.frontend.camera.camera`) requires room anchors supplied at
construction time rather than reading `world/data/*` itself.
"""

import json
import os
from typing import Any

from world.frontend.interfaces.district_renderer import DistrictRenderer
from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.render_state import RenderCommand
from world.frontend.scene.layer import LayerType
from world.frontend.viewport.viewport import ViewportState, world_to_screen

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/frontend/renderer
_WORLD_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # world/
_DEFAULT_ROOMS_LAYOUT_PATH = os.path.join(_WORLD_DIR, "data", "layout", "rooms.json")

#: Anchor used for the three `CirculationType` rooms and any other
#: room with no `world/data/layout/rooms.json` entry — see the
#: module docstring's coordinate note. Documented gap: a future
#: Phase W2-layout addition giving lobby/hallway/elevator real
#: anchors would let this module stop special-casing them.
_FALLBACK_ROOM_ORIGIN = (0.0, 0.0)


def load_room_anchors(path: str = _DEFAULT_ROOMS_LAYOUT_PATH) -> dict[str, tuple[float, float]]:
    """Return `{room_id: (cameraAnchor.x, cameraAnchor.y)}` for every
    room with a `world/data/layout/rooms.json` entry. Returns `{}`
    rather than raising if the file is missing, matching every other
    fail-soft reader in this package."""
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        rooms: list[dict[str, Any]] = json.load(f)
    return {
        room["id"]: (room["cameraAnchor"]["x"], room["cameraAnchor"]["y"])
        for room in rooms
        if "cameraAnchor" in room
    }


class OfficeDistrictRenderer(DistrictRenderer):
    def __init__(
        self,
        asset_locator: AssetLocator,
        viewport: ViewportState,
        camera_x: float,
        camera_y: float,
        room_anchors: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self._asset_locator = asset_locator
        self._viewport = viewport
        self._camera_x = camera_x
        self._camera_y = camera_y
        self._room_anchors = room_anchors if room_anchors is not None else load_room_anchors()
        self._commands: list[RenderCommand] = []

    def room_origin(self, room_id: str) -> tuple[float, float]:
        return self._room_anchors.get(room_id, _FALLBACK_ROOM_ORIGIN)

    def _to_screen(self, room_id: str, local_x: float, local_y: float) -> tuple[float, float]:
        origin_x, origin_y = self.room_origin(room_id)
        return world_to_screen(
            self._viewport, self._camera_x, self._camera_y,
            origin_x + local_x, origin_y + local_y,
        )

    def render_district(self, district_id: str, district_data: dict[str, Any]) -> None:
        origin_x, origin_y = self.room_origin(district_id)
        floor_screen_x, floor_screen_y = world_to_screen(
            self._viewport, self._camera_x, self._camera_y, origin_x, origin_y,
        )
        self._commands.append(RenderCommand(
            command_type="tile",
            entity_id=f"floor-{district_id}",
            layer=LayerType.FLOOR.value,
            z_order=1,
            screen_x=floor_screen_x,
            screen_y=floor_screen_y,
            asset_id=None,
            metadata={
                "visualTheme": district_data.get("visualTheme"),
                "name": district_data.get("name", district_id),
            },
        ))

        for prop in self._asset_locator.room_props(district_id):
            screen_x, screen_y = self._to_screen(district_id, prop.x, prop.y)
            manifest_entry = None
            try:
                manifest_entry = self._asset_locator.registry.resolve(prop.asset_id)
            except Exception:  # noqa: BLE001 — resolution failure must not drop the room
                manifest_entry = None
            self._commands.append(RenderCommand(
                command_type="tile" if prop.kind == "decoration" else "sprite",
                entity_id=prop.instance_id,
                layer=LayerType.FURNITURE.value,
                z_order=2,
                screen_x=screen_x,
                screen_y=screen_y,
                asset_id=prop.asset_id if manifest_entry is not None else None,
                metadata={"kind": prop.kind, "interactions": list(prop.interactions)},
            ))

    def take_commands(self) -> list[RenderCommand]:
        commands, self._commands = self._commands, []
        return commands
