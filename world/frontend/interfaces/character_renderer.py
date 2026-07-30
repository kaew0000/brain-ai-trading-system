"""CharacterRenderer — abstraction only. Draws one character using
`world/characters/definitions/<id>.json` plus its
`world/data/characters/placement.json` entry. No drawing
implementation here."""

from abc import ABC, abstractmethod
from typing import Any


class CharacterRenderer(ABC):
    """Contract for drawing one character at its current placement and
    animation state. Does not decide *what* animation state to use —
    that is `AnimationController`'s job."""

    @abstractmethod
    def render_character(self, character_id: str, character_data: dict[str, Any], state: str) -> None:
        """Render one character. `state` is one of the five standard
        animation states defined in `world/WORLD.md` §4: `idle`,
        `walking`, `working`, `celebration`, `emergency`."""
        raise NotImplementedError
