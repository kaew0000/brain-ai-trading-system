"""All validated data models. Strict (extra='forbid') so unexpected/LLM-invented fields are rejected."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .security import contains_secret

_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,63}$")
_SYMBOL = re.compile(r"^[A-Z0-9]{3,20}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyCategory(StrEnum):
    TREND_FOLLOWING = "trend_following"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    SMART_MONEY = "smart_money_concepts"
    SUPPORT_RESISTANCE = "support_resistance"
    VOLATILITY = "volatility"
    MULTI_TIMEFRAME = "multi_timeframe_confluence"
    VOLUME_DERIVATIVES = "volume_derivatives"


class ValidationStatus(StrEnum):
    UNVALIDATED = "unvalidated"  # default for everything, including anything an LLM wrote
    BACKTESTED = "backtested"  # a COMPLETE evaluation exists (evidence id required)
    VALIDATED = "validated"  # evaluation evidence + (for AI-origin) a named human approver
    REJECTED = "rejected"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class Provenance(_Strict):
    source: str = Field(min_length=1, max_length=200)
    origin: Literal["human", "ai_generated", "imported", "builtin"] = "human"
    reference: str | None = Field(None, max_length=500)
    created_at: datetime = Field(default_factory=utcnow)
    notes: str = Field("", max_length=1000)


class StrategyDefinition(_Strict):
    id: str
    version: int = Field(1, ge=1)
    name: str = Field(min_length=1, max_length=120)
    category: StrategyCategory
    description: str = Field(min_length=1, max_length=4000)
    engine: str | None = Field(None, max_length=64)  # name of a built-in, deterministic signal engine, or None
    parameters: dict[str, int | float | bool | str] = Field(default_factory=dict)
    param_grid: dict[str, list[int | float]] = Field(default_factory=dict)  # optional, for walk-forward tuning
    market_conditions: list[str] = Field(default_factory=list)  # regimes: TREND | RANGE | VOLATILE | SQUEEZE
    invalidation_conditions: list[str] = Field(default_factory=list)  # DECLARED by the author, not verified
    tags: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    evidence_evaluation_id: str | None = None
    approved_by: str | None = None
    provenance: Provenance
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("id must match ^[a-z0-9][a-z0-9_-]{1,63}$")
        return v

    @field_validator("market_conditions")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [x.strip().upper() for x in v if x.strip()]

    @field_validator("param_grid")
    @classmethod
    def _grid_bounded(cls, v: dict[str, list[int | float]]) -> dict[str, list[int | float]]:
        combos = 1
        for k, vals in v.items():
            if not 1 <= len(vals) <= 7:
                raise ValueError(f"param_grid[{k}] must have 1..7 values")
            combos *= len(vals)
        if combos > 200:
            raise ValueError("param_grid has more than 200 combinations")
        return v

    @model_validator(mode="after")
    def _consistency(self):
        blob = json.dumps(
            [self.name, self.description, self.parameters, self.tags, self.provenance.model_dump(mode="json")],
            default=str,
        )
        if contains_secret(blob):
            raise ValueError("strategy record appears to contain a credential; secrets must never be stored")
        for k in self.param_grid:
            if k not in self.parameters:
                raise ValueError(f"param_grid key '{k}' is not in parameters")
        if (
            self.validation_status in (ValidationStatus.BACKTESTED, ValidationStatus.VALIDATED)
            and not self.evidence_evaluation_id
        ):
            raise ValueError("backtested/validated status requires evidence_evaluation_id")
        if (
            self.validation_status == ValidationStatus.VALIDATED
            and self.provenance.origin == "ai_generated"
            and not self.approved_by
        ):
            raise ValueError("AI-generated strategies cannot be validated without a named human approver")
        return self


class Candle(_Strict):
    ts: int = Field(ge=0)  # bar OPEN time, epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(0.0, ge=0)

    @model_validator(mode="after")
    def _ohlc(self):
        vals = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(x) for x in vals):
            raise ValueError("non-finite candle value")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("candle prices must be > 0")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("inconsistent OHLC")
        return self


class RiskContext(_Strict):
    """Risk information the caller obtains from Brain Bot's own Risk Manager. Required - the adapter fails closed without it."""

    trading_allowed: bool
    max_leverage: float = Field(gt=0)
    risk_pct: float = Field(gt=0, le=1)


