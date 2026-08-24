import os
from typing import Literal
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

    # Binance rejects ISOLATED margin (error -4168) on accounts that have
    # Multi-Assets Mode enabled — that mode only supports CROSSED. Default
    # stays ISOLATED so every existing single-asset-mode deployment is
    # unaffected; set MARGIN_TYPE=CROSSED in .env only if your Binance
    # account itself is in Multi-Assets Mode. Switching this changes real
    # trading risk: CROSSED shares margin across the whole futures wallet
    # instead of isolating it per symbol.
    MARGIN_TYPE: Literal["ISOLATED", "CROSSED"] = Field(
        default="ISOLATED", alias="MARGIN_TYPE"
    )

    # ── Multi-Symbol Foundation (V16 Phase 1, architecture only) ──────────
    # Optional list of symbols, e.g. SYMBOLS=["BTCUSDT","ETHUSDT"] in .env
    # (JSON array). Left unset (None) by default so every existing
    # single-symbol deployment is completely unaffected — use the
    # `symbol_list` property below rather than reading SYMBOLS directly,
    # since that property is what actually applies the SYMBOL fallback.
    SYMBOLS: list | None = Field(default=None, alias="SYMBOLS")

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
    # Legacy v1 pipeline (decision/brain_decision_engine.py) — 0-9 raw
    # integer score scale. Unrelated to CONFIDENCE_TRADE_THRESHOLD below
    # despite the similar name; kept as-is for backward compat.
    TRADE_THRESHOLD: int = Field(default=7)
    WAIT_THRESHOLD: int = Field(default=5)

    # ── Confidence Engine Thresholds (decision/confidence_engine.py) ──────
    # 0-100 weighted confidence scale ("confluence score" in operator
    # terms — smc+volume+oi+funding+regime buckets summed). Was a
    # hardcoded module constant (TRADE_THRESHOLD=75) until this setting
    # was added; defaults preserve that exact prior behavior. Lowering
    # CONFIDENCE_TRADE_THRESHOLD admits lower-confluence setups as real
    # trade entries — a risk-policy change, not just a "find more
    # candidates" change: it directly affects which signals the
    # execution layer is willing to act on with real capital, especially
    # combined with SCANNER_ENABLED/SCHEDULER_ENABLED/
    # CEO_MULTI_SYMBOL_ENABLED (more symbols evaluated × lower bar to
    # pass = materially higher trade frequency).
    CONFIDENCE_TRADE_THRESHOLD: int = Field(default=75, alias="CONFIDENCE_TRADE_THRESHOLD")
    CONFIDENCE_WAIT_THRESHOLD: int = Field(default=50, alias="CONFIDENCE_WAIT_THRESHOLD")

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

    # ── Dashboard API Authentication (P1-A / V16 BUG-LIVE-RISK-01) ────────
    # V16 BUG-LIVE-RISK-01: was default=False ("off by default so existing
    # deployments/tests keep working unchanged"). In practice that meant
    # every /api/* and /ws/* endpoint — including POST /api/command
    # (pause/resume live trading) and live position/balance data — was
    # reachable with NO authentication unless an operator remembered to
    # flip this in .env before exposing the dashboard beyond localhost.
    # Now defaults to True: a fresh deployment is secure without extra
    # config. Set to false explicitly (.env: API_AUTH_ENABLED=false) for
    # local-only dashboards where auth is genuinely unnecessary. api/app.py
    # additionally refuses to start at all when EXECUTION_MODE=live and
    # this is false (see api/app.py's lifespan()) — real-money live mode
    # can no longer run with an unauthenticated dashboard even if this is
    # left/set to false by mistake. The test suite pins its own default
    # via conftest.py's autouse fixture, matching the old behavior, so
    # this change doesn't require touching every test file individually.
    API_AUTH_ENABLED: bool = Field(default=True, alias="API_AUTH_ENABLED")
    # JSON object mapping raw API key -> role ("admin"|"operator"|"viewer").
    # e.g. API_KEYS={"changeme-op-key":"operator","changeme-view-key":"viewer"}
    API_KEYS: dict[str, str] = Field(default_factory=dict, alias="API_KEYS")
    # HMAC signing secret for bearer JWTs. If left blank while
    # API_AUTH_ENABLED=true, api/auth.py generates a random per-process
    # secret and logs a critical warning (tokens won't survive a restart).
    JWT_SECRET: str = Field(default="", alias="JWT_SECRET")
    JWT_EXPIRY_MINUTES: int = Field(default=60, alias="JWT_EXPIRY_MINUTES")
    # V16 Phase 4C: Session Persistence. The bearer JWT above stays
    # short-lived and browser-memory-only (see dashboard_src/src/lib/
    # api.ts's own docstring) — that design is unchanged. This is a
    # SEPARATE, longer-lived refresh token, delivered only as an
    # httpOnly cookie (never readable by page JS, so a page refresh
    # doesn't lose it the way the in-memory bearer token does, and an
    # XSS bug still can't read or exfiltrate it the way it could a
    # bearer token sitting in localStorage/sessionStorage). See
    # api/auth.py's refresh-token section for the full design.
    JWT_REFRESH_EXPIRY_DAYS: int = Field(default=7, alias="JWT_REFRESH_EXPIRY_DAYS")
    # Whether the refresh-token cookie is marked Secure (HTTPS-only).
    # Defaults to True — browsers silently refuse to persist a Secure
    # cookie set over plain HTTP, so this MUST be set to false in .env
    # for local/dev deployments served over http:// (e.g.
    # http://localhost:8000). Leave true for any real deployment.
    COOKIE_SECURE: bool = Field(default=True, alias="COOKIE_SECURE")

    # ── Ensemble Decision Engine — Phase 4B proper (architecture.md §28) ───
    # Off by default: CEOAgent.WEIGHTS stays static until explicitly opted
    # in, same reasoning as SCANNER_ENABLED above. When enabled, blends each
    # agent's static weight toward its measured win-rate (from
    # journal_v2.get_agent_performance(), Phase 4B Step 1) — but only once
    # that agent has at least DYNAMIC_WEIGHT_MIN_SAMPLES closed,
    # direction-matching trades; below that floor its static weight is used
    # unchanged, so a quiet or brand-new agent is never blended off noise.
    DYNAMIC_AGENT_WEIGHTS_ENABLED: bool = Field(default=False, alias="DYNAMIC_AGENT_WEIGHTS_ENABLED")
    # Minimum closed, direction-matching trades before an agent's win-rate
    # is trusted enough to influence its weight at all.
    DYNAMIC_WEIGHT_MIN_SAMPLES: int = Field(default=20, alias="DYNAMIC_WEIGHT_MIN_SAMPLES")
    # 0.0 = fully static (dynamic weighting has no effect even if enabled),
    # 1.0 = fully performance-driven. Kept well below 1.0 by default so one
    # agent's recent streak can't swing the fused vote on its own.
    DYNAMIC_WEIGHT_BLEND: float = Field(default=0.3, alias="DYNAMIC_WEIGHT_BLEND")
    # How long a fetched performance snapshot is reused before CEOAgent
    # queries journal_v2.get_agent_performance() again — avoids a DB query
    # on every single decision cycle.
    DYNAMIC_WEIGHT_REFRESH_SECONDS: int = Field(default=300, alias="DYNAMIC_WEIGHT_REFRESH_SECONDS")

    # ── Recommendation Application Layer — V16 Phase 4C Step 3 (Track A) ───
    # Off by default: recommendations are advisory-only and CEOAgent.decide()
    # (the pre-existing, unmodified method) keeps working identically
    # whether this is on or off. Only CEOAgent.decide_with_recommendations()
    # — a new, additive method nothing pre-existing calls — reads any of
    # these. Existing protections (Risk Manager, Circuit Breaker, CEO
    # BLOCKED veto) are evaluated before this layer runs and are never
    # reachable from it — see agents/ceo_agent.py and
    # learning/application/recommendation_advisor.py.
    RECOMMENDATION_APPLICATION_ENABLED: bool = Field(default=False, alias="RECOMMENDATION_APPLICATION_ENABLED")
    # How long a generated Recommendation is considered current before
    # RecommendationValidator marks it "expired". Recommendations are
    # regenerated from a live dataset each learning-report run (there is no
    # scheduled cadence today), so this is a safety ceiling against a stale
    # snapshot being reused long after the market conditions it described.
    RECOMMENDATION_TTL_HOURS: float = Field(default=24.0, alias="RECOMMENDATION_TTL_HOURS")
    # Minimum `based_on.metric.sample_size` (or `.length` for streak
    # patterns) before a recommendation is trusted enough to be applied —
    # same floor pattern_miner.py's own DEFAULT_MIN_SAMPLE_SIZE (5) uses,
    # kept as its own setting since the two are validated for different
    # purposes (pattern detection vs. decision-application) and may need to
    # diverge later.
    RECOMMENDATION_MIN_SAMPLE_SIZE: int = Field(default=5, alias="RECOMMENDATION_MIN_SAMPLE_SIZE")
    # Sample size at which the scoring layer's "coverage"/"sample_size"
    # sub-scores saturate to 1.0 (a diminishing-returns cap, not a hard
    # cutoff — pattern_miner's "high" confidence bucket already starts at
    # 30; this is set a little above that so "high confidence" patterns
    # still have room to be scored better than "just barely high").
    RECOMMENDATION_SCORE_SATURATION_N: int = Field(default=50, alias="RECOMMENDATION_SCORE_SATURATION_N")
    # Scoring-component weights for recommendation_scoring.py — must sum to
    # 1.0 (validated by that module's own tests). Historical win-rate and
    # validator status are weighted highest because they are the most
    # directly decision-relevant; recency is weighted lowest because a
    # recommendation's expiry (RECOMMENDATION_TTL_HOURS) already handles
    # the "too stale to use at all" case on its own.
    RECOMMENDATION_SCORE_WEIGHT_CONFIDENCE: float = Field(default=0.20, alias="RECOMMENDATION_SCORE_WEIGHT_CONFIDENCE")
    RECOMMENDATION_SCORE_WEIGHT_SUCCESS: float = Field(default=0.25, alias="RECOMMENDATION_SCORE_WEIGHT_SUCCESS")
    RECOMMENDATION_SCORE_WEIGHT_SAMPLE_SIZE: float = Field(default=0.15, alias="RECOMMENDATION_SCORE_WEIGHT_SAMPLE_SIZE")
    RECOMMENDATION_SCORE_WEIGHT_RECENCY: float = Field(default=0.10, alias="RECOMMENDATION_SCORE_WEIGHT_RECENCY")
    RECOMMENDATION_SCORE_WEIGHT_COVERAGE: float = Field(default=0.10, alias="RECOMMENDATION_SCORE_WEIGHT_COVERAGE")
    RECOMMENDATION_SCORE_WEIGHT_VALIDATOR: float = Field(default=0.20, alias="RECOMMENDATION_SCORE_WEIGHT_VALIDATOR")
    # Hard ceiling on how much a recommendation may move CEODecision.confidence
    # (percentage points, since CEODecision.confidence is 0-100). Bounded so
    # no combination of recommendations can single-handedly flip a decision
    # across the existing >=40-point action threshold on its own — see
    # decide_with_recommendations()'s own docstring for the exact clamp.
    RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT: float = Field(default=5.0, alias="RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT")
    # Maximum number of applied recommendations counted toward one
    # decision's confidence adjustment — prevents a symbol with many
    # simultaneously-applicable recommendations from compounding past the
    # max-adjustment ceiling in a way that's hard to explain to a human
    # reading the decision's `reasons`.
    RECOMMENDATION_MAX_APPLIED_PER_DECISION: int = Field(default=5, alias="RECOMMENDATION_MAX_APPLIED_PER_DECISION")

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
    RANKER_FACTOR_WEIGHTS: dict[str, float] = Field(
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

    # ── Portfolio Manager Orchestrator (V16 Phase 2B) ──────────────────────
    # See portfolio/portfolio_manager.py for how each of these is applied.
    # Replacement threshold: a new candidate must beat the weakest held
    # position's current-cycle score by more than this fraction before a
    # ReplacementProposal is generated — prevents proposing a swap for a
    # marginal, noise-level improvement.
    PORTFOLIO_REPLACEMENT_THRESHOLD_PCT: float = Field(default=0.15, alias="PORTFOLIO_REPLACEMENT_THRESHOLD_PCT")
    # Cooldown: once a symbol is replaced out (or externally reported closed
    # via notify_position_closed()), it's ineligible for re-selection as a
    # NEW candidate for this many seconds — prevents immediate flip-flopping
    # between two similarly-scored symbols.
    PORTFOLIO_COOLDOWN_SECONDS:          int   = Field(default=3600, alias="PORTFOLIO_COOLDOWN_SECONDS")
    # Minimum hold: a symbol just proposed as a replacement's incoming side
    # is protected from being proposed as an outgoing (replaced-out) side
    # again for this many seconds — the pairing to PORTFOLIO_COOLDOWN_SECONDS
    # that keeps a single volatile ranking cycle from oscillating a position
    # in and out repeatedly.
    PORTFOLIO_MIN_HOLD_SECONDS:          int   = Field(default=1800, alias="PORTFOLIO_MIN_HOLD_SECONDS")
    # Retention for portfolio_history rows, mirrors RANKER_HISTORY_RETENTION_HOURS.
    PORTFOLIO_HISTORY_RETENTION_HOURS:   int   = Field(default=168,  alias="PORTFOLIO_HISTORY_RETENTION_HOURS")
    # ── Bundle Manager (tools/) ────────────────────────────────────────────
    # See tools/bundle_manager.py for the CLI and this module's own
    # docstring in tools/ for the full workflow. Paths are repo-root-
    # relative; resolved to absolute paths by tools/bundle_utils.py so this
    # works identically regardless of the working directory the tool is
    # invoked from (Windows/Linux/Termux).
    BUNDLE_INCOMING_DIR:  str = Field(default="update/incoming",     alias="BUNDLE_INCOMING_DIR")
    BUNDLE_APPLIED_DIR:   str = Field(default="update/applied",      alias="BUNDLE_APPLIED_DIR")
    BUNDLE_FAILED_DIR:    str = Field(default="update/failed",       alias="BUNDLE_FAILED_DIR")
    BUNDLE_HISTORY_FILE:  str = Field(default="bundle_history.json", alias="BUNDLE_HISTORY_FILE")
    BUNDLE_REMOTE:        str = Field(default="origin",              alias="BUNDLE_REMOTE")
    BUNDLE_BASE_BRANCH:   str = Field(default="main",                alias="BUNDLE_BASE_BRANCH")
    # Network-touching git ops (fetch-from-bundle is local I/O, but push
    # goes over the network) get a small retry budget — see
    # tools/git_utils.py's module docstring for why this isn't
    # utils/retry.py's decorator (that one's exception set is
    # Binance/requests-specific, not subprocess/git-specific).
    BUNDLE_PUSH_RETRIES:        int = Field(default=3,   alias="BUNDLE_PUSH_RETRIES")
    BUNDLE_GIT_TIMEOUT_SECONDS: int = Field(default=120, alias="BUNDLE_GIT_TIMEOUT_SECONDS")
    # W14-2B: `cmd_import`'s real pass calls history.save() unconditionally
    # (correct — see tools/history.py) but, left uncommitted, that write
    # lingers as a local modification to a tracked file and trips
    # get_dirty_files()'s preflight check on the *next* invocation. When
    # true (default), cmd_import locally commits BUNDLE_HISTORY_FILE
    # (that path only — see tools/git_utils.py:commit_paths()) right
    # after saving it. Local commit only, never pushed. Set false to
    # restore the pre-W14-2B manual `git add ... && git commit` workflow
    # — e.g. if this environment has no git user.name/user.email
    # configured and the commit step would just fail on every run.
    BUNDLE_AUTO_COMMIT_HISTORY: bool = Field(default=True, alias="BUNDLE_AUTO_COMMIT_HISTORY")

    # ── V16 Phase 2E: Execution Wiring & Live Orchestrator ──────────────
    # Orchestration-level retry (see execution/execution_orchestrator.py's
    # module docstring for why this is separate from — and layered above
    # — trade_manager.py's own @retry_api_call retries).
    EXECUTION_MAX_RETRIES:              int   = Field(default=2,   alias="EXECUTION_MAX_RETRIES")
    EXECUTION_RETRY_DELAY_SECONDS:      float = Field(default=0.0, alias="EXECUTION_RETRY_DELAY_SECONDS")

    # ── V16 Phase 2F: Execution Scheduler + Multi-Symbol Signals ────────
    # Off by default — same reasoning as SCANNER_ENABLED above: this is a
    # new background thread that calls decide()+execute() (i.e. can place
    # real orders) on a timer. It must never auto-start just because
    # main.py or a test imports build_system(). Requires SCANNER_ENABLED
    # (feeds it candidates) to produce any real allocations.
    SCHEDULER_ENABLED: bool = Field(default=False, alias="SCHEDULER_ENABLED")
    SCHEDULER_INTERVAL_SECONDS: int = Field(default=60, alias="SCHEDULER_INTERVAL_SECONDS")
    # Ranker candidates considered per cycle — separate knob from
    # RANKER_TOP_N (the ranker's own persisted top-N) so the scheduler can
    # deliberately look at fewer/more without changing what gets logged.
    SCHEDULER_CANDIDATE_LIMIT: int = Field(default=20, alias="SCHEDULER_CANDIDATE_LIMIT")

    # ── V16 Phase 4B Step 3C: Live CEO Agent Integration ────────────────
    # Off by default — same posture as SCHEDULER_ENABLED/
    # DYNAMIC_AGENT_WEIGHTS_ENABLED above. False = ExecutionScheduler's
    # signal_provider behaves byte-identically to before this phase
    # (PortfolioSignalProvider.get_signal(), unchanged). True = CEOAgent
    # becomes a confirm/veto gate on top of that same signal — see
    # execution/ceo_gated_signal_provider.py's module docstring for why
    # it can only confirm or veto, never independently invent a trade
    # the underlying pipeline didn't already price out.
    CEO_MULTI_SYMBOL_ENABLED: bool = Field(default=False, alias="CEO_MULTI_SYMBOL_ENABLED")

    # ── V16 Phase 3A: Strategy Plugin System ─────────────────────────────
    # Selects which execution/strategy_registry.py strategy main.py's
    # ExecutionScheduler bootstrap resolves signal_provider to. Default
    # is the exact class Phase 2F hardcoded at that call site
    # (PortfolioSignalProvider) — every existing deployment is
    # byte-for-byte unaffected until this is deliberately changed. See
    # execution/strategy_registry.py module docstring for the full list
    # of registered strategies and what each one requires.
    STRATEGY_NAME: str = Field(default="portfolio_signal_provider", alias="STRATEGY_NAME")

    # ── fix/execution-coordinator-symbol-mismatch ────────────────────────
    # Off by default — same posture as SCHEDULER_ENABLED/CEO_MULTI_SYMBOL_
    # ENABLED above. False = ExecutionCoordinator.get_manager() rejects any
    # symbol outside settings.symbol_list exactly as it always has
    # (ValueError). True = a scanner/ranker-discovered symbol outside that
    # static list gets registered on first use instead of being rejected —
    # see execution/execution_coordinator.py's __init__ docstring for the
    # full design (including why max_dynamic_symbols exists — this is not
    # purely a memory optimization, it's a live-money scope-of-trading
    # decision, so both dials default to the conservative posture: off,
    # and bounded once on).
    EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS: bool = Field(default=False, alias="EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS")
    # Ignored when the flag above is False. See
    # ExecutionCoordinator.__init__'s max_dynamic_symbols docstring for
    # the full reasoning behind the default of 50.
    EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS: int = Field(default=50, alias="EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS")

    # ── Track C3 Phase 1: Unified Order/Trade Timeline (read-model) ─────
    # Off by default — same posture as SCHEDULER_ENABLED/CEO_MULTI_SYMBOL_
    # ENABLED above: this starts a new background poller
    # (execution/order_timeline.py) that only READS execution/
    # trade_lifecycle.py's TradeLifecycle and exchange_state/manager.py's
    # ExchangeStateManager (C1) — it never mutates either, and neither's
    # existing behavior changes whether this is on or off. False = byte-
    # identical to before this phase.
    ORDER_TIMELINE_ENABLED: bool = Field(default=False, alias="ORDER_TIMELINE_ENABLED")
    # Deliberately >= exchange_state/constants.py's DEFAULT_SNAPSHOT_TTL_
    # SECONDS (3.0s): OrderTimeline never forces a refresh (get_orders()
    # -> get_snapshot(force=False) respects C1's own TTL cache), so a
    # poll interval below the TTL can never cause an EXTRA Binance call
    # — C1 just returns its still-cached snapshot — but it would mean
    # OrderTimeline is calling get_orders() more often than the
    # underlying data can actually change. Keeping this >= the TTL keeps
    # the two knobs aligned by convention, not by hard coupling.
    ORDER_TIMELINE_POLL_INTERVAL_SECONDS: float = Field(
        default=5.0, alias="ORDER_TIMELINE_POLL_INTERVAL_SECONDS"
    )
    # ── V16 Phase 4C Track C: Background Paper-Training Engine ──────────
    # Off by default — same posture as every other optional subsystem in
    # this file (SCHEDULER_ENABLED, ORDER_TIMELINE_ENABLED, etc.): a
    # fresh clone's boot behavior is byte-identical to before this
    # feature existed until a person explicitly turns it on. When True,
    # main.py starts training_lane/training_lane_runner.py::
    # TrainingLaneRunner on its own daemon thread at boot — independent
    # of commander/control_state.py's lifecycle_state (that gate only
    # matters once lifecycle_state == RUNNING and only governs live-order
    # call sites; see control_state.py's own LIFECYCLE_STOPPED docstring)
    # and independent of the primary execution_lane's balance, per the
    # person's explicit request that this run "even if real balance is 0".
    BACKGROUND_PAPER_TRAINING_ENABLED: bool = Field(
        default=False, alias="BACKGROUND_PAPER_TRAINING_ENABLED"
    )
    # Starting (and post-bust reset) balance for the training lane's own
    # dedicated PaperAccount — fully isolated from the primary lane's
    # execution engine (see paper/paper_account.py::PaperAccount, a
    # plain in-memory object with its own lock; no shared state).
    BACKGROUND_TRAINING_STARTING_BALANCE: float = Field(
        default=100.0, alias="BACKGROUND_TRAINING_STARTING_BALANCE"
    )
    # Deliberately faster than the primary loop's 60s cycle (person's
    # explicit choice: denser training data over lower REST call volume).
    # Safe because data/binance_provider.py's market-data calls are
    # already circuit-breaker + retry wrapped (@retry_api_call,
    # system_health/circuit_breaker.py) and already have multiple
    # concurrent readers today (legacy loop + MarketScanner both call it
    # independently) — this is one more reader of the same wrapper, not
    # a new unprotected REST client.
    BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS: float = Field(
        default=20.0, alias="BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS"
    )

    # Row-count cap for order_timeline_history (operational history
    # only — the journal, not this table, is the durable trade record).
    # Trimmed lazily every _TRIM_CHECK_INTERVAL persisted batches (see
    # execution/order_timeline.py) rather than on every insert.
    ORDER_TIMELINE_HISTORY_MAX_ROWS: int = Field(
        default=100_000, alias="ORDER_TIMELINE_HISTORY_MAX_ROWS"
    )

    # ── Track C3 Phase 2: Ghost Detection + Reconciliation Metrics ──────
    # Off by default — same posture as ORDER_TIMELINE_ENABLED above. This
    # gates ONLY the optional scheduled background job (main.py's
    # run_ghost_reconciliation_check(), mirroring the existing
    # unconditional run_position_reconciliation() 60s job). The read
    # path (system_health/ghost_reconciliation.py's check(), and the
    # GET /api/order-state/ghosts + /api/order-state/metrics API
    # routes) works on-demand regardless of this flag — same
    # relationship OrderStateManager has with ORDER_TIMELINE_ENABLED's
    # background poller. False = byte-identical to before this phase:
    # no new schedule.every(...) job is registered at all.
    ORDER_RECONCILIATION_ENABLED: bool = Field(default=False, alias="ORDER_RECONCILIATION_ENABLED")
    ORDER_RECONCILIATION_INTERVAL_SECONDS: float = Field(
        default=60.0, alias="ORDER_RECONCILIATION_INTERVAL_SECONDS"
    )
    # Minimum seconds between two publishes of the SAME new event type
    # (RUNTIME_POSITION_MISMATCH/ORDER_TIMELINE_DESYNC/RECONCILIATION_
    # FAILED) for the same symbol, even across repeated status
    # transitions — a secondary guard against event-storming on a
    # rapidly flapping condition, on top of (not instead of) C3-2's
    # primary transition-only dedup (see ghost_reconciliation.py's
    # _maybe_publish()).
    ORDER_RECONCILIATION_DEDUP_SECONDS: float = Field(
        default=30.0, alias="ORDER_RECONCILIATION_DEDUP_SECONDS"
    )

    # ── V16 Phase 4C Track B: HFT Flow — HFT-1 WS Ingestion ────────────────
    # Off by default — same posture as ORDER_RECONCILIATION_ENABLED above.
    # False = byte-identical to before this phase: no WebSocket connection
    # is opened, api/app.py's lifespan() starts no new supervised task, and
    # nothing in decision/execution is touched (HFT-1 does not wire into
    # ConfidenceEngine at all — that is a later, separately-approved phase).
    HFT_WS_ENABLED: bool = Field(default=False, alias="HFT_WS_ENABLED")
    # Binance USDT-M Futures combined-stream base URL. Kept separate from
    # BINANCE_TESTNET_BASE_URL/BINANCE_PROD_BASE_URL (REST) since the WS
    # host differs from the REST host.
    HFT_WS_BASE_URL: str = Field(
        default="wss://fstream.binance.com/stream", alias="HFT_WS_BASE_URL"
    )
    HFT_WS_TESTNET_BASE_URL: str = Field(
        default="wss://stream.binancefuture.com/stream", alias="HFT_WS_TESTNET_BASE_URL"
    )
    # Depth-diff update speed Binance publishes at: "100ms" or "250ms".
    HFT_WS_DEPTH_SPEED: str = Field(default="100ms", alias="HFT_WS_DEPTH_SPEED")
    # REST depth-snapshot levels fetched for initial sync/resync (see
    # data/local_order_book.py's Binance-sequencing docstring).
    HFT_WS_SNAPSHOT_LIMIT: int = Field(default=1000, alias="HFT_WS_SNAPSHOT_LIMIT")
    # Local order-book state older than this is treated as invalid
    # (feature_confidence=0 once HFT-2/HFT-3 consume this — see design
    # review §10). Deliberately generous for HFT-1: this module only
    # reconstructs the book, it does not yet score anything.
    HFT_WS_DATA_AGE_LIMIT_MS: int = Field(default=5000, alias="HFT_WS_DATA_AGE_LIMIT_MS")
    # Reconnect backoff (matches the shape of utils/retry.py's
    # retry_api_call: exponential with a cap), applied by the supervised
    # run loop in data/binance_ws_client.py.
    HFT_WS_RECONNECT_DELAY_SECONDS: float = Field(default=2.0, alias="HFT_WS_RECONNECT_DELAY_SECONDS")
    HFT_WS_RECONNECT_MAX_DELAY_SECONDS: float = Field(default=30.0, alias="HFT_WS_RECONNECT_MAX_DELAY_SECONDS")
    # Rolling in-memory trade buffer per symbol, seconds. HFT-1 only stores
    # raw parsed aggTrade events for this window — computing
    # aggressive_buy_volume/CVD/trade_intensity FROM this buffer is HFT-2,
    # not implemented here.
    HFT_WS_TRADE_BUFFER_SECONDS: int = Field(default=60, alias="HFT_WS_TRADE_BUFFER_SECONDS")

    # ── V16 Phase 4C Track B: HFT Flow — HFT-2 Microstructure Features ────
    # Feature computation only (depth_imbalance, aggressive buy/sell,
    # CVD/CVD-slope, trade_intensity) — no HFT_FLOW_SCORE, no
    # ConfidenceEngine wiring; those are HFT-3/HFT-4, separately approved.
    # Number of top-of-book price levels summed for depth_imbalance. Must
    # be <= the max_levels a BinanceWSClient/LocalOrderBook was built with.
    HFT_FLOW_DEPTH_LEVELS: int = Field(default=10, alias="HFT_FLOW_DEPTH_LEVELS")
    # Rolling window used for aggressive_buy/sell_volume, delta, and
    # trade_intensity. Deliberately shorter than HFT_WS_TRADE_BUFFER_SECONDS
    # (the WS client's raw retention window) so this is a sub-window of it,
    # not a mismatched/overlapping period.
    HFT_FLOW_TRADE_WINDOW_SECONDS: int = Field(default=10, alias="HFT_FLOW_TRADE_WINDOW_SECONDS")
    # EMA smoothing factor applied to the periodic delta measurement to
    # produce cvd_slope (design review §5: "slope = short EMA of delta").
    # Higher = more reactive/less smoothed.
    HFT_FLOW_CVD_EMA_ALPHA: float = Field(default=0.3, alias="HFT_FLOW_CVD_EMA_ALPHA")

    # ── V16 Phase 4C Track B: HFT Flow — HFT-3 Flow Score ──────────────────
    # Combines HFT-2's raw features (depth_imbalance, delta, cvd_slope,
    # trade_intensity) into HFT_FLOW_SCORE (-100..+100) + a 5-state enum.
    # Still NOT wired into decision/confidence_engine.py — that is a later,
    # separately-approved phase (see the design review's roadmap: HFT-4 is
    # shadow-mode telemetry with explicitly NO trading impact; decision
    # integration comes after that).
    #
    # CALIBRATION CAVEAT (documented, not hidden): the *_NORMALIZER values
    # below convert raw volume units (delta, cvd_slope) into a [-1, 1]
    # range. Per the design review §17, no historical order-book/trade-flow
    # data exists yet to calibrate these against real per-symbol volume
    # distributions — these are placeholder defaults that MUST be reviewed
    # against real recorded data (HFT-5's replay dataset, once it exists)
    # before this score is trusted for anything beyond shadow-mode
    # observation. depth_imbalance needs no normalizer (already [-1, 1] by
    # construction in MicrostructureEngine).
    HFT_FLOW_DELTA_NORMALIZER: float = Field(default=10.0, alias="HFT_FLOW_DELTA_NORMALIZER")
    HFT_FLOW_CVD_SLOPE_NORMALIZER: float = Field(default=5.0, alias="HFT_FLOW_CVD_SLOPE_NORMALIZER")

    # Combination weights (design review §6's MVP model: depth_imbalance +
    # delta + cvd_slope as directional inputs; trade_intensity as a
    # magnitude multiplier, not a 4th directional term — see
    # HFT_FLOW_INTENSITY_REFERENCE below). Need not sum to 1.0 — the
    # scorer normalizes by their sum, mirroring
    # ConfidenceEngine._normalise_weights()'s own convention.
    HFT_FLOW_WEIGHT_DEPTH_IMBALANCE: float = Field(default=0.30, alias="HFT_FLOW_WEIGHT_DEPTH_IMBALANCE")
    HFT_FLOW_WEIGHT_DELTA: float = Field(default=0.35, alias="HFT_FLOW_WEIGHT_DELTA")
    HFT_FLOW_WEIGHT_CVD_SLOPE: float = Field(default=0.35, alias="HFT_FLOW_WEIGHT_CVD_SLOPE")

    # trade_intensity acts as a magnitude DAMPENER, not a directional
    # input (design review §6): a quiet/thin market's directional reading
    # is trusted less, but never fully zeroed (the floor below prevents
    # that) — it should never be able to flip or invent a direction.
    HFT_FLOW_INTENSITY_REFERENCE: float = Field(default=2.0, alias="HFT_FLOW_INTENSITY_REFERENCE")
    HFT_FLOW_MIN_INTENSITY_MULTIPLIER: float = Field(default=0.3, alias="HFT_FLOW_MIN_INTENSITY_MULTIPLIER")

    # State classification thresholds — matches the -100..+100 scale and
    # 5-state enum specified for this phase. Symmetric for buy/sell sides.
    HFT_FLOW_STRONG_THRESHOLD: float = Field(default=70.0, alias="HFT_FLOW_STRONG_THRESHOLD")
    HFT_FLOW_MODERATE_THRESHOLD: float = Field(default=30.0, alias="HFT_FLOW_MODERATE_THRESHOLD")

    # ── V16 Phase 4C Track B: HFT Flow — HFT-5 Confidence Integration ──────
    # First phase where hft_flow can actually influence a trading decision
    # (via decision/confidence_engine.py) — deliberately double-gated so
    # the shipped defaults are byte-identical to before this phase:
    #   1. DEFAULT_WEIGHTS["hft_flow"] = 0.0 in confidence_engine.py itself
    #      (not a settings field — matches that module's existing pattern
    #      of a hardcoded module-level weights dict). At weight 0, the
    #      additive term contributes exactly nothing regardless of score.
    #   2. HFT_FLOW_CONTRADICTION_ENABLED below, off by default — the
    #      separate reduce/block contradiction path (design review
    #      Section 9's Hybrid Model C) does not run at all unless this is
    #      explicitly turned on, independent of the weight above.
    # A person enabling HFT flow for paper-lane validation sets a non-zero
    # weight via ConfidenceEngine.update_weights() and/or turns this flag
    # on — ConfidenceEngine itself has no notion of execution_lane, so lane
    # scoping (paper-only) is an operational choice made by whoever
    # configures the paper-trading profile, not something this engine can
    # enforce internally.
    HFT_FLOW_CONTRADICTION_ENABLED: bool = Field(default=False, alias="HFT_FLOW_CONTRADICTION_ENABLED")
    # Two-tier structure, mirroring ConfidenceEngine._check_blocks()'s
    # existing reduce-vs-hard-block pattern (design review Section 9):
    # opposing-direction hft_flow magnitude >= REDUCE_THRESHOLD subtracts
    # HFT_FLOW_CONTRADICTION_PENALTY_POINTS from the final confidence;
    # magnitude >= BLOCK_THRESHOLD (a further, more extreme boundary)
    # forces action=BLOCKED outright, added as one more entry alongside
    # the existing FUTURES_BLOCK_LONG/SHORT and FUNDING_BLOCK_LONG/SHORT
    # reasons already returned by _check_blocks(). Defaults reuse HFT-3's
    # own STRONG threshold for the reduce tier (a strongly-opposing flow
    # reading), with BLOCK_THRESHOLD set near saturation so only the most
    # extreme, near-maximal disagreement escalates all the way to a block.
    HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD: float = Field(default=70.0, alias="HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD")
    HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD: float = Field(default=90.0, alias="HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD")
    HFT_FLOW_CONTRADICTION_PENALTY_POINTS: int = Field(default=15, alias="HFT_FLOW_CONTRADICTION_PENALTY_POINTS")

    # ── V16 Phase 4C Track B: HFT Flow — HFT-6 Low-weight Live ─────────────
    # A named, auditable config value for the weight to use once HFT flow
    # graduates from paper validation (HFT-5) to controlled live use. This
    # setting exists purely as a documented value — nothing in this
    # codebase reads it automatically. It is NOT wired into
    # ConfidenceEngine's construction anywhere, and DEFAULT_WEIGHTS in
    # decision/confidence_engine.py still hardcodes hft_flow at 0.0
    # regardless of this setting's value. Enabling it for live is a
    # deliberate, explicit operational step — see docs/architecture.md's
    # HFT Flow Trend Following section ("Enabling for live") for the
    # exact one-line change required, and do it only after HFT-5's paper
    # validation has produced enough evidence to justify it.
    #
    # Default of 5.0 (vs. HFT-5's own paper-testing examples of 20.0) is
    # deliberately small — about 5% of total confidence weight — so that
    # even if this value is mistakenly applied, it can only ever nudge an
    # already-close decision, never dominate SMC/Volume/OI/Funding/Regime.
    HFT_FLOW_LIVE_WEIGHT: float = Field(default=5.0, alias="HFT_FLOW_LIVE_WEIGHT")

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

    @property
    def hft_ws_url(self) -> str:
        """V16 Phase 4C Track B (HFT-1): mirrors `base_url`'s
        testnet/mainnet selection, for the WebSocket host instead of REST."""
        return self.HFT_WS_TESTNET_BASE_URL if self.BINANCE_TESTNET else self.HFT_WS_BASE_URL


settings = Settings()

import os as _os
EXECUTION_MODE: str = _os.environ.get("EXECUTION_MODE", "paper").lower()

# ── W14-2D-1: execution_lane — derived, not independent state ────────────────
# Single source of truth for "which lane does every journal/dataset write in
# this process belong to". Deliberately NOT a new control-plane flag and NOT
# persisted anywhere — it is a pure function of the EXECUTION_MODE this
# process already booted with (see execution/execution_factory.py, which
# picks the actual engine from the same EXECUTION_MODE value). Concurrent
# LIVE + TRAINING in one process is out of scope for W14-2D-1 (see
# docs/architecture.md's W14-2D-1 section) — today's reality is exactly one
# engine per process, so exactly one lane per process is the honest mapping:
#   live | testnet  -> LIVE      (real Binance account codepath, even though
#                                  testnet's money is fake, the execution
#                                  codepath and risk surface are the live one)
#   paper           -> TRAINING  (the existing PaperExecutionEngine feeds the
#                                  automated ML training pipeline)
#   anything else   -> TRAINING  (fail-safe: an unrecognized EXECUTION_MODE
#                                  must never be silently labeled LIVE)
# PAPER is a reserved third value for a future manual/dry-run lane distinct
# from the automated TRAINING lane — not derived here because no runtime
# path in the codebase produces it yet (W14-2D-1 must not invent one).
_EXECUTION_LANE_BY_MODE = {"live": "LIVE", "testnet": "LIVE", "paper": "TRAINING"}
EXECUTION_LANE: str = _EXECUTION_LANE_BY_MODE.get(EXECUTION_MODE, "TRAINING")
