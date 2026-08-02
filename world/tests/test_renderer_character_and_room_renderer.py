"""Phase W8: SpriteCharacterRenderer + OfficeDistrictRenderer — concrete
implementations of the Phase W3 `CharacterRenderer`/`DistrictRenderer`
ABCs."""

import inspect

from world.frontend.interfaces.character_renderer import CharacterRenderer
from world.frontend.interfaces.district_renderer import DistrictRenderer
from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.character_renderer import SpriteCharacterRenderer
from world.frontend.renderer.room_renderer import OfficeDistrictRenderer, load_room_anchors
from world.frontend.viewport.viewport import ViewportState


def test_character_renderer_is_a_real_character_renderer():
    assert inspect.isabstract(CharacterRenderer)
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720)
    renderer = SpriteCharacterRenderer(locator, viewport, camera_x=0.0, camera_y=0.0)
    assert isinstance(renderer, CharacterRenderer)


def test_district_renderer_is_a_real_district_renderer():
    assert inspect.isabstract(DistrictRenderer)
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720)
    renderer = OfficeDistrictRenderer(locator, viewport, camera_x=0.0, camera_y=0.0)
    assert isinstance(renderer, DistrictRenderer)


def test_render_character_returns_none_and_accumulates_a_command():
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720)
    renderer = SpriteCharacterRenderer(locator, viewport, camera_x=18.0, camera_y=10.0, origin_x=18.0, origin_y=10.0)
    result = renderer.render_character("bastion", {"x": 0.5, "y": 0.5, "room_id": "risk-fortress"}, "idle")
    assert result is None
    commands = renderer.take_commands()
    assert len(commands) == 1
    assert commands[0].entity_id == "bastion"
    assert commands[0].asset_id == "sprite.bastion.idle"


def test_render_character_unresolved_sprite_does_not_raise():
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720)
    renderer = SpriteCharacterRenderer(locator, viewport, camera_x=0.0, camera_y=0.0)
    renderer.render_character("not-a-character", {"x": 0.0, "y": 0.0}, "idle")
    commands = renderer.take_commands()
    assert commands[0].asset_id is None
    assert commands[0].metadata["resolved"] is False


def test_take_commands_drains_the_buffer():
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720)
    renderer = SpriteCharacterRenderer(locator, viewport, camera_x=0.0, camera_y=0.0)
    renderer.render_character("bastion", {"x": 0.0, "y": 0.0}, "idle")
    first = renderer.take_commands()
    second = renderer.take_commands()
    assert len(first) == 1
    assert second == []


def test_character_and_furniture_land_in_the_same_room_near_each_other():
    """Regression pin for the coordinate bug found and fixed this
    phase: room-local character positions must be offset by the same
    room origin furniture positions already use, or the two land in
    completely different places on screen for the same room."""
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720, scale=32.0)
    anchors = load_room_anchors()
    origin_x, origin_y = anchors["risk-fortress"]

    room_renderer = OfficeDistrictRenderer(locator, viewport, camera_x=origin_x, camera_y=origin_y)
    room_renderer.render_district("risk-fortress", {"name": "Risk Department"})
    room_commands = room_renderer.take_commands()
    furniture_x = next(c.screen_x for c in room_commands if c.command_type in ("sprite", "tile") and c.layer == "furniture")

    char_renderer = SpriteCharacterRenderer(
        locator, viewport, camera_x=origin_x, camera_y=origin_y, origin_x=origin_x, origin_y=origin_y,
    )
    char_renderer.render_character("bastion", {"x": 0.5, "y": 0.5, "room_id": "risk-fortress"}, "idle")
    char_x = char_renderer.take_commands()[0].screen_x

    # both within a couple hundred px of the room's floor tile at
    # (640, 360) — nowhere near the ~550px-off bug this test would
    # have caught before the fix
    assert abs(char_x - furniture_x) < 200


def test_render_district_emits_floor_and_prop_commands():
    locator = AssetLocator()
    viewport = ViewportState(width=1280, height=720)
    renderer = OfficeDistrictRenderer(locator, viewport, camera_x=0.0, camera_y=0.0)
    result = renderer.render_district("risk-fortress", {"name": "Risk Department", "visualTheme": "glass office"})
    assert result is None
    commands = renderer.take_commands()
    floor_commands = [c for c in commands if c.entity_id == "floor-risk-fortress"]
    assert len(floor_commands) == 1
    assert floor_commands[0].metadata["visualTheme"] == "glass office"
    prop_count = len(locator.room_props("risk-fortress"))
    assert len(commands) == 1 + prop_count


def test_load_room_anchors_covers_the_fourteen_departments():
    anchors = load_room_anchors()
    assert len(anchors) == 14
    assert anchors["risk-fortress"] == (18.0, 10.0)
