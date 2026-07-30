"""RoomType — styling categories for the renderer's Room System
requirement.

Deliberately **not** a hand-typed enum of room display names (e.g.
"CEO Office", "Risk Department", "Execution Center"). Those already
exist as the `id`/`name` fields in `world/districts/definitions/*.json`
— the single source of truth established by the Phase W2.1
documentation-sync work, which existed specifically to stop parallel
copies of this list from drifting apart. Re-typing a second list here
(even with slightly different wording, e.g. "Execution Center" instead
of the already-shipped "Trading Floor") would recreate that exact
problem one file later. See `world/docs/OFFICE_LAYOUT.md` for the
current canonical department list.

This module instead provides:

1. `CirculationType` — the non-department room kinds a floor plan
   needs (lobby, hallway, elevator) that have no
   `world/districts/definitions/` entry because they aren't
   departments.
2. `load_department_ids()` — reads the real department ids straight
   from `world/districts/definitions/`, for anything (e.g. a
   renderer's per-room style lookup table) that needs "all valid
   room ids"."""

import json
import os
from enum import Enum

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/frontend/rooms
_WORLD_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # world/
_DISTRICTS_DIR = os.path.join(_WORLD_DIR, "districts", "definitions")


class CirculationType(str, Enum):
    """Structural room kinds that exist for movement between
    departments, not as departments themselves. `ELEVATOR` already
    matches the node `type` values used in
    `world/data/navigation/graph.json`."""

    LOBBY = "lobby"
    HALLWAY = "hallway"
    ELEVATOR = "elevator"


def load_department_ids(districts_dir: str = _DISTRICTS_DIR) -> list[str]:
    """Return every real department id, read live from
    `world/districts/definitions/*.json`. Returns an empty list rather
    than raising if the directory is missing, so importing this module
    never fails outside a full repo checkout."""
    if not os.path.isdir(districts_dir):
        return []
    ids = []
    for fname in sorted(os.listdir(districts_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(districts_dir, fname)) as f:
                ids.append(json.load(f)["id"])
    return ids


def all_room_type_ids(districts_dir: str = _DISTRICTS_DIR) -> list[str]:
    """Every valid room id a renderer might need a style for: real
    departments plus the fixed circulation types."""
    return load_department_ids(districts_dir) + [c.value for c in CirculationType]
