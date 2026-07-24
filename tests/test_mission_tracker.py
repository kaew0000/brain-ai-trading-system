"""
tests/test_mission_tracker.py
================================
v14 Phase 2.5 — Mission Pipeline test suite (standalone module + API).

Covers:
  - MissionTracker core behaviour (create/advance/get/list/get_active/clear)
  - Forward-only transition enforcement + CLOSED-from-anywhere abort path
  - Bounded store eviction
  - GET /api/missions, GET /api/missions/{id}
  - WS /ws/missions (always sends init frame)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_tracker():
    from missions.mission_tracker import reset_mission_tracker
    reset_mission_tracker()
    yield
    reset_mission_tracker()


# ─────────────────────────────────────────────────────────────────────────────
# Core: create / advance
# ─────────────────────────────────────────────────────────────────────────────
class TestMissionCreate:

    def test_create_returns_mission_at_signal_found(self):
        from missions.mission_tracker import get_mission_tracker
        m = get_mission_tracker().create(symbol="BTCUSDT", direction="LONG", confidence=78.0)
        assert m.stage == "SIGNAL_FOUND"
        assert m.symbol == "BTCUSDT"
        assert m.direction == "LONG"
        assert m.confidence == 78.0

    def test_create_generates_unique_ids(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m1 = t.create(symbol="BTCUSDT", direction="LONG")
        m2 = t.create(symbol="BTCUSDT", direction="LONG")
        assert m1.id != m2.id

    def test_create_records_initial_history_entry(self):
        from missions.mission_tracker import get_mission_tracker
        m = get_mission_tracker().create(symbol="BTCUSDT", direction="SHORT")
        assert len(m.history) == 1
        assert m.history[0]["stage"] == "SIGNAL_FOUND"

    def test_create_stores_meta(self):
        from missions.mission_tracker import get_mission_tracker
        m = get_mission_tracker().create(symbol="BTCUSDT", direction="LONG",
                                          meta={"entry_price": 67000.0})
        assert m.meta["entry_price"] == 67000.0

    def test_create_default_confidence_zero(self):
        from missions.mission_tracker import get_mission_tracker
        m = get_mission_tracker().create(symbol="BTCUSDT", direction="LONG")
        assert m.confidence == 0.0


class TestMissionAdvance:

    def test_advance_through_full_lifecycle(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        for stage in ("VALIDATION", "RISK_CHECK", "EXECUTION", "MONITORING", "CLOSED"):
            m = t.advance(m.id, stage)
        assert m.stage == "CLOSED"
        assert len(m.history) == 6   # SIGNAL_FOUND + 5 advances

    def test_advance_unknown_mission_raises_keyerror(self):
        from missions.mission_tracker import get_mission_tracker
        with pytest.raises(KeyError):
            get_mission_tracker().advance("nonexistent_id", "VALIDATION")

    def test_advance_unknown_stage_raises_valueerror(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        with pytest.raises(ValueError):
            t.advance(m.id, "NOT_A_REAL_STAGE")

    def test_advance_backward_raises_invalid_transition(self):
        from missions.mission_tracker import get_mission_tracker, InvalidTransitionError
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        t.advance(m.id, "VALIDATION")
        t.advance(m.id, "RISK_CHECK")
        with pytest.raises(InvalidTransitionError):
            t.advance(m.id, "VALIDATION")   # backward — illegal

    def test_advance_same_stage_raises_invalid_transition(self):
        from missions.mission_tracker import get_mission_tracker, InvalidTransitionError
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        with pytest.raises(InvalidTransitionError):
            t.advance(m.id, "SIGNAL_FOUND")   # no-op — illegal

    def test_advance_skip_stages_forward_allowed(self):
        """Forward-only rule permits skipping intermediate stages
        (e.g. SIGNAL_FOUND straight to EXECUTION) — only CLOSED-from-
        anywhere and strict-forward are enforced, not "every stage
        in sequence"."""
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        m = t.advance(m.id, "EXECUTION")   # skips VALIDATION, RISK_CHECK
        assert m.stage == "EXECUTION"

    def test_advance_to_closed_always_allowed_from_any_stage(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        for start_stage in ("SIGNAL_FOUND", "VALIDATION", "RISK_CHECK"):
            m = t.create(symbol="BTCUSDT", direction="LONG")
            if start_stage != "SIGNAL_FOUND":
                # walk forward to start_stage first
                idx = ["SIGNAL_FOUND", "VALIDATION", "RISK_CHECK"].index(start_stage)
                for s in ["VALIDATION", "RISK_CHECK"][:idx]:
                    t.advance(m.id, s)
            closed = t.advance(m.id, "CLOSED", note="aborted")
            assert closed.stage == "CLOSED"

    def test_advance_updates_timestamp(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        original_updated = m.updated_at
        import time; time.sleep(0.01)
        m2 = t.advance(m.id, "VALIDATION")
        assert m2.updated_at != original_updated

    def test_advance_with_note_recorded_in_history(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        m = t.advance(m.id, "CLOSED", note="Blocked by risk: daily loss limit")
        assert m.history[-1]["note"] == "Blocked by risk: daily loss limit"

    def test_advance_with_meta_update_merges(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG", meta={"entry_price": 67000.0})
        m = t.advance(m.id, "EXECUTION", meta_update={"order_id": "999"})
        assert m.meta["entry_price"] == 67000.0   # preserved
        assert m.meta["order_id"] == "999"        # merged in


# ─────────────────────────────────────────────────────────────────────────────
# get / list / get_active
# ─────────────────────────────────────────────────────────────────────────────
class TestMissionQueries:

    def test_get_returns_mission(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m = t.create(symbol="BTCUSDT", direction="LONG")
        fetched = t.get(m.id)
        assert fetched.id == m.id

    def test_get_unknown_returns_none(self):
        from missions.mission_tracker import get_mission_tracker
        assert get_mission_tracker().get("nope") is None

    def test_list_newest_first(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m1 = t.create(symbol="BTCUSDT", direction="LONG")
        m2 = t.create(symbol="BTCUSDT", direction="SHORT")
        listed = t.list(limit=10)
        assert listed[0]["id"] == m2.id
        assert listed[1]["id"] == m1.id

    def test_list_filters_by_stage(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m1 = t.create(symbol="BTCUSDT", direction="LONG")
        m2 = t.create(symbol="BTCUSDT", direction="SHORT")
        t.advance(m2.id, "VALIDATION")
        validation_only = t.list(stage="VALIDATION")
        assert len(validation_only) == 1
        assert validation_only[0]["id"] == m2.id

    def test_list_respects_limit(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        for _ in range(5):
            t.create(symbol="BTCUSDT", direction="LONG")
        assert len(t.list(limit=2)) == 2

    def test_get_active_excludes_closed(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m1 = t.create(symbol="BTCUSDT", direction="LONG")
        m2 = t.create(symbol="BTCUSDT", direction="SHORT")
        t.advance(m2.id, "CLOSED")
        active = t.get_active()
        assert len(active) == 1
        assert active[0]["id"] == m1.id

    def test_clear_empties_tracker(self):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        t.create(symbol="BTCUSDT", direction="LONG")
        t.clear()
        assert t.list() == []
        assert t.get_active() == []


# ─────────────────────────────────────────────────────────────────────────────
# Bounded store / capacity eviction
# ─────────────────────────────────────────────────────────────────────────────
class TestCapacity:

    def test_eviction_beyond_max_capacity(self):
        from missions.mission_tracker import MissionTracker, _MAX_MISSIONS
        t = MissionTracker()
        # Create slightly over capacity — should never exceed _MAX_MISSIONS
        for i in range(_MAX_MISSIONS + 5):
            t.create(symbol="BTCUSDT", direction="LONG")
        with t._lock:
            assert len(t._missions) == _MAX_MISSIONS

    def test_oldest_evicted_first(self):
        from missions.mission_tracker import MissionTracker, _MAX_MISSIONS
        t = MissionTracker()
        first = t.create(symbol="BTCUSDT", direction="LONG")
        for i in range(_MAX_MISSIONS):
            t.create(symbol="BTCUSDT", direction="LONG")
        assert t.get(first.id) is None   # evicted


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────
class TestSingleton:

    def test_singleton_persists(self):
        from missions.mission_tracker import get_mission_tracker
        assert get_mission_tracker() is get_mission_tracker()

    def test_thread_safety_concurrent_creates(self):
        from missions.mission_tracker import get_mission_tracker
        import threading
        t = get_mission_tracker()

        def worker():
            for _ in range(20):
                t.create(symbol="BTCUSDT", direction="LONG")

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for th in threads: th.start()
        for th in threads: th.join()

        assert len(t.list(limit=1000)) == 100


# ─────────────────────────────────────────────────────────────────────────────
# API: GET /api/missions
# ─────────────────────────────────────────────────────────────────────────────
class TestMissionsAPI:

    @pytest.fixture
    def client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_endpoint_200(self, client):
        r = client.get("/api/missions")
        assert r.status_code == 200

    def test_endpoint_empty_returns_empty_list(self, client):
        body = client.get("/api/missions").json()
        assert body["data"]["missions"] == []
        assert body["data"]["mission_count"] == 0

    def test_endpoint_returns_stages_list(self, client):
        body = client.get("/api/missions").json()
        assert body["data"]["stages"] == [
            "SIGNAL_FOUND", "VALIDATION", "RISK_CHECK",
            "EXECUTION", "MONITORING", "CLOSED",
        ]

    def test_endpoint_returns_created_mission(self, client):
        from missions.mission_tracker import get_mission_tracker
        get_mission_tracker().create(symbol="BTCUSDT", direction="LONG", confidence=80.0)
        body = client.get("/api/missions").json()
        assert body["data"]["mission_count"] == 1
        assert body["data"]["missions"][0]["direction"] == "LONG"

    def test_endpoint_stage_filter(self, client):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m1 = t.create(symbol="BTCUSDT", direction="LONG")
        m2 = t.create(symbol="BTCUSDT", direction="SHORT")
        t.advance(m2.id, "VALIDATION")
        body = client.get("/api/missions?stage=VALIDATION").json()
        assert body["data"]["mission_count"] == 1

    def test_endpoint_active_only_excludes_closed(self, client):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        m1 = t.create(symbol="BTCUSDT", direction="LONG")
        m2 = t.create(symbol="BTCUSDT", direction="SHORT")
        t.advance(m2.id, "CLOSED")
        body = client.get("/api/missions?active_only=true").json()
        assert body["data"]["mission_count"] == 1

    def test_endpoint_limit_param(self, client):
        from missions.mission_tracker import get_mission_tracker
        t = get_mission_tracker()
        for _ in range(5):
            t.create(symbol="BTCUSDT", direction="LONG")
        body = client.get("/api/missions?limit=2").json()
        assert body["data"]["mission_count"] == 2

    def test_detail_endpoint_200(self, client):
        from missions.mission_tracker import get_mission_tracker
        m = get_mission_tracker().create(symbol="BTCUSDT", direction="LONG")
        r = client.get(f"/api/missions/{m.id}")
        assert r.status_code == 200

    def test_detail_endpoint_returns_history(self, client):
        from missions.mission_tracker import get_mission_tracker
        m = get_mission_tracker().create(symbol="BTCUSDT", direction="LONG")
        body = client.get(f"/api/missions/{m.id}").json()
        assert "history" in body["data"]

    def test_detail_endpoint_404_unknown_id(self, client):
        r = client.get("/api/missions/does_not_exist")
        assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# WS: /ws/missions
# ─────────────────────────────────────────────────────────────────────────────
class TestMissionsWebSocket:

    def test_ws_missions_sends_init_when_empty(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/missions") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert msg["data"] == []

    def test_ws_missions_sends_init_with_active_mission(self):
        from api.app import app
        from missions.mission_tracker import get_mission_tracker
        from fastapi.testclient import TestClient
        get_mission_tracker().create(symbol="BTCUSDT", direction="LONG", confidence=70.0)
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/missions") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert len(msg["data"]) == 1
            assert msg["data"][0]["direction"] == "LONG"
