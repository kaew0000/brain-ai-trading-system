"""
portfolio/sector_engine.py — V16 Phase 2B: Portfolio Manager Orchestrator

Symbol → sector classification, sector exposure, and a diversification
score — the piece §17/§18 (docs/architecture.md) flagged as missing:
"no sector field is populated anywhere yet; PortfolioPosition.sector and
PortfolioState.sector_exposure() exist and are tested against None
today, ready for this to populate them."

Why this does NOT read PortfolioPosition.sector
------------------------------------------------------------------------
PortfolioPosition is a frozen dataclass (portfolio_models.py) constructed
by whoever owns reading real exchange/journal state into a
PortfolioState — that orchestrator doesn't exist yet either (it's the
future execution-wiring phase referenced in architecture.md, currently
out of scope; see portfolio_manager.py's own module docstring). Until
something actually constructs PortfolioPosition objects with `sector`
filled in, PortfolioState.sector_exposure() — which trusts
p.sector — will always return 0.0 for every sector, silently, which
would make PortfolioManager's sector-exposure enforcement a no-op
without an obvious failure signal.

SectorEngine sidesteps that dependency entirely: every method here
computes sector directly from `position.symbol` via sector_of(), never
from `position.sector`. This is correct today (the field is always
None) AND automatically stays correct later if/when a future phase
populates the field for real, since sector_of() is a pure function of
the symbol — the computed answer doesn't change either way. Nothing
about this class assigns to PortfolioPosition.sector (it's frozen;
callers who want that field populated do so at construction time,
typically via `sector=SectorEngine.sector_of(symbol)`).
"""
from __future__ import annotations

from typing import Dict, Iterable

from config.sector_table import SECTORS, sector_of

__all__ = ["SectorEngine"]


