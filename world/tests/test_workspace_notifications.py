"""Phase W12: notification_dock — pin/read/clear/filter over the real
Phase W9 NotificationCenter (InteractionNotification: category/room_id/
tick_number/message/agent_id — no timestamp/severity/read at that layer)."""
from world.interaction import api as interaction_api
from world.interaction.models import InteractionNotification
from world.workspace.notification_dock import NotificationDockStore, build_dock_items


def test_empty_store_returns_whatever_notification_center_has():
    store = NotificationDockStore()
    items = build_dock_items(store)
    assert isinstance(items, tuple)


def test_pin_marks_item_pinned(monkeypatch):
    fake = (InteractionNotification(notification_id="n1", category="alert", room_id="risk-fortress",
                                     tick_number=1, message="m"),)
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    store = NotificationDockStore()
    store.pin("n1")
    items = build_dock_items(store)
    assert items[0].pinned is True


def test_cleared_item_is_excluded(monkeypatch):
    fake = (InteractionNotification(notification_id="n1", category="alert", room_id="risk-fortress",
                                     tick_number=1, message="m"),)
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    store = NotificationDockStore()
    store.clear("n1")
    items = build_dock_items(store)
    assert items == ()


def test_unread_only_filters_read_items(monkeypatch):
    fake = (
        InteractionNotification(notification_id="n1", category="alert", room_id="risk-fortress",
                                 tick_number=1, message="read"),
        InteractionNotification(notification_id="n2", category="alert", room_id="risk-fortress",
                                 tick_number=2, message="unread"),
    )
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    store = NotificationDockStore()
    store.mark_read("n1")
    items = build_dock_items(store, unread_only=True)
    assert len(items) == 1
    assert items[0].notification_id == "n2"


def test_pinned_items_sort_first_even_if_older_tick(monkeypatch):
    fake = (
        InteractionNotification(notification_id="n1", category="alert", room_id="risk-fortress",
                                 tick_number=5, message="a"),
        InteractionNotification(notification_id="n2", category="alert", room_id="risk-fortress",
                                 tick_number=1, message="b"),
    )
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    store = NotificationDockStore()
    store.pin("n2")  # older tick, but pinned
    items = build_dock_items(store)
    assert items[0].notification_id == "n2"


def test_category_passes_through_unmodified(monkeypatch):
    fake = (InteractionNotification(notification_id="n1", category="emergency", room_id="risk-fortress",
                                     tick_number=1, message="m"),)
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    store = NotificationDockStore()
    items = build_dock_items(store)
    assert items[0].category == "emergency"


def test_category_filter_calls_get_notifications_by_category(monkeypatch):
    calls = []

    def fake_by_category(category):
        calls.append(category)
        return ()

    monkeypatch.setattr(interaction_api, "get_notifications_by_category", fake_by_category)
    store = NotificationDockStore()
    build_dock_items(store, category="mission")
    assert calls == ["mission"]


def test_reset_clears_all_tracked_sets():
    store = NotificationDockStore()
    store.pin("n1")
    store.mark_read("n2")
    store.clear("n3")
    store.reset()
    assert store.pinned_ids == set()
    assert store.read_ids == set()
    assert store.cleared_ids == set()
