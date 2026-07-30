"""Phase W6: AssetRegistry + concrete AssetLoader wiring."""
import pytest

from world.frontend.asset_loader.asset_registry import AssetSource, UnresolvedAssetError
from world.frontend.asset_loader.registry_factory import build_default_registry


def test_all_four_sources_registered():
    registry = build_default_registry()
    sources = set(registry.registered_sources())
    assert sources == {
        AssetSource.OPENGAMEART, AssetSource.LPC, AssetSource.KENNEY, AssetSource.CUSTOM
    }


def test_resolve_character_sprite_from_lpc():
    registry = build_default_registry()
    handle = registry.resolve("sprite.primus.idle")
    assert handle["id"] == "sprite.primus.idle"
    assert handle["source"] == "lpc"


def test_resolve_furniture_from_kenney():
    registry = build_default_registry()
    handle = registry.resolve("furniture.desk")
    assert handle["source"] == "kenney"


def test_resolve_decoration_from_custom_source():
    registry = build_default_registry()
    handle = registry.resolve("decoration.wall-poster-brainai-logo")
    assert handle["source"] == "custom"


def test_resolve_furniture_from_opengameart():
    registry = build_default_registry()
    handle = registry.resolve("furniture.monitor")
    assert handle["source"] == "opengameart"


def test_unresolved_asset_raises():
    registry = build_default_registry()
    with pytest.raises(UnresolvedAssetError):
        registry.resolve("sprite.nonexistent-character.idle")


def test_resolution_is_cached():
    registry = build_default_registry()
    first = registry.resolve("sprite.primus.idle")
    second = registry.resolve("sprite.primus.idle")
    assert first is second
