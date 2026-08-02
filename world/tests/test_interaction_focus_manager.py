"""Phase W9: FocusManager — thin wrapper around ReferenceCameraController."""

import pytest

from world.interaction.focus_manager import FocusManager

_ANCHORS = {"risk-fortress": (5.0, 6.0), "lobby": (0.0, 0.0)}


def test_focus_room_uses_room_anchor():
    manager = FocusManager(room_anchors=_ANCHORS)
    state = manager.focus_room("risk-fortress")
    assert (state.x, state.y) == (5.0, 6.0)


def test_focus_unknown_room_raises_key_error():
    manager = FocusManager(room_anchors=_ANCHORS)
    with pytest.raises(KeyError):
        manager.focus_room("nonexistent")


def test_follow_character_requires_a_known_position_first():
    manager = FocusManager(room_anchors=_ANCHORS)
    with pytest.raises(KeyError):
        manager.follow_character("bastion")
    manager.update_character_position("bastion", 1.0, 2.0)
    state = manager.follow_character("bastion")
    assert (state.x, state.y) == (1.0, 2.0)


def test_default_construction_loads_real_room_anchors_without_raising():
    manager = FocusManager()
    state = manager.focus_room("risk-fortress")
    assert isinstance(state.x, float)
