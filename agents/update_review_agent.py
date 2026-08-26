"""agents/update_review_agent.py — deterministic second opinion on an
UpdateProposal (V16 Phase 4C, AI Self-Improvement Governance Layer, Phase 1
— docs/architecture.md §48).

Not a BaseAgent subclass — deliberately. Read agents/base_agent.py in full
before deciding this: BaseAgent.analyse(market_context) -> AgentReport is
built specifically around trading signals (LONG/SHORT/NEUTRAL/WAIT,
EventBus SIGNAL_/ANALYSIS events, telemetry keyed on "last_signal"). None of
that fits "should this model/parameter/logic proposal be approved" — forcing
the shape on here would be a worse fit than a small standalone class.

Deterministic and explainable only — no LLM call, no trained model. Checked
agents/ before writing this: nothing in that package calls out to an LLM
anywhere in the decision path, and
learning/application/recommendation_scoring.py's own docstring states the
same philosophy explicitly ("deterministic, explainable, arithmetic ...
nothing that could silently drift") — this mirrors that, deliberately.

Phase 1 scope: real scoring for proposal_type="model_promotion" only — the
only type with an honest metrics source today (ml/trainer.py's 80/20
held-out validation split, which is where a model_promotion proposal's
before/after win_rate/profit_factor/max_drawdown actually come from). Every
other proposal_type (agent_weight, recommendation_param, strategy_selection,
logic_change) returns an explicitly "unscored" ReviewResult — verdict="",
reasoning explains why — rather than inventing numbers there is no honest
source for yet. See docs/architecture.md §48's "Decision Replay" section for
what has to exist first (Replay Tier A) before those types can be scored for
real; that is not part of this delivery.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings
from utils.logger import get_logger

from governance.update_proposal import UpdateProposal

logger = get_logger(__name__)


@dataclass
class ReviewResult:
    verdict: str                        # "" | "approve_recommended" | "caution" | "reject_recommended"
    score: float                        # 0.0-1.0 composite; 0.0 when unscored or hard-gate-failed
    reasoning: str
    hard_gate_passed: bool | None = None   # None when proposal_type is unscored in Phase 1


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def model_promotion_hard_gate_passed(before: dict, after: dict) -> bool:
    """The SAME rule ml/model_registry.py's should_promote() already uses:
    win_rate up AND profit_factor up AND drawdown not worse. Re-implemented
    literally rather than imported, so this module has no import-time
    dependency on ml/model_registry.py — the two are intentionally required
    to encode the identical rule; tests/test_update_review_agent.py asserts
    that directly against a real ModelRegistry.should_promote() call so the
    two can never silently drift apart.

    No prior active model (before == {}) => nothing to compare against =>
    passes unconditionally, same as should_promote()'s own
    "if current is None: return True"."""
    if not before:
        return True
    old_wr = float(before.get("win_rate", 0.0))
    new_wr = float(after.get("win_rate", 0.0))
    old_pf = float(before.get("profit_factor", 0.0))
    new_pf = float(after.get("profit_factor", 0.0))
    old_dd = float(before.get("max_drawdown", 0.0))
    new_dd = float(after.get("max_drawdown", 0.0))
    return new_wr > old_wr and new_pf > old_pf and new_dd <= old_dd


class UpdateReviewAgent:
    """Call .review(proposal) to get a ReviewResult. Nothing here writes to
    ProposalStore — that's the caller's job (see
    ProposalStore.set_review()), keeping "compute an opinion" and "persist
    it" separate on purpose."""

    AGENT_NAME = "UPDATE_REVIEW_AGENT"

    def __init__(self) -> None:
        self._logger = get_logger(f"agents.{self.AGENT_NAME.lower()}")

    def review(self, proposal: UpdateProposal) -> ReviewResult:
        if proposal.proposal_type == "model_promotion":
            return self._review_model_promotion(proposal)
        return ReviewResult(
            verdict="",
            score=0.0,
            reasoning=(
                f"No honest metrics source for proposal_type="
                f"{proposal.proposal_type!r} yet in Phase 1 — see "
                f"docs/architecture.md §48. Left unscored rather than "
                f"estimating."
            ),
            hard_gate_passed=None,
        )

    def _review_model_promotion(self, proposal: UpdateProposal) -> ReviewResult:
        before = proposal.before or {}
        after = proposal.after or {}

        old_wr = float(before.get("win_rate", 0.0))
        new_wr = float(after.get("win_rate", 0.0))
        old_pf = float(before.get("profit_factor", 0.0))
        new_pf = float(after.get("profit_factor", 0.0))
        old_dd = float(before.get("max_drawdown", 0.0))
        new_dd = float(after.get("max_drawdown", 0.0))
        sample_size = int(
            proposal.metrics.get("training_rows")
            or after.get("training_rows")
            or 0
        )

        hard_gate_passed = model_promotion_hard_gate_passed(before, after)

        if not hard_gate_passed:
            reasoning = (
                f"Fails the promotion gate: win_rate {old_wr:.3f}->{new_wr:.3f}, "
                f"profit_factor {old_pf:.3f}->{new_pf:.3f}, "
                f"max_drawdown {old_dd:.3f}->{new_dd:.3f} "
                f"(needs win_rate up AND profit_factor up AND drawdown not worse)."
            )
            lane_note = self._lane_note(proposal)
            if lane_note:
                reasoning += " " + lane_note
            return ReviewResult(
                verdict="reject_recommended", score=0.0,
                reasoning=reasoning, hard_gate_passed=False,
            )

        wr_scale = max(1e-9, settings.REVIEW_SCORE_WIN_RATE_DELTA_SCALE)
        pf_scale = max(1e-9, settings.REVIEW_SCORE_PROFIT_FACTOR_DELTA_SCALE)
        improvement_score = (
            _clamp01(max(0.0, new_wr - old_wr) / wr_scale)
            + _clamp01(max(0.0, new_pf - old_pf) / pf_scale)
        ) / 2.0

        drawdown_margin_score = (
            _clamp01((old_dd - new_dd) / old_dd) if old_dd > 0 else 0.5
        )

        saturation_n = max(1, settings.REVIEW_SCORE_SATURATION_N)
        sample_size_score = _clamp01(sample_size / saturation_n)

        composite = (
            improvement_score * settings.REVIEW_SCORE_WEIGHT_IMPROVEMENT
            + drawdown_margin_score * settings.REVIEW_SCORE_WEIGHT_DRAWDOWN_MARGIN
            + sample_size_score * settings.REVIEW_SCORE_WEIGHT_SAMPLE_SIZE
        )

        below_floor = sample_size < settings.REVIEW_MIN_SAMPLE_SIZE
        if below_floor:
            verdict = "caution"
        elif composite >= settings.REVIEW_SCORE_APPROVE_THRESHOLD:
            verdict = "approve_recommended"
        else:
            verdict = "caution"

        reasoning = (
            f"Passes promotion gate: win_rate {old_wr:.3f}->{new_wr:.3f}, "
            f"profit_factor {old_pf:.3f}->{new_pf:.3f}, "
            f"max_drawdown {old_dd:.3f}->{new_dd:.3f}. "
            f"Composite score {composite:.2f} (improvement={improvement_score:.2f}, "
            f"drawdown_margin={drawdown_margin_score:.2f}, "
            f"sample_size={sample_size_score:.2f} over {sample_size} rows)."
        )
        if below_floor:
            reasoning += (
                f" Capped at 'caution': only {sample_size} training rows, "
                f"below the {settings.REVIEW_MIN_SAMPLE_SIZE}-row floor."
            )
        lane_note = self._lane_note(proposal)
        if lane_note:
            reasoning += " " + lane_note

        return ReviewResult(
            verdict=verdict, score=round(composite, 4),
            reasoning=reasoning, hard_gate_passed=True,
        )

    @staticmethod
    def _lane_note(proposal: UpdateProposal) -> str:
        """Surfaces training_rows_by_lane transparently when a proposal's
        metrics carry it (see governance/lane_breakdown.py). Phase 1 does
        not itself populate this for any live proposal — that starts in
        Phase 2, once ml/learning_mode.py's nightly retrain is wired to
        create proposals instead of calling ModelRegistry.promote()
        directly. Rendering it only when present keeps this honest either
        way — no lane composition is ever guessed."""
        by_lane = proposal.metrics.get("training_rows_by_lane")
        if not by_lane or not isinstance(by_lane, dict):
            return ""
        total = sum(int(v) for v in by_lane.values()) or 1
        parts = ", ".join(f"{lane}={n} ({n / total:.0%})" for lane, n in by_lane.items())
        non_live = total - int(by_lane.get("LIVE", 0))
        flag = " — includes non-LIVE data" if non_live > 0 else ""
        return f"Training data by lane: {parts}.{flag}"


_agent: UpdateReviewAgent | None = None


def get_update_review_agent() -> UpdateReviewAgent:
    global _agent
    if _agent is None:
        _agent = UpdateReviewAgent()
    return _agent
