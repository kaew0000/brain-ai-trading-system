"""world/workspace/notification_dock.py — Phase W12, Feature 4.

Reuses Phase W9's `world.interaction.api.get_notifications()` /
`get_notifications_by_category()` verbatim — "no backend changes" per
this phase's own brief. `InteractionNotification` (Phase W9) already has
`category` (one of `NOTIFICATION_CATEGORIES`: emergency/meeting/alert/
mission/celebration/system_status) and `tick_number`, but no `read` or
`pinned` concept at that layer — those two flags are purely
workspace-layer UI state, tracked here exactly like Phase W9's own
`InteractionHistory` (in-memory, bounded, not persisted across restarts).
"""

from dataclasses import dataclass, field

from world.interaction import api as interaction_api
from world.workspace.models import NotificationDockItem


@dataclass
class NotificationDockStore:
    """Holds pinned/read/cleared notification-id sets — the only state
    this feature needs beyond what `world.interaction` already tracks."""

    pinned_ids: set = field(default_factory=set)
    read_ids: set = field(default_factory=set)
    cleared_ids: set = field(default_factory=set)

    def pin(self, notification_id: str) -> None:
        self.pinned_ids.add(notification_id)

    def unpin(self, notification_id: str) -> None:
        self.pinned_ids.discard(notification_id)

    def mark_read(self, notification_id: str) -> None:
        self.read_ids.add(notification_id)

    def clear(self, notification_id: str) -> None:
        self.cleared_ids.add(notification_id)

    def clear_all(self, items: tuple) -> None:
        for item in items:
            self.cleared_ids.add(item.notification_id)

    def reset(self) -> None:
        self.pinned_ids.clear()
        self.read_ids.clear()
        self.cleared_ids.clear()


def build_dock_items(
    store: NotificationDockStore, category: str | None = None, unread_only: bool = False,
) -> tuple[NotificationDockItem, ...]:
    source = (
        interaction_api.get_notifications_by_category(category)
        if category else interaction_api.get_notifications()
    )
    items = []
    for n in source:
        if n.notification_id in store.cleared_ids:
            continue
        is_read = n.notification_id in store.read_ids
        if unread_only and is_read:
            continue
        items.append(NotificationDockItem(
            notification_id=n.notification_id, category=n.category, room_id=n.room_id,
            tick_number=n.tick_number, message=n.message, agent_id=n.agent_id,
            read=is_read, pinned=n.notification_id in store.pinned_ids,
        ))

    # Pinned items first; within each group, most recent tick first.
    pinned = sorted((i for i in items if i.pinned), key=lambda i: i.tick_number, reverse=True)
    unpinned = sorted((i for i in items if not i.pinned), key=lambda i: i.tick_number, reverse=True)
    return tuple(pinned + unpinned)
