"""governance/ — AI Self-Improvement Governance Layer (V16 Phase 4C, Track A).

Phase 1 of docs/architecture.md §48. Nothing in this package ever applies a
change to the live system by itself — it only records what the system
*proposes* to change (`UpdateProposal`, in update_proposal.py), persists that
proposal (`ProposalStore`, in proposal_store.py), and — via
agents/update_review_agent.py — attaches a deterministic, explainable second
opinion to help a human decide. Every proposal starts and stays 'pending'
until a human explicitly approves or rejects it; nothing in this codebase
calls ProposalStore.set_status(..., 'approved') automatically.

Phase 1 scope (this package, as delivered): the proposal record + store +
review agent only, no producer wired in yet.

Phase 2 (§58, 2026-09-08): wired the first real proposal producer —
ml/learning_mode.py's nightly retrain creates a "model_promotion" proposal
instead of calling ModelRegistry.promote() directly (gated behind
MODEL_PROMOTION_REQUIRES_APPROVAL) — plus apply_proposal.py (the one place
an approved proposal takes effect) and the three /api/governance/proposals
endpoints.

Phase 3 / G5 (§72): a second proposal producer,
recommendation_proposals.py — gates learning/'s daily recommendation batch
(main.py::run_learning_recommendation_refresh()) behind the same
propose/review/approve pipeline (RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL),
extending apply_proposal.py accordingly. agent_weight, strategy_selection,
and logic_change proposal types remain unwired — see docs/architecture.md
§72's own scope note for why agent_weight specifically was deferred.
"""
from __future__ import annotations
