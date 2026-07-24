"""
portfolio/portfolio_manager.py — V16 Phase 2B: Portfolio Manager Orchestrator

The orchestration layer docs/architecture.md §17/§18 deliberately left
out of Phase 2A: "2B's orchestrator will own reading real exchange/
journal state into a PortfolioState each cycle" and "portfolio/
portfolio_manager.py ... is where position replacement/cooldown logic
... belongs." This phase builds that orchestrator as a pure decision
layer — same boundary CapitalManager already draws for itself.

PortfolioManager MUST NOT execute trades
------------------------------------------------------------------------
Nothing in this module places an order, calls set_leverage, or imports
from execution/ or data/. `decide()` returns an OrchestratedDecision —
capital amounts, risk-%, sector exposure, and (advisory) replacement
proposals — never an executed action. Reading real exchange/journal
state into a PortfolioState each cycle, and actually acting on a
ReplacementProposal, remain out of scope here too: that's the future
execution-wiring/scheduler phase docs/architecture.md refers to
provisionally as "Phase 2E" — this module is written so that phase only
has to call decide() and act on its output, not change anything in here.

What this adds on top of CapitalManager (unmodified, called as-is)
------------------------------------------------------------------------
CapitalManager.decide() already handles: the RiskEngine circuit-breaker
gate, max_positions capacity, already-held rejection, liquidity/spread/
coverage eligibility gates, correlation hard-reject, and capital/risk
allocation ordering. PortfolioManager does not re-implement any of that
— it calls CapitalManager.decide() once as-is, then layers three things
CapitalManager structurally has no way to do itself:

1. **Sector exposure enforcement** (PortfolioLimits.max_sector_pct —
   explicitly "NOT ENFORCED in 2A" per portfolio_models.py's own
   comment, because no sector data existed yet). Processes
   CapitalManager's already priority-sorted `selected` list in order,
   rejecting anything that would push its sector's cumulative notional
   (existing holdings + already-approved picks this cycle, same sector)
   over max_sector_pct * balance. Same "no redistribution of freed
   capital" simplification 2A already accepted for max_symbol_pct — see
   docs/architecture.md §17's "Known simplification" for the precedent.

2. **Replacement logic**, for when the portfolio is full and a strong
   new candidate got rejected purely for lack of capacity
   (`portfolio_full`), never evaluated for eligibility at all in that
   case. Rather than re-implementing CapitalManager's own eligibility/
   correlation/scoring rules a second time here (a maintenance hazard —
   two copies of the same logic drifting apart), this re-runs
   CapitalManager itself with room for exactly one more slot
   (`max_positions + 1`) against the same held state and candidate list.
   Anything that decision selects beyond what the real (unmodified)
   decision already selected is, by construction, the single best
   candidate that eligibility/correlation/scoring rules would actually
   allow in — no separate eligibility re-check needed. That challenger is
   compared against the current-cycle score of the WEAKEST held position
   (0.0 if it's fallen out of the ranked universe entirely — the
   strongest possible signal); a replacement is proposed only if the
   challenger clears PORTFOLIO_REPLACEMENT_THRESHOLD_PCT above it. V1
   proposes at most one replacement per decide() call, to avoid several
   simultaneous swaps destabilizing the book in one cycle.

3. **Cooldown / minimum-hold bookkeeping.** A symbol proposed as a
   replacement's outgoing side enters cooldown (ineligible as a NEW
   candidate for PORTFOLIO_COOLDOWN_SECONDS); its incoming side is
   protected from being proposed as an outgoing side again for
   PORTFOLIO_MIN_HOLD_SECONDS. Together these stop a single volatile
   ranking cycle from oscillating a symbol in and out repeatedly. Known
   V1 limitation: cooldown/protection are registered at *proposal* time,
   not confirmed-execution time — there is no feedback loop yet telling
   PortfolioManager whether a proposal was actually acted on (that
   requires the execution-wiring phase this module explicitly excludes).
   `notify_position_closed()` exists as the hook that phase should call
   for real closures (stop-loss, take-profit, manual) so this isn't the
   only path into cooldown.

Sector exposure is computed via SectorEngine directly from symbols, not
from PortfolioPosition.sector — see sector_engine.py's module docstring
for why (the field is structurally always None until a later phase
populates it, and trusting it would make enforcement here a silent
no-op).
"""
from __future__ import annotations

