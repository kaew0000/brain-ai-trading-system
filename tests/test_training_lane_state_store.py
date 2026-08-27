"""tests/test_training_lane_state_store.py — V16 Phase 4C §49:
training_lane/state_store.py's own persistence mechanics, independent
of TrainingLaneRunner."""
from __future__ import annotations

import os
import tempfile

import pytest

from training_lane.state_store import (
    TrainingLaneStateStore,
    get_training_lane_state_store,
    reset_training_lane_state_store,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class TestSaveAndLoad:
    def test_load_returns_none_when_nothing_saved_yet(self, db_path):
        store = TrainingLaneStateStore(db_path=db_path)
        assert store.load_state() is None

    def test_save_then_load_roundtrips(self, db_path):
        store = TrainingLaneStateStore(db_path=db_path)
        state = {"symbol": "ETHUSDT", "bust_count": 2, "nested": {"a": [1, 2, 3]}}
        store.save_state(state)
        assert store.load_state() == state

    def test_save_twice_overwrites_not_duplicates(self, db_path):
        store = TrainingLaneStateStore(db_path=db_path)
        store.save_state({"symbol": "BTCUSDT"})
        store.save_state({"symbol": "ETHUSDT"})
        loaded = store.load_state()
        assert loaded == {"symbol": "ETHUSDT"}

        with store._conn() as c:
            count = c.execute("SELECT COUNT(*) AS n FROM training_lane_state").fetchone()["n"]
        assert count == 1

    def test_two_store_instances_same_path_see_each_others_writes(self, db_path):
        writer = TrainingLaneStateStore(db_path=db_path)
        reader = TrainingLaneStateStore(db_path=db_path)
        writer.save_state({"symbol": "SOLUSDT"})
        assert reader.load_state() == {"symbol": "SOLUSDT"}


class TestNeverRaises:
    def test_save_state_never_raises_on_unwritable_path(self):
        store = TrainingLaneStateStore(db_path="/nonexistent-dir-xyz/cannot-write.db")
        store.save_state({"symbol": "BTCUSDT"})  # must not raise

    def test_load_state_never_raises_on_unwritable_path(self):
        store = TrainingLaneStateStore(db_path="/nonexistent-dir-xyz/cannot-write.db")
        assert store.load_state() is None  # must not raise


class TestSingletonAccessor:
    def setup_method(self):
        reset_training_lane_state_store()

    def teardown_method(self):
        reset_training_lane_state_store()

    def test_returns_the_same_instance_on_repeated_calls(self):
        first = get_training_lane_state_store()
        second = get_training_lane_state_store()
        assert first is second

    def test_reset_replaces_the_cached_instance(self, db_path):
        first = get_training_lane_state_store()
        reset_training_lane_state_store(db_path=db_path)
        second = get_training_lane_state_store()
        assert first is not second
        assert second.db_path == db_path
