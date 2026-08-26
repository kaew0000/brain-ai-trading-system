"""tests/test_update_review_agent.py — V16 Phase 4C, AI Self-Improvement
Governance Layer Phase 1 (docs/architecture.md §48).
"""
from __future__ import annotations

import pytest

from agents.update_review_agent import (
    UpdateReviewAgent,
    model_promotion_hard_gate_passed,
)
from governance.update_proposal import UpdateProposal
from ml.model_registry import ModelRegistry

pytestmark = pytest.mark.unit


@pytest.fixture
def agent():
    return UpdateReviewAgent()


def _proposal(before, after, metrics=None, proposal_type="model_promotion"):
    return UpdateProposal(
        proposal_type=proposal_type,
        target="model_registry.meta_label",
        before=before, after=after,
        rationale="test", metrics=metrics or {},
        generated_by="test",
    )


class TestHardGateMatchesModelRegistryExactly:
    """model_promotion_hard_gate_passed() must encode the identical rule
    ml/model_registry.py's should_promote() uses — asserted directly
    against a real ModelRegistry instance, not just re-derived by eye, so
    the two can never silently drift apart."""

    @pytest.fixture
    def registry(self, tmp_path):
        reg = ModelRegistry(db_path=str(tmp_path / "test.db"), models_dir=str(tmp_path / "models"))
        model_id = reg.register(
            model_type="meta_label", model_obj={"dummy": True}, algorithm="dummy",
            training_rows=100,
            metrics={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
        )
        reg.promote(model_id, "meta_label")
        return reg

    @pytest.mark.parametrize("new_metrics", [
        {"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.12},   # clear improvement
        {"win_rate": 0.50, "profit_factor": 1.30, "max_drawdown": 0.12},   # win_rate not improved
        {"win_rate": 0.58, "profit_factor": 1.10, "max_drawdown": 0.12},   # pf not improved
        {"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.20},   # drawdown worse
        {"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.15},   # drawdown exactly equal
    ])
    def test_agrees_with_should_promote(self, registry, new_metrics):
        before = registry.get_active("meta_label")
        expected = registry.should_promote(new_metrics, "meta_label")
        actual = model_promotion_hard_gate_passed(
            before={"win_rate": before["win_rate"], "profit_factor": before["profit_factor"],
                    "max_drawdown": before["max_drawdown"]},
            after=new_metrics,
        )
        assert actual == expected

    def test_no_prior_model_passes_unconditionally(self, tmp_path):
        reg = ModelRegistry(db_path=str(tmp_path / "empty.db"), models_dir=str(tmp_path / "models"))
        assert reg.get_active("meta_label") is None
        assert reg.should_promote({"win_rate": 0.01, "profit_factor": 0.01, "max_drawdown": 99}, "meta_label") is True
        assert model_promotion_hard_gate_passed(before={}, after={"win_rate": 0.01}) is True


class TestReviewModelPromotion:

    def test_failing_gate_is_reject_recommended_with_zero_score(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.55, "profit_factor": 1.30, "max_drawdown": 0.10},
            after={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.20, "training_rows": 200},
        ))
        assert result.hard_gate_passed is False
        assert result.verdict == "reject_recommended"
        assert result.score == 0.0

    def test_strong_improvement_with_ample_samples_is_approve_recommended(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
            after={"win_rate": 0.60, "profit_factor": 1.70, "max_drawdown": 0.05, "training_rows": 200},
        ))
        assert result.hard_gate_passed is True
        assert result.verdict == "approve_recommended"
        assert 0.0 < result.score <= 1.0

    def test_marginal_improvement_is_caution_not_approve(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.500, "profit_factor": 1.100, "max_drawdown": 0.150},
            after={"win_rate": 0.501, "profit_factor": 1.101, "max_drawdown": 0.149, "training_rows": 200},
        ))
        assert result.hard_gate_passed is True
        assert result.verdict == "caution"

    def test_below_min_sample_size_capped_at_caution_even_if_gate_passes(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
            after={"win_rate": 0.65, "profit_factor": 2.00, "max_drawdown": 0.02, "training_rows": 3},
        ))
        assert result.hard_gate_passed is True
        assert result.verdict == "caution"
        assert "floor" in result.reasoning

    def test_no_prior_model_passes_gate_and_can_be_scored(self, agent):
        result = agent.review(_proposal(
            before={},
            after={"win_rate": 0.55, "profit_factor": 1.40, "max_drawdown": 0.08, "training_rows": 100},
        ))
        assert result.hard_gate_passed is True
        assert result.verdict in ("approve_recommended", "caution")

    def test_score_is_always_between_zero_and_one(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.10, "profit_factor": 0.50, "max_drawdown": 0.50},
            after={"win_rate": 0.99, "profit_factor": 9.0, "max_drawdown": 0.0, "training_rows": 100_000},
        ))
        assert 0.0 <= result.score <= 1.0

    def test_zero_prior_drawdown_is_neutral_not_a_crash(self, agent):
        # Regression guard for the old_dd == 0 division-by-zero edge case.
        result = agent.review(_proposal(
            before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.0},
            after={"win_rate": 0.55, "profit_factor": 1.20, "max_drawdown": 0.0, "training_rows": 100},
        ))
        assert result.hard_gate_passed is True


class TestUnscoredProposalTypes:

    @pytest.mark.parametrize("proposal_type", [
        "agent_weight", "recommendation_param", "strategy_selection", "logic_change",
    ])
    def test_returns_unscored_result_not_a_guess(self, agent, proposal_type):
        result = agent.review(_proposal(
            before={"weight": 0.25}, after={"weight": 0.30},
            proposal_type=proposal_type,
        ))
        assert result.verdict == ""
        assert result.score == 0.0
        assert result.hard_gate_passed is None
        assert "Phase 1" in result.reasoning


class TestLaneNoteTransparency:

    def test_lane_breakdown_present_in_reasoning_when_provided(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
            after={"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.12, "training_rows": 200},
            metrics={"training_rows": 200, "training_rows_by_lane": {"LIVE": 150, "TRAINING": 50}},
        ))
        assert "LIVE" in result.reasoning
        assert "TRAINING" in result.reasoning
        assert "non-LIVE" in result.reasoning

    def test_all_live_lane_breakdown_does_not_flag_non_live(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
            after={"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.12, "training_rows": 200},
            metrics={"training_rows": 200, "training_rows_by_lane": {"LIVE": 200}},
        ))
        assert "non-LIVE" not in result.reasoning

    def test_no_lane_breakdown_provided_omits_the_note(self, agent):
        result = agent.review(_proposal(
            before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
            after={"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.12, "training_rows": 200},
        ))
        assert "Training data by lane" not in result.reasoning


class TestScoreWeightsSumToOne:

    def test_review_score_weights_sum_to_one(self):
        from config.settings import settings
        total = (
            settings.REVIEW_SCORE_WEIGHT_IMPROVEMENT
            + settings.REVIEW_SCORE_WEIGHT_DRAWDOWN_MARGIN
            + settings.REVIEW_SCORE_WEIGHT_SAMPLE_SIZE
        )
        assert total == pytest.approx(1.0)
