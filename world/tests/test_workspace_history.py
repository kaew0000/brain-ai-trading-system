"""Phase W12: NavigationHistory — undo navigation only."""
from world.workspace.history import NavigationHistory


def test_record_returns_the_entry():
    h = NavigationHistory()
    entry = h.record("selection", {"roomId": "ceo-tower"}, "t1")
    assert entry.kind == "selection"
    assert entry.payload == {"roomId": "ceo-tower"}


def test_current_is_the_latest_recorded_entry():
    h = NavigationHistory()
    h.record("selection", {}, "t1")
    h.record("camera", {}, "t2")
    assert h.current().kind == "camera"


def test_undo_moves_cursor_back_one():
    h = NavigationHistory()
    h.record("selection", {"a": 1}, "t1")
    h.record("camera", {"b": 2}, "t2")
    prev = h.undo()
    assert prev.kind == "selection"
    assert h.current().kind == "selection"


def test_undo_at_the_beginning_returns_none():
    h = NavigationHistory()
    h.record("selection", {}, "t1")
    assert h.undo() is None
    assert h.current().kind == "selection"


def test_undo_on_empty_history_returns_none():
    h = NavigationHistory()
    assert h.undo() is None
    assert h.current() is None


def test_recording_after_undo_discards_the_redone_future():
    h = NavigationHistory()
    h.record("a", {}, "t1")
    h.record("b", {}, "t2")
    h.undo()
    h.record("c", {}, "t3")
    entries = h.all_entries()
    assert [e.kind for e in entries] == ["a", "c"]


def test_max_entries_bounds_history_length():
    h = NavigationHistory(max_entries=3)
    for i in range(5):
        h.record("kind", {"i": i}, f"t{i}")
    assert len(h) == 3
    assert [e.payload["i"] for e in h.all_entries()] == [2, 3, 4]


def test_entry_ids_increment_monotonically():
    h = NavigationHistory()
    e1 = h.record("a", {}, "t1")
    e2 = h.record("b", {}, "t2")
    assert e2.entry_id == e1.entry_id + 1


def test_reset_clears_everything():
    h = NavigationHistory()
    h.record("a", {}, "t1")
    h.reset()
    assert len(h) == 0
    assert h.current() is None


def test_serializes_to_dict():
    import json
    h = NavigationHistory()
    entry = h.record("selection", {"roomId": "ceo-tower"}, "t1")
    json.dumps(entry.to_dict())
