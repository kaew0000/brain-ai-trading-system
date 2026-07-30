"""DistrictRenderer — abstraction only. Draws one department/room
using its `world/districts/definitions/<id>.json` data (name,
visualTheme, connectedDistricts) plus its
`world/data/layout/rooms.json` spatial data. No drawing implementation
here — this is what a concrete renderer implements once a floor plan
+ art style is chosen (Phase W4+)."""

from abc import ABC, abstractmethod
from typing import Any


class DistrictRenderer(ABC):
    """Contract for drawing one room/department's static
    presentation: walls, floor, connections to adjacent rooms."""

    @abstractmethod
    def render_district(self, district_id: str, district_data: dict[str, Any]) -> None:  # noqa
        """Render the static presentation of one district/room.
        `district_data` is the parsed content of
        `world/districts/definitions/<district_id>.json` merged with
        its `world/data/layout/rooms.json` entry — no engine-specific
        shape is mandated here."""
        raise NotImplementedError
