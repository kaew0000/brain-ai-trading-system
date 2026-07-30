"""AnimationController — INTERFACE ONLY. Phase W3 explicitly does not
implement animations (no sprite sheets exist yet — see Phase W5, asset
pipeline activation). This module must stay abstract-only until a
concrete asset pipeline exists to drive it."""

from abc import ABC, abstractmethod

#: The five standard animation states, per `world/WORLD.md` §4 and
#: every `world/characters/definitions/*.json` `spriteMeta.animations`
#: block. Kept here as the single source of truth for valid state
#: names so `AnimationController` implementations don't each redefine
#: their own list.
STANDARD_ANIMATION_STATES = ("idle", "walking", "working", "celebration", "emergency")


class AnimationController(ABC):
    """Contract for driving a character's animation state machine.
    No implementation — Phase W3 deliverable is the interface only."""

    @abstractmethod
    def set_state(self, character_id: str, state: str) -> None:
        """Request a character transition to one of
        `STANDARD_ANIMATION_STATES`. Implementations should validate
        `state` against that tuple."""
        raise NotImplementedError

    @abstractmethod
    def current_state(self, character_id: str) -> str:
        """Return the character's current animation state."""
        raise NotImplementedError

    @abstractmethod
    def advance(self, character_id: str, delta_seconds: float) -> None:  # noqa
        """Advance the character's current animation by
        `delta_seconds` (frame stepping). No implementation in W3."""
        raise NotImplementedError
