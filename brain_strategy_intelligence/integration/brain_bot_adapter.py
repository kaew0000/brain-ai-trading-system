"""Brain Bot integration adapter - ADVISORY ONLY.

This module imports nothing from Brain Bot and nothing that can reach an exchange. It accepts plain dicts
(or validated models), returns a `Recommendation` that has no order/size/price/leverage fields, and never
touches Brain Bot configuration, the Risk Manager, or the execution layer.

Field mapping for `snapshot_from_market_context` was taken from the documented output schema in
intelligence/market_context_builder.py (V16.5.0): symbol, timestamp, mark_price, regime, regime_conf,
trend_bias, trend_strength, futures_signal, fear_greed, macro_risk, futures.funding.rate, futures.open_interest.value.
Brain Bot's market_context carries NO risk information, so the caller must supply `risk` (from its own Risk
Manager). Without it the adapter fails closed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from ..config import Config
from ..interfaces import LLMProvider
from ..knowledge.repository import KnowledgeRepository
from ..knowledge.retrieval import Retriever
from ..knowledge.sqlite_store import SQLiteStrategyStore
from ..learning.trade_recorder import RecordResult, TradeRecorder
from ..ranking.ranker import StrategyRanker
from ..research.agent import ResearchAgent
from ..research.providers import build_provider
from ..schemas import (
    CandidateRecommendation,
    EvaluationResult,
    MarketSnapshot,
    Recommendation,
    RiskContext,
    StrategyDefinition,
    TradeRecord,
    utcnow,
)

log = logging.getLogger(__name__)


def _dig(d: Mapping | None, *path: str) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(p)
    return cur


def snapshot_from_market_context(
    ctx: Mapping[str, Any],
    risk: Mapping[str, Any] | RiskContext | None = None,
    timeframe: str | None = None,
    extras: Mapping[str, Any] | None = None,
) -> MarketSnapshot:
    """Normalize a Brain Bot `market_context` dict. Unknown/absent keys stay None - nothing is guessed."""
    risk_obj = risk if isinstance(risk, RiskContext) or risk is None else RiskContext.model_validate(dict(risk))
    return MarketSnapshot(
        symbol=ctx.get("symbol", ""),
        timestamp=ctx.get("timestamp"),
        timeframe=timeframe,
        mark_price=ctx.get("mark_price", 0),
        regime=ctx.get("regime") or None,
        regime_conf=ctx.get("regime_conf"),
        trend_bias=ctx.get("trend_bias"),
        trend_strength=ctx.get("trend_strength"),
        futures_signal=ctx.get("futures_signal"),
        funding_rate=_dig(ctx, "futures", "funding", "rate"),
        open_interest=_dig(ctx, "futures", "open_interest", "value"),
        fear_greed=ctx.get("fear_greed"),
        macro_risk=ctx.get("macro_risk"),
        risk=risk_obj,
        extras=dict(extras or {}),
    )


class BrainBotAdapter:
    def __init__(
        self,
        config: Config,
        repository: KnowledgeRepository,
        agent: ResearchAgent,
        ranker: StrategyRanker,
        recorder: TradeRecorder | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.cfg, self.repo, self.agent, self.ranker, self._recorder, self._clock = (
            config,
            repository,
            agent,
            ranker,
            recorder,
            clock,
        )
        self.retriever = Retriever(repository)

    @classmethod
    def from_config(
        cls, config: Config, provider: LLMProvider | None = None, env: Mapping[str, str] | None = None
    ) -> BrainBotAdapter:
        env = os.environ if env is None else env
        if config.storage.backend == "postgres":
            from ..knowledge.vector_store import PgVectorStore  # lazy: optional dependency

            store: Any = PgVectorStore(env.get(config.storage.postgres_dsn_env, ""), config.storage.embedding_dim)
        else:
            store = SQLiteStrategyStore(config.storage.sqlite_path)
        from ..knowledge.vector_store import HashingEmbedder

        repo = KnowledgeRepository(store, HashingEmbedder(config.storage.embedding_dim))
        agent = ResearchAgent(provider or build_provider(config.llm, env), config)
        return cls(config, repo, agent, StrategyRanker(config.ranking))

    @property
    def recorder(self) -> TradeRecorder:
        if self._recorder is None:
            self._recorder = TradeRecorder(self.cfg.learning.db_path)
        return self._recorder

    # ------------------------------------------------------------------ recommend
    def _reject(self, status: str, symbol: str | None = None, **kw: Any) -> Recommendation:
        return Recommendation(status=status, symbol=symbol, config_fingerprint=self.cfg.fingerprint(), **kw)  # type: ignore[arg-type]

    def recommend(self, snapshot: MarketSnapshot | Mapping[str, Any]) -> Recommendation:
        """Never raises: every failure becomes a non-OK Recommendation (fail closed)."""
        if not self.cfg.bundle.enabled:
            return self._reject("DISABLED")
        try:
            return self._recommend(snapshot)
        except Exception as exc:  # noqa: BLE001 - last-resort guard; analytics must never break the host
            log.exception("recommend failed")
            return self._reject("ERROR", warnings=[f"internal error: {type(exc).__name__}"])

    def _recommend(self, snapshot: MarketSnapshot | Mapping[str, Any]) -> Recommendation:
        try:
            snap = snapshot if isinstance(snapshot, MarketSnapshot) else MarketSnapshot.model_validate(dict(snapshot))
        except ValidationError as exc:
            problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:10]
            return self._reject("REJECTED_INVALID_SNAPSHOT", warnings=problems)
        age = (self._clock() - snap.timestamp).total_seconds()
        if age > self.cfg.integration.max_snapshot_age_seconds or age < -60:
            return self._reject(
                "REJECTED_STALE_SNAPSHOT", snap.symbol, warnings=[f"snapshot age {age:.0f}s outside allowed window"]
            )
        crit = snap.critical_missing()
        if crit:
            return self._reject(
                "REJECTED_MISSING_DATA",
                snap.symbol,
                missing_data=snap.missing_fields(),
                warnings=[f"critical data missing: {crit}"],
            )
        assert snap.risk is not None
        if not snap.risk.trading_allowed:
            return self._reject(
                "REJECTED_RISK_BLOCKED",
                snap.symbol,
                warnings=["Risk Manager reports trading not allowed; no strategies recommended"],
            )

        found = self.retriever.search(snap.regime or "", regime=snap.regime, limit=self.cfg.research.max_candidates)
        cands: list[StrategyDefinition] = [r.strategy for r in found]
        warnings: list[str] = []
        if not cands:
            warnings.append(f"no stored strategy declares regime {snap.regime}")
        report = self.agent.research(snap, cands) if cands else None
        warnings += report.warnings if report else []
        by_id = {i.strategy_id: i for i in (report.items if report else [])}

        evals: dict[tuple[str, int], EvaluationResult | None] = {
            (s.id, s.version): self.repo.store.latest_evaluation(s.id, s.version) for s in cands
        }
        ranking = self.ranker.rank(
            [(s, e) for s in cands if (e := evals[(s.id, s.version)]) is not None and e.status == "COMPLETE"]
        )
        rank_by = {(r.strategy_id, r.strategy_version): r for r in ranking.entries}
        out: list[CandidateRecommendation] = []
        for s in cands:
            ev, item, rk = evals[(s.id, s.version)], by_id.get(s.id), rank_by.get((s.id, s.version))
            out.append(
                CandidateRecommendation(
                    strategy_id=s.id,
                    strategy_version=s.version,
                    validation_status=s.validation_status,
                    rank=rk.rank if rk else None,
                    score=rk.score if rk else None,
                    evaluation_status=ev.status if ev else "NOT_EVALUATED",
                    regime_fit=item.regime_fit if item else None,
                    supporting_evidence=item.supporting_evidence if item else [],
                    contradicting_evidence=item.contradicting_evidence if item else [],
                    invalidation_conditions=item.invalidation_conditions if item else list(s.invalidation_conditions),
                    recommend_backtest=(item.recommend_backtest if item else False) or ev is None,
                )
            )
        out.sort(key=lambda c: (c.rank is None, c.rank or 0, -(c.regime_fit or 0.0), c.strategy_id))
        rec = Recommendation(
            status="OK",
            symbol=snap.symbol,
            candidates=out,
            missing_data=snap.missing_fields(),
            warnings=warnings,
            research_mode=report.mode if report else None,
            config_fingerprint=self.cfg.fingerprint(),
        )
        log.info(
            "recommendation symbol=%s status=OK mode=%s config=%s candidates=%s",
            snap.symbol,
            rec.research_mode,
            rec.config_fingerprint,
            [f"{c.strategy_id}@v{c.strategy_version}" for c in out],
        )
        return rec

    # ------------------------------------------------------------------ learning
    def record_closed_trade(self, trade: TradeRecord | Mapping[str, Any]) -> RecordResult:
        tid = str(trade.get("trade_id", "?")) if isinstance(trade, Mapping) else trade.trade_id
        if not self.cfg.bundle.enabled:
            return RecordResult("rejected", tid, ["bundle disabled"])
        try:
            rec = trade if isinstance(trade, TradeRecord) else TradeRecord.model_validate(dict(trade))
        except ValidationError as exc:
            return RecordResult(
                "rejected", tid, [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:10]
            )
        return self.recorder.record(rec)
