"""TelemetryReader — turns raw metric rows into `TelemetryPoint`
dataclasses. Source-agnostic."""

from dataclasses import dataclass

from world.readers.base import Reader


@dataclass
class TelemetryPoint:
    name: str
    value: float
    unit: str = ""
    district: str = ""


class TelemetryReader(Reader):
    """Expects `self.source.load_raw()` to return a list of dict-like
    rows with at least `name`/`value` keys. Rows missing a required
    key, or with a non-numeric `value`, are skipped."""

    def read(self) -> list[TelemetryPoint]:
        raw = self.source.load_raw()
        points = []
        for row in raw:
            try:
                points.append(
                    TelemetryPoint(
                        name=str(row["name"]),
                        value=float(row["value"]),
                        unit=str(row.get("unit", "")),
                        district=str(row.get("district", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return points