import time
from dataclasses import replace as dc_replace

from config.settings import settings
from portfolio import portfolio_history
from portfolio.capital_manager import CapitalManager
from portfolio.portfolio_models import (
    OrchestratedDecision,
    PortfolioAllocation,
    RejectedCandidate,
    ReplacementProposal,
)
from portfolio.portfolio_state import PortfolioState
from portfolio.sector_engine import SectorEngine
from utils.logger import get_logger

logger = get_logger(__name__)


class PortfolioManager:

    def __init__(
        self,
        capital_manager: CapitalManager | None = None,
        sector_engine: SectorEngine | None = None,
        replacement_threshold_pct: float | None = None,
        cooldown_seconds: int | None = None,
        min_hold_seconds: int | None = None,
    ) -> None:
        self.capital_manager = capital_manager or CapitalManager()
        # Read limits from the wrapped CapitalManager rather than
        # accepting a separate limits param — guarantees sector
        # enforcement here always agrees with the max_positions/
        # max_symbol_pct/etc. the underlying decision was actually made
        # under, instead of two independently-configurable limits
        # objects silently drifting apart.
        self.limits = self.capital_manager.limits
        self.sector_engine = sector_engine or SectorEngine()
        self.replacement_threshold_pct = (
            replacement_threshold_pct if replacement_threshold_pct is not None
            else settings.PORTFOLIO_REPLACEMENT_THRESHOLD_PCT
        )
        self.cooldown_seconds = (
            cooldown_seconds if cooldown_seconds is not None
            else settings.PORTFOLIO_COOLDOWN_SECONDS
        )
        self.min_hold_seconds = (
            min_hold_seconds if min_hold_seconds is not None
            else settings.PORTFOLIO_MIN_HOLD_SECONDS
        )
        self._cooldowns: dict[str, float] = {}         # symbol -> cooldown_until epoch
        self._protected_until: dict[str, float] = {}   # symbol -> min-hold protection epoch
        logger.info("PortfolioManager ready")

    @classmethod
    def from_settings(cls) -> PortfolioManager:
        return cls(capital_manager=CapitalManager.from_settings())

    # ── Main entry point ─────────────────────────────────────────────────

    def decide(
        self,
        candidates: list,             # List[ranking.ranking_models.RankedOpportunity], already rank-sorted
        risk_engine,                   # risk.risk_engine.RiskEngine
        state: PortfolioState,
        balance: float,
    ) -> OrchestratedDecision:
        now = time.time()

        active_candidates, cooldown_rejected = self._apply_cooldown(candidates, state, now)

        base_decision = self.capital_manager.decide(active_candidates, risk_engine, state, balance)

        current_exposure = self.sector_engine.exposure_by_sector(state.active_positions)

        if base_decision.blocked:
            decision = OrchestratedDecision(
                generated_at=now, blocked=True, block_reason=base_decision.block_reason,
                selected=[], rejected=base_decision.rejected + cooldown_rejected,
                replacements=[],
                sector_exposure=current_exposure,
                diversification_score=SectorEngine.diversification_score_from_exposure(current_exposure),
                total_capital_allocated=0.0, total_risk_allocated=0.0,
                portfolio_score=0.0,
                explanation=base_decision.explanation,
            )
            self._persist(decision, state, balance)
            return decision

        selected, sector_rejected = self._enforce_sector_limits(
            base_decision.selected, state, balance, active_candidates,
        )

        replacements = self._evaluate_replacements(
            active_candidates, base_decision, state, risk_engine, balance, now,
        )
        for r in replacements:
            self._register_cooldown(r.outgoing_symbol, now)
            self._protected_until[r.incoming_symbol] = now + self.min_hold_seconds

        # Sector exposure/diversification for the portfolio AS IT WILL
        # LOOK after this decision (existing holdings + this cycle's
        # newly approved picks) — more actionable than only reporting
        # pre-decision state. New picks are folded in via their
        # notional-equivalent (capital_amount * leverage) since they're
        # not PortfolioPosition objects yet (no entry/stop-loss price
        # exists at this decision layer — same reasoning CapitalManager
        # itself gives for returning capital amounts, not order qty).
        projected_exposure = dict(current_exposure)
        for alloc in selected:
            sector = self.sector_engine.sector_of(alloc.symbol)
            projected_exposure[sector] = (
                projected_exposure.get(sector, 0.0) + alloc.capital_amount * alloc.leverage
            )

        total_capital_allocated = sum(a.capital_amount for a in selected)
        total_risk_allocated = sum(a.risk_amount for a in selected)
        total_weight = sum(a.allocation_pct for a in selected)
        portfolio_score = (
            sum(a.final_score * a.allocation_pct for a in selected) / total_weight
            if selected and total_weight > 0 else 0.0
        )

        decision = OrchestratedDecision(
            generated_at=now, blocked=False, block_reason=None,
            selected=selected,
            rejected=base_decision.rejected + cooldown_rejected + sector_rejected,
            replacements=replacements,
            sector_exposure=projected_exposure,
            diversification_score=SectorEngine.diversification_score_from_exposure(projected_exposure),
            total_capital_allocated=total_capital_allocated,
            total_risk_allocated=total_risk_allocated,
            portfolio_score=portfolio_score,
            explanation=self._build_explanation(
                base_decision, selected, sector_rejected, cooldown_rejected, replacements,
            ),
        )
        self._persist(decision, state, balance)
        return decision

    # ── Cooldown ─────────────────────────────────────────────────────────

    def is_in_cooldown(self, symbol: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        until = self._cooldowns.get(symbol)
        return until is not None and now < until

    def notify_position_closed(self, symbol: str, now: float | None = None) -> None:
        """External hook for a future execution-wiring phase: report that
        a position was closed for ANY reason (stop-loss, take-profit,
        manual, an executed replacement) so its symbol enters cooldown
        before being eligible for new selection again. decide() does NOT
        call this itself for ordinary per-cycle rejections — only actual
        removals should cool a symbol down, not merely not being picked
        this cycle."""
        now = now if now is not None else time.time()
        self._register_cooldown(symbol, now)

    def _register_cooldown(self, symbol: str, now: float) -> None:
        self._cooldowns[symbol] = now + self.cooldown_seconds

    def _apply_cooldown(self, candidates, state: PortfolioState, now: float):
        active: list = []
        rejected: list[RejectedCandidate] = []
        held = set(state.held_symbols)
        for c in candidates:
            if c.symbol not in held and self.is_in_cooldown(c.symbol, now):
                rejected.append(RejectedCandidate(
                    symbol=c.symbol, rank=c.rank, reason="in_cooldown",
                    details={"cooldown_until": self._cooldowns[c.symbol]},
                ))
                continue
            active.append(c)
        return active, rejected

    # ── Sector exposure enforcement ─────────────────────────────────────

    def _enforce_sector_limits(self, selected, state: PortfolioState, balance: float, candidates):
        """
        Capital-based (see SectorEngine.capital_by_sector's docstring for
        why NOT notional) enforcement of PortfolioLimits.max_sector_pct,
        mirroring exactly how capital_manager.py already enforces
        max_symbol_pct: a cap on deployed capital, not leveraged notional.
        """
        candidates_by_symbol = {c.symbol: c for c in candidates}
        kept: list[PortfolioAllocation] = []
        newly_rejected: list[RejectedCandidate] = []
        cumulative = dict(self.sector_engine.capital_by_sector(state.active_positions))
        cap_usdt = self.limits.max_sector_pct * balance if balance > 0 else 0.0

        for alloc in selected:
            sector = self.sector_engine.sector_of(alloc.symbol)
            projected = cumulative.get(sector, 0.0) + alloc.capital_amount
            if cap_usdt > 0 and projected > cap_usdt:
                rank = (
                    candidates_by_symbol[alloc.symbol].rank
                    if alloc.symbol in candidates_by_symbol else alloc.priority
                )
                newly_rejected.append(RejectedCandidate(
                    symbol=alloc.symbol, rank=rank, reason="sector_exposure_exceeded",
                    details={"sector": sector, "projected_capital_usdt": round(projected, 2),
                             "cap_usdt": round(cap_usdt, 2)},
                ))
                continue
            cumulative[sector] = projected
            kept.append(alloc)
        return kept, newly_rejected

    # ── Replacement logic ────────────────────────────────────────────────

    def _evaluate_replacements(
        self, candidates, base_decision, state: PortfolioState, risk_engine, balance: float, now: float,
    ) -> list[ReplacementProposal]:
        if state.position_count < self.limits.max_positions:
            return []   # there was room this cycle; CapitalManager already used it
        if not state.active_positions:
            return []

        expanded_limits = dc_replace(self.limits, max_positions=self.limits.max_positions + 1)
        probe = CapitalManager(
            limits=expanded_limits,
            correlation_engine=self.capital_manager.correlation_engine,
            coverage_weight_floor=self.capital_manager.coverage_weight_floor,
        )
        probe_decision = probe.decide(candidates, risk_engine, state, balance)
        if probe_decision.blocked or not probe_decision.selected:
            return []

        base_symbols = {a.symbol for a in base_decision.selected}
        extra = [a for a in probe_decision.selected if a.symbol not in base_symbols]
        if not extra:
            return []
        challenger = max(extra, key=lambda a: a.final_score)

        candidates_by_symbol = {c.symbol: c for c in candidates}
        weakest_symbol: str | None = None
        weakest_score: float | None = None
        for pos in state.active_positions:
            protected_until = self._protected_until.get(pos.symbol)
            if protected_until is not None and now < protected_until:
                continue
            score = (
                candidates_by_symbol[pos.symbol].composite_score
                if pos.symbol in candidates_by_symbol else 0.0
            )
            if weakest_score is None or score < weakest_score:
                weakest_symbol, weakest_score = pos.symbol, score

        if weakest_symbol is None:
            return []   # every held position is still min-hold protected

        improvement = challenger.final_score - weakest_score
        if improvement <= 0:
            return []
        if weakest_score > 0 and improvement < weakest_score * self.replacement_threshold_pct:
            return []

        return [ReplacementProposal(
            incoming_symbol=challenger.symbol, outgoing_symbol=weakest_symbol,
            incoming_score=challenger.final_score, outgoing_score=weakest_score,
            reason=(
                f"{challenger.symbol} final_score {challenger.final_score:.1f} exceeds held "
                f"{weakest_symbol}'s current score {weakest_score:.1f} by more than "
                f"{self.replacement_threshold_pct*100:.0f}% while portfolio is at capacity "
                f"({state.position_count}/{self.limits.max_positions})"
            ),
        )]

    # ── Explanation / persistence ────────────────────────────────────────

    def _build_explanation(
        self, base_decision, selected, sector_rejected, cooldown_rejected, replacements,
    ) -> str:
        parts = [base_decision.explanation]
        if cooldown_rejected:
            parts.append(f"{len(cooldown_rejected)} candidate(s) skipped (in cooldown).")
        if sector_rejected:
            parts.append(f"{len(sector_rejected)} candidate(s) rejected (sector exposure cap).")
        if replacements:
            parts.append(f"{len(replacements)} replacement(s) proposed.")
        return " ".join(parts)

    def _persist(self, decision: OrchestratedDecision, state: PortfolioState, balance: float) -> None:
        try:
            portfolio_history.save_decision(
                decision,
                sector_exposure=decision.sector_exposure,
                drawdown=state.portfolio_drawdown(balance),
            )
        except Exception as exc:
            # Belt-and-suspenders: save_decision already has its own
            # internal try/except (mirroring ranking_history.save_ranking)
            # — this is a second, outer safety net so a bug there can
            # never prevent the freshly computed decision from being
            # returned to the caller.
            logger.error(f"PortfolioManager: portfolio_history.save_decision raised unexpectedly: {exc}")

    # ── Status / observability ───────────────────────────────────────────

    def status(self) -> dict:
        now = time.time()
        return {
            "max_positions":             self.limits.max_positions,
            "max_sector_pct":            self.limits.max_sector_pct,
            "replacement_threshold_pct": self.replacement_threshold_pct,
            "cooldown_seconds":          self.cooldown_seconds,
            "min_hold_seconds":          self.min_hold_seconds,
            "active_cooldowns":          {s: u for s, u in self._cooldowns.items() if now < u},
            "active_protections":        {s: u for s, u in self._protected_until.items() if now < u},
        }
