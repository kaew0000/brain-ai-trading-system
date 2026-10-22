"""Hybrid retrieval: keyword overlap + embedding cosine + declared-regime match."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import StrategyCategory, StrategyDefinition, ValidationStatus
from .repository import KnowledgeRepository, strategy_text
from .vector_store import cosine, tokenize

W_KEYWORD, W_VECTOR, W_REGIME = 0.5, 0.3, 0.2


@dataclass(frozen=True)
class ScoredStrategy:
    strategy: StrategyDefinition
    score: float
    components: dict[str, float] = field(default_factory=dict)


class Retriever:
    def __init__(self, repo: KnowledgeRepository) -> None:
        self.repo = repo

    def search(
        self,
        query: str = "",
        *,
        regime: str | None = None,
        category: StrategyCategory | None = None,
        limit: int = 10,
        include_rejected: bool = False,
    ) -> list[ScoredStrategy]:
        if limit < 1:
            return []
        regime = regime.strip().upper() if regime else None
        q_tokens = set(tokenize(query))
        q_vec = self.repo.embedder.embed(query) if q_tokens else None
        embeddings = self.repo.store.all_embeddings()
        out: list[ScoredStrategy] = []
        for s in self.repo.list(category=category):
            if s.validation_status == ValidationStatus.REJECTED and not include_rejected:
                continue
            doc = set(tokenize(strategy_text(s)))
            kw = len(q_tokens & doc) / len(q_tokens) if q_tokens else 0.0
            vec = (
                cosine(q_vec, embeddings[(s.id, s.version)])
                if q_vec is not None and (s.id, s.version) in embeddings
                else 0.0
            )
            vec = max(vec, 0.0)
            rg = 1.0 if regime and regime in s.market_conditions else 0.0
            if not q_tokens and not regime:
                score = 0.0
            elif not q_tokens:
                score = rg
            else:
                score = W_KEYWORD * kw + W_VECTOR * vec + W_REGIME * rg
            if (q_tokens or regime) and score <= 0:
                continue
            out.append(ScoredStrategy(s, round(score, 6), {"keyword": kw, "vector": vec, "regime": rg}))
        out.sort(key=lambda r: (-r.score, r.strategy.id))
        if not q_tokens and not regime:  # browse mode: deterministic id order
            out = [
                ScoredStrategy(s, 0.0)
                for s in sorted(self.repo.list(category=category), key=lambda x: x.id)
                if include_rejected or s.validation_status != ValidationStatus.REJECTED
            ]
        return out[:limit]
