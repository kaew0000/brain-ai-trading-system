"""NotificationCenter — Notifications section.

The phase brief states "Notifications consume SimulationState only," so
this deliberately does NOT read `world.runtime.models.NotificationState`
(Phase W5's own notification model, sourced from
`world/data/runtime/notifications.json`) even though that would be the
more obvious source. Every `InteractionNotification` here is derived from
`world.simulation.models.SimulationState` alone: `EventDescriptor.kind`
and `RoomActivityState.activity`.

Category mapping (`EVENT_KIND_TO_CATEGORY` / `ROOM_ACTIVITY_TO_CATEGORY`)
is this phase's own judgment call, made explicit here rather than left
implicit, since `SimulationState` has no `category` field of its own to
read: `risk_alert` -> alert, `system_recovery` -> system_status,
`portfolio_growth` -> celebration, `trade_opened`/`trade_closed` ->
mission (the closest available reading of "ongoing mission-like
activity," since `SimulationState` carries no mission identity of its
own), generic `notification` -> system_status. Room activity `critical`
-> emergency, `meeting` -> meeting, `celebration` -> celebration
(redundant with the event-kind mapping when both fire the same tick;
`build_notifications` de-duplicates by `notification_id`).
"""

from world.interaction.models import InteractionNotification
from world.simulation import api as simulation_api
from world.simulation.models import SimulationState

EVENT_KIND_TO_CATEGORY = {
    "risk_alert": "alert",
    "system_recovery": "system_status",
    "portfolio_growth": "celebration",
    "trade_opened": "mission",
    "trade_closed": "mission",
    "notification": "system_status",
}

ROOM_ACTIVITY_TO_CATEGORY = {
    "critical": "emergency",
    "meeting": "meeting",
    "celebration": "celebration",
}


def build_notifications(
    get_simulation_state=simulation_api.get_simulation_state,
) -> tuple[InteractionNotification, ...]:
    state: SimulationState = get_simulation_state()
    notifications: list[InteractionNotification] = []
    seen_ids: set[str] = set()

    for event in state.events:
        category = EVENT_KIND_TO_CATEGORY.get(event.kind, "system_status")
        notif_id = f"event:{event.event_id}"
        if notif_id in seen_ids:
            continue
        seen_ids.add(notif_id)
        notifications.append(InteractionNotification(
            notification_id=notif_id, category=category, room_id=event.room_id,
            tick_number=state.tick.tick_number, message=event.message, agent_id=event.agent_id,
        ))

    for room in state.rooms:
        category = ROOM_ACTIVITY_TO_CATEGORY.get(room.activity)
        if category is None:
            continue
        notif_id = f"room:{room.room_id}:{state.tick.tick_number}:{room.activity}"
        if notif_id in seen_ids:
            continue
        seen_ids.add(notif_id)
        notifications.append(InteractionNotification(
            notification_id=notif_id, category=category, room_id=room.room_id,
            tick_number=state.tick.tick_number,
            message=f"{room.room_id} is {room.activity} ({room.occupant_count} occupants)",
        ))

    return tuple(notifications)


def filter_by_category(
    notifications: tuple[InteractionNotification, ...], category: str,
) -> tuple[InteractionNotification, ...]:
    return tuple(n for n in notifications if n.category == category)
