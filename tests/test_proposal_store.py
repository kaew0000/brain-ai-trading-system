"""tests/test_proposal_store.py — V16 Phase 4C, AI Self-Improvement
Governance Layer Phase 1 (docs/architecture.md §48).

Uses a tmp_path-backed temp-file DB per test (database/db.py caches one
shared connection per the literal path ":memory:" for the whole process —
same reasoning as tests/test_learning_dataset_builder.py and
tests/test_agent_outcome_attribution.py).
"""
from __future__ import annotations

import pytest

from governance.proposal_store import ProposalStore
from governance.update_proposal import UpdateProposal

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    return ProposalStore(db_path=str(tmp_path / "test.db"))


def _sample_proposal(**overrides) -> UpdateProposal:
    kwargs = dict(
        proposal_type="model_promotion",
        target="model_registry.meta_label",
        before={"win_rate": 0.50, "profit_factor": 1.10, "max_drawdown": 0.15},
        after={"win_rate": 0.58, "profit_factor": 1.30, "max_drawdown": 0.12, "training_rows": 120},
        rationale="Nightly retrain produced a candidate that clears the promotion gate.",
        metrics={"training_rows": 120},
        generated_by="ml.learning_mode",
    )
    kwargs.update(overrides)
    return UpdateProposal(**kwargs)


class TestUpdateProposalValidation:

    def test_unknown_proposal_type_raises(self):
        with pytest.raises(ValueError):
            UpdateProposal(proposal_type="not_a_real_type", target="x")

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError):
            UpdateProposal(proposal_type="model_promotion", target="x", status="not_a_real_status")

    def test_logic_change_always_requires_pr_review(self):
        p = UpdateProposal(proposal_type="logic_change", target="x", requires_pr_review=False)
        assert p.requires_pr_review is True

    def test_non_logic_change_defaults_requires_pr_review_false(self):
        p = _sample_proposal()
        assert p.requires_pr_review is False

    def test_created_at_and_updated_at_default_to_now_and_match(self):
        p = _sample_proposal()
        assert p.created_at is not None
        assert p.updated_at == p.created_at


class TestUpdateProposalRoundTrip:

    def test_to_row_from_row_round_trip_preserves_fields(self):
        p = _sample_proposal()
        row = p.to_row()
        rebuilt = UpdateProposal.from_row({**row, "id": 1})
        assert rebuilt.proposal_type == p.proposal_type
        assert rebuilt.target == p.target
        assert rebuilt.before == p.before
        assert rebuilt.after == p.after
        assert rebuilt.metrics == p.metrics
        assert rebuilt.status == p.status

    def test_to_row_json_encodes_dict_fields(self):
        p = _sample_proposal()
        row = p.to_row()
        assert isinstance(row["before_json"], str)
        assert isinstance(row["after_json"], str)
        assert isinstance(row["metrics_json"], str)


class TestProposalStoreCreateAndGet:

    def test_create_returns_positive_id(self, store):
        pid = store.create(_sample_proposal())
        assert pid > 0

    def test_get_returns_the_created_proposal(self, store):
        pid = store.create(_sample_proposal(target="ceo_agent.WEIGHTS.smc"))
        got = store.get(pid)
        assert got is not None
        assert got.id == pid
        assert got.target == "ceo_agent.WEIGHTS.smc"

    def test_get_missing_id_returns_none(self, store):
        assert store.get(999999) is None

    def test_created_proposal_always_starts_pending(self, store):
        pid = store.create(_sample_proposal(status="approved"))
        got = store.get(pid)
        assert got.status == "pending"

    def test_before_after_metrics_survive_round_trip_through_store(self, store):
        p = _sample_proposal()
        pid = store.create(p)
        got = store.get(pid)
        assert got.before == p.before
        assert got.after == p.after
        assert got.metrics == p.metrics


class TestProposalStoreList:

    def test_list_returns_newest_first(self, store):
        first = store.create(_sample_proposal(target="a"))
        second = store.create(_sample_proposal(target="b"))
        results = store.list()
        assert [r.id for r in results][:2] == [second, first]

    def test_list_filters_by_status(self, store):
        pid = store.create(_sample_proposal())
        store.set_status(pid, "approved")
        store.create(_sample_proposal(target="still-pending"))
        pending = store.list(status="pending")
        approved = store.list(status="approved")
        assert all(p.status == "pending" for p in pending)
        assert all(p.status == "approved" for p in approved)
        assert pid in [p.id for p in approved]

    def test_list_filters_by_proposal_type(self, store):
        store.create(_sample_proposal(proposal_type="model_promotion"))
        store.create(_sample_proposal(proposal_type="agent_weight", target="ceo_agent.WEIGHTS.smc"))
        weights_only = store.list(proposal_type="agent_weight")
        assert all(p.proposal_type == "agent_weight" for p in weights_only)

    def test_list_respects_limit(self, store):
        for i in range(5):
            store.create(_sample_proposal(target=f"t{i}"))
        assert len(store.list(limit=2)) == 2


class TestProposalStoreSetReview:

    def test_set_review_updates_verdict_score_reasoning(self, store):
        pid = store.create(_sample_proposal())
        ok = store.set_review(pid, "approve_recommended", "looks good", 0.82)
        assert ok is True
        got = store.get(pid)
        assert got.review_verdict == "approve_recommended"
        assert got.review_reasoning == "looks good"
        assert got.review_score == pytest.approx(0.82)

    def test_set_review_does_not_change_status(self, store):
        pid = store.create(_sample_proposal())
        store.set_review(pid, "approve_recommended", "looks good", 0.82)
        got = store.get(pid)
        assert got.status == "pending"

    def test_set_review_missing_id_returns_false(self, store):
        assert store.set_review(999999, "caution", "n/a", 0.0) is False


class TestProposalStoreSetStatus:

    def test_approve_sets_decided_at(self, store):
        pid = store.create(_sample_proposal())
        store.set_status(pid, "approved")
        got = store.get(pid)
        assert got.status == "approved"
        assert got.decided_at != ""

    def test_reject_sets_decided_at(self, store):
        pid = store.create(_sample_proposal())
        store.set_status(pid, "rejected")
        got = store.get(pid)
        assert got.status == "rejected"
        assert got.decided_at != ""

    def test_applied_sets_applied_at(self, store):
        pid = store.create(_sample_proposal())
        store.set_status(pid, "approved")
        store.set_status(pid, "applied")
        got = store.get(pid)
        assert got.status == "applied"
        assert got.applied_at != ""

    def test_unknown_status_raises(self, store):
        pid = store.create(_sample_proposal())
        with pytest.raises(ValueError):
            store.set_status(pid, "not_a_real_status")

    def test_set_status_missing_id_returns_false(self, store):
        assert store.set_status(999999, "approved") is False


class TestProposalStoreRequiresPrReviewPersists:

    def test_logic_change_requires_pr_review_survives_round_trip(self, store):
        p = UpdateProposal(
            proposal_type="logic_change",
            target="execution.strategy_registry",
            before={}, after={"diff": "placeholder"},
            rationale="AI-authored strategy candidate",
        )
        pid = store.create(p)
        got = store.get(pid)
        assert got.requires_pr_review is True
