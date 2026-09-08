"""governance/apply_proposal.py — Phase 2 (V16 §58): the one place a
human's "approved" decision on an UpdateProposal actually takes effect.

Deliberately separate from ProposalStore.set_status(): setting
status="approved" is a pure data write — governance/__init__.py's module
docstring says "nothing in this codebase calls
ProposalStore.set_status(..., 'approved') automatically", and that
invariant is still true here, only a human-triggered API route
(api/app.py) ever calls it. Actually promoting a model is a separate,
real, consequential action with its own failure mode (missing model
file, DB error) that needs to be handled and recorded as
"apply_failed", not silently swallowed by the approval write itself.

Phase 2 scope: proposal_type == "model_promotion" only, mirroring
agents/update_review_agent.py's own Phase 1 scope for the identical
reason — it's the only proposal type with a concrete "what does
approving this actually DO" answer today (see that module's docstring).
Every other proposal_type raises rather than silently no-op'ing, so a
caller can never mistake "nothing happened" for "applied".
"""
from __future__ import annotations

from governance.proposal_store import get_proposal_store
from governance.update_proposal import UpdateProposal
from utils.logger import get_logger

logger = get_logger(__name__)


class ProposalApplyError(Exception):
    pass


def apply_proposal(proposal_id: int) -> UpdateProposal:
    """Carry out an already-approved proposal.

    Caller's responsibility to have already set status="approved" (see
    ProposalStore.set_status) — this function re-checks that status
    itself rather than trusting the caller, since this is the one place
    a real state change happens (a model going live with real trading
    decisions).

    Raises ProposalApplyError on any failure. Always records the outcome
    on the proposal (status="applied" or "apply_failed") before
    returning/raising once the check for "is this even applyable"
    passes — never leaves a proposal silently stuck at "approved" with
    no record of what happened when someone tried to apply it.
    """
    store = get_proposal_store()
    proposal = store.get(proposal_id)
    if proposal is None:
        raise ProposalApplyError(f"proposal #{proposal_id} not found")

    if proposal.status != "approved":
        raise ProposalApplyError(
            f"proposal #{proposal_id} is {proposal.status!r}, not 'approved' -- "
            f"call ProposalStore.set_status(id, 'approved') first"
        )

    if proposal.proposal_type != "model_promotion":
        raise ProposalApplyError(
            f"apply_proposal() has no defined behavior for "
            f"proposal_type={proposal.proposal_type!r} yet (Phase 2 scope: "
            f"model_promotion only) -- proposal left at status='approved'"
        )

    model_type = proposal.metrics.get("model_type")
    model_id = proposal.metrics.get("model_id")
    if not model_type or model_id is None:
        store.set_status(proposal_id, "apply_failed")
        raise ProposalApplyError(
            f"proposal #{proposal_id} is missing model_type/model_id in "
            f"its metrics -- cannot apply"
        )

    try:
        from ml.model_registry import get_model_registry
        reg = get_model_registry()
        reg.promote(int(model_id), model_type)

        if model_type == "meta_label":
            # Best-effort — a failed reload here doesn't undo the
            # promotion (the new model is already active in the DB); the
            # advisor will pick it up on its own next natural reload if
            # this one fails. Same "best-effort, don't let an auxiliary
            # step fail the main action" posture ml/learning_mode.py's
            # pre-existing reload-on-promote already uses.
            try:
                from ml.ml_advisor import get_ml_advisor
                get_ml_advisor().reload()
            except Exception as exc:
                logger.warning(
                    f"apply_proposal #{proposal_id}: MLAdvisor reload "
                    f"failed (model is promoted regardless): {exc}"
                )
    except Exception as exc:
        store.set_status(proposal_id, "apply_failed")
        logger.error(f"apply_proposal #{proposal_id} failed: {exc}", exc_info=True)
        raise ProposalApplyError(str(exc)) from exc

    store.set_status(proposal_id, "applied")
    logger.critical(
        f"GOVERNANCE: proposal #{proposal_id} applied -- promoted "
        f"model #{model_id} ({model_type})"
    )
    return store.get(proposal_id)
