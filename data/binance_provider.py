"""
Data Layer: BinanceDataProvider (V15 Production)

V14 bugs fixed
--------------
BUG-V15-BP-01: _time_drift_ms attribute missing.
  /api/health called getattr(dp, "_time_drift_ms", 0) which always returned 0
  since BinanceDataProvider stored the offset as _time_offset_ms_market.
  Fix: Added @property _time_drift_ms aliasing _time_offset_ms_market.

BUG-V15-BP-02: No request timeout on HTTP calls.
  A hanging Binance TCP connection would block indefinitely.
  Fix: binance-connector uses requests internally; we monkey-patch the
  session timeout to 10s via _set_session_timeout().

BUG-V15-BP-03: No circuit breaker for market data.
  Repeated failures to get_mark_price() would burn through retries every
  cycle even when Binance is clearly down.
  Fix: Integrated CircuitBreaker via get_breaker("binance_market") and
  get_breaker("binance_trade"); opens after 5 consecutive failures, probes
  after 60s.

BUG-V15-BP-04: Clock sync failure on startup swallowed silently but left
  _time_offset_ms_* at 0 — subsequent signed requests could be rejected
  by Binance for timestamp mismatch.
  Fix: Warns clearly and stores None sentinel so dashboard can show
  "time sync failed" instead of "0ms drift".
"""

from __future__ import annotations

import time
import types
import pandas as pd

from binance.um_futures import UMFutures
from binance.error import ClientError

from config.settings import settings, EXECUTION_MODE
from utils.logger import get_logger
from utils.retry import retry_api_call
from data.validation import validate_ohlcv, clean_ohlcv
from system_health.circuit_breaker import get_breaker, CircuitBreakerOpen

logger = get_logger(__name__)

# Circuit breakers: separate for market data vs trading endpoints
_MARKET_BREAKER = get_breaker("binance_market", failure_threshold=5, recovery_timeout=60)
_TRADE_BREAKER  = get_breaker("binance_trade",  failure_threshold=5, recovery_timeout=60)

_HTTP_TIMEOUT = 10  # seconds; applied to every requests.Session


