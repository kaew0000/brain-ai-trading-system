"""WorldState — the concrete, engine-agnostic snapshot shape a
`Renderer.render(world_state)` consumes on every update.

Phase W3 ships the *shape* only. Every field defaults to an empty
collection because no `WorldStateProvider` implementation exists yet
(that is Phase W4, the read-only ingestion adapter). Constructing a
`WorldState` today is only useful for tests and for a future
placeholder/mock renderer."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorldState:
    """Read-only snapshot. `frozen=True` so a `Renderer` cannot
    accidentally mutate what it's given — matches the read-only
    presentation-layer contract in
    `docs/architecture/SEPARATION_POLICY.md`."""

    #: district_id -> arbitrary status payload (shape TBD by the
    #: Phase W4 ingestion adapter; kept generic here on purpose)
    district_status: dict = field(default_factory=dict)

    #: character_id -> one of
    #: `world.frontend.interfaces.animation_controller.STANDARD_ANIMATION_STATES`
    character_states: dict = field(default_factory=dict)

    #: character_id -> {"room_id": str, "x": float, "y": float}
    character_positions: dict = field(default_factory=dict)

    #: free-form recent notifications/events for the UI panels in
    #: `world/ui/specs/notification-center.md` and
    #: `world/ui/specs/activity-feed.md`
    recent_events: tuple = field(default_factory=tuple)

    #: monotonically increasing snapshot sequence number, so a
    #: renderer can detect stale/duplicate snapshots
    sequence: int = 0
