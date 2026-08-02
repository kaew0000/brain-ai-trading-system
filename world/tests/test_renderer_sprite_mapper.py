"""Phase W8: SpriteMapper behaviour -> animation-state fallback and
character_assets.json-backed sprite id resolution."""

import pytest

from world.frontend.renderer.render_config import BEHAVIOR_TO_ANIMATION_STATE
from world.frontend.renderer.sprite_mapper import SpriteMapper, UnknownCharacterError
from world.simulation.models import CHARACTER_BEHAVIORS


def test_every_character_behavior_has_a_fallback_mapping():
    """The seven Phase W7 behaviour labels must all resolve to one of
    the five real animation states — this is the gap this phase found
    and had to resolve; this test pins that resolution."""
    for behavior in CHARACTER_BEHAVIORS:
        assert behavior in BEHAVIOR_TO_ANIMATION_STATE


def test_fallback_targets_are_real_animation_states():
    real_states = {"idle", "walking", "working", "celebration", "emergency"}
    for target in BEHAVIOR_TO_ANIMATION_STATE.values():
        assert target in real_states


def test_meeting_and_resting_fall_back_as_documented():
    mapper = SpriteMapper()
    assert mapper.animation_state_for("meeting") == "working"
    assert mapper.animation_state_for("resting") == "idle"


def test_identity_mapped_states_are_unchanged():
    mapper = SpriteMapper()
    for state in ("idle", "walking", "working", "celebration", "emergency"):
        assert mapper.animation_state_for(state) == state


def test_unrecognized_behavior_raises_value_error():
    mapper = SpriteMapper()
    with pytest.raises(ValueError):
        mapper.animation_state_for("dancing")


def test_asset_id_for_resolves_every_real_character_and_behavior():
    """Every one of the 16 real characters, in every one of the seven
    Phase W7 behaviours, must resolve to a non-empty asset id string —
    this is the actual bridge this phase built between the two
    previously-disconnected data sources."""
    mapper = SpriteMapper()
    assert len(mapper.known_character_ids()) == 16
    for character_id in mapper.known_character_ids():
        for behavior in CHARACTER_BEHAVIORS:
            asset_id = mapper.asset_id_for(character_id, behavior)
            assert isinstance(asset_id, str) and asset_id


def test_asset_id_uses_dotted_manifest_convention_not_stale_underscore_ids():
    """Regression pin for the real mismatch found this phase: the
    character definitions' `spriteMeta.animations` (e.g.
    `"bastion_idle"`) never resolve against
    `asset_manifest.json`; `character_assets.json`'s dotted ids
    (e.g. `"sprite.bastion.idle"`) do."""
    mapper = SpriteMapper()
    asset_id = mapper.asset_id_for("bastion", "idle")
    assert asset_id == "sprite.bastion.idle"


def test_unknown_character_raises():
    mapper = SpriteMapper()
    with pytest.raises(UnknownCharacterError):
        mapper.asset_id_for("not-a-real-character", "idle")


def test_refresh_reloads_from_disk():
    mapper = SpriteMapper()
    before = mapper.known_character_ids()
    mapper.refresh()
    assert mapper.known_character_ids() == before
