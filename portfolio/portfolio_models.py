"""
portfolio/portfolio_models.py — V16 Phase 2A: Portfolio Intelligence Core

Data models only — no decision logic (see capital_manager.py), no
correlation logic (see correlation_engine.py), no exchange/network access
anywhere in this package. This phase does not execute trades; every
dataclass here describes a *decision*, not an action.

Field-naming note: PortfolioCandidate mirrors the subset of
ranking.ranking_models.RankedOpportunity that Capital Manager actually
uses, copied in as plain fields rather than importing RankedOpportunity
as a base class — dataclass inheritance across modules gets brittle
(field-ordering/default-value rules), and this way portfolio/ has no
import-time dependency on ranking/'s internal shape beyond what
capital_manager.py explicitly reads. See capital_manager.py's module
docstring for exactly which RankedOpportunity/ScoreBreakdown fields feed
each PortfolioCandidate field.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class PositionState(str, Enum):
    """
    Full state machine per the V16 Phase 2 Part 3 brief. Phase 2A (this
    module) is a decision engine that never executes — so only WAITING
    and ALLOCATED are ever actually produced here. OPEN/PARTIAL/CLOSING/
    CLOSED/ARCHIVED exist now so PortfolioPosition has a stable shape for
    2B's orchestrator (which will own the transitions into and through
    those states once execution wiring exists) — defining them here
    rather than 2B redefining this enum keeps there being exactly one
    definition of "what states can a position be in" for the whole
    portfolio/ package.
    """
    WAITING    = "WAITING"
    ALLOCATED  = "ALLOCATED"
    OPEN       = "OPEN"
    PARTIAL    = "PARTIAL"
    CLOSING    = "CLOSING"
    CLOSED     = "CLOSED"
    ARCHIVED   = "ARCHIVED"


class CorrelationTier(str, Enum):
    """See correlation_engine.py / config/correlation_table.py."""
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    UNKNOWN  = "UNKNOWN"


@dataclass(frozen=True)
class PortfolioLimits:
    """
    Portfolio-wide constraints. All defaults are conservative starting
    points meant to be tuned via config/settings.py (PORTFOLIO_* fields),
    not hardcoded call sites — see capital_manager.py for how these are
    normally constructed (CapitalManager.from_settings()).
    """
    max_positions:            int   = 5
    max_symbol_pct:           float = 0.35   # one symbol never exceeds 35% of deployed capital
    max_sector_pct:           float = 0.50   # NOT ENFORCED in 2A — no sector data exists yet (2B). Accepted
                                              # here so PortfolioLimits' shape doesn't change again in 2B.
    max_capital_deployed_pct: float = 0.80   # never deploy more than 80% of balance across all positions
    max_daily_risk_pct:       float = 0.03   # matches RiskEngine's own MAX_DAILY_LOSS by default
    max_account_risk_pct:     float = 0.10   # total risk-at-stake across all open positions, account-wide
    max_leverage:              int  = 10
    min_liquidity_score:      float = 30.0   # reject candidates below this ranking/score_breakdown.py
                                              # "liquidity" factor score (0-100) regardless of composite
    min_spread_score:         float = 20.0   # reject candidates below this "spread" factor score (0-100);
                                              # score_spread() already means "tighter is better", so this
                                              # is a floor, not a ceiling
    min_coverage:              float = 0.0   # reject candidates with ranker data coverage below this;
                                              # 0.0 = accept any coverage (composite_score/coverage weighting
                                              # in capital_manager.py already handles partial coverage)
    correlation_hard_reject_tier: CorrelationTier = CorrelationTier.HIGH
    correlation_hard_reject_enabled: bool = True


@dataclass(frozen=True)
class RiskBudget:
    """
    A snapshot of how much risk is available to spend, computed fresh
    each decision cycle from balance + PortfolioState + RiskEngine — not
    persisted/mutated in place (that's why this is frozen; CapitalManager
    builds a new one every call).
    """
    balance:                 float
    max_daily_risk_usdt:     float
    risk_used_today_usdt:    float
    max_account_risk_usdt:   float
    risk_used_open_usdt:     float

    @property
    def remaining_daily_risk_usdt(self) -> float:
        return max(0.0, self.max_daily_risk_usdt - self.risk_used_today_usdt)

    @property
    def remaining_account_risk_usdt(self) -> float:
        return max(0.0, self.max_account_risk_usdt - self.risk_used_open_usdt)

    @property
    def remaining_risk_usdt(self) -> float:
        """The binding constraint is whichever budget is tighter."""
        return min(self.remaining_daily_risk_usdt, self.remaining_account_risk_usdt)


@dataclass(frozen=True)
class PortfolioPosition:
    """
    One currently-held (or pending) position. In 2A this is a pure value
    object fed into PortfolioState by whoever constructs it (tests, or —
    once it exists — 2B's orchestrator reading real exchange/journal
    state); nothing in this phase creates PortfolioPosition from a live
    trade.
    """
    symbol:               str
    direction:             str            # "LONG" | "SHORT"
    entry_price:           float
    quantity:               float
    leverage:               int
    notional:               float
    margin_used:            float
    unrealized_pnl:         float
    state:                 PositionState
    opened_at:              float          # unix epoch
    sector:                Optional[str] = None               # None until 2B's Sector Engine
    correlation_cluster:    Optional[str] = None               # config/correlation_table.py cluster name

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass(frozen=True)
class PortfolioCandidate:
    """
    A RankedOpportunity, carried through with the portfolio-specific
    fields CapitalManager derives from it (correlation, eligibility,
    final_score). See capital_manager.py's module docstring for the exact
    RankedOpportunity → PortfolioCandidate field mapping.
    """
    symbol:                str
    rank:                  int
    composite_score:        float          # 0-100, from RankedOpportunity, unchanged
    coverage:               float          # 0-1, from RankedOpportunity (see ranking/ changes below)
    liquidity_score:         float          # 0-100, from breakdown.factors["liquidity"].score
    spread_score:            float          # 0-100, from breakdown.factors["spread"].score
    atr_pct:                Optional[float] # from breakdown.factors["risk"].raw_value; None if UNAVAILABLE
    correlation_tier:        CorrelationTier
    correlation_penalty:     float          # 1.0 / 0.75 / 0.5 / 0.25
    correlation_against:     Optional[str]  # which held/selected symbol produced the worst-case tier, if any
    final_score:             float          # composite_score * coverage_weight * correlation_penalty


@dataclass(frozen=True)
class RejectedCandidate:
    symbol:  str
    rank:    int
    reason:  str
    details: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioAllocation:
    """One accepted candidate's sizing decision. Capital, not exchange
    quantity — Capital Manager has no entry/stop-loss price (those come
    from the per-symbol Strategy/Decision layer at execution time, which
    is out of scope here), so this expresses "how much capital and at
    what leverage/risk-%", not a base-asset order quantity."""
    symbol:            str
    priority:           int             # 1 = highest priority (first selected / largest allocation)
    allocation_pct:     float           # fraction of deployable capital assigned to this symbol
    capital_amount:     float           # USDT, = balance * allocation_pct
    risk_pct:           float           # from RiskEngine.get_risk_pct(balance, atr_pct=...)
    risk_amount:        float           # USDT = capital_amount * risk_pct
    leverage:           int             # from RiskEngine.get_leverage(atr_pct=...), capped by PortfolioLimits
    correlation_tier:    CorrelationTier
    correlation_penalty: float
    coverage:            float
    final_score:         float
    reason:              str            # human-readable explanation of the sizing decision


@dataclass(frozen=True)
class PortfolioDecision:
    """
    The complete output of one CapitalManager.decide() call. This is the
    ONLY thing capital_manager.py returns — nothing in this package
    places an order, calls set_leverage, or touches an exchange client.
    """
    generated_at:          float
    blocked:               bool                          # True if RiskEngine.can_trade() said no
    block_reason:           Optional[str]
    selected:               List[PortfolioAllocation] = field(default_factory=list)
    rejected:                List[RejectedCandidate]    = field(default_factory=list)
    total_capital_allocated: float = 0.0
    total_risk_allocated:    float = 0.0
    explanation:              str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at":            self.generated_at,
            "blocked":                 self.blocked,
            "block_reason":            self.block_reason,
            "selected":                [asdict(a) | {
                                            "correlation_tier": a.correlation_tier.value
                                        } for a in self.selected],
            "rejected":                [asdict(r) for r in self.rejected],
            "total_capital_allocated": self.total_capital_allocated,
            "total_risk_allocated":    self.total_risk_allocated,
            "explanation":             self.explanation,
        }
