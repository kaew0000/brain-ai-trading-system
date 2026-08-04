"""PortfolioReader — turns raw position rows into `PortfolioPosition`
dataclasses. Source-agnostic. Deliberately does not read raw notional
size for individual positions — see `world/data/schemas/portfolio.schema.json`
docstring on `sizeLabel` for why (presentation-only reflection of
per-position size, not a financial data feed).

Phase W11 update: portfolio-*wide* read-only figures (daily/floating
PnL, drawdown, win rate, avg R:R) are a deliberate, explicit exception
to that same principle, made by request (see
`docs/architecture/SEPARATION_POLICY.md` "Phase W11 amendment"). These
numbers are never computed here or anywhere in `world/` - they are
read verbatim from the trading engine's own existing read-only
accessors (`portfolio.portfolio_history.get_latest_decisions()`,
`journal.journal_v2.get_daily_stats()`) by `telemetry/world_export.py`
on the Track A side, and arrive here already-computed, inside the same
raw payload as `positions`."""

from dataclasses import dataclass

from world.readers.base import DataSource, Reader


@dataclass
class PortfolioPosition:
    symbol: str
    district: str = "portfolio-garden"
    size_label: str = ""


@dataclass
class PortfolioSummary:
    """Portfolio-wide, read-only figures for one capture. Every field is
    optional: a raw payload that omits `summary` entirely (the original
    Phase W4 shape) or omits individual keys within it produces a
    `PortfolioSummary` of all-`None` fields, which
    `SnapshotBuilder.build_portfolio()` simply leaves out of its
    output - never a fabricated 0.0."""

    daily_pnl: float | None = None
    floating_pnl: float | None = None
    drawdown: float | None = None
    win_rate: float | None = None
    avg_rr: float | None = None


class PortfolioReader(Reader):
    """`self.source.load_raw()` may return either shape, both supported
    for backward compatibility:

    - a plain list of position dict rows (original Phase W4 shape), or
    - a dict `{"positions": [...], "summary": {...}}` (Phase W11+),
      where `summary` is optional and each of its keys is optional.

    `read()`'s return type and behavior for the plain-list shape are
    byte-for-byte unchanged from Phase W4. The parsed summary (if any)
    is exposed as `self.last_summary` immediately after `read()`
    returns - a deliberate side-channel rather than a second element
    of `read()`'s return value, so every existing caller of
    `read() -> list[PortfolioPosition]` keeps working unmodified, and
    so `self.source.load_raw()` is only invoked once per capture."""

    def __init__(self, source: DataSource) -> None:
        super().__init__(source)
        self.last_summary: PortfolioSummary | None = None

    def read(self) -> list[PortfolioPosition]:
        raw = self.source.load_raw()
        self.last_summary = None

        if isinstance(raw, dict):
            rows = raw.get("positions", [])
            summary_raw = raw.get("summary")
            if isinstance(summary_raw, dict):
                self.last_summary = PortfolioSummary(
                    daily_pnl=summary_raw.get("daily_pnl", summary_raw.get("dailyPnl")),
                    floating_pnl=summary_raw.get("floating_pnl", summary_raw.get("floatingPnl")),
                    drawdown=summary_raw.get("drawdown"),
                    win_rate=summary_raw.get("win_rate", summary_raw.get("winRate")),
                    avg_rr=summary_raw.get("avg_rr", summary_raw.get("avgRr")),
                )
        else:
            rows = raw  # original Phase W4 shape: bare list of position rows

        positions = []
        for row in rows:
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
