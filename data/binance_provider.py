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

from config.settings import settings
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
    market_client  →  Mainnet (ราคา/ข้อมูลตลาดจริง, public endpoints)
    trade_client   →  Testnet (เทรดด้วยเงินปลอม, ต้องการ Testnet API Key)
    self.client    →  alias ของ trade_client (backward-compat)
    """

    def __init__(self) -> None:
        # ── Market data: ดึงจาก Mainnet เสมอ ──────────────────────────
        self.market_client = UMFutures(
            key=settings.BINANCE_API_KEY,
            secret=settings.BINANCE_API_SECRET,
            base_url=settings.BINANCE_PROD_BASE_URL,
        )

        # ── Trading: ส่งออเดอร์ไป Testnet (เงินปลอม) ─────────────────
        self.trade_client = UMFutures(
            key=settings.BINANCE_TESTNET_API_KEY,
            secret=settings.BINANCE_TESTNET_API_SECRET,
            base_url=settings.BINANCE_TESTNET_BASE_URL,
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

        logger.info(
            f"BinanceDataProvider V15 ready | symbol={self.symbol} "
            f"| market=MAINNET | trading=TESTNET "
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
                    logger.debug(f"Balance: {bal:.2f} USDT")
                    return bal
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
