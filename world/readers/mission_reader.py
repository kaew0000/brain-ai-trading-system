"""MissionReader — turns raw mission rows into `Mission` dataclasses
matching the existing `world/data/schemas/missions.schema.json` shape
(Phase W1) exactly, so `SnapshotBuilder` can serialize straight back
to that schema with no field renaming."""

from dataclasses import dataclass

from world.readers.base import Reader

VALID_STATUSES = ("proposed", "active", "complete", "aborted")


@dataclass
class Mission:
    mission_id: str
    title: str
    district: str
    status: str
    description: str = ""


class MissionReader(Reader):
    """Expects `self.source.load_raw()` to return a list of dict-like
    rows with at least `id`/`title`/`district`/`status` keys. Rows
    with a `status` outside `VALID_STATUSES` are skipped, matching
    `missions.schema.json`'s enum."""

    def read(self) -> list[Mission]:
        raw = self.source.load_raw()
        missions = []
        for row in raw:
            try:
                status = str(row["status"])
                if status not in VALID_STATUSES:
                    continue
                missions.append(
                    Mission(
                        mission_id=str(row["id"]),
                        title=str(row["title"]),
                        district=str(row["district"]),
                        status=status,
                        description=str(row.get("description", "")),
                    )
                )
            except (KeyError, TypeError):
                continue
        return missions
