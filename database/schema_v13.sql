-- ============================================================================
-- Brain Bot V13 — Unified Database Schema
-- ============================================================================
-- Replaces the 47MB agi_memory.db with a lean, purpose-built schema that
-- serves three consumers:
--   1. Trading core   (journal, risk, decision audit trail)
--   2. Dashboard      (/api/* read endpoints)
--   3. Pixel Office / AI Command Center (agent_messages, agent_decisions,
--      ai_explanations — narrative + causal output for NPC interactions)
--
-- Design notes
-- ------------
--   - All timestamps stored as ISO-8601 UTC strings (TEXT), matching the
--     existing trade_journal.py convention for consistency.
--   - JSON columns (TEXT) hold structured breakdowns (confidence, causal
--     reasoning, event payloads) so the API layer can pass them through
--     without reshaping.
--   - Every table that the dashboard will query has an index on timestamp
--     (and symbol where relevant) for fast "latest N" queries.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- trades — one row per executed/managed trade (extends v1 trade_journal)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,          -- LONG | SHORT
    regime          TEXT,

    -- SMC flags
    bos             INTEGER DEFAULT 0,
    choch           INTEGER DEFAULT 0,
    fvg             INTEGER DEFAULT 0,
    ob              INTEGER DEFAULT 0,

    -- Futures context at entry
    oi_delta        REAL    DEFAULT 0.0,
    funding         REAL    DEFAULT 0.0,
    volume_spike    INTEGER DEFAULT 0,

    -- Confidence Engine output (see confidence_engine.py)
    confidence      REAL    DEFAULT 0.0,        -- 0-100
    confidence_breakdown TEXT DEFAULT '',       -- JSON: {"smc":30,"volume":15,...}
    score           INTEGER DEFAULT 0,

    -- Trade parameters
    entry_price     REAL    DEFAULT 0.0,
    stop_loss       REAL    DEFAULT 0.0,
    take_profit     REAL    DEFAULT 0.0,
    quantity        REAL    DEFAULT 0.0,

    -- Outcome
    result          TEXT    DEFAULT 'OPEN',     -- OPEN | WIN | LOSS | CANCELLED
    pnl             REAL    DEFAULT 0.0,
    rr              REAL    DEFAULT 0.0,
    exit_price      REAL    DEFAULT 0.0,

    mtf_aligned     INTEGER DEFAULT 0,
    block_reasons   TEXT    DEFAULT '',
    order_id        TEXT    DEFAULT '',

    -- Link to the signal + causal explanation that produced this trade
    signal_id       INTEGER REFERENCES signals(id),
    explanation_id  INTEGER REFERENCES ai_explanations(id),

    extra_data      TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_symbol    ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_result    ON trades(result);


-- ----------------------------------------------------------------------------
-- daily_stats — rollup, retained from v1
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_stats (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL UNIQUE,
    total_trades INTEGER DEFAULT 0,
    wins         INTEGER DEFAULT 0,
    losses       INTEGER DEFAULT 0,
    win_rate     REAL    DEFAULT 0.0,
    total_pnl    REAL    DEFAULT 0.0,
    avg_rr       REAL    DEFAULT 0.0
);


-- ----------------------------------------------------------------------------
-- signals — every decision cycle's output, regardless of whether a trade
-- was opened. This is the primary feed for /api/signals.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    action          TEXT    NOT NULL,           -- LONG | SHORT | WAIT | SKIP
    direction       TEXT,
    confidence      REAL    DEFAULT 0.0,
    confidence_breakdown TEXT DEFAULT '',        -- JSON
    score           INTEGER DEFAULT 0,
    max_score       INTEGER DEFAULT 9,
    regime          TEXT,
    mtf_aligned     INTEGER DEFAULT 0,
    blocked         INTEGER DEFAULT 0,
    block_reasons   TEXT    DEFAULT '',          -- JSON array
    entry_price     REAL    DEFAULT 0.0,
    stop_loss       REAL    DEFAULT 0.0,
    take_profit     REAL    DEFAULT 0.0,
    raw_features    TEXT    DEFAULT ''           -- JSON: SMC/volume/trend/futures snapshot
);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_symbol    ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_action    ON signals(action);


-- ----------------------------------------------------------------------------
-- market_regimes — time series of regime classifications
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_regimes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    regime          TEXT    NOT NULL,           -- TREND | RANGE | VOLATILE | SQUEEZE
    confidence      REAL    DEFAULT 0.0,
    adx             REAL    DEFAULT 0.0,
    bb_width        REAL    DEFAULT 0.0,
    atr_normalized  REAL    DEFAULT 0.0,
    probabilities   TEXT    DEFAULT ''           -- JSON: {"TREND":0.6,"RANGE":0.2,...}
);
CREATE INDEX IF NOT EXISTS idx_market_regimes_timestamp ON market_regimes(timestamp);
CREATE INDEX IF NOT EXISTS idx_market_regimes_symbol    ON market_regimes(symbol);


-- ----------------------------------------------------------------------------
-- market_snapshots — periodic full-state capture (mark price, OHLCV summary,
-- trend bias, etc.) for dashboard charts and replay/backtesting.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    mark_price      REAL    DEFAULT 0.0,
    h4_close        REAL    DEFAULT 0.0,
    h1_close        REAL    DEFAULT 0.0,
    m15_close       REAL    DEFAULT 0.0,
    trend_bias_h4   TEXT    DEFAULT '',
    trend_bias_h1   TEXT    DEFAULT '',
    trend_bias_m15  TEXT    DEFAULT '',
    ema20           REAL    DEFAULT 0.0,
    ema50           REAL    DEFAULT 0.0,
    ema200          REAL    DEFAULT 0.0,
    vwap            REAL    DEFAULT 0.0,
    adx             REAL    DEFAULT 0.0,
    extra_data      TEXT    DEFAULT ''           -- JSON: anything else worth keeping
);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_timestamp ON market_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol    ON market_snapshots(symbol);


-- ----------------------------------------------------------------------------
-- funding_history — funding rate time series (own table so dashboard can
-- chart it independently of market_snapshots)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS funding_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    funding_rate    REAL    NOT NULL,
    mark_price      REAL    DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_funding_history_timestamp ON funding_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_funding_history_symbol    ON funding_history(symbol);


-- ----------------------------------------------------------------------------
-- oi_history — open interest time series (own table; binance_provider already
-- computes oi_delta_pct on the fly, this persists it for charting/backtesting)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oi_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    open_interest   REAL    NOT NULL,
    oi_value        REAL    DEFAULT 0.0,         -- sumOpenInterestValue (USDT notional)
    oi_delta_pct    REAL    DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_oi_history_timestamp ON oi_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_oi_history_symbol    ON oi_history(symbol);


-- ----------------------------------------------------------------------------
-- scanner_snapshots — V16 Phase 2 Part 1 (Market Scanner). One row per scan
-- cycle (not per symbol — a 200+-symbol universe scanning every 20s would
-- make a per-symbol-per-row table grow ~36k rows/hour with mostly-static
-- data). `data` holds the full symbol -> metrics map as JSON, matching the
-- extra_data JSON-blob convention already used by market_snapshots above.
-- Per-symbol funding_history/oi_history tables already exist for anyone
-- who wants a narrower single-symbol time series instead.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scanner_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT    NOT NULL,     -- ISO8601 UTC
    scanned_at        REAL    NOT NULL,     -- unix epoch (float)
    symbol_count      INTEGER NOT NULL,     -- symbols in the bulk pass this cycle
    detail_count      INTEGER NOT NULL,     -- symbols that also got the ATR/OI detail pass
    cycle_duration_s  REAL    DEFAULT 0.0,
    data              TEXT    NOT NULL      -- JSON: {symbol: {price, price_change_pct_24h,
                                             --   quote_volume_24h, funding_rate, spread_pct,
                                             --   open_interest, atr_pct, detail_at}, ...}
);
CREATE INDEX IF NOT EXISTS idx_scanner_snapshots_timestamp ON scanner_snapshots(timestamp);


-- ----------------------------------------------------------------------------
-- ranking_history — V16 Phase 2 Part 2 (Opportunity Ranking Engine). One row
-- per ranking cycle (same one-row-per-cycle JSON-blob convention as
-- scanner_snapshots above, for the same reason — a wide, dynamic per-symbol
-- shape that would be awkward and slow as one column-per-factor row).
-- avg_coverage is the mean ScoreBreakdown coverage (confidence_fusion.py)
-- across the top_n entries — lets a dashboard/alert flag a ranking cycle
-- where most of the composite scores were built from unusually little
-- real data (e.g. scanner detail pass was degraded) without parsing `data`.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ranking_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT    NOT NULL,     -- ISO8601 UTC
    ranked_at      REAL    NOT NULL,     -- unix epoch
    symbol_count   INTEGER NOT NULL,     -- symbols scored this cycle (scanner universe size)
    top_n          INTEGER NOT NULL,     -- how many opportunities made the output
    avg_coverage   REAL    DEFAULT 0.0,  -- mean composite-score data-coverage, 0-1
    duration_s     REAL    DEFAULT 0.0,
    data           TEXT    NOT NULL      -- JSON: [RankedOpportunity.to_dict(), ...]
);
CREATE INDEX IF NOT EXISTS idx_ranking_history_timestamp ON ranking_history(timestamp);


-- ----------------------------------------------------------------------------
-- agent_decisions — every "agent" (SMC_ANALYST, VOLUME_ANALYST,
-- FUTURES_ANALYST, REGIME_ANALYST, RISK_MANAGER, CONFIDENCE_ENGINE, ...)
-- logs its individual contribution here. This is what later powers
-- Pixel Office NPCs — each NPC = one agent, reading its own row stream.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    agent           TEXT    NOT NULL,            -- e.g. "SMC_ANALYST"
    symbol          TEXT    NOT NULL,
    decision        TEXT    NOT NULL,            -- e.g. "BOS_BULLISH", "OI_RISING_STRONG"
    score           REAL    DEFAULT 0.0,
    weight          REAL    DEFAULT 0.0,
    details         TEXT    DEFAULT '',          -- JSON
    signal_id       INTEGER REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_timestamp ON agent_decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent     ON agent_decisions(agent);


-- ----------------------------------------------------------------------------
-- agent_messages — free-form chatter / status messages published via the
-- event bus (event_bus.py). Pixel Office NPCs read this stream to decide
-- what to "say" and how to animate.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    agent           TEXT    NOT NULL,            -- e.g. "SMC_ANALYST"
    event           TEXT    NOT NULL,            -- e.g. "BOS_DETECTED"
    message         TEXT    NOT NULL,            -- human-readable text
    severity        TEXT    DEFAULT 'info',      -- info | warning | critical
    payload         TEXT    DEFAULT ''           -- JSON: arbitrary event data
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_timestamp ON agent_messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_messages_agent     ON agent_messages(agent);
CREATE INDEX IF NOT EXISTS idx_agent_messages_event     ON agent_messages(event);


-- ----------------------------------------------------------------------------
-- ai_explanations — structured causal reasoning produced by
-- causal_explainer.py. One row per decision cycle; trades reference this
-- via trades.explanation_id.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_explanations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    signal_id       INTEGER REFERENCES signals(id),
    direction       TEXT,                        -- LONG | SHORT | WAIT | SKIP
    confidence      REAL    DEFAULT 0.0,
    summary         TEXT    DEFAULT '',           -- short natural-language summary
    reasoning       TEXT    NOT NULL              -- JSON: structured causal reasoning
                                                   -- {"factors":[{"name":"BOS","direction":"Bullish",
                                                   --   "contribution":30,"detail":"..."}], "summary":"..."}
);
CREATE INDEX IF NOT EXISTS idx_ai_explanations_timestamp ON ai_explanations(timestamp);
CREATE INDEX IF NOT EXISTS idx_ai_explanations_symbol    ON ai_explanations(symbol);


-- ----------------------------------------------------------------------------
-- config_profiles — live-editable strategy configuration (dashboard
-- Strategy Config Panel writes here; runtime_config.py reads here).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,      -- e.g. "default", "conservative"
    active          INTEGER DEFAULT 0,            -- 1 = currently in use
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    config_json      TEXT    NOT NULL              -- JSON: full settings override dict
);
CREATE INDEX IF NOT EXISTS idx_config_profiles_active ON config_profiles(active);


-- ============================================================================
-- v14 Phase 3 — Stability + Research + ML (all idempotent)
-- ============================================================================

CREATE TABLE IF NOT EXISTS reconciliation_events (
    id                  TEXT    PRIMARY KEY,
    timestamp           TEXT    NOT NULL,
    mismatch_type        TEXT    NOT NULL,
    severity            TEXT    NOT NULL,
    exchange_view        TEXT    NOT NULL,
    journal_view         TEXT    NOT NULL,
    bot_view             TEXT    NOT NULL,
    detail               TEXT    DEFAULT '',
    recovery_attempted   INTEGER DEFAULT 0,
    recovery_result      TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_recon_timestamp ON reconciliation_events(timestamp);

CREATE TABLE IF NOT EXISTS feature_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL,
    mission_id          TEXT,
    trade_id            INTEGER,
    symbol              TEXT    NOT NULL DEFAULT 'BTCUSDT',
    direction           TEXT    NOT NULL DEFAULT '',
    confidence           REAL    DEFAULT 0.0,
    funding             REAL    DEFAULT 0.0,
    open_interest        REAL    DEFAULT 0.0,
    oi_delta             REAL    DEFAULT 0.0,
    liquidation_signal    REAL    DEFAULT 0.0,
    fear_greed           REAL    DEFAULT 50.0,
    regime               TEXT    DEFAULT '',
    volatility           REAL    DEFAULT 0.0,
    atr                  REAL    DEFAULT 0.0,
    smc_score            REAL    DEFAULT 0.0,
    volume_score         REAL    DEFAULT 0.0,
    entry_price           REAL    DEFAULT 0.0,
    stop_loss             REAL    DEFAULT 0.0,
    take_profit           REAL    DEFAULT 0.0,
    holding_time_s         REAL,
    result                REAL,
    pnl                  REAL,
    extra_json            TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_feature_rows_created  ON feature_rows(created_at);
CREATE INDEX IF NOT EXISTS idx_feature_rows_result   ON feature_rows(result);

CREATE TABLE IF NOT EXISTS model_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    model_type      TEXT    NOT NULL,
    version          TEXT    NOT NULL,
    active           INTEGER DEFAULT 0,
    algorithm        TEXT    DEFAULT '',
    training_rows     INTEGER DEFAULT 0,
    win_rate          REAL    DEFAULT 0.0,
    profit_factor     REAL    DEFAULT 0.0,
    max_drawdown      REAL    DEFAULT 0.0,
    feature_importance TEXT   DEFAULT '',
    metrics_json      TEXT    DEFAULT '',
    model_path        TEXT    DEFAULT '',
    notes            TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_model_registry_type_active ON model_registry(model_type, active);

CREATE TABLE IF NOT EXISTS ml_predictions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    trade_id            INTEGER,
    signal_id           INTEGER,
    model_type          TEXT    NOT NULL,
    model_version        TEXT    DEFAULT '',
    raw_confidence        REAL    DEFAULT 0.0,
    calibrated_confidence  REAL    DEFAULT 0.0,
    meta_label            TEXT    DEFAULT '',
    outcome_probability    REAL    DEFAULT 0.0,
    actual_result         TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_timestamp ON ml_predictions(timestamp);

-- ----------------------------------------------------------------------------
-- portfolio_history — V16 Phase 2B (Portfolio Manager Orchestrator). One row
-- per PortfolioManager.decide() cycle, same one-row-per-cycle JSON-blob
-- convention as ranking_history/scanner_snapshots above, for the same
-- reason — a wide, dynamic shape (selected/rejected/replacements/sector
-- exposure) that would be awkward and slow as one column-per-field row.
-- portfolio_score is the capital-weighted mean final_score of `selected`
-- (see portfolio/portfolio_models.py:OrchestratedDecision) — lets a
-- dashboard/alert flag a degraded-quality cycle without parsing `data`.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_history (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                TEXT    NOT NULL,     -- ISO8601 UTC
    decided_at               REAL    NOT NULL,     -- unix epoch
    blocked                  INTEGER NOT NULL DEFAULT 0,
    block_reason             TEXT,
    selected_count            INTEGER NOT NULL DEFAULT 0,
    rejected_count            INTEGER NOT NULL DEFAULT 0,
    replacement_count          INTEGER NOT NULL DEFAULT 0,
    total_capital_allocated    REAL    DEFAULT 0.0,
    total_risk_allocated       REAL    DEFAULT 0.0,
    diversification_score      REAL    DEFAULT 100.0,
    portfolio_score            REAL    DEFAULT 0.0,
    drawdown                  REAL    DEFAULT 0.0,
    data                     TEXT    NOT NULL      -- JSON: OrchestratedDecision.to_dict() + sector_exposure/drawdown context
);
CREATE INDEX IF NOT EXISTS idx_portfolio_history_timestamp ON portfolio_history(timestamp);
