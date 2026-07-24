"""
portfolio/capital_manager.py — V16 Phase 2A: Portfolio Intelligence Core

The decision engine. CapitalManager.decide() is the one entry point:
takes a ranked candidate list + RiskEngine + PortfolioState + balance,
returns a PortfolioDecision. Nothing in this module places an order,
calls set_leverage, or imports anything from execution/ or data/ —
that boundary is deliberate and enforced by what's imported below.

RankedOpportunity → PortfolioCandidate field mapping (see
ranking/ranking_models.py / ranking/score_breakdown.py for the source):
    composite_score            -> opportunity.composite_score            (unchanged)
    coverage                   -> opportunity.coverage                   (V16 Phase 2A addition to ranking/)
    liquidity_score            -> opportunity.breakdown.factors["liquidity"].score
    spread_score                -> opportunity.breakdown.factors["spread"].score
    atr_pct                     -> opportunity.breakdown.factors["risk"].raw_value (None if UNAVAILABLE)

Why "AI Confidence" and "Historical Win Rate" are NOT allocation inputs
------------------------------------------------------------------------
The original brief asked for capital allocation weighted by AI Confidence
and Historical Win Rate. Both map to ranking/score_breakdown.py factors
that are ALWAYS ScoreStatus.UNAVAILABLE (a constant 50.0 placeholder,
explicitly excluded from the Ranker's own composite score — see
ranking/confidence_fusion.py's module docstring) — computing them for
real would mean per-symbol Binance calls the scanner's two-tier design
exists specifically to avoid. Using the constant placeholder as a real
allocation input would be identical for every candidate (a no-op that
looks like it's doing something) — worse than not using it, since it
would misrepresent the allocation as AI-informed when it structurally
cannot be. `coverage` is used instead: it's real, per-symbol data (it
varies with how many of the 8 computable factors actually had fresh data
this cycle — e.g. lower-volume symbols the scanner didn't do a detail
pass on this cycle have lower OI/risk coverage than top-volume ones), and
it answers a related, honest question: "how much of the composite_score
can we actually trust this cycle." Historical Win Rate can become real
once multi-symbol trading produces enough per-symbol trade history to
compute it from (ties to the original roadmap's Performance Analytics
phase) — not fabricated now.

Why "higher expected reward" isn't a separate input
------------------------------------------------------------------------
No expected-value/RR factor exists anywhere in ranking/ either — same
"don't invent it" reasoning. composite_score already includes trend and
momentum (opportunity-strength proxies); adding a second, fabricated
"expected reward" number on top would just be double-weighting an
invented signal, not incorporating real information.

Why liquidity/spread are eligibility GATES, not extra score multipliers
------------------------------------------------------------------------
composite_score already includes "liquidity" and "spread" as two of its
eight computed factors (see ranking/score_breakdown.py). Multiplying
final_score by liquidity_score and spread_score AGAIN, on top of their
existing weight inside composite_score, would double-count exactly those
two factors relative to trend/momentum/funding/risk/volume/OI — a
meaningful, easy-to-miss bias. Instead, PortfolioLimits.min_liquidity_score
/ min_spread_score are used as a pass/fail eligibility screen (reject a
candidate outright if either is too low, regardless of composite_score),
which honors "higher liquidity / lower spread should matter for
allocation" without re-weighting them into the score twice.

Capital allocation formula
------------------------------------------------------------------------
    coverage_weight = COVERAGE_WEIGHT_FLOOR + (1 - COVERAGE_WEIGHT_FLOOR) * coverage
    final_score      = composite_score * coverage_weight * correlation_penalty
    allocation_pct    = (final_score / sum(final_score for all selected)) capped at max_symbol_pct

Never equal-weighted unless every selected candidate's final_score is
identical (satisfies the brief's "never use equal allocation unless
scores are equal").
"""
from __future__ import annotations

import time

from config.settings import settings
from portfolio.correlation_engine import CorrelationEngine
from portfolio.portfolio_models import (
    PortfolioAllocation,
    PortfolioCandidate,
    PortfolioDecision,
    PortfolioLimits,
    RejectedCandidate,
    RiskBudget,
)
from portfolio.portfolio_state import PortfolioState


def _factor_score(opportunity, name: str, default: float = 0.0) -> float:
    f = opportunity.breakdown.factors.get(name)
    return f.score if f is not None else default


def _factor_raw(opportunity, name: str) -> float | None:
    f = opportunity.breakdown.factors.get(name)
    return f.raw_value if f is not None else None


