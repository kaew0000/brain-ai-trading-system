"""Configuration: validated pydantic models, YAML overrides, env overrides.

Defaults live here in code so an installed wheel works without any file. config/strategy_intelligence.yaml mirrors
these defaults (a test asserts they stay identical). Secrets are NEVER read from YAML - only from env.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ConfigError

SAFE_MODE = "research_only"
# Runtime output lives in its own gitignored directory so it never mixes with Brain Bot packages (data/, reports/).
DATA_DIR = "brain_strategy_intelligence_data"


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BundleCfg(_Cfg):
    enabled: bool = True
    mode: str = SAFE_MODE

    @model_validator(mode="after")
    def _only_research_only(self):
        if self.mode != SAFE_MODE:
            raise ValueError(
                f"mode must be '{SAFE_MODE}'; this bundle is an analytical subsystem and has no execution mode"
            )
        return self


class StorageCfg(_Cfg):
    backend: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: str = f"{DATA_DIR}/knowledge.sqlite3"
    postgres_dsn_env: str = "BSI_POSTGRES_DSN"
    embedding_dim: int = Field(256, ge=16, le=4096)


class LLMCfg(_Cfg):
    provider: Literal["none", "anthropic"] = "none"
    model: str = ""  # must be set by the operator when provider != none
    api_key_env: str = "ANTHROPIC_API_KEY"
    timeout_seconds: float = Field(20.0, gt=0, le=300)
    max_retries: int = Field(2, ge=0, le=5)
    max_tokens: int = Field(1500, ge=100, le=8000)


class ResearchCfg(_Cfg):
    schedule_cron: str = "0 6 * * *"  # informational; consumed only by the optional n8n workflow
    max_candidates: int = Field(8, ge=1, le=50)


class SplitCfg(_Cfg):
    train: float = Field(0.6, gt=0)
    validation: float = Field(0.2, gt=0)
    oos: float = Field(0.2, gt=0)

    @model_validator(mode="after")
    def _sum(self):
        if abs(self.train + self.validation + self.oos - 1.0) > 1e-9:
            raise ValueError("split fractions must sum to 1.0")
        return self


class WalkForwardCfg(_Cfg):
    train_bars: int = Field(600, ge=20)
    test_bars: int = Field(150, ge=5)
    step_bars: int = Field(150, ge=1)
    purge_bars: int = Field(5, ge=0)


class EvaluationCfg(_Cfg):
    initial_capital: float = Field(10000.0, gt=0)
    position_pct: float = Field(0.10, gt=0, le=1.0)  # notional per trade as a fraction of equity
    max_leverage: float = Field(1.0, gt=0, le=20)  # cap on gross notional / equity
    fee_bps: float = Field(5.0, ge=0)  # per side, ASSUMPTION - set to your real tier
    slippage_bps: float = Field(2.0, ge=0)  # per side, ASSUMPTION
    include_funding: bool = True
    funding_rate_per_8h: float = 0.0001  # ASSUMPTION used when no funding series is supplied
    funding_conservative: bool = True  # charge funding on both sides (never credit shorts)
    stop_loss_pct: float | None = Field(None, gt=0, lt=1)
    allow_short: bool = True
    min_bars: int = Field(1000, ge=50)
    min_oos_trades: int = Field(10, ge=1)
    min_wf_windows: int = Field(2, ge=1)
    max_gap_fraction: float = Field(0.02, ge=0, le=1)
    split: SplitCfg = SplitCfg()
    walk_forward: WalkForwardCfg = WalkForwardCfg()
    sensitivity_perturbation_pct: float = Field(0.2, gt=0, lt=1)


class RankingCfg(_Cfg):
    weights: dict[str, float] = {
        "oos_profit_factor": 0.15,
        "return_over_drawdown": 0.20,
        "drawdown": 0.15,
        "regime_stability": 0.15,
        "reliability": 0.10,
        "degradation": 0.10,
        "sensitivity": 0.10,
        "cost_drag": 0.05,
    }
    min_reliable_trades: int = Field(50, ge=1)
    max_acceptable_drawdown_pct: float = Field(30.0, gt=0)
    negative_oos_penalty: float = Field(0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _weights(self):
        if any(w < 0 for w in self.weights.values()) or abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError("ranking weights must be non-negative and sum to 1.0")
        return self


class LearningCfg(_Cfg):
    db_path: str = f"{DATA_DIR}/outcomes.sqlite3"
    min_samples_degradation: int = Field(20, ge=5)
    poor_execution_slippage_ratio: float = Field(2.0, gt=1)
    degradation_z: float = Field(1.645, gt=0)


class IntegrationCfg(_Cfg):
    max_snapshot_age_seconds: int = Field(900, ge=1)


class ReportingCfg(_Cfg):
    output_dir: str = f"{DATA_DIR}/reports"


class LoggingCfg(_Cfg):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class Config(_Cfg):
    bundle: BundleCfg = BundleCfg()
    storage: StorageCfg = StorageCfg()
    llm: LLMCfg = LLMCfg()
    research: ResearchCfg = ResearchCfg()
    evaluation: EvaluationCfg = EvaluationCfg()
    ranking: RankingCfg = RankingCfg()
    learning: LearningCfg = LearningCfg()
    integration: IntegrationCfg = IntegrationCfg()
    reporting: ReportingCfg = ReportingCfg()
    logging: LoggingCfg = LoggingCfg()

    def fingerprint(self) -> str:
        """Stable hash of the effective config (contains no secrets by construction)."""
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]


def _deep_merge(base: dict, over: Mapping) -> dict:
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(
    path: str | os.PathLike | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Config:
    """Build the effective Config. Reads only the bundle's own YAML + BSI_* env vars; never touches Brain Bot config."""
    env = os.environ if env is None else env
    data: dict = {}
    cfg_path = path or env.get("BSI_CONFIG") or None
    if cfg_path:
        p = Path(cfg_path)
        if not p.is_file():
            raise ConfigError(f"config file not found: {p}")
        try:
            import yaml  # lazy: PyYAML is only needed when a YAML file is actually loaded
        except ImportError as exc:
            raise ConfigError("PyYAML is required to load a YAML config file (pip install PyYAML)") from exc
        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {p}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError("config root must be a mapping")
        data = loaded
    if (v := env.get("BSI_ENABLED")) is not None and v != "":
        if v.lower() not in ("true", "false", "1", "0"):
            raise ConfigError("BSI_ENABLED must be true/false")
        _deep_merge(data, {"bundle": {"enabled": v.lower() in ("true", "1")}})
    if v := env.get("BSI_LOG_LEVEL"):
        _deep_merge(data, {"logging": {"level": v.upper()}})
    if overrides:
        _deep_merge(data, overrides)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
