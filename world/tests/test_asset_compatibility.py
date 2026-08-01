"""Phase W6: asset versioning / compatibility layer."""
from world.frontend.asset_loader.compatibility import is_compatible, unknown_engines


def test_compatible_engine_returns_true():
    entry = {"compatibleWith": ["pixijs", "phaser"]}
    assert is_compatible(entry, "pixijs") is True


def test_incompatible_engine_returns_false():
    entry = {"compatibleWith": ["pixijs", "phaser"]}
    assert is_compatible(entry, "unity") is False


def test_empty_compatible_with_is_universally_compatible():
    entry = {"compatibleWith": []}
    assert is_compatible(entry, "godot") is True


def test_missing_compatible_with_is_universally_compatible():
    entry = {}
    assert is_compatible(entry, "react") is True


def test_unknown_engines_flags_typos():
    entry = {"compatibleWith": ["pixijs", "unrealengine"]}
    assert unknown_engines(entry) == ["unrealengine"]


def test_unknown_engines_empty_for_all_known():
    entry = {"compatibleWith": ["pixijs", "phaser", "godot", "unity", "react"]}
    assert unknown_engines(entry) == []
