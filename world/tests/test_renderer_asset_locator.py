"""Phase W8: AssetLocator — character sprite + room prop resolution
against the real Phase W6 asset data."""

from world.frontend.renderer.asset_locator import AssetLocator, PlacedProp


def test_character_sprite_resolves_to_manifest_entry():
    locator = AssetLocator()
    entry = locator.character_sprite("bastion", "idle")
    assert entry is not None
    assert entry["id"] == "sprite.bastion.idle"
    assert entry["category"] == "character-sprite"


def test_character_sprite_uses_fallback_for_unsupported_behavior():
    locator = AssetLocator()
    meeting_entry = locator.character_sprite("bastion", "meeting")
    working_entry = locator.character_sprite("bastion", "working")
    assert meeting_entry == working_entry


def test_character_sprite_returns_none_for_unknown_character():
    locator = AssetLocator()
    assert locator.character_sprite("not-a-character", "idle") is None


def test_room_props_returns_placed_props_for_a_real_room():
    locator = AssetLocator()
    props = locator.room_props("ai-council")
    assert len(props) > 0
    assert all(isinstance(p, PlacedProp) for p in props)
    kinds = {p.kind for p in props}
    assert kinds <= {"furniture", "decoration"}


def test_room_props_asset_ids_all_resolve_in_registry():
    locator = AssetLocator()
    for room_id in locator.known_room_ids():
        for prop in locator.room_props(room_id):
            assert locator.registry.resolve(prop.asset_id) is not None


def test_room_props_empty_for_unknown_room():
    locator = AssetLocator()
    assert locator.room_props("not-a-real-room") == []


def test_known_room_ids_covers_all_seventeen_rooms():
    """14 departments + 3 CirculationType rooms (lobby, hallway,
    elevator) — verified this phase against the live repo data."""
    locator = AssetLocator()
    assert len(locator.known_room_ids()) == 17
    assert "lobby" in locator.known_room_ids()
    assert "risk-fortress" in locator.known_room_ids()