class CapitalManager:

    def __init__(
        self,
        limits: PortfolioLimits | None = None,
        correlation_engine: CorrelationEngine | None = None,
        coverage_weight_floor: float | None = None,
    ) -> None:
        self.limits = limits or PortfolioLimits()
        self.correlation_engine = correlation_engine or CorrelationEngine()
        self.coverage_weight_floor = (
            coverage_weight_floor
            if coverage_weight_floor is not None
            else settings.PORTFOLIO_COVERAGE_WEIGHT_FLOOR
        )

    @classmethod
    def from_settings(cls) -> CapitalManager:
        limits = PortfolioLimits(
            max_positions=settings.PORTFOLIO_MAX_POSITIONS,
            max_symbol_pct=settings.PORTFOLIO_MAX_SYMBOL_PCT,
            max_sector_pct=settings.PORTFOLIO_MAX_SECTOR_PCT,
            max_capital_deployed_pct=settings.PORTFOLIO_MAX_CAPITAL_DEPLOYED_PCT,
            max_daily_risk_pct=settings.PORTFOLIO_MAX_DAILY_RISK_PCT,
            max_account_risk_pct=settings.PORTFOLIO_MAX_ACCOUNT_RISK_PCT,
            max_leverage=settings.PORTFOLIO_MAX_LEVERAGE,
            min_liquidity_score=settings.PORTFOLIO_MIN_LIQUIDITY_SCORE,
            min_spread_score=settings.PORTFOLIO_MIN_SPREAD_SCORE,
            min_coverage=settings.PORTFOLIO_MIN_COVERAGE,
            correlation_hard_reject_enabled=settings.PORTFOLIO_CORRELATION_HARD_REJECT_ENABLED,
        )
        return cls(limits=limits)

    # ── Main entry point ─────────────────────────────────────────────────

    def decide(
        self,
        candidates: list,             # List[ranking.ranking_models.RankedOpportunity], already rank-sorted
        risk_engine,                   # risk.risk_engine.RiskEngine
        state: PortfolioState,
        balance: float,
    ) -> PortfolioDecision:
        now = time.time()

        # ── Gate 0: RiskEngine's own account-level circuit breaker ────────
        # "Never allocate if RiskEngine already blocks trading" — checked
        # before anything else, unconditionally.
        can_trade, block_reason = risk_engine.can_trade(balance)
        if not can_trade:
            return PortfolioDecision(
                generated_at=now, blocked=True, block_reason=block_reason,
                selected=[], rejected=[
                    RejectedCandidate(symbol=c.symbol, rank=c.rank,
                                       reason=f"risk_engine_blocked: {block_reason}")
                    for c in candidates
                ],
                explanation=f"RiskEngine blocked trading this cycle: {block_reason}",
            )

        budget = RiskBudget(
            balance=balance,
            max_daily_risk_usdt=balance * self.limits.max_daily_risk_pct,
            risk_used_today_usdt=max(0.0, -state.daily_pnl),
            max_account_risk_usdt=balance * self.limits.max_account_risk_pct,
            risk_used_open_usdt=state.risk_used,
        )

        available_slots = max(0, self.limits.max_positions - state.position_count)
        rejected: list[RejectedCandidate] = []

        if available_slots <= 0:
            rejected = [
                RejectedCandidate(symbol=c.symbol, rank=c.rank, reason="portfolio_full",
                                   details={"max_positions": self.limits.max_positions,
                                            "current_positions": state.position_count})
                for c in candidates
            ]
            return PortfolioDecision(
                generated_at=now, blocked=False, block_reason=None,
                selected=[], rejected=rejected,
                explanation=(f"Portfolio already at max_positions="
                             f"{self.limits.max_positions}; no new allocations this cycle."),
            )

        # ── Per-candidate eligibility gates, in rank order ────────────────
        held_and_selected: list[str] = list(state.held_symbols)
        eligible: list[PortfolioCandidate] = []

        for c in candidates:
            if len(eligible) >= available_slots:
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="portfolio_full",
                    details={"available_slots": available_slots},
                ))
                continue

            if state.has_position(c.symbol):
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="already_held",
                ))
                continue

            liquidity_score = _factor_score(c, "liquidity")
            spread_score    = _factor_score(c, "spread")
            atr_pct         = _factor_raw(c, "risk")

            if liquidity_score < self.limits.min_liquidity_score:
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="liquidity_below_minimum",
                    details={"liquidity_score": liquidity_score,
                             "minimum": self.limits.min_liquidity_score},
                ))
                continue

            if spread_score < self.limits.min_spread_score:
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="spread_below_minimum",
                    details={"spread_score": spread_score,
                             "minimum": self.limits.min_spread_score},
                ))
                continue

            if c.coverage < self.limits.min_coverage:
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="coverage_below_minimum",
                    details={"coverage": c.coverage, "minimum": self.limits.min_coverage},
                ))
                continue

            tier, penalty, against = self.correlation_engine.worst_against_portfolio(
                c.symbol, held_and_selected,
            )

            if (self.limits.correlation_hard_reject_enabled
                    and CorrelationEngine.is_at_least_as_severe(
                        tier, self.limits.correlation_hard_reject_tier)):
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="correlation_hard_reject",
                    details={"tier": tier.value, "against": against},
                ))
                continue

            coverage_weight = (
                self.coverage_weight_floor
                + (1.0 - self.coverage_weight_floor) * c.coverage
            )
            final_score = c.composite_score * coverage_weight * penalty

            eligible.append(PortfolioCandidate(
                symbol=c.symbol, rank=c.rank, composite_score=c.composite_score,
                coverage=c.coverage, liquidity_score=liquidity_score,
                spread_score=spread_score, atr_pct=atr_pct,
                correlation_tier=tier, correlation_penalty=penalty,
                correlation_against=against, final_score=final_score,
            ))
            held_and_selected.append(c.symbol)

        if not eligible:
            return PortfolioDecision(
                generated_at=now, blocked=False, block_reason=None,
                selected=[], rejected=rejected,
                explanation="No candidates passed portfolio eligibility gates this cycle.",
            )

        # ── Capital allocation across eligible candidates ──────────────────
        deployable_capital = min(
            balance * self.limits.max_capital_deployed_pct - state.reserved_capital,
            state.free_capital(balance),
        )
        deployable_capital = max(0.0, deployable_capital)

        total_final_score = sum(c.final_score for c in eligible)
        allocations: list[PortfolioAllocation] = []
        total_capital_allocated = 0.0
        total_risk_allocated    = 0.0

        for priority, cd in enumerate(
            sorted(eligible, key=lambda x: x.final_score, reverse=True), start=1
        ):
            raw_pct = (
                cd.final_score / total_final_score
                if total_final_score > 0 else 1.0 / len(eligible)
            )
            allocation_pct = min(raw_pct, self.limits.max_symbol_pct)
            capital_amount = deployable_capital * allocation_pct

            risk_pct = risk_engine.get_risk_pct(balance, atr_pct=cd.atr_pct)
            leverage = min(risk_engine.get_leverage(atr_pct=cd.atr_pct), self.limits.max_leverage)
            risk_amount = capital_amount * risk_pct

            remaining_risk = max(0.0, budget.remaining_risk_usdt - total_risk_allocated)
            if risk_amount > remaining_risk:
                if remaining_risk <= 0:
                    rejected.append(RejectedCandidate(
                        symbol=cd.symbol, rank=cd.rank, reason="risk_budget_exhausted",
                        details={"remaining_risk_usdt": remaining_risk},
                    ))
                    continue
                scale = remaining_risk / risk_amount if risk_amount > 0 else 0.0
                capital_amount *= scale
                allocation_pct *= scale
                risk_amount = remaining_risk

            if capital_amount <= 0:
                rejected.append(RejectedCandidate(
                    symbol=cd.symbol, rank=cd.rank, reason="no_capital_remaining",
                ))
                continue

            allocations.append(PortfolioAllocation(
                symbol=cd.symbol, priority=priority, allocation_pct=allocation_pct,
                capital_amount=capital_amount, risk_pct=risk_pct, risk_amount=risk_amount,
                leverage=leverage, correlation_tier=cd.correlation_tier,
                correlation_penalty=cd.correlation_penalty, coverage=cd.coverage,
                final_score=cd.final_score,
                reason=(
                    f"rank {cd.rank}, composite {cd.composite_score:.1f}, "
                    f"coverage {cd.coverage*100:.0f}%, correlation {cd.correlation_tier.value}"
                    f"{f' (vs {cd.correlation_against})' if cd.correlation_against else ''}, "
                    f"final_score {cd.final_score:.1f}"
                ),
            ))
            total_capital_allocated += capital_amount
            total_risk_allocated    += risk_amount

        explanation = (
            f"{len(allocations)}/{len(candidates)} candidates selected "
            f"({len(rejected)} rejected). Deployed {total_capital_allocated:.2f} USDT "
            f"({(total_capital_allocated/balance*100) if balance else 0.0:.1f}% of balance), "
            f"risk {total_risk_allocated:.2f} USDT "
            f"(budget remaining {budget.remaining_risk_usdt - total_risk_allocated:.2f} USDT)."
        )

        return PortfolioDecision(
            generated_at=now, blocked=False, block_reason=None,
            selected=allocations, rejected=rejected,
            total_capital_allocated=total_capital_allocated,
            total_risk_allocated=total_risk_allocated,
            explanation=explanation,
        )
