"""KnowledgeRepository: policy layer over any StrategyStore.

Policies enforced here (not in the store):
* revising a strategy creates a NEW version that is reset to UNVALIDATED (old evidence does not carry over);
* only a COMPLETE evaluation for the SAME strategy+version can mark it BACKTESTED/VALIDATED;
* AI-generated strategies additionally need a named human approver to become VALIDATED.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from ..errors import StorageError, ValidationRefused
from ..interfaces import Embedder, StrategyStore
from ..schemas import EvaluationResult, StrategyDefinition, ValidationStatus, utcnow
from .vector_store import HashingEmbedder

log = logging.getLogger(__name__)


def strategy_text(s: StrategyDefinition) -> str:
    return " ".join(
        [
            s.name,
            s.category.value.replace("_", " "),
            s.description,
            " ".join(s.tags),
            " ".join(s.market_conditions),
            s.engine or "",
        ]
    )


class KnowledgeRepository:
    def __init__(self, store: StrategyStore, embedder: Embedder | None = None) -> None:
        self.store = store
        self.embedder = embedder or HashingEmbedder()

    def add_new(
        self, strategy: StrategyDefinition, *, actor: str = "system", reason: str = "initial import"
    ) -> StrategyDefinition:
        if strategy.version != 1:
            raise StorageError("new strategies must start at version 1; use revise() for later versions")
        if self.store.get(strategy.id) is not None:
            raise StorageError(f"strategy '{strategy.id}' exists; use revise()")
        self.store.add(strategy, actor=actor, reason=reason)
        self.store.upsert_embedding(strategy.id, strategy.version, self.embedder.embed(strategy_text(strategy)))
        return strategy

    def revise(self, strategy_id: str, changes: dict[str, Any], *, actor: str, reason: str) -> StrategyDefinition:
        latest = self.store.get(strategy_id)
        if latest is None:
            raise StorageError(f"unknown strategy '{strategy_id}'")
        forbidden = {"id", "version", "validation_status", "evidence_evaluation_id", "approved_by", "created_at"} & set(
            changes
        )
        if forbidden:
            raise StorageError(f"fields cannot be set through revise(): {sorted(forbidden)}")
        data = latest.model_dump()
        data.update(changes)
        data.update(
            {
                "version": latest.version + 1,
                "validation_status": ValidationStatus.UNVALIDATED,
                "evidence_evaluation_id": None,
                "approved_by": None,
                "created_at": utcnow(),
            }
        )
        new = StrategyDefinition.model_validate(data)
        self.store.add(new, actor=actor, reason=reason)
        self.store.upsert_embedding(new.id, new.version, self.embedder.embed(strategy_text(new)))
        return new

    def get(self, strategy_id: str, version: int | None = None) -> StrategyDefinition | None:
        return self.store.get(strategy_id, version)

    def list(self, **kw: Any) -> list[StrategyDefinition]:
        return self.store.list(**kw)

    def history(self, strategy_id: str) -> list[dict[str, Any]]:
        return self.store.history(strategy_id)

    def record_evaluation(self, result: EvaluationResult, *, actor: str = "system") -> StrategyDefinition:
        """Persist an evaluation. A COMPLETE one advances an UNVALIDATED strategy to BACKTESTED (never beyond)."""
        s = self.store.get(result.strategy_id, result.strategy_version)
        if s is None:
            raise StorageError(f"unknown strategy {result.strategy_id} v{result.strategy_version}")
        self.store.save_evaluation(result)
        if result.status == "COMPLETE" and s.validation_status == ValidationStatus.UNVALIDATED:
            self.store.set_validation(
                s.id,
                s.version,
                ValidationStatus.BACKTESTED,
                result.evaluation_id,
                None,
                actor,
                f"complete evaluation {result.evaluation_id} on {result.data_label} data",
            )
            return self.store.get(s.id, s.version)  # type: ignore[return-value]
        return s

    def mark_validated(
        self, strategy_id: str, version: int, evaluation: EvaluationResult, *, approved_by: str, reason: str
    ) -> StrategyDefinition:
        """Explicit human-approved promotion to VALIDATED. This is the ONLY path to that status."""
        s = self.store.get(strategy_id, version)
        if s is None:
            raise ValidationRefused("unknown strategy")
        if not approved_by.strip():
            raise ValidationRefused("approved_by is required")
        if (evaluation.strategy_id, evaluation.strategy_version) != (strategy_id, version):
            raise ValidationRefused("evaluation belongs to a different strategy/version")
        if evaluation.status != "COMPLETE":
            raise ValidationRefused(f"evaluation is {evaluation.status}: {evaluation.incomplete_reasons}")
        if evaluation.data_label.upper().startswith("SYNTHETIC"):
            raise ValidationRefused("synthetic data can never validate a strategy")
        if self.store.latest_evaluation(strategy_id, version) is None:
            self.store.save_evaluation(evaluation)
        self.store.set_validation(
            strategy_id, version, ValidationStatus.VALIDATED, evaluation.evaluation_id, approved_by, approved_by, reason
        )
        return self.store.get(strategy_id, version)  # type: ignore[return-value]

    def reject(self, strategy_id: str, version: int, *, actor: str, reason: str) -> None:
        self.store.set_validation(strategy_id, version, ValidationStatus.REJECTED, None, None, actor, reason)

    def load_many(self, strategies: Iterable[StrategyDefinition], *, actor: str = "system") -> tuple[int, list[str]]:
        added, skipped = 0, []
        for s in strategies:
            try:
                self.add_new(s, actor=actor)
                added += 1
            except StorageError as exc:
                skipped.append(f"{s.id}: {exc}")
        return added, skipped
