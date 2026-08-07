"""world/workspace/mission_workspace.py — Phase W12, Feature 5.

Built from `WorldState.missions` (Phase W5, sourced from Phase W4's
`MissionReader` <- Track A's `MissionTracker` — "reuse MissionTracker"
per this phase's own brief, satisfied via the already-established
one-way pipeline rather than a new direct Track A import into `world/`).

**Documented gap, not fabricated**: `missions.schema.json`'s status
enum (`proposed`/`active`/`complete`/`aborted`) has no explicit
dependency-graph or "blocked" concept — Phase W11's own SEPARATION_POLICY
amendment already documents that `MissionTracker`'s real stage
vocabulary doesn't map cleanly to this schema. `bucket` below is
therefore a straightforward, honest status->bucket mapping, not an
invented dependency/blocked-detection algorithm: `aborted` missions are
shown as `blocked` (the closest real meaning — a mission that stopped
before completing), not because a dependency check identified them.
"""

from world.runtime.models import WorldState
from world.workspace.models import MissionWorkspaceItem

_BUCKET_BY_STATUS = {
    "proposed": "waiting",
    "active": "active",
    "complete": "completed",
    "aborted": "blocked",
}


def build_mission_workspace(state: WorldState) -> tuple[MissionWorkspaceItem, ...]:
    return tuple(
        MissionWorkspaceItem(
            mission_id=m.mission_id, title=m.title, district=m.district, status=m.status,
            bucket=_BUCKET_BY_STATUS.get(m.status, "waiting"),
        )
        for m in state.missions
    )


def group_by_bucket(items: tuple[MissionWorkspaceItem, ...]) -> dict[str, tuple[MissionWorkspaceItem, ...]]:
    grouped: dict[str, list[MissionWorkspaceItem]] = {b: [] for b in ("waiting", "active", "completed", "blocked")}
    for item in items:
        grouped[item.bucket].append(item)
    return {k: tuple(v) for k, v in grouped.items()}
