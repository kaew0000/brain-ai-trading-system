"""Phase W9: NotificationCenter — must consume SimulationState only."""

from world.interaction.notification_center import build_notifications, filter_by_category
from world.simulation.models import EventDescriptor, RoomActivityState, SimulationState, SimulationTick


def _fake_simulation_state():
    return SimulationState(
        tick=SimulationTick(tick_number=7, simulated_seconds=7.0, world_sequence=7),
        rooms=(
            RoomActivityState(room_id="risk-fortress", activity="critical", occupant_count=2),
            RoomActivityState(room_id="ai-council", activity="meeting", occupant_count=3),
            RoomActivityState(room_id="lobby", activity="quiet", occupant_count=0),
        ),
        events=(
            EventDescriptor(event_id="evt-1", kind="risk_alert", room_id="risk-fortress",
                             agent_id="bastion", message="risk flagged"),
            EventDescriptor(event_id="evt-2", kind="portfolio_growth", room_id="portfolio-garden",
                             message="portfolio up"),
            EventDescriptor(event_id="evt-3", kind="trade_opened", room_id="trading-floor",
                             message="new trade"),
        ),
    )


def test_build_notifications_maps_event_kinds_to_categories():
    notifications = build_notifications(get_simulation_state=_fake_simulation_state)
    by_id = {n.notification_id: n for n in notifications}
    assert by_id["event:evt-1"].category == "alert"
    assert by_id["event:evt-2"].category == "celebration"
    assert by_id["event:evt-3"].category == "mission"


def test_build_notifications_includes_room_activity_derived_entries():
    notifications = build_notifications(get_simulation_state=_fake_simulation_state)
    categories = {n.category for n in notifications}
    assert "emergency" in categories  # from risk-fortress's "critical" activity
    assert "meeting" in categories  # from ai-council's "meeting" activity


def test_quiet_rooms_produce_no_notification():
    notifications = build_notifications(get_simulation_state=_fake_simulation_state)
    assert not any(n.room_id == "lobby" for n in notifications)


def test_notifications_carry_tick_number():
    notifications = build_notifications(get_simulation_state=_fake_simulation_state)
    assert all(n.tick_number == 7 for n in notifications)


def test_filter_by_category():
    notifications = build_notifications(get_simulation_state=_fake_simulation_state)
    alerts = filter_by_category(notifications, "alert")
    assert len(alerts) == 1
    assert alerts[0].notification_id == "event:evt-1"


def test_no_duplicate_ids():
    notifications = build_notifications(get_simulation_state=_fake_simulation_state)
    ids = [n.notification_id for n in notifications]
    assert len(ids) == len(set(ids))
