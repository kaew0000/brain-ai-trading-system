"""Event animation model — Part E. Metadata-only descriptors: no graphics,
no renderer hints, just `kind` + `where` + `who` + `when` + `what`.

`world.runtime.models.EventState.event_type` is whatever raw string the
trading engine happens to log (Phase W4 doesn't constrain it — see
`world/docs/INGESTION_ADAPTER.md`), so `classify_event_kind` is a
best-effort, documented substring mapping down to this phase's fixed
`EVENT_KINDS`, not a guarantee the engine uses these exact words. Anything
that doesn't match a known pattern still gets a descriptor — classified as
`"notification"`, the catch-all kind — rather than being silently dropped.
"""

from world.runtime.models import EventState, NotificationState, WorldState
from world.simulation.models import EVENT_KINDS, EventDescriptor

_KEYWORD_TO_KIND = (
    ("open", "trade_opened"),
    ("close", "trade_closed"),
    ("fill", "trade_closed"),
    ("risk", "risk_alert"),
    ("alert", "risk_alert"),
    ("recover", "system_recovery"),
    ("growth", "portfolio_growth"),
    ("portfolio", "portfolio_growth"),
)


def classify_event_kind(raw_event_type: str) -> str:
    lowered = raw_event_type.lower()
    for keyword, kind in _KEYWORD_TO_KIND:
        if keyword in lowered:
            assert kind in EVENT_KINDS, f"invalid event kind mapping: {kind!r}"
            return kind
    return "notification"


def _from_event(e: EventState) -> EventDescriptor:
    return EventDescriptor(
        event_id=e.event_id,
        kind=classify_event_kind(e.event_type),
        room_id=e.district,
        agent_id=e.agent,
        timestamp=e.timestamp,
        message=e.message,
    )


def _from_notification(n: NotificationState) -> EventDescriptor:
    return EventDescriptor(
        event_id=n.notification_id,
        kind="notification",
        room_id="",
        timestamp=n.timestamp,
        message=n.message,
    )


def build_event_descriptors(state: WorldState) -> tuple[EventDescriptor, ...]:
    """Every Phase W5 event plus every notification, as Phase W7
    descriptors — this tick's complete "what happened" list, for
    `Timeline` to record and `get_current_events()` to expose."""
    descriptors = [_from_event(e) for e in state.events]
    descriptors.extend(_from_notification(n) for n in state.notifications)
    return tuple(descriptors)