class MarketSnapshot(_Strict):
    symbol: str
    timestamp: datetime
    timeframe: str | None = None
    mark_price: float = Field(gt=0)
    regime: str | None = None
    regime_conf: float | None = Field(None, ge=0, le=1)
    trend_bias: Literal["LONG_BIAS", "SHORT_BIAS", "NEUTRAL"] | None = None
    trend_strength: Literal["STRONG", "MODERATE", "WEAK"] | None = None
    futures_signal: Literal["LONG", "SHORT", "NEUTRAL"] | None = None
    funding_rate: float | None = None
    open_interest: float | None = Field(None, ge=0)
    fear_greed: int | None = Field(None, ge=0, le=100)
    macro_risk: bool | None = None
    risk: RiskContext | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        v = v.strip().upper()
        if not _SYMBOL.match(v):
            raise ValueError("invalid symbol")
        return v

    @field_validator("timestamp")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)  # naive == UTC (documented)

    @field_validator("regime")
    @classmethod
    def _regime(cls, v: str | None) -> str | None:
        return v.strip().upper() if v and v.strip() else None

    @field_validator("mark_price", "funding_rate")
    @classmethod
    def _finite(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("non-finite number")
        return v

    def critical_missing(self) -> list[str]:
        return [f for f in ("regime", "risk") if getattr(self, f) is None]

    def missing_fields(self) -> list[str]:
        names = ("regime", "risk", "trend_bias", "futures_signal", "funding_rate", "open_interest", "fear_greed")
        return [f for f in names if getattr(self, f) is None]

    def numeric_values(self) -> list[float]:
        """Every number present in the snapshot - used to reject LLM text that cites invented figures."""
        out: list[float] = []

        def walk(o: Any) -> None:
            if isinstance(o, bool):
                return
            if isinstance(o, (int, float)):
                out.append(float(o))
            elif isinstance(o, dict):
                for x in o.values():
                    walk(x)
            elif isinstance(o, (list, tuple)):
                for x in o:
                    walk(x)

        walk(self.model_dump(mode="json", exclude={"timestamp"}))
        return out


# ---------------------------------------------------------------- research


class ResearchItem(_Strict):
    strategy_id: str
    regime_fit: float = Field(ge=0, le=1)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=8)
    contradicting_evidence: list[str] = Field(default_factory=list, max_length=8)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=8)
    recommend_backtest: bool = False


class LLMResearchOutput(_Strict):
    """Exact JSON shape an LLM must return. Anything else is rejected."""

    items: list[ResearchItem] = Field(max_length=50)
    missing_data: list[str] = Field(default_factory=list, max_length=20)
    uncertainty: str = Field("", max_length=1500)


class ResearchReport(_Strict):
    symbol: str
    generated_at: datetime = Field(default_factory=utcnow)
    mode: Literal["llm", "offline_rules", "offline_rules_fallback"]
    items: list[ResearchItem]
    missing_data: list[str]  # computed by code, never by the LLM
    uncertainty: str
    warnings: list[str] = Field(default_factory=list)
    provider: str = "none"


# ---------------------------------------------------------------- evaluation


class Metrics(_Strict):
    net_pnl: float
    return_pct: float
    max_drawdown_pct: float
    profit_factor: float | None = None  # None when there are no losing trades (undefined) or no trades
    win_rate: float | None = None
    expectancy: float | None = None  # mean net PnL per trade (quote currency)
    trade_count: int
    avg_win: float | None = None
    avg_loss: float | None = None
    payoff_ratio: float | None = None  # avg_win / |avg_loss|
    exposure: float  # fraction of bars with an open position
    turnover: float  # traded notional / initial capital
    benchmark_return_pct: float  # buy & hold over the same bars (no costs)
    fees_paid: float
    slippage_cost: float
    funding_paid: float
    return_over_drawdown: float | None = None
    sharpe: float | None = None
    bars: int


class WalkForwardWindow(_Strict):
    train_range: tuple[int, int]  # [start, end) bar indices
    test_range: tuple[int, int]
    chosen_params: dict[str, int | float | bool | str]
    train_net_pnl: float
    test_net_pnl: float
    test_trades: int


class WalkForwardSummary(_Strict):
    windows: list[WalkForwardWindow]
    profitable_fraction: float | None
    total_test_net_pnl: float
    total_test_trades: int


