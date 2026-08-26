"""governance/update_proposal.py — UpdateProposal record.

One instance = one row of the `update_proposals` table (see
database/schema_v13.sql's §48 block for the authoritative column list and
CHECK constraints — this class mirrors that, not the other way around).

Not `@dataclass(frozen=True)` like learning/recommendation_engine.py's
Recommendation — deliberately, since a proposal has a real lifecycle
(status/review_*/decided_at/applied_at all mutate in place as a human
reviews it and, later, as it gets applied) rather than being generated fresh
every cycle and thrown away like a Recommendation is.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

PROPOSAL_TYPES = (
    "model_promotion",
    "agent_weight",
    "recommendation_param",
    "strategy_selection",
    "logic_change",
)

STATUSES = ("pending", "approved", "rejected", "applied", "apply_failed", "expired")

REVIEW_VERDICTS = ("", "approve_recommended", "caution", "reject_recommended")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UpdateProposal:
    proposal_type: str          # one of PROPOSAL_TYPES
    target: str                 # e.g. "model_registry.meta_label",
                                 # "ceo_agent.WEIGHTS.smc"
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    rationale: str = ""
    metrics: dict = field(default_factory=dict)
    generated_by: str = ""

    # Lifecycle — additive, all safely defaulted so a caller building a
    # brand-new proposal only has to fill in the fields above.
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    status: str = "pending"
    review_verdict: str = ""
    review_reasoning: str = ""
    review_score: float = 0.0
    decided_at: str = ""
    applied_at: str = ""
    apply_result: str = ""

    # Tier 3 (logic_change) safety valve — see governance/__init__.py and
    # database/schema_v13.sql's §48 block for the full rationale. Always
    # True for proposal_type == "logic_change"; ProposalStore.create()
    # enforces this rather than trusting the caller to set it correctly.
    requires_pr_review: bool = False
    pr_branch: str = ""
    pr_bundle_path: str = ""

    def __post_init__(self) -> None:
        if self.proposal_type not in PROPOSAL_TYPES:
            raise ValueError(f"UpdateProposal: unknown proposal_type {self.proposal_type!r}")
        if self.status not in STATUSES:
            raise ValueError(f"UpdateProposal: unknown status {self.status!r}")
        if self.review_verdict not in REVIEW_VERDICTS:
            raise ValueError(f"UpdateProposal: unknown review_verdict {self.review_verdict!r}")
        if self.proposal_type == "logic_change":
            self.requires_pr_review = True
        if self.created_at is None:
            self.created_at = _now_iso()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def to_row(self) -> dict:
        """Flat dict matching update_proposals' columns exactly, JSON-encoding
        the dict fields — what ProposalStore hands to sqlite3's INSERT."""
        return {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "proposal_type": self.proposal_type,
            "target": self.target,
            "before_json": json.dumps(self.before),
            "after_json": json.dumps(self.after),
            "rationale": self.rationale,
            "metrics_json": json.dumps(self.metrics),
            "generated_by": self.generated_by,
            "review_verdict": self.review_verdict,
            "review_reasoning": self.review_reasoning,
            "review_score": float(self.review_score),
            "status": self.status,
            "decided_at": self.decided_at,
            "applied_at": self.applied_at,
            "apply_result": self.apply_result,
            "requires_pr_review": int(self.requires_pr_review),
            "pr_branch": self.pr_branch,
            "pr_bundle_path": self.pr_bundle_path,
        }

    @classmethod
    def from_row(cls, row: dict) -> "UpdateProposal":
        """Inverse of to_row() — builds an UpdateProposal back from a
        sqlite3.Row (already dict()-ed by the caller, same convention
        ml/model_registry.py's get_active()/list_models() use)."""
        return cls(
            proposal_type=row["proposal_type"],
            target=row["target"],
            before=json.loads(row["before_json"]) if row["before_json"] else {},
            after=json.loads(row["after_json"]) if row["after_json"] else {},
            rationale=row.get("rationale", ""),
            metrics=json.loads(row["metrics_json"]) if row.get("metrics_json") else {},
            generated_by=row.get("generated_by", ""),
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            review_verdict=row.get("review_verdict") or "",
            review_reasoning=row.get("review_reasoning", ""),
            review_score=float(row.get("review_score") or 0.0),
            decided_at=row.get("decided_at", ""),
            applied_at=row.get("applied_at", ""),
            apply_result=row.get("apply_result", ""),
            requires_pr_review=bool(row.get("requires_pr_review")),
            pr_branch=row.get("pr_branch", ""),
            pr_bundle_path=row.get("pr_bundle_path", ""),
        )
