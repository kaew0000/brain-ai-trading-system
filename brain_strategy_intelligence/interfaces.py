"""Replaceable interfaces (PEP 544 protocols). Nothing here imports optional packages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .schemas import Candle, EvaluationResult, StrategyCategory, StrategyDefinition, ValidationStatus


@runtime_checkable
class StrategyStore(Protocol):
    """Storage contract implemented by SQLiteStrategyStore and PgVectorStore."""

    def add(self, strategy: StrategyDefinition, *, actor: str, reason: str) -> None: ...
    def get(self, strategy_id: str, version: int | None = None) -> StrategyDefinition | None: ...
    def list(
        self,
        *,
        category: StrategyCategory | None = None,
        status: ValidationStatus | None = None,
        latest_only: bool = True,
    ) -> list[StrategyDefinition]: ...
    def history(self, strategy_id: str) -> list[dict[str, Any]]: ...
    def set_validation(
        self,
        strategy_id: str,
        version: int,
        status: ValidationStatus,
        evidence_evaluation_id: str | None,
        approved_by: str | None,
        actor: str,
        reason: str,
    ) -> None: ...
    def upsert_embedding(self, strategy_id: str, version: int, vector: Sequence[float]) -> None: ...
    def all_embeddings(self) -> dict[tuple[str, int], list[float]]: ...
    def save_evaluation(self, result: EvaluationResult) -> None: ...
    def latest_evaluation(self, strategy_id: str, version: int) -> EvaluationResult | None: ...
    def close(self) -> None: ...


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Provider contract. Implementations MUST honour `timeout` and raise ProviderTimeout/ProviderUnavailable."""

    name: str

    def complete(self, system: str, user: str, *, timeout: float) -> str: ...


@runtime_checkable
class DataAdapter(Protocol):
    """Historical data contract. Implement this against Brain Bot's own data layer (see docs/INTEGRATION.md).

    Candles must be returned oldest-first with strictly increasing `ts` (epoch seconds, bar OPEN time).
    """

    label: str  # e.g. "SYNTHETIC", "CSV:<file>", "BRAIN_BOT:<source>" - copied into every EvaluationResult

    def get_candles(
        self, symbol: str, timeframe: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]: ...


@runtime_checkable
class BrainBotGateway(Protocol):
    """Documented contract the Brain Bot side may implement. All members are OPTIONAL read-only providers.

    The bundle never calls anything that places or modifies orders; this protocol deliberately has none.
    """

    def get_market_context(self, symbol: str) -> dict[str, Any]: ...
    def get_risk_context(self, symbol: str) -> dict[str, Any]: ...