class SensitivityResult(_Strict):
    base_net_pnl: float
    neighbours: list[dict[str, Any]]
    positive_neighbour_fraction: float | None
    max_relative_change: float | None


class EvaluationResult(_Strict):
    evaluation_id: str
    strategy_id: str
    strategy_version: int
    symbol: str
    timeframe: str
    data_label: str  # SYNTHETIC / CSV:... / adapter label - always shown in reports
    status: Literal["COMPLETE", "INCOMPLETE"]
    incomplete_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    in_sample: Metrics | None = None
    validation: Metrics | None = None
    out_of_sample: Metrics | None = None
    walk_forward: WalkForwardSummary | None = None
    sensitivity: SensitivityResult | None = None
    assumptions: list[str] = Field(default_factory=list)
    config_fingerprint: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- ranking


class RankedStrategy(_Strict):
    strategy_id: str
    strategy_version: int
    rank: int | None
    score: float | None
    status: Literal["RANKED", "UNRANKED"]
    validation_status: ValidationStatus
    breakdown: dict[str, float | None] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_label: str = ""


class RankingReport(_Strict):
    generated_at: datetime = Field(default_factory=utcnow)
    weights: dict[str, float]
    entries: list[RankedStrategy]


# ---------------------------------------------------------------- learning


class TradeRecord(_Strict):
    """A trade as handed to the recorder. `realized_pnl` is GROSS price PnL; net = realized_pnl - fees - funding."""

    trade_id: str = Field(min_length=1, max_length=100)
    strategy_id: str
    strategy_version: int = Field(ge=1)
    symbol: str
    timeframe: str | None = None
    regime: str | None = None
    direction: Direction
    status: Literal["OPEN", "CLOSED", "CANCELLED"]
    verified: bool = False  # True only once reconciled against the exchange/journal
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    entry_price: float | None = Field(None, gt=0)
    exit_price: float | None = Field(None, gt=0)
    quantity: float | None = Field(None, gt=0)
    decision_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk_params: dict[str, Any] = Field(default_factory=dict)
    fees: float | None = Field(None, ge=0)
    funding: float | None = None
    realized_pnl: float | None = None
    expected_slippage_bps: float | None = Field(None, ge=0)
    realized_slippage_bps: float | None = Field(None, ge=0)
    path_high: float | None = Field(None, gt=0)  # highest price while open (for MFE)
    path_low: float | None = Field(None, gt=0)  # lowest price while open (for MAE)
    data_quality_flags: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        v = v.strip().upper()
        if not _SYMBOL.match(v):
            raise ValueError("invalid symbol")
        return v

    @field_validator("regime")
    @classmethod
    def _regime(cls, v: str | None) -> str | None:
        return v.strip().upper() if v and v.strip() else None


class OutcomeAnalysis(_Strict):
    trade_id: str
    outcome: Literal["WIN", "LOSS", "BREAKEVEN"]
    net_pnl: float
    mfe: float | None = None
    mae: float | None = None
    failure_class: (
        Literal[
            "normal_variance",
            "poor_execution",
            "incorrect_market_assumption",
            "data_quality",
            "possible_strategy_degradation",
        ]
        | None
    ) = None
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- integration output


class CandidateRecommendation(_Strict):
    strategy_id: str
    strategy_version: int
    validation_status: ValidationStatus
    rank: int | None = None
    score: float | None = None
    evaluation_status: Literal["COMPLETE", "INCOMPLETE", "NOT_EVALUATED"] = "NOT_EVALUATED"
    regime_fit: float | None = None
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    recommend_backtest: bool = False


class Recommendation(_Strict):
    """Advisory output ONLY. There is deliberately no order, size, price or leverage field."""

    status: Literal[
        "OK",
        "DISABLED",
        "REJECTED_INVALID_SNAPSHOT",
        "REJECTED_STALE_SNAPSHOT",
        "REJECTED_MISSING_DATA",
        "REJECTED_RISK_BLOCKED",
        "ERROR",
    ]
    advisory_only: Literal[True] = True
    may_execute: Literal[False] = False
    symbol: str | None = None
    generated_at: datetime = Field(default_factory=utcnow)
    candidates: list[CandidateRecommendation] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    research_mode: str | None = None
    config_fingerprint: str = ""
