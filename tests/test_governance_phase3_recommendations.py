"""tests/test_governance_phase3_recommendations.py — V16 §72: Phase 3
(G5) of the AI Self-Improvement Governance Layer.

Covers the three pieces added on top of Phase 1 + Phase 2:

1. governance/recommendation_proposals.py::gate_recommendations() —
   the proposal producer + live-eligibility reader for learning/
   recommendations.
2. governance/apply_proposal.py's new proposal_type=="recommendation_param"
   branch.
3. api/app.py's approve endpoint extended to recommendation_param.
4. main.py::run_learning_recommendation_refresh()'s wiring of the above.

agent_weight remains out of scope for this phase (see
docs/architecture.md §72's scope note) — tests/test_governance_phase2.py's
existing test_approve_non_model_promotion_leaves_unapplied /
test_apply_rejects_non_model_promotion_type (both use agent_weight as the
still-unsupported example) are the regression check that this phase did
not accidentally widen apply_proposal()'s support beyond what was decided.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import settings
from governance.apply_proposal import ProposalApplyError, apply_proposal
from governance.recommendation_proposals import gate_recommendations
from governance.update_proposal import UpdateProposal
from learning.recommendation_engine import Recommendation

pytestmark = pytest.mark.unit


def _rec(id="rec_abc123", category="symbol", confidence="high", **kw) -> Recommendation:
    now = datetime.now(timezone.utc)
    defaults = dict(
        text="BTCUSDT performs well during TRENDING regime",
        category=category,
        confidence=confidence,
        based_on={"kind": "symbol_regime", "subject": "BTCUSDT|TRENDING", "metric": "win_rate"},
        id=id,
        symbol="BTCUSDT",
        regime="TRENDING",
        generated_at=now.isoformat(),
        expires_at=(now + timedelta(hours=settings.RECOMMENDATION_TTL_HOURS)).isoformat(),
    )
    defaults.update(kw)
    return Recommendation(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# governance/recommendation_proposals.py -- gate_recommendations()
# ─────────────────────────────────────────────────────────────────────────────
class TestGateRecommendations:

    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        from governance.proposal_store import reset_proposal_store
        self.store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        monkeypatch.setattr(settings, "RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL", True)
        yield

    def test_flag_off_returns_unchanged_no_proposals_created(self, monkeypatch):
        monkeypatch.setattr(settings, "RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL", False)
        recs = [_rec()]
        result = gate_recommendations(recs)
        assert result == recs
        assert self.store.list(proposal_type="recommendation_param") == []

    def test_fresh_recommendation_creates_pending_proposal_not_eligible(self):
        rec = _rec()
        result = gate_recommendations([rec])
        assert result == []  # not yet approved -> not eligible this cycle

        proposals = self.store.list(proposal_type="recommendation_param")
        assert len(proposals) == 1
        assert proposals[0].status == "pending"
        assert proposals[0].target == "recommendation.rec_abc123"
        assert proposals[0].rationale == rec.text
        assert proposals[0].after["confidence"] == "high"

    def test_existing_pending_proposal_not_duplicated(self):
        gate_recommendations([_rec()])
        gate_recommendations([_rec()])  # second cycle, same recommendation
        proposals = self.store.list(proposal_type="recommendation_param")
        assert len(proposals) == 1

    def test_approved_proposal_makes_recommendation_eligible(self):
        gate_recommendations([_rec()])
        proposal = self.store.list(proposal_type="recommendation_param")[0]
        self.store.set_status(proposal.id, "approved")

        result = gate_recommendations([_rec()])
        assert len(result) == 1
        assert result[0].id == "rec_abc123"
        # still only one proposal row -- approval reused, not re-proposed
        assert len(self.store.list(proposal_type="recommendation_param")) == 1

    def test_rejected_proposal_stays_excluded_not_reproposed(self):
        gate_recommendations([_rec()])
        proposal = self.store.list(proposal_type="recommendation_param")[0]
        self.store.set_status(proposal.id, "rejected")

        result = gate_recommendations([_rec()])
        assert result == []
        assert len(self.store.list(proposal_type="recommendation_param")) == 1

    def test_expired_approved_proposal_triggers_reproposal(self):
        gate_recommendations([_rec()])
        proposal = self.store.list(proposal_type="recommendation_param")[0]
        self.store.set_status(proposal.id, "approved")

        # simulate calling with `now` far past the recommendation's own
        # expires_at (default TTL 24h)
        future = datetime.now(timezone.utc) + timedelta(hours=48)
        result = gate_recommendations([_rec()], now=future)

        assert result == []  # the new proposal starts pending again
        proposals = self.store.list(proposal_type="recommendation_param")
        assert len(proposals) == 2
        statuses = sorted(p.status for p in proposals)
        assert statuses == ["approved", "pending"]

    def test_proposal_creation_failure_excludes_only_that_recommendation(self, monkeypatch):
        good = _rec(id="rec_good")
        bad = _rec(id="rec_bad")

        orig_create = self.store.create

        def _flaky_create(proposal):
            if proposal.target == "recommendation.rec_bad":
                raise RuntimeError("simulated DB failure")
            return orig_create(proposal)

        monkeypatch.setattr(self.store, "create", _flaky_create)

        result = gate_recommendations([good, bad])
        assert result == []  # neither approved yet
        proposals = self.store.list(proposal_type="recommendation_param")
        assert len(proposals) == 1
        assert proposals[0].target == "recommendation.rec_good"

    def test_multiple_recommendations_handled_independently(self):
        approved_rec = _rec(id="rec_approved")
        pending_rec = _rec(id="rec_pending")
        gate_recommendations([approved_rec, pending_rec])
        approved_proposal = next(
            p for p in self.store.list(proposal_type="recommendation_param")
            if p.target == "recommendation.rec_approved"
        )
        self.store.set_status(approved_proposal.id, "approved")

        result = gate_recommendations([approved_rec, pending_rec])
        assert [r.id for r in result] == ["rec_approved"]

    def test_new_proposal_is_reviewed_unscored(self):
        """Mirrors agents/update_review_agent.py's own Phase 1 scope:
        every type except model_promotion comes back unscored — this
        phase deliberately does not change that (no honest metrics
        source exists yet to score a recommendation's predictive
        value)."""
        gate_recommendations([_rec()])
        proposal = self.store.list(proposal_type="recommendation_param")[0]
        assert proposal.review_verdict == ""


# ─────────────────────────────────────────────────────────────────────────────
# governance/apply_proposal.py -- proposal_type == "recommendation_param"
# ─────────────────────────────────────────────────────────────────────────────
class TestApplyRecommendationParam:

    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path):
        from governance.proposal_store import reset_proposal_store
        self.store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        yield

    def _pending(self):
        proposal = UpdateProposal(
            proposal_type="recommendation_param", target="recommendation.rec_x",
            before={}, after={"text": "test", "id": "rec_x"}, rationale="test",
            generated_by="test",
        )
        return self.store.create(proposal)

    def test_apply_rejects_non_approved(self):
        pid = self._pending()  # still 'pending', never approved
        with pytest.raises(ProposalApplyError):
            apply_proposal(pid)

    def test_apply_approved_sets_applied_status(self):
        pid = self._pending()
        self.store.set_status(pid, "approved")
        result = apply_proposal(pid)
        assert result.status == "applied"
        assert self.store.get(pid).status == "applied"

    def test_apply_not_found_raises(self):
        with pytest.raises(ProposalApplyError):
            apply_proposal(999999)


# ─────────────────────────────────────────────────────────────────────────────
# api/app.py -- POST /api/governance/proposals/approve for recommendation_param
# ─────────────────────────────────────────────────────────────────────────────
class TestGovernanceAPIRecommendationParam:

    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path):
        from governance.proposal_store import reset_proposal_store
        self.store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        yield

    def _client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def _pending_recommendation_param(self):
        proposal = UpdateProposal(
            proposal_type="recommendation_param", target="recommendation.rec_api",
            before={}, after={"text": "test", "id": "rec_api"}, rationale="test",
            generated_by="test",
        )
        return self.store.create(proposal)

    def test_approve_recommendation_param_applies_immediately(self):
        pid = self._pending_recommendation_param()
        with self._client() as c:
            r = c.post("/api/governance/proposals/approve", json={"proposal_id": pid})
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["approved"] is True
        assert body["applied"] is True
        assert body["proposal"]["status"] == "applied"

    def test_reject_recommendation_param_still_works(self):
        pid = self._pending_recommendation_param()
        with self._client() as c:
            r = c.post("/api/governance/proposals/reject", json={"proposal_id": pid})
        assert r.status_code == 200
        assert self.store.get(pid).status == "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# main.py -- run_learning_recommendation_refresh()'s gate_recommendations() wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestRunLearningRecommendationRefreshGating:

    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        from governance.proposal_store import reset_proposal_store
        self.store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        monkeypatch.setattr(settings, "RECOMMENDATION_APPLICATION_ENABLED", True)
        yield

    def _fake_bundle(self, recs):
        from unittest.mock import MagicMock
        bundle = MagicMock()
        bundle.recommendations = recs
        bundle.dataset.row_count = 42
        return bundle

    def test_only_approved_recommendations_reach_state(self, monkeypatch):
        from main import run_learning_recommendation_refresh
        monkeypatch.setattr(settings, "RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL", True)

        rec = _rec()
        import learning.learning_report as lr_module
        bundle = self._fake_bundle([rec])
        monkeypatch.setattr(lr_module.LearningReportGenerator, "generate", lambda self: bundle)

        captured_state = {}
        import api.app as api_module
        monkeypatch.setattr(api_module, "set_state", lambda k, v: captured_state.__setitem__(k, v))

        run_learning_recommendation_refresh({"journal_v2": None})

        assert captured_state["learning_recommendations"] == []  # not yet approved

        proposal = self.store.list(proposal_type="recommendation_param")[0]
        self.store.set_status(proposal.id, "approved")

        run_learning_recommendation_refresh({"journal_v2": None})
        assert [r.id for r in captured_state["learning_recommendations"]] == [rec.id]

    def test_flag_off_preserves_pre_governance_behavior(self, monkeypatch):
        from main import run_learning_recommendation_refresh
        monkeypatch.setattr(settings, "RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL", False)

        rec = _rec()
        import learning.learning_report as lr_module
        bundle = self._fake_bundle([rec])
        monkeypatch.setattr(lr_module.LearningReportGenerator, "generate", lambda self: bundle)

        captured_state = {}
        import api.app as api_module
        monkeypatch.setattr(api_module, "set_state", lambda k, v: captured_state.__setitem__(k, v))

        run_learning_recommendation_refresh({"journal_v2": None})

        assert captured_state["learning_recommendations"] == [rec]
        assert self.store.list(proposal_type="recommendation_param") == []
