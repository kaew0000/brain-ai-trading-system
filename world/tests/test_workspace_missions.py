"""Phase W12: mission_workspace — status->bucket mapping."""
from world.runtime.models import MissionState, WorldState
from world.workspace.mission_workspace import build_mission_workspace, group_by_bucket


def _state(*missions):
    return WorldState(missions=missions)


def test_proposed_maps_to_waiting():
    m = MissionState(mission_id="m1", title="X", district="ceo-tower", status="proposed")
    items = build_mission_workspace(_state(m))
    assert items[0].bucket == "waiting"


def test_active_maps_to_active():
    m = MissionState(mission_id="m1", title="X", district="ceo-tower", status="active")
    items = build_mission_workspace(_state(m))
    assert items[0].bucket == "active"


def test_complete_maps_to_completed():
    m = MissionState(mission_id="m1", title="X", district="ceo-tower", status="complete")
    items = build_mission_workspace(_state(m))
    assert items[0].bucket == "completed"


def test_aborted_maps_to_blocked():
    m = MissionState(mission_id="m1", title="X", district="ceo-tower", status="aborted")
    items = build_mission_workspace(_state(m))
    assert items[0].bucket == "blocked"


def test_group_by_bucket_covers_all_four_buckets_even_when_empty():
    grouped = group_by_bucket(())
    assert set(grouped.keys()) == {"waiting", "active", "completed", "blocked"}
    assert all(v == () for v in grouped.values())


def test_group_by_bucket_sorts_missions_correctly():
    m1 = MissionState(mission_id="m1", title="A", district="ceo-tower", status="active")
    m2 = MissionState(mission_id="m2", title="B", district="ceo-tower", status="complete")
    items = build_mission_workspace(_state(m1, m2))
    grouped = group_by_bucket(items)
    assert len(grouped["active"]) == 1
    assert len(grouped["completed"]) == 1


def test_serializes_to_dict():
    import json
    m = MissionState(mission_id="m1", title="X", district="ceo-tower", status="active")
    items = build_mission_workspace(_state(m))
    json.dumps([i.to_dict() for i in items])
