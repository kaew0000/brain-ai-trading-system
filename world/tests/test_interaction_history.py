"""Phase W9: InteractionHistory."""

import pytest

from world.interaction.interaction_history import InteractionHistory


def test_record_selection_and_command():
    history = InteractionHistory()
    history.record_selection("room", "risk-fortress")
    history.record_command("focus_room", ok=True, detail="")
    records = history.all()
    assert len(records) == 2
    assert records[0].kind == "selection"
    assert records[0].detail == {"selectionKind": "room", "targetId": "risk-fortress"}
    assert records[1].kind == "command"
    # Phase W13-2 — record_command() gained audit metadata fields, all
    # with defaults matching the pre-W13-2 3-positional-arg call above
    # exactly, so this call site (unchanged from Phase W9) still works.
    assert records[1].detail["command"] == "focus_room"
    assert records[1].detail["ok"] is True
    assert records[1].detail["detail"] == ""
    assert records[1].detail["actor"] == "unknown"
    assert records[1].detail["parameters"] == {}
    assert records[1].detail["durationMs"] is None
    assert isinstance(records[1].detail["timestamp"], str) and records[1].detail["timestamp"]


def test_history_window_bounds_memory():
    history = InteractionHistory(history_window=3)
    for i in range(10):
        history.record_selection("room", f"room-{i}")
    assert len(history) == 3
    assert history.all()[-1].detail["targetId"] == "room-9"


def test_clear_empties_history():
    history = InteractionHistory()
    history.record_selection("room", "risk-fortress")
    history.clear()
    assert len(history) == 0


def test_invalid_window_raises():
    with pytest.raises(ValueError):
        InteractionHistory(history_window=0)
