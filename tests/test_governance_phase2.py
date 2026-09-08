"""tests/test_governance_phase2.py — V16 §58: Phase 2 of the AI
Self-Improvement Governance Layer.

Covers the three pieces added on top of Phase 1
(governance/proposal_store.py, governance/update_proposal.py,
agents/update_review_agent.py — already covered by
tests/test_update_review_agent.py):

1. ml/learning_mode.py's MODEL_PROMOTION_REQUIRES_APPROVAL gate --
   a nightly retrain that beats should_promote() creates a proposal
   instead of promoting directly, by default.
2. governance/apply_proposal.py -- the one place an "approved"
   decision actually promotes a model.
3. api/app.py's three governance endpoints -- list / approve / reject.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config.settings import settings
from governance.apply_proposal import ProposalApplyError, apply_proposal
from governance.update_proposal import UpdateProposal
from ml.model_registry import ModelRegistry

pytestmark = pytest.mark.unit


def _metrics(wr=0.60, pf=1.40, dd=0.10, rows=200):
    return {"win_rate": wr, "profit_factor": pf, "max_drawdown": dd, "training_rows": rows}


# ─────────────────────────────────────────────────────────────────────────────
# ml/learning_mode.py -- _register_and_gate_promotion() / run_nightly_retrain()
# ─────────────────────────────────────────────────────────────────────────────
class TestRegisterAndGatePromotion:

    @pytest.fixture
    def reg(self, tmp_path):
        return ModelRegistry(db_path=str(tmp_path / "test.db"), models_dir=str(tmp_path / "models"))

    def test_gated_by_default_creates_proposal_not_promote(self, reg, monkeypatch, tmp_path):
        from governance.proposal_store import reset_proposal_store
        store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        monkeypatch.setattr(settings, "MODEL_PROMOTION_REQUIRES_APPROVAL", True)

        from ml.learning_mode import _register_and_gate_promotion
        metrics = _metrics()
        promoted, reason, proposal_id = _register_and_gate_promotion(
            reg, "meta_label", {"dummy": True}, "xgboost_or_gbm", metrics,
            "test", builder=None, symbol=None,
        )

        assert promoted is False
        assert proposal_id is not None
        assert "pending human approval" in reason
        # The model was registered (candidate saved) but NOT activated.
        assert reg.get_active("meta_label") is None
        proposal = store.get(proposal_id)
        assert proposal.status == "pending"
        assert proposal.proposal_type == "model_promotion"
        assert proposal.metrics["model_type"] == "meta_label"
        assert proposal.after == metrics
        # A review opinion was attached (Phase 1's UpdateReviewAgent).
        assert proposal.review_verdict != "" or proposal.review_reasoning != ""

    def test_promotes_directly_when_approval_not_required(self, reg, monkeypatch, tmp_path):
        from governance.proposal_store import reset_proposal_store
        store = reset_proposal_store(db_path=str(tmp_path / "test2.db"))
        monkeypatch.setattr(settings, "MODEL_PROMOTION_REQUIRES_APPROVAL", False)

        from ml.learning_mode import _register_and_gate_promotion
        promoted, reason, proposal_id = _register_and_gate_promotion(
            reg, "meta_label", {"dummy": True}, "xgboost_or_gbm", _metrics(),
            "test", builder=None, symbol=None,
        )

        assert promoted is True
        assert proposal_id is None
        assert "promoted" in reason
        assert reg.get_active("meta_label") is not None
        # No proposal created at all in this mode.
        assert store.list() == []

    def test_proposal_creation_failure_does_not_fall_back_to_auto_promote(self, reg, monkeypatch):
        """If creating the governance proposal itself blows up (e.g. DB
        unavailable), the model must stay un-promoted -- silently
        falling back to auto-promote would defeat the entire point of
        MODEL_PROMOTION_REQUIRES_APPROVAL."""
        monkeypatch.setattr(settings, "MODEL_PROMOTION_REQUIRES_APPROVAL", True)

        import governance.proposal_store as ps_module
        broken_store = MagicMock()
        broken_store.create.side_effect = RuntimeError("db is down")
        monkeypatch.setattr(ps_module, "get_proposal_store", lambda: broken_store)

        from ml.learning_mode import _register_and_gate_promotion
        promoted, reason, proposal_id = _register_and_gate_promotion(
            reg, "meta_label", {"dummy": True}, "xgboost_or_gbm", _metrics(),
            "test", builder=None, symbol=None,
        )

        assert promoted is False
        assert proposal_id is None
        assert "governance proposal creation failed" in reason
        assert reg.get_active("meta_label") is None   # still not promoted

    def test_lane_breakdown_attached_when_builder_provides_it(self, reg, monkeypatch, tmp_path):
        from governance.proposal_store import reset_proposal_store
        store = reset_proposal_store(db_path=str(tmp_path / "test3.db"))
        monkeypatch.setattr(settings, "MODEL_PROMOTION_REQUIRES_APPROVAL", True)

        builder = MagicMock()
        builder.get_lane_breakdown.return_value = {"LIVE": 150, "TRAINING": 50}

        from ml.learning_mode import _register_and_gate_promotion
        _, _, proposal_id = _register_and_gate_promotion(
            reg, "meta_label", {"dummy": True}, "xgboost_or_gbm", _metrics(),
            "test", builder=builder, symbol="BTCUSDT",
        )
        proposal = store.get(proposal_id)
        assert proposal.metrics["training_rows_by_lane"] == {"LIVE": 150, "TRAINING": 50}
        builder.get_lane_breakdown.assert_called_once_with(symbol="BTCUSDT")


class TestRunNightlyRetrainGovernanceWiring:
    """End-to-end-ish: run_nightly_retrain() itself, with training and
    the dataset builder mocked out (that's ml/trainer.py's own test
    surface, not this module's), asserting only that a beat-the-gate
    result routes through the governance gate rather than promoting."""

    def test_meta_label_promotion_gated_creates_proposal(self, monkeypatch, tmp_path):
        from ml.model_registry import reset_model_registry
        from governance.proposal_store import reset_proposal_store
        reset_model_registry(db_path=str(tmp_path / "test.db"))
        store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        monkeypatch.setattr(settings, "MODEL_PROMOTION_REQUIRES_APPROVAL", True)

        import pandas as pd
        fake_df = pd.DataFrame({"a": [1, 2, 3]})
        builder = MagicMock()
        builder.export_training_dataframe.return_value = fake_df
        builder.row_count.return_value = 200
        builder.get_lane_breakdown.return_value = {}
        monkeypatch.setattr(
            "research.dataset_builder.get_dataset_builder", lambda: builder
        )
        monkeypatch.setattr(
            "ml.trainer.train_meta_label",
            lambda df: ({"dummy": True}, _metrics(wr=0.65, pf=1.5)),
        )
        monkeypatch.setattr(
            "ml.trainer.train_outcome_predictor", lambda df: None,
        )

        from ml.learning_mode import run_nightly_retrain
        result = run_nightly_retrain(min_rows=50)

        assert result["status"] == "completed"
        assert result["meta_label"]["trained"] is True
        assert result["meta_label"]["promoted"] is False
        assert "proposal_id" in result["meta_label"]
        assert store.get(result["meta_label"]["proposal_id"]).status == "pending"
        from ml.model_registry import get_model_registry
        assert get_model_registry().get_active("meta_label") is None


# ─────────────────────────────────────────────────────────────────────────────
# governance/apply_proposal.py
# ─────────────────────────────────────────────────────────────────────────────
class TestApplyProposal:

    @pytest.fixture
    def store(self, tmp_path):
        from governance.proposal_store import reset_proposal_store
        return reset_proposal_store(db_path=str(tmp_path / "test.db"))

    @pytest.fixture
    def reg(self, tmp_path, monkeypatch):
        from ml.model_registry import reset_model_registry
        r = reset_model_registry(db_path=str(tmp_path / "test.db"))
        return r

    def _pending_model_promotion(self, store, reg, model_type="meta_label"):
        model_id = reg.register(model_type, {"dummy": True}, "xgboost_or_gbm", 200, _metrics())
        proposal = UpdateProposal(
            proposal_type="model_promotion", target=f"model_registry.{model_type}",
            before={}, after=_metrics(), rationale="test",
            metrics={"model_id": model_id, "model_type": model_type},
            generated_by="test",
        )
        return store.create(proposal), model_id

    def test_apply_not_found_raises(self, store, reg):
        with pytest.raises(ProposalApplyError, match="not found"):
            apply_proposal(999)

    def test_apply_requires_approved_status(self, store, reg):
        pid, _ = self._pending_model_promotion(store, reg)
        with pytest.raises(ProposalApplyError, match="not 'approved'"):
            apply_proposal(pid)   # still 'pending'
        assert store.get(pid).status == "pending"   # unchanged

    def test_apply_rejects_non_model_promotion_type(self, store, reg):
        proposal = UpdateProposal(
            proposal_type="agent_weight", target="ceo_agent.WEIGHTS.smc",
            before={}, after={}, rationale="test", generated_by="test",
        )
        pid = store.create(proposal)
        store.set_status(pid, "approved")
        with pytest.raises(ProposalApplyError, match="model_promotion only"):
            apply_proposal(pid)
        # Left at 'approved', not silently marked applied or failed.
        assert store.get(pid).status == "approved"

    def test_apply_fails_cleanly_when_model_metadata_missing(self, store, reg):
        proposal = UpdateProposal(
            proposal_type="model_promotion", target="model_registry.meta_label",
            before={}, after={}, rationale="test", metrics={}, generated_by="test",
        )
        pid = store.create(proposal)
        store.set_status(pid, "approved")
        with pytest.raises(ProposalApplyError, match="missing model_type/model_id"):
            apply_proposal(pid)
        assert store.get(pid).status == "apply_failed"

    def test_apply_success_promotes_and_marks_applied(self, store, reg):
        pid, model_id = self._pending_model_promotion(store, reg)
        store.set_status(pid, "approved")
        assert reg.get_active("meta_label") is None

        result = apply_proposal(pid)

        assert result.status == "applied"
        active = reg.get_active("meta_label")
        assert active is not None
        assert active["id"] == model_id

    def test_apply_failure_marks_apply_failed_not_silent(self, store, reg, monkeypatch):
        pid, _ = self._pending_model_promotion(store, reg)
        store.set_status(pid, "approved")

        import ml.model_registry as mr_module
        broken_reg = MagicMock()
        broken_reg.promote.side_effect = RuntimeError("disk full")
        monkeypatch.setattr(mr_module, "get_model_registry", lambda: broken_reg)

        with pytest.raises(ProposalApplyError, match="disk full"):
            apply_proposal(pid)
        assert store.get(pid).status == "apply_failed"


# ─────────────────────────────────────────────────────────────────────────────
# api/app.py -- /api/governance/proposals (list / approve / reject)
# ─────────────────────────────────────────────────────────────────────────────
class TestGovernanceAPI:

    @pytest.fixture(autouse=True)
    def _isolated_stores(self, tmp_path, monkeypatch):
        from governance.proposal_store import reset_proposal_store
        from ml.model_registry import reset_model_registry
        self.store = reset_proposal_store(db_path=str(tmp_path / "test.db"))
        self.reg = reset_model_registry(db_path=str(tmp_path / "test.db"))
        yield

    def _client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def _pending_model_promotion(self):
        model_id = self.reg.register("meta_label", {"dummy": True}, "xgboost_or_gbm", 200, _metrics())
        proposal = UpdateProposal(
            proposal_type="model_promotion", target="model_registry.meta_label",
            before={}, after=_metrics(), rationale="test",
            metrics={"model_id": model_id, "model_type": "meta_label"},
            generated_by="test",
        )
        return self.store.create(proposal), model_id

    def test_list_proposals_empty(self):
        with self._client() as c:
            r = c.get("/api/governance/proposals")
        assert r.status_code == 200
        assert r.json()["data"]["proposals"] == []

    def test_list_proposals_returns_created(self):
        pid, _ = self._pending_model_promotion()
        with self._client() as c:
            r = c.get("/api/governance/proposals")
        rows = r.json()["data"]["proposals"]
        assert len(rows) == 1
        assert rows[0]["id"] == pid
        assert rows[0]["status"] == "pending"

    def test_list_proposals_rejects_invalid_status(self):
        with self._client() as c:
            r = c.get("/api/governance/proposals", params={"status": "not_a_real_status"})
        assert r.status_code == 400

    def test_approve_requires_int_proposal_id(self):
        with self._client() as c:
            r = c.post("/api/governance/proposals/approve", json={"proposal_id": "abc"})
        assert r.status_code == 400

    def test_approve_not_found(self):
        with self._client() as c:
            r = c.post("/api/governance/proposals/approve", json={"proposal_id": 999})
        assert r.status_code == 404

    def test_approve_rejects_non_pending(self):
        pid, _ = self._pending_model_promotion()
        self.store.set_status(pid, "rejected")
        with self._client() as c:
            r = c.post("/api/governance/proposals/approve", json={"proposal_id": pid})
        assert r.status_code == 409

    def test_approve_model_promotion_applies_immediately(self):
        pid, model_id = self._pending_model_promotion()
        with self._client() as c:
            r = c.post("/api/governance/proposals/approve", json={"proposal_id": pid})
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["approved"] is True
        assert body["applied"] is True
        assert body["proposal"]["status"] == "applied"
        assert self.reg.get_active("meta_label")["id"] == model_id

    def test_approve_non_model_promotion_leaves_unapplied(self):
        proposal = UpdateProposal(
            proposal_type="agent_weight", target="ceo_agent.WEIGHTS.smc",
            before={}, after={}, rationale="test", generated_by="test",
        )
        pid = self.store.create(proposal)
        with self._client() as c:
            r = c.post("/api/governance/proposals/approve", json={"proposal_id": pid})
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["approved"] is True
        assert body["applied"] is False
        assert self.store.get(pid).status == "approved"   # not "applied"

    def test_reject_requires_int_proposal_id(self):
        with self._client() as c:
            r = c.post("/api/governance/proposals/reject", json={"proposal_id": "abc"})
        assert r.status_code == 400

    def test_reject_success(self):
        pid, model_id = self._pending_model_promotion()
        with self._client() as c:
            r = c.post("/api/governance/proposals/reject",
                       json={"proposal_id": pid, "reason": "sample size too small"})
        assert r.status_code == 200
        assert self.store.get(pid).status == "rejected"
        # Rejected -- must NOT have been applied/promoted.
        assert self.reg.get_active("meta_label") is None

    def test_reject_rejects_non_pending(self):
        pid, _ = self._pending_model_promotion()
        self.store.set_status(pid, "approved")
        with self._client() as c:
            r = c.post("/api/governance/proposals/reject", json={"proposal_id": pid})
        assert r.status_code == 409

    def test_operator_role_required_for_approve_when_auth_enabled(self, monkeypatch):
        """Mirrors TestRiskOverrideAPI's own auth-tier expectations --
        approve/reject must be gated at Role.OPERATOR, same trust level
        as arming a risk override."""
        import api.app as app_module
        assert ("POST", "/api/governance/proposals/approve") in app_module._AUTH_OPERATOR_ROUTES
        assert ("POST", "/api/governance/proposals/reject") in app_module._AUTH_OPERATOR_ROUTES