def _base_symbol(symbol: str) -> str:
    """Strips a trailing USDT/BUSD/USDC/FDUSD quote suffix. Deliberately
    duplicated from correlation_engine.py's private _base_symbol() rather
    than imported — that helper is private (leading underscore, not part
    of correlation_engine's public contract) and, per
    config/sector_table.py's module docstring, sector and correlation
    classification are independent taxonomies that should not become
    accidentally coupled via a shared private helper. Both
    implementations must agree on suffix-stripping rules; if that ever
    needs to change, it changes in both places deliberately, not as a
    surprise side effect of one import."""
    s = symbol.upper()
    for suffix in ("USDT", "BUSD", "USDC", "FDUSD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


class SectorEngine:
    """Stateless — every method is a pure function of its arguments plus
    the module-level static table (config/sector_table.py), exactly
    mirroring CorrelationEngine's own "stateless but kept as a class"
    rationale: no __init__ state needed, kept as a class for consistency
    with the other portfolio/ engines and so a future Version 2 (e.g.
    on-chain-category-sourced classification) can subclass/swap this
    without changing portfolio_manager.py's call sites."""

    #: Exposed so callers (tests, dashboards) can iterate the fixed
    #: sector universe without importing config/sector_table.py directly.
    SECTORS = SECTORS

    # ── Lookup ───────────────────────────────────────────────────────────

    @staticmethod
    def sector_of(symbol: str) -> str:
        """Symbol (with or without quote suffix) → sector name. Never
        raises; returns "Unknown" for anything not in the table."""
        return sector_of(_base_symbol(symbol))

    # ── Exposure ─────────────────────────────────────────────────────────

    @classmethod
    def exposure_by_sector(cls, positions: Iterable) -> Dict[str, float]:
        """
        Notional exposure (USDT) summed per sector, computed fresh from
        each position's symbol (see module docstring for why this never
        reads position.sector). Sectors with zero exposure are simply
        absent from the returned dict rather than present with 0.0 — the
        caller decides whether "not present" and "present at 0.0" should
        be treated differently; PortfolioManager currently treats them
        the same way via .get(sector, 0.0).

        Notional (leveraged), not capital/margin — this is deliberately
        the "how much price-correlated market exposure am I carrying"
        view, appropriate for diversification_score() below. Enforcing
        PortfolioLimits.max_sector_pct against a *capital* baseline is a
        different question with a different answer — see
        capital_by_sector() and portfolio_manager.py's
        _enforce_sector_limits(), which deliberately does NOT use this
        method for that reason.
        """
        exposure: Dict[str, float] = {}
        for p in positions:
            sector = cls.sector_of(p.symbol)
            exposure[sector] = exposure.get(sector, 0.0) + p.notional
        return exposure

    @classmethod
    def capital_by_sector(cls, positions: Iterable) -> Dict[str, float]:
        """
        Capital/margin (USDT) summed per sector — the leverage-independent
        counterpart to exposure_by_sector() above. Exists specifically for
        enforcing PortfolioLimits.max_sector_pct the same way
        max_symbol_pct is already enforced in capital_manager.py: as a
        cap on deployed CAPITAL, not leveraged notional. Comparing
        notional exposure against `max_sector_pct * balance` would make
        the cap fail for perfectly ordinary single positions at normal
        leverage (5x leverage alone can put one position's notional at
        multiple times account balance) — capital is the metric that's
        actually bounded by `balance` in the first place.
        """
        capital: Dict[str, float] = {}
        for p in positions:
            sector = cls.sector_of(p.symbol)
            capital[sector] = capital.get(sector, 0.0) + p.margin_used
        return capital

    @classmethod
    def sector_exposure_pct(cls, positions: Iterable, sector: str, balance: float) -> float:
        """Fraction (0.0-1.0+, uncapped — can exceed 1.0 at high
        leverage) of `balance` currently deployed as notional exposure in
        one sector. 0.0 when balance <= 0 rather than raising — mirrors
        PortfolioState.free_capital()'s own max(0.0, ...) defensiveness
        for degenerate balances."""
        if balance <= 0:
            return 0.0
        return cls.exposure_by_sector(positions).get(sector, 0.0) / balance

    # ── Diversification ─────────────────────────────────────────────────

    @staticmethod
    def diversification_score_from_exposure(exposure: Dict[str, float]) -> float:
        """
        0-100, higher = more spread across sectors, computed directly
        from a precomputed {sector: notional_usdt} map. Split out from
        diversification_score() so a caller that already has an exposure
        map — including a *projected* one that folds in not-yet-open
        allocations, which SectorEngine has no position objects for —
        doesn't need to fabricate synthetic PortfolioPosition-like
        objects just to reuse this math (see portfolio_manager.py, which
        does exactly this to score "the portfolio as it will look after
        this cycle's picks", not just its current holdings).

        Formula: 100 * (1 - HHI), where HHI (Herfindahl-Hirschman Index)
        is the sum of squared sector-exposure *weights* — a standard
        concentration measure: HHI=1.0 when 100% of notional sits in one
        sector (score 0), HHI=1/k when notional is spread evenly across
        k sectors (score approaches 100 as k grows). This is Version 1;
        see config/sector_table.py's module docstring on why the
        underlying sector classification itself is also Version 1 and
        expected to be extended/tuned over time — the score inherits
        that same tunability.

        Empty/all-zero exposure → 100.0 (nothing to be concentrated;
        treating it as the worst score would perversely encourage
        holding a first, low-conviction position purely to avoid an
        "undiversified" reading).
        """
        total = sum(exposure.values())
        if total <= 0:
            return 100.0
        hhi = sum((v / total) ** 2 for v in exposure.values())
        return max(0.0, 100.0 * (1.0 - hhi))

    @classmethod
    def diversification_score(cls, positions: Iterable) -> float:
        """Convenience wrapper: computes exposure_by_sector(positions)
        then scores it. See diversification_score_from_exposure() for the
        formula and for the variant that skips the positions->exposure
        step when the caller already has an exposure map."""
        return cls.diversification_score_from_exposure(cls.exposure_by_sector(positions))

    @classmethod
    def most_concentrated_sector(cls, positions: Iterable) -> "tuple[str, float] | None":
        """(sector, exposure_usdt) for the single largest sector
        exposure, or None if there are no positions. Convenience for
        callers (explanations, dashboards) that want the "why" behind a
        low diversification_score without recomputing exposure_by_sector
        themselves."""
        exposure = cls.exposure_by_sector(positions)
        if not exposure:
            return None
        sector = max(exposure, key=exposure.get)
        return sector, exposure[sector]
