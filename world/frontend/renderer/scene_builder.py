"""SceneBuilder — Phase W8.

`WorldState -> Scene`, one room at a time. Populates every layer in
`world.frontend.scene.layer.STANDARD_LAYER_ORDER` with entity ids;
resolving those ids to actual screen-space `render_state.RenderCommand`s
is `renderer.SceneGraphRenderer`'s job (via `character_renderer`,
`room_renderer`, `overlay_renderer`) — this module only decides *what
belongs in the scene*, not where on screen it goes or what it looks
like. Matches the interfaces/data split already established by
`world.frontend.scene.scene` (`Scene` = data, `SceneRenderer` =
behavior) and `world.frontend.scene.layer` (`Layer` = data,
`LayerRenderer` = behavior).

Note on `Scene.district_id`: `world.frontend.scene.scene.Scene`'s
docstring says this "must be a real id from
`world/districts/definitions/`" — true for the 14 departments, but
`world.frontend.rooms.room_type.CirculationType` rooms (`lobby`,
`hallway`, `elevator`) have no district definition and are not
covered by that constraint. `Scene` performs no runtime validation of
this field, so building a `Scene` for a circulation room is safe; it
is simply not, strictly, a "district." Both room kinds have real
`world/data/assets/room_assets.json` furniture/decoration data and
real `WorldState.district_status` entries (Phase W7's simulation
covers all 17 rooms, not just the 14 departments — verified against
a live `world.runtime.api.get_world_state()` call this phase), so
both are built as scenes here.
"""

from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.world_state import WorldState
from world.frontend.scene.layer import STANDARD_LAYER_ORDER, Layer, LayerType
from world.frontend.scene.scene import Scene

#: Behaviours that warrant a visual-effects layer entry (a flourish
#: on top of the base sprite) rather than just the base animation
#: state the character layer already carries.
_EFFECT_BEHAVIORS = frozenset({"emergency", "celebration"})


def _characters_in_room(world_state: WorldState, room_id: str) -> list[str]:
    return [
        char_id
        for char_id, pos in world_state.character_positions.items()
        if pos.get("room_id") == room_id
    ]


def _events_in_room(world_state: WorldState, room_id: str) -> list[str]:
    return [
        event["eventId"]
        for event in world_state.recent_events
        if event.get("roomId") == room_id and event.get("eventId")
    ]


def build_scene(scene_id: str, room_id: str, world_state: WorldState, asset_locator: AssetLocator) -> Scene:
    """Build one `Scene` for `room_id`. `scene_id` is caller-assigned
    (a `SceneRegistry` key) so the same room can back more than one
    named scene if a future phase needs that (e.g. a "focused" vs.
    "overview" variant) — this function itself is stateless.
    """
    room_characters = _characters_in_room(world_state, room_id)
    room_props = asset_locator.room_props(room_id)
    effect_characters = [
        char_id for char_id in room_characters
        if world_state.character_states.get(char_id) in _EFFECT_BEHAVIORS
    ]
    room_events = _events_in_room(world_state, room_id)

    layers = [
        Layer(layer_type=LayerType.BACKGROUND, z_order=0, entity_ids=[]),
        Layer(layer_type=LayerType.FLOOR, z_order=1, entity_ids=[f"floor-{room_id}"]),
        Layer(
            layer_type=LayerType.FURNITURE,
            z_order=2,
            entity_ids=[prop.instance_id for prop in room_props],
        ),
        Layer(layer_type=LayerType.CHARACTERS, z_order=3, entity_ids=list(room_characters)),
        Layer(
            layer_type=LayerType.EFFECTS,
            z_order=4,
            entity_ids=[f"fx-{char_id}" for char_id in effect_characters],
        ),
        Layer(
            layer_type=LayerType.UI_OVERLAY,
            z_order=5,
            entity_ids=[f"room-label-{room_id}", f"room-status-{room_id}"],
        ),
        Layer(layer_type=LayerType.NOTIFICATION, z_order=6, entity_ids=room_events),
    ]
    assert [layer.layer_type for layer in layers] == list(STANDARD_LAYER_ORDER), (
        "scene layers must be built in STANDARD_LAYER_ORDER"
    )

    return Scene(
        scene_id=scene_id,
        district_id=room_id,
        character_ids=list(room_characters),
        layers=layers,
    )
