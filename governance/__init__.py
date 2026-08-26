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
review agent only. Wiring an actual proposal *producer* — e.g.
ml/learning_mode.py's nightly retrain creating a 'model_promotion' proposal
instead of calling ModelRegistry.promote() directly — is Phase 2 and not
part of this delivery; see PATCH_NOTES.md.
"""
from __future__ import annotations
