"""
tests/test_recommendation_events.py — V16 Phase 4C Step 3
(learning/application/recommendation_events.py)
"""
from __future__ import annotations

import pytest

from events.event_bus import reset_event_bus
from learning.application.recommendation_events import (
    publish_recommendation_applied,
    publish_recommendation_contradicted,
    publish_recommendation_expired,
    publish_recommendation_loaded,
    publish_recommendation_skipped,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_bus():
    bus = reset_event_bus(persist=False)
    yield bus


class TestEventPublishing:

    def test_loaded_event(self):
        publish_recommendation_loaded(5, symbol="BTCUSDT")
        from events.event_bus import get_event_bus
        recent = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_LOADED")
        assert len(recent) == 1
        assert recent[0]["payload"]["count"] == 5
        assert recent[0]["payload"]["symbol"] == "BTCUSDT"

    def test_applied_event(self):
        publish_recommendation_applied("abc123", score=0.75, symbol="ETHUSDT")
        from events.event_bus import get_event_bus
        recent = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_APPLIED")
        assert len(recent) == 1
        assert recent[0]["payload"]["recommendation_id"] == "abc123"
        assert recent[0]["payload"]["score"] == 0.75

    def test_skipped_event(self):
        publish_recommendation_skipped("abc123", reason="symbol_mismatch")
        from events.event_bus import get_event_bus
        recent = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_SKIPPED")
        assert recent[0]["payload"]["reason"] == "symbol_mismatch"

    def test_expired_event(self):
        publish_recommendation_expired("abc123")
        from events.event_bus import get_event_bus
        recent = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_EXPIRED")
        assert len(recent) == 1

    def test_contradicted_event(self):
        publish_recommendation_contradicted("abc123", reason="contradicted_by=def456")
        from events.event_bus import get_event_bus
        recent = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_CONTRADICTED")
        assert recent[0]["payload"]["reason"] == "contradicted_by=def456"
        assert recent[0]["severity"] == "warning"

    def test_publish_failure_never_raises(self, monkeypatch):
        """A broken EventBus must not be able to take down a caller mid
        decision cycle — publish is fire-and-forget."""
        import learning.application.recommendation_events as ev_mod

        def _boom(*a, **k):
            raise RuntimeError("bus is down")

        monkeypatch.setattr(ev_mod, "get_event_bus", _boom)
        publish_recommendation_loaded(1)  # must not raise
