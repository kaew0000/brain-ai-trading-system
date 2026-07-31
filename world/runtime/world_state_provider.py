"""WorldStateProvider — Phase W5, Part A.

Reads every Phase W4 runtime snapshot (portfolio, missions, telemetry,
notifications, events, active agents/districts) plus the static Phase
W1/W2 canon, and produces one immutable `world.runtime.models.WorldState`.

This class is deliberately NOT a subclass of
`world.frontend.interfaces.world_state.WorldStateProvider` (the Phase W3
ABC that returns a `world.frontend.renderer.world_state.WorldState`).
Binding this backend-only provider to that renderer-facing interface is
Phase W6's job (Renderer Integration) — this phase's own success criteria
says "No renderer exists yet." Building that binding now would mean
importing `world.frontend.renderer`/`world.frontend.interfaces` from
`world/runtime/`, which this phase's docs explicitly avoid so the backend
state layer stays usable even before a renderer is chosen.
"""

from world.runtime.models import WorldState
from world.runtime.state_builder import StateBuilder
from world.runtime.update_manager import UpdateManager


class WorldStateProvider:
    """Thin, stateful facade over `UpdateManager`: the one object most
    callers should hold onto. `world.runtime.api` wraps a module-level
    instance of this for the Part H functional API."""

    def __init__(self, update_manager: UpdateManager | None = None) -> None:
        self._update_manager = update_manager or UpdateManager(builder=StateBuilder())

    def get_current_state(self, force: bool = False) -> WorldState:
        return self._update_manager.get_state(force=force)

    def refresh(self) -> WorldState:
        return self._update_manager.get_state(force=True)

    def invalidate(self) -> None:
        self._update_manager.invalidate()

    @property
    def update_manager(self) -> UpdateManager:
        return self._update_manager
