import os
from typing import Optional, Dict
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


class Settings(BaseSettings):
    # ── Binance API (Mainnet — ดึงข้อมูลตลาดเท่านั้น) ─────
    BINANCE_API_KEY: str = Field(default="", alias="BINANCE_API_KEY")
    BINANCE_API_SECRET: str = Field(default="", alias="BINANCE_API_SECRET")

    # ── Binance Testnet/Demo API (เทรดด้วยเงินปลอม) ───────
    BINANCE_TESTNET_API_KEY: str = Field(default="", alias="BINANCE_TESTNET_API_KEY")
    BINANCE_TESTNET_API_SECRET: str = Field(default="", alias="BINANCE_TESTNET_API_SECRET")

    BINANCE_TESTNET: bool = Field(default=True, alias="BINANCE_TESTNET")
    BINANCE_TESTNET_BASE_URL: str = Field(default="https://demo-fapi.binance.com")
    BINANCE_PROD_BASE_URL: str = Field(default="https://fapi.binance.com")

    # ── Trading ───────────────────────────────────────────
    SYMBOL: str = Field(default="BTCUSDT")
    LEVERAGE: int = Field(default=5)

    # ── Multi-Symbol Foundation (V16 Phase 1, architecture only) ──────────
    # Optional list of symbols, e.g. SYMBOLS=["BTCUSDT","ETHUSDT"] in .env
    # (JSON array). Left unset (None) by default so every existing
    # single-symbol deployment is completely unaffected — use the
    # `symbol_list` property below rather than reading SYMBOLS directly,
    # since that property is what actually applies the SYMBOL fallback.
    SYMBOLS: Optional[list] = Field(default=None, alias="SYMBOLS")

    # ── Risk Management ───────────────────────────────────
    RISK_PER_TRADE_MIN: float = Field(default=0.005)
    RISK_PER_TRADE_MAX: float = Field(default=0.01)
    MAX_DAILY_LOSS: float = Field(default=0.03)
    MAX_CONSECUTIVE_LOSSES: int = Field(default=3)
    MAX_MARGIN_USAGE: float = Field(default=0.20)

    # ── Volatility Risk (P1-B1) ────────────────────────────
    # ATR-normalized (ATR / close price) threshold above which risk-per-trade
    # and leverage start scaling down. Matches RegimeEngine.ATR_VOLATILE_THRESHOLD
    # (regime/regime_engine.py) by default so "VOLATILE" regime classification
    # and risk tightening agree on what counts as volatile — kept as an
    # independent setting (not imported from regime_engine) so it can be
    # tuned for risk purposes without affecting regime classification, and
    # vice versa.
    VOLATILITY_RISK_THRESHOLD: float = Field(default=0.015)
    # Floor on the volatility scaling factor: even in extreme volatility,
    # risk-per-trade and leverage never drop below this fraction of their
    # base (streak/drawdown-adjusted) value. Prevents position sizing from
    # collapsing toward zero (which risks qty rounding to an unfillable size).
    VOLATILITY_RISK_FLOOR: float = Field(default=0.5)

    # ── Decision Thresholds ───────────────────────────────
    TRADE_THRESHOLD: int = Field(default=7)
    WAIT_THRESHOLD: int = Field(default=5)

    # ── SMC ───────────────────────────────────────────────
    SWING_HL_COUNT: int = Field(default=10)

    # ── Volume ────────────────────────────────────────────
    VOLUME_SPIKE_MULTIPLIER: float = Field(default=2.0)
    VOLUME_AVG_PERIOD: int = Field(default=20)

    # ── Open Interest ─────────────────────────────────────
    OI_RISING_STRONG: float = Field(default=0.01)
    OI_RISING_WEAK: float = Field(default=0.0)

    # ── Funding Rate ──────────────────────────────────────
    FUNDING_BLOCK_LONG: float = Field(default=0.0005)
    FUNDING_BLOCK_SHORT: float = Field(default=-0.0005)

    # ── ATR / SL ─────────────────────────────────────────
    ATR_PERIOD: int = Field(default=14)
    ATR_SL_MULTIPLIER: float = Field(default=1.5)

    # ── Take Profit ───────────────────────────────────────
    DEFAULT_RR: float = Field(default=2.0)

    # ── Timeframes ────────────────────────────────────────
    H4_TIMEFRAME: str = Field(default="4h")
    H1_TIMEFRAME: str = Field(default="1h")
    M15_TIMEFRAME: str = Field(default="15m")
    KLINE_LIMIT: int = Field(default=500)

    # ── Logging ───────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(default="logs/brain_bot.log")

    # ── Main Loop ─────────────────────────────────────────
    LOOP_INTERVAL: int = Field(default=60)

    # ── Journal ───────────────────────────────────────────
    JOURNAL_DB_PATH: str = Field(default="brain_bot_journal.db")
    DATABASE_PATH: str = Field(default="brain_bot_v13.db")

    # ── Dashboard API Authentication (P1-A) ────────────────
    # Off by default so existing deployments/tests keep working unchanged.
    # api/app.py logs a loud warning at startup whenever this is False.
    # Flip to true + configure API_KEYS + JWT_SECRET before exposing the
    # dashboard beyond localhost.
    API_AUTH_ENABLED: bool = Field(default=False, alias="API_AUTH_ENABLED")
    # JSON object mapping raw API key -> role ("admin"|"operator"|"viewer").
    # e.g. API_KEYS={"changeme-op-key":"operator","changeme-view-key":"viewer"}
    API_KEYS: Dict[str, str] = Field(default_factory=dict, alias="API_KEYS")
    # HMAC signing secret for bearer JWTs. If left blank while
    # API_AUTH_ENABLED=true, api/auth.py generates a random per-process
    # secret and logs a critical warning (tokens won't survive a restart).
    JWT_SECRET: str = Field(default="", alias="JWT_SECRET")
    JWT_EXPIRY_MINUTES: int = Field(default=60, alias="JWT_EXPIRY_MINUTES")

    # ── Market Scanner (V16 Phase 2, Part 1) ───────────────
    # Off by default: (1) this is a brand-new background thread making live
    # exchange calls — it must never auto-start just because main.py or a
    # test imports build_system(), and (2) nothing downstream (Portfolio
    # Manager) exists yet to consume its output, so there's nothing to
    # break by leaving it off until you're ready for Part 3.
    SCANNER_ENABLED: bool = Field(default=False, alias="SCANNER_ENABLED")
    SCANNER_INTERVAL_SECONDS: int = Field(default=20, alias="SCANNER_INTERVAL_SECONDS")
    # Only the top N symbols by 24h quote volume get the per-symbol detail
    # pass (ATR + open interest) each cycle — see scanner/market_scanner.py
    # module docstring for why a full-universe detail pass isn't safe.
    SCANNER_DETAIL_TOP_N: int = Field(default=40, alias="SCANNER_DETAIL_TOP_N")
    # Symbols below this 24h quote volume (USDT) are excluded from the
    # detail-pass candidate pool entirely — filters out dead/illiquid
    # perpetuals nobody would trade anyway.
    SCANNER_MIN_QUOTE_VOLUME: float = Field(default=1_000_000.0, alias="SCANNER_MIN_QUOTE_VOLUME")
    SCANNER_UNIVERSE_REFRESH_SECONDS: int = Field(default=3600, alias="SCANNER_UNIVERSE_REFRESH_SECONDS")
    SCANNER_SNAPSHOT_RETENTION_HOURS: int = Field(default=168, alias="SCANNER_SNAPSHOT_RETENTION_HOURS")

    # ── Opportunity Ranking Engine (V16 Phase 2 Part 2) ────────────────────
    RANKER_TOP_N: int = Field(default=20, alias="RANKER_TOP_N")
    RANKER_HISTORY_RETENTION_HOURS: int = Field(default=168, alias="RANKER_HISTORY_RETENTION_HOURS")
    # Weights sum to 100 by convention (not enforced — confidence_fusion.py
    # renormalizes over whatever's COMPUTED regardless). market_structure/
    # ai_confidence/historical_performance are given real weight here even
    # though they're UNAVAILABLE today (see ranking/score_breakdown.py) —
    # that weight is simply excluded from the composite until a future
    # phase makes them computable; leaving them at 0 would misrepresent
    # their intended importance once they ARE wired in.
    RANKER_FACTOR_WEIGHTS: Dict[str, float] = Field(
        default_factory=lambda: {
            "trend": 10.0, "market_structure": 15.0, "momentum": 8.0,
            "volume": 7.0, "funding": 8.0, "open_interest": 7.0,
            "liquidity": 10.0, "spread": 5.0, "risk": 10.0,
            "ai_confidence": 15.0, "historical_performance": 5.0,
        },
        alias="RANKER_FACTOR_WEIGHTS",
    )

    # ── Portfolio Intelligence Core (V16 Phase 2A) ─────────────────────────
    # See portfolio/portfolio_models.py:PortfolioLimits for what each of
    # these means and portfolio/capital_manager.py for how they're applied.
    # Defaults mirror PortfolioLimits' own dataclass defaults exactly —
    # duplicated here (rather than only living on the dataclass) so they're
    # tunable via .env without a code change, per project convention
    # ("move constants into configuration files").
    PORTFOLIO_MAX_POSITIONS:            int   = Field(default=5,    alias="PORTFOLIO_MAX_POSITIONS")
    PORTFOLIO_MAX_SYMBOL_PCT:           float = Field(default=0.35, alias="PORTFOLIO_MAX_SYMBOL_PCT")
    PORTFOLIO_MAX_SECTOR_PCT:           float = Field(default=0.50, alias="PORTFOLIO_MAX_SECTOR_PCT")
    PORTFOLIO_MAX_CAPITAL_DEPLOYED_PCT: float = Field(default=0.80, alias="PORTFOLIO_MAX_CAPITAL_DEPLOYED_PCT")
    PORTFOLIO_MAX_DAILY_RISK_PCT:       float = Field(default=0.03, alias="PORTFOLIO_MAX_DAILY_RISK_PCT")
    PORTFOLIO_MAX_ACCOUNT_RISK_PCT:     float = Field(default=0.10, alias="PORTFOLIO_MAX_ACCOUNT_RISK_PCT")
    PORTFOLIO_MAX_LEVERAGE:              int  = Field(default=10,   alias="PORTFOLIO_MAX_LEVERAGE")
    PORTFOLIO_MIN_LIQUIDITY_SCORE:      float = Field(default=30.0, alias="PORTFOLIO_MIN_LIQUIDITY_SCORE")
    PORTFOLIO_MIN_SPREAD_SCORE:         float = Field(default=20.0, alias="PORTFOLIO_MIN_SPREAD_SCORE")
    PORTFOLIO_MIN_COVERAGE:             float = Field(default=0.0,  alias="PORTFOLIO_MIN_COVERAGE")
    PORTFOLIO_CORRELATION_HARD_REJECT_ENABLED: bool = Field(
        default=True, alias="PORTFOLIO_CORRELATION_HARD_REJECT_ENABLED"
    )
    # Coverage-weighting floor: final_score = composite_score *
    # (COVERAGE_WEIGHT_FLOOR + (1-COVERAGE_WEIGHT_FLOOR)*coverage) * correlation_penalty
    # 0.5 means even 0% coverage retains half weight — see
    # capital_manager.py module docstring for why a harsh linear multiply
    # was rejected (it would conflate "3 factors are structurally always
    # unavailable for every symbol" with "this symbol specifically has
    # worse data than its peers").
    PORTFOLIO_COVERAGE_WEIGHT_FLOOR:    float = Field(default=0.5, alias="PORTFOLIO_COVERAGE_WEIGHT_FLOOR")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
        "extra": "ignore",
    }

    def __repr__(self) -> str:
        """V15-SEC: Completely omit API keys from repr to prevent accidental logging."""
        _SECRET_FIELDS = {
            "BINANCE_API_KEY", "BINANCE_API_SECRET",
            "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
            "API_KEYS", "JWT_SECRET",
        }
        parts = []
        for k, v in self.model_dump().items():
            if k in _SECRET_FIELDS:
                continue   # omit entirely — neither name nor value appears in repr
            parts.append(f"{k}={v!r}")
        return f"Settings({', '.join(parts)})"

    @property
    def symbol_list(self) -> list:
        """
        V16 Multi-Symbol Foundation: the effective list of symbols to
        trade. Falls back to [SYMBOL] whenever SYMBOLS is unset/empty, so
        every single-symbol deployment (the default) behaves identically
        to pre-V16 — this is the ONLY place that fallback is applied;
        ExecutionCoordinator and everything else should read this
        property, not settings.SYMBOL / settings.SYMBOLS directly, so the
        fallback rule lives in exactly one place.
        """
        return list(self.SYMBOLS) if self.SYMBOLS else [self.SYMBOL]

    @property
    def base_url(self) -> str:
        return self.BINANCE_TESTNET_BASE_URL if self.BINANCE_TESTNET else self.BINANCE_PROD_BASE_URL


settings = Settings()

import os as _os
EXECUTION_MODE: str = _os.environ.get("EXECUTION_MODE", "paper").lower()