class BinanceDataProvider:
    """Single entry-point for all Binance Futures market data.

    Dual-client design
    ------------------
    market_client  →  Mainnet (ราคา/ข้อมูลตลาดจริง, public endpoints เสมอ)
    trade_client   →  Mainnet หรือ Testnet ตาม settings.BINANCE_TESTNET
                       (V16 BUG-V16-BP-05 fix — ก่อนหน้านี้ hardcode เป็น
                       Testnet เสมอ ไม่ว่า EXECUTION_MODE จะเป็น live หรือไม่)
    self.client    →  alias ของ trade_client (backward-compat)

    BUG-V16-BP-05: trade_client hardcoded to Testnet regardless of mode.
      run_live.bat/run_live.sh set BINANCE_TESTNET=false + EXECUTION_MODE=live,
      and execution_factory.py logged "Binance LIVE ⚠️", but every real
      order/balance/position call (execution/trade_manager.py → self.client)
      went through a trade_client that was *always* constructed with
      BINANCE_TESTNET_API_KEY + BINANCE_TESTNET_BASE_URL — so EXECUTION_MODE=live
      could never actually reach Binance mainnet. settings.base_url already
      encoded the correct mainnet/testnet branching but was never wired to
      this client. Fix: branch on settings.BINANCE_TESTNET (same flag the
      run_live/run_testnet scripts already set) and fail fast instead of
      silently starting with empty mainnet keys.
    """

    def __init__(self) -> None:
        # ── BUG-LIVE-RISK-06: EXECUTION_MODE / BINANCE_TESTNET invariant ──
        # Read-only audit Critical Finding A: EXECUTION_MODE only selects
        # which execution engine class is built (execution_factory.py);
        # settings.BINANCE_TESTNET independently decides which network
        # THIS client actually talks to. Nothing previously required the
        # two to agree, so EXECUTION_MODE=testnet + BINANCE_TESTNET=false
        # could reach Binance MAINNET with real money, and
        # EXECUTION_MODE=live + BINANCE_TESTNET=true could silently run on
        # Testnet while the operator believed they were live. Enforced only
        # for testnet/live — paper mode never uses this provider's
        # trade_client for a real order (PaperExecutionEngine is fully
        # separate), so BINANCE_TESTNET is irrelevant to paper and is left
        # unconstrained, matching pre-existing paper-mode behavior exactly.
        # Deliberately placed here (not scattered across main.py /
        # execution_factory.py) because this __init__ is the single point
        # that actually constructs the network-bound trade_client — same
        # convention as the mainnet-credentials guard a few lines below.
        _mode = EXECUTION_MODE.strip().lower()
        if _mode in ("testnet", "live"):
            _expected_testnet = _mode == "testnet"
            _actual_testnet = bool(settings.BINANCE_TESTNET)
            if _actual_testnet != _expected_testnet:
                raise RuntimeError(
                    f"Refusing to start: EXECUTION_MODE={_mode!r} requires "
                    f"BINANCE_TESTNET={_expected_testnet}, but BINANCE_TESTNET="
                    f"{_actual_testnet} in the current configuration. "
                    f"EXECUTION_MODE=testnet must run with BINANCE_TESTNET=true "
                    f"(so real orders go to Binance Testnet), and "
                    f"EXECUTION_MODE=live must run with BINANCE_TESTNET=false "
                    f"(so real orders go to Binance Mainnet). A mismatch here "
                    f"means orders could go to the wrong network. Fix .env and "
                    f"restart — no API keys are included in this message."
                )

        # ── Market data: ดึงจาก Mainnet เสมอ ──────────────────────────
        self.market_client = UMFutures(
            key=settings.BINANCE_API_KEY,
            secret=settings.BINANCE_API_SECRET,
            base_url=settings.BINANCE_PROD_BASE_URL,
        )

        # ── Trading: mainnet (เงินจริง) หรือ testnet (เงินปลอม) ──────────
        # ตาม settings.BINANCE_TESTNET — ค่าเดียวกับที่ run_live.*/run_testnet.*
        # ตั้งไว้ และตรงกับ settings.base_url property ที่มีอยู่แล้ว
        if settings.BINANCE_TESTNET:
            trade_key, trade_secret, trade_base_url = (
                settings.BINANCE_TESTNET_API_KEY,
                settings.BINANCE_TESTNET_API_SECRET,
                settings.BINANCE_TESTNET_BASE_URL,
            )
        else:
            if not settings.BINANCE_API_KEY or not settings.BINANCE_API_SECRET:
                raise RuntimeError(
                    "BINANCE_TESTNET=false (live trading) but BINANCE_API_KEY / "
                    "BINANCE_API_SECRET are not set — refusing to start with "
                    "empty mainnet credentials. Set both in .env before running "
                    "run_live.bat / run_live.sh."
                )
            trade_key, trade_secret, trade_base_url = (
                settings.BINANCE_API_KEY,
                settings.BINANCE_API_SECRET,
                settings.BINANCE_PROD_BASE_URL,
            )

        self.trade_client = UMFutures(
            key=trade_key,
            secret=trade_secret,
            base_url=trade_base_url,
        )

        # backward-compat: execution layer ยังคงใช้ self.client
        self.client = self.trade_client

        self.symbol = settings.SYMBOL

        # Clock drift correction ─────────────────────────────────────────────
        self._time_offset_ms_market: int = 0
        self._time_offset_ms_trade:  int = 0
        self._time_sync_ok: bool = False

        self._patch_sign_request(self.market_client, "market")
        self._patch_sign_request(self.trade_client,  "trade")

        # Apply request timeouts to underlying HTTP sessions ─────────────────
        self._set_session_timeout(self.market_client, _HTTP_TIMEOUT)
        self._set_session_timeout(self.trade_client,  _HTTP_TIMEOUT)

        self._sync_time_offset()

        trading_label = "TESTNET" if settings.BINANCE_TESTNET else "MAINNET ⚠️ LIVE-REAL-MONEY"
        logger.info(
            f"BinanceDataProvider V15 ready | symbol={self.symbol} "
            f"| market=MAINNET | trading={trading_label} "
            f"| clock_sync={'OK' if self._time_sync_ok else 'FAILED'}"
        )

    # ── V15 FIX BUG-V15-BP-01: _time_drift_ms property ──────────────────────

    @property
    def _time_drift_ms(self) -> int:
        """Alias for /api/health time_drift_ms field (was always 0 in V14)."""
        return self._time_offset_ms_market

    # ── V15 FIX BUG-V15-BP-02: HTTP timeout ──────────────────────────────────

    @staticmethod
    def _set_session_timeout(client: UMFutures, timeout: int) -> None:
        """
        Monkey-patch the binance-connector's underlying requests.Session
        to enforce a socket timeout. Without this, a stalled TCP connection
        blocks the trading loop indefinitely.
        """
        try:
            session = getattr(client, "session", None)
            if session is not None:
                # requests.Session.request() accepts timeout as keyword
                original_request = session.request
                def _timed_request(method, url, **kwargs):
                    kwargs.setdefault("timeout", timeout)
                    return original_request(method, url, **kwargs)
                session.request = _timed_request
                logger.debug(f"HTTP timeout={timeout}s applied to {type(client).__name__}")
        except Exception as exc:
            logger.debug(f"_set_session_timeout failed (non-fatal): {exc}")

    # ── Clock drift correction ────────────────────────────────────────────────

    def _patch_sign_request(self, client: UMFutures, role: str) -> None:
        """Override sign_request on this client instance to inject clock offset."""
        offset_attr = f"_time_offset_ms_{role}"
        provider = self

        def _offset_sign_request(self_client, http_method, url_path, payload=None, special=False):
            if payload is None:
                payload = {}
            offset = getattr(provider, offset_attr, 0)
            payload["timestamp"] = int(time.time() * 1000) + offset
            query_string = self_client._prepare_params(payload, special)
            payload["signature"] = self_client._get_sign(query_string)
            return self_client.send_request(http_method, url_path, payload, special)

        client.sign_request = types.MethodType(_offset_sign_request, client)

    def _sync_time_offset(self) -> None:
        """Refresh clock offsets for both clients. Called at startup and periodically."""
        any_ok = False
        for client, role in ((self.market_client, "market"), (self.trade_client, "trade")):
            try:
                local_before = int(time.time() * 1000)
                server_time  = client.time()["serverTime"]
                local_after  = int(time.time() * 1000)
                local_mid = (local_before + local_after) // 2
                offset = server_time - local_mid
                setattr(self, f"_time_offset_ms_{role}", offset)
                logger.debug(f"Clock sync | {role} | offset={offset}ms")
                any_ok = True
            except Exception as exc:
                logger.warning(
                    f"Clock sync failed for {role} client (keeping previous offset={getattr(self, f'_time_offset_ms_{role}', 0)}ms): {exc}"
                )
        self._time_sync_ok = any_ok

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _klines_to_df(raw: list) -> pd.DataFrame:
        """Convert raw klines list → OHLCV DataFrame (UTC-indexed)."""
        df = pd.DataFrame(
            raw,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "count",
                "taker_buy_vol", "taker_buy_quote_vol", "ignore",
            ],
        )
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.set_index("open_time", inplace=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        return df[["open", "high", "low", "close", "volume"]].copy()

    # ─────────────────────────────────────────────────────────────────────
    # Market data  (V15: circuit-breaker wrapped)
    # ─────────────────────────────────────────────────────────────────────

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_ohlcv(self, timeframe: str, limit: int | None = None, symbol: str | None = None) -> pd.DataFrame:
        """Fetch OHLCV candlestick data for a single timeframe.

        symbol: V16 Phase 2F — explicit override for multi-symbol callers
        (execution/portfolio_signal_provider.py). Omit for the existing
        single-symbol behavior (uses self.symbol), unchanged.
        """
        limit = limit or settings.KLINE_LIMIT
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                raw = self.market_client.klines(symbol=target_symbol, interval=timeframe, limit=limit)
            df = self._klines_to_df(raw)
            logger.debug(f"OHLCV | tf={timeframe} | bars={len(df)}")
            return df
        except CircuitBreakerOpen as exc:
            logger.warning(f"OHLCV skipped — market circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"OHLCV error [{timeframe}]: {exc}")
            raise

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_mark_price(self, symbol: str | None = None) -> float:
        """Return current mark price."""
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                result = self.market_client.mark_price(symbol=target_symbol)
            mark = float(result["markPrice"])
            logger.debug(f"Mark price: {mark:.2f}")
            return mark
        except CircuitBreakerOpen as exc:
            logger.warning(f"mark_price skipped — market circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"Mark price error: {exc}")
            raise

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_order_book_snapshot(self, symbol: str | None = None, limit: int = 1000) -> dict:
        """V16 Phase 4C Track B (HFT-1): REST order-book snapshot, used by
        data/local_order_book.py to initialize/resync local book state
        before/around applying diff-depth WebSocket updates. Returns the
        raw parsed shape Binance provides (`lastUpdateId`, `bids`, `asks`
        as [str, str] pairs) rather than a project-specific dataclass —
        conversion to data.local_order_book.DepthSnapshot is the caller's
        job, keeping this method a thin, consistent REST wrapper like every
        other method in this class.

        limit: Binance valid values are 5/10/20/50/100/500/1000 — 1000 is
        the largest depth the endpoint supports and matches what a diff-
        depth stream can resync against without a level gap.
        """
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                raw = self.market_client.depth(symbol=target_symbol, limit=limit)
            logger.debug(
                f"Order book snapshot | {target_symbol} | lastUpdateId={raw.get('lastUpdateId')} "
                f"| bids={len(raw.get('bids', []))} | asks={len(raw.get('asks', []))}"
            )
            return raw
        except CircuitBreakerOpen as exc:
            logger.warning(f"Order book snapshot skipped — market circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"Order book snapshot error [{target_symbol}]: {exc}")
            raise

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_current_open_interest(self, symbol: str | None = None) -> float:
        """Return current open interest (contracts)."""
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                result = self.market_client.open_interest(symbol=target_symbol)
            oi = float(result["openInterest"])
            logger.debug(f"Open Interest: {oi:.2f}")
            return oi
        except CircuitBreakerOpen as exc:
            logger.warning(f"OI skipped — market circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"OI error: {exc}")
            raise

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_oi_history(self, period: str = "5m", limit: int = 30, symbol: str | None = None) -> list:
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                raw = self.market_client.open_interest_hist(
                    symbol=target_symbol, period=period, limit=limit
                )
            return raw if isinstance(raw, list) else []
        except CircuitBreakerOpen:
            return []
        except ClientError as exc:
            logger.warning(f"OI history error: {exc}")
            return []

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_funding_rate(self, symbol: str | None = None) -> float:
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                result = self.market_client.mark_price(symbol=target_symbol)
            rate = float(result.get("lastFundingRate", 0.0))
            logger.debug(f"Funding rate: {rate:.6f}")
            return rate
        except CircuitBreakerOpen:
            return 0.0
        except ClientError as exc:
            logger.warning(f"Funding rate error: {exc}")
            return 0.0

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_long_short_ratio(self, symbol: str | None = None) -> dict:
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                raw = self.market_client.top_long_short_account_ratio(
                    symbol=target_symbol, period="5m", limit=1
                )
            if raw:
                return raw[0] if isinstance(raw, list) else raw
            return {}
        except (CircuitBreakerOpen, ClientError, Exception) as exc:
            logger.debug(f"L/S ratio error (non-fatal): {exc}")
            return {}

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_taker_ratio(self, symbol: str | None = None) -> dict:
        target_symbol = symbol or self.symbol
        try:
            with _MARKET_BREAKER:
                raw = self.market_client.taker_long_short_ratio(
                    symbol=target_symbol, period="5m", limit=1
                )
            if raw:
                return raw[0] if isinstance(raw, list) else raw
            return {}
        except (CircuitBreakerOpen, ClientError, Exception) as exc:
            logger.debug(f"Taker ratio error (non-fatal): {exc}")
            return {}

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_liquidations(self) -> list:
        try:
            with _MARKET_BREAKER:
                raw = self.market_client.get_all_liquidation_orders(
                    symbol=self.symbol, limit=10
                )
            return raw if isinstance(raw, list) else []
        except (CircuitBreakerOpen, ClientError, Exception) as exc:
            logger.debug(f"Liquidations error (non-fatal): {exc}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # Account / Trade data
    # ─────────────────────────────────────────────────────────────────────

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_account_balance(self) -> float:
        try:
            with _TRADE_BREAKER:
                raw = self.trade_client.balance(recvWindow=5000)
            for asset in raw:
                if asset.get("asset") == "USDT":
                    bal = float(asset.get("availableBalance", 0.0))
                    logger.info(f"Balance: {bal:.2f} USDT")
                    return bal
            # fix/live-balance-zero-diagnostics: this branch used to
            # silently `return 0.0` with no log line at any level, which
            # is indistinguishable from a genuinely empty account and was
            # never visible in an INFO-level production log. Every real
            # order this bot has ever attempted was skipped downstream by
            # trade_manager.py's minQty guard because of exactly this path
            # (see PATCH_NOTES.md for the production log evidence). Logging
            # asset *names* only (never balance figures — none were found
            # anyway) so the response shape is diagnosable from
            # logs/brain_bot.log without needing DEBUG enabled. See
            # scripts/diagnose_balance.py for a standalone deep-dive.
            seen = [a.get("asset") for a in raw] if isinstance(raw, list) else type(raw).__name__
            logger.warning(
                f"get_account_balance: no 'USDT' entry in trade_client.balance() "
                f"response — returning 0.0. Assets seen: {seen}. If this persists, "
                f"run scripts/diagnose_balance.py to check BINANCE_TESTNET, API key "
                f"permissions, and Multi-Assets Mode."
            )
            return 0.0
        except CircuitBreakerOpen as exc:
            logger.warning(f"get_account_balance skipped — trade circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"Balance error: {exc}")
            raise

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_position_info(self) -> dict | None:
        """Return open position dict or None."""
        try:
            with _TRADE_BREAKER:
                raw = self.trade_client.get_position_risk(
                    symbol=self.symbol, recvWindow=5000
                )
            for p in raw:
                amt = float(p.get("positionAmt", 0.0))
                if amt != 0.0:
                    return {
                        "symbol":            p.get("symbol"),
                        "side":              "LONG" if amt > 0 else "SHORT",
                        "positionAmt":       abs(amt),
                        "entryPrice":        float(p.get("entryPrice", 0.0)),
                        "unrealizedProfit":  float(p.get("unRealizedProfit", 0.0)),
                        "leverage":          int(p.get("leverage", settings.LEVERAGE)),
                        "markPrice":         float(p.get("markPrice", 0.0)),
                    }
            return None
        except CircuitBreakerOpen as exc:
            logger.warning(f"get_position_info skipped — trade circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"Position info error: {exc}")
            raise

    def get_all_market_data(self) -> dict:
        """Fetch all market data needed for one pipeline cycle."""
        ohlcv = {}
        for tf_key, tf_val in [("h4", settings.H4_TIMEFRAME), ("h1", settings.H1_TIMEFRAME), ("m15", settings.M15_TIMEFRAME)]:
            try:
                df = self.get_ohlcv(tf_val)
                # BUG-V15-BP-05: validate_ohlcv returns (bool, reasons) tuple —
                # do NOT assign its return value back to df, or clean_ohlcv will
                # receive a tuple and crash with "'tuple' has no attribute 'copy'".
                is_valid, reasons = validate_ohlcv(df)
                if not is_valid:
                    logger.warning(f"OHLCV validation issues [{tf_val}]: {reasons} — cleaning anyway")
                df = clean_ohlcv(df)
                ohlcv[tf_key] = df
            except Exception as exc:
                logger.error(f"OHLCV fetch failed for {tf_val}: {exc}")
                raise

        mark_price    = self.get_mark_price()
        open_interest = self.get_current_open_interest()
        funding_rate  = self.get_funding_rate()
        ls_ratio      = self.get_long_short_ratio()
        taker_ratio   = self.get_taker_ratio()

        # Delta OI %
        oi_hist = self.get_oi_history(limit=2)
        oi_delta = 0.0
        if len(oi_hist) >= 2:
            try:
                prev = float(oi_hist[-2].get("sumOpenInterest", open_interest))
                oi_delta = (open_interest - prev) / prev if prev != 0 else 0.0
            except Exception:
                pass

        return {
            "ohlcv":          ohlcv,
            "mark_price":     mark_price,
            "open_interest":  open_interest,
            "funding_rate":   funding_rate,
            "ls_ratio":       ls_ratio,
            "taker_ratio":    taker_ratio,
            "oi_delta":       oi_delta,
            "oi_history":     oi_hist,
        }

    def get_market_data_for(self, symbol: str) -> dict:
        """V16 Phase 2F: identical to get_all_market_data() above — same
        shape, same fields, same fetch order — but for an explicit
        arbitrary `symbol` instead of self.symbol. Exists so
        execution/portfolio_signal_provider.py can reuse this class's
        already-configured market_client (mainnet, shared circuit
        breaker) for any of the Portfolio Manager's selected symbols,
        without a second BinanceDataProvider instance per symbol (that
        would also stand up a redundant trade_client / testnet
        connection per symbol for no reason — this only ever reads
        market data).

        Intentionally a separate method rather than making
        get_all_market_data() itself take a symbol= parameter: every
        existing call site (main.py's single-symbol loop) calls it with
        zero arguments every cycle, and this keeps that call site's
        contract (and this method's own docstring/behavior) completely
        unchanged rather than threading a new optional parameter through
        code that doesn't need it.
        """
        ohlcv = {}
        for tf_key, tf_val in [("h4", settings.H4_TIMEFRAME), ("h1", settings.H1_TIMEFRAME), ("m15", settings.M15_TIMEFRAME)]:
            try:
                df = self.get_ohlcv(tf_val, symbol=symbol)
                is_valid, reasons = validate_ohlcv(df)
                if not is_valid:
                    logger.warning(f"OHLCV validation issues [{symbol}/{tf_val}]: {reasons} — cleaning anyway")
                df = clean_ohlcv(df)
                ohlcv[tf_key] = df
            except Exception as exc:
                logger.error(f"OHLCV fetch failed for {symbol}/{tf_val}: {exc}")
                raise

        mark_price    = self.get_mark_price(symbol=symbol)
        open_interest = self.get_current_open_interest(symbol=symbol)
        funding_rate  = self.get_funding_rate(symbol=symbol)
        ls_ratio      = self.get_long_short_ratio(symbol=symbol)
        taker_ratio   = self.get_taker_ratio(symbol=symbol)

        oi_hist = self.get_oi_history(limit=2, symbol=symbol)
        oi_delta = 0.0
        if len(oi_hist) >= 2:
            try:
                prev = float(oi_hist[-2].get("sumOpenInterest", open_interest))
                oi_delta = (open_interest - prev) / prev if prev != 0 else 0.0
            except Exception:
                pass

        return {
            "ohlcv":          ohlcv,
            "mark_price":     mark_price,
            "open_interest":  open_interest,
            "funding_rate":   funding_rate,
            "ls_ratio":       ls_ratio,
            "taker_ratio":    taker_ratio,
            "oi_delta":       oi_delta,
            "oi_history":     oi_hist,
        }

    # ─────────────────────────────────────────────────────────────────────
    # C1 Exchange State Manager accessors (additive, read-only)
    #
    # These exist solely so exchange_state/manager.py never has to parse
    # raw Binance JSON itself — this class remains the single place that
    # translates UMFutures responses into plain dicts, exactly like
    # get_account_balance()/get_position_info() above already do.
    # Unlike get_position_info() (scoped to self.symbol only), these two
    # cover the whole account, since C1 serves multi-symbol consumers
    # (World/Dashboard/CEO context).
    # ─────────────────────────────────────────────────────────────────────

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_account_snapshot(self) -> dict:
        """One /fapi/v3/account call → wallet/margin totals AND every open
        position (Binance returns positions embedded in this response, so
        this is a single upstream call, not one-call-per-field)."""
        try:
            with _TRADE_BREAKER:
                raw = self.trade_client.account(recvWindow=5000)
        except CircuitBreakerOpen as exc:
            logger.warning(f"get_account_snapshot skipped — trade circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"get_account_snapshot error: {exc}")
            raise

        positions = []
        for p in raw.get("positions", []):
            amt = float(p.get("positionAmt", 0.0))
            if amt == 0.0:
                continue
            positions.append({
                "symbol":            p.get("symbol"),
                "side":              "LONG" if amt > 0 else "SHORT",
                "quantity":          abs(amt),
                "entry_price":       float(p.get("entryPrice", 0.0)),
                "mark_price":        float(p.get("markPrice", 0.0)),
                "unrealized_pnl":    float(p.get("unrealizedProfit", p.get("unRealizedProfit", 0.0))),
                "leverage":          int(p.get("leverage", settings.LEVERAGE)),
                "margin_type":       p.get("marginType", "UNKNOWN"),
                "liquidation_price": float(p.get("liquidationPrice", 0.0)),
            })

        return {
            "wallet_balance":       float(raw.get("totalWalletBalance", 0.0)),
            "available_balance":    float(raw.get("availableBalance", 0.0)),
            "unrealized_pnl":       float(raw.get("totalUnrealizedProfit", 0.0)),
            "total_margin_balance": float(raw.get("totalMarginBalance", 0.0)),
            "maintenance_margin":   float(raw.get("totalMaintMargin", 0.0)),
            "initial_margin":       float(raw.get("totalInitialMargin", 0.0)),
            "positions":            positions,
        }

    @retry_api_call(retries=3, delay=2.0, backoff=2.0)
    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        """All open orders, optionally filtered to one symbol. Uses
        GET /fapi/v1/openOrders (get_orders — safe with no symbol), not
        the single-order lookup endpoint."""
        kwargs = {"recvWindow": 5000}
        if symbol:
            kwargs["symbol"] = symbol
        try:
            with _TRADE_BREAKER:
                raw = self.trade_client.get_orders(**kwargs)
        except CircuitBreakerOpen as exc:
            logger.warning(f"get_open_orders skipped — trade circuit open: {exc}")
            raise
        except ClientError as exc:
            logger.error(f"get_open_orders error: {exc}")
            raise

        return [
            {
                "symbol":           o.get("symbol"),
                "order_id":         int(o.get("orderId", 0)),
                "client_order_id":  o.get("clientOrderId", ""),
                "side":             o.get("side"),
                "type":             o.get("type"),
                "status":           o.get("status"),
                "stop_price":       float(o.get("stopPrice", 0.0)),
                "orig_qty":         float(o.get("origQty", 0.0)),
                "executed_qty":     float(o.get("executedQty", 0.0)),
                "reduce_only":      bool(o.get("reduceOnly", False)),
            }
            for o in raw
        ]

    def get_server_time(self) -> int:
        """Thin wrapper around the market client's time endpoint — reuses
        the same client _sync_time_offset() already calls internally."""
        raw = self.market_client.time()
        return int(raw["serverTime"])
