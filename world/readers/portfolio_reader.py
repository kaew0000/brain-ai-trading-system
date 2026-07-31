"""PortfolioReader — turns raw position rows into `PortfolioPosition`
dataclasses. Source-agnostic. Deliberately does not read raw notional
size — see `world/data/schemas/portfolio.schema.json` docstring on
`sizeLabel` for why (presentation-only reflection, not a financial
data feed)."""

from dataclasses import dataclass

from world.readers.base import Reader


@dataclass
class PortfolioPosition:
    symbol: str
    district: str = "portfolio-garden"
    size_label: str = ""


class PortfolioReader(Reader):
    """Expects `self.source.load_raw()` to return a list of dict-like
    rows with at least a `symbol` key."""

    def read(self) -> list[PortfolioPosition]:
        raw = self.source.load_raw()
        positions = []
        for row in raw:
            try:
                positions.append(
                    PortfolioPosition(
                        symbol=str(row["symbol"]),
                        district=str(row.get("district", "portfolio-garden")),
                        size_label=str(row.get("size_label", row.get("sizeLabel", ""))),
                    )
                )
            except (KeyError, TypeError):
                continue
        return positions
