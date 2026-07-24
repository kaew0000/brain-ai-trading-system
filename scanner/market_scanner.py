"""
scanner/market_scanner.py — V16 Phase 2, Part 1: Market Scanner
=================================================================
Turns the bot from "watches one symbol" into "watches the whole USDT
perpetual futures universe" — read-only market intelligence, no trading
decisions made here (that's Part 2 Opportunity Ranker / Part 3 Portfolio
Manager, built on top of this).

Two-tier fetch design — READ THIS BEFORE CHANGING THE CADENCE
---------------------------------------------------------------
The brief asks to fetch price/volume/OI/funding/ATR/spread/liquidity for
every symbol every 20 seconds. Binance Futures has ~300 USDT perpetuals.
Price, funding, and book-ticker (spread) all have bulk endpoints that
return every symbol in ONE call — cheap, always fetched for the full
universe. ATR (needs klines) and open interest do NOT have bulk endpoints
on Binance Futures — they are strictly per-symbol. Calling both for ~300
symbols every 20s is ~600 extra weighted requests every cycle, which is
both a real rate-limit/ban risk and mostly wasted effort on symbols
nobody would ever trade (dead/illiquid pairs).

So: every cycle fetches cheap bulk data (price, 24h change, volume,
funding, spread) for the FULL universe, then does the expensive per-symbol
detail fetch (ATR, open interest) only for the top `SCANNER_DETAIL_TOP_N`
symbols by 24h quote volume (liquidity-first — matches what Part 2/3 will
actually care about ranking). Symbols that drop out of the top-N keep
their last-known detail values (not nulled every cycle) rather than
flickering between real and missing data.

Runs in its own daemon thread (same pattern as main.py's `_start_api_server`
— `threading.Thread(daemon=True)`) with its own internal sleep loop, so it
never blocks the main trading loop. Off by default — see
config/settings.py SCANNER_ENABLED for why.

Binance field-name note: `open_interest`/`markPrice` field names are
already relied on elsewhere in this codebase (data/binance_provider.py) —
verified against real usage, not guessed. The bulk-endpoint field names
below (`priceChangePercent`, `quoteVolume`, `lastFundingRate`, `bidPrice`,
`askPrice`) match Binance's documented, stable Futures REST API shape,
but this sandbox has no network path to api.binance.com to smoke-test
them live — parsing is defensive (`.get()` + type coercion, never raises
on an unexpected/missing field) and every test in this delivery uses
mocked responses shaped exactly like Binance's published API docs. Worth
one live smoke-test before this runs unattended in production.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import pandas as pd
import ta

from config.settings import settings
from utils.logger import get_logger
from utils.retry import retry_api_call
from system_health.circuit_breaker import get_breaker, CircuitBreakerOpen
from system_health.heartbeat import get_heartbeat
from database.db import ManagedConn

logger = get_logger(__name__)

_SCANNER_BREAKER = get_breaker("binance_scanner", failure_threshold=5, recovery_timeout=60)

_ATR_WINDOW = 14
_ATR_INTERVAL = "15m"
_ATR_KLINE_LIMIT = _ATR_WINDOW + 6  # small pad so the ATR indicator has warmup bars


@dataclass
class SymbolSnapshot:
    symbol: str
    price: float
    price_change_pct_24h: float
    quote_volume_24h: float
    funding_rate: float
    spread_pct: float
    open_interest: float | None   # None until this symbol gets a detail pass
    atr_pct: float | None         # None until this symbol gets a detail pass
    scanned_at: float                # unix epoch — bulk pass time
    detail_at: float | None       # unix epoch of last detail refresh, None if never

    def to_dict(self) -> dict:
        return asdict(self)


class MarketScanner:
    """
    Usage:
        scanner = MarketScanner(data_provider)
        scanner.start()             # background thread, returns immediately
        ...
        scanner.get_snapshots()     # {symbol: SymbolSnapshot}, thread-safe
        scanner.stop()

    `data_provider` is a BinanceDataProvider — the scanner only reads its
    `.market_client` (mainnet, public endpoints, no signing needed), the
    same "share the data_provider instance, read-only" pattern already
    established between ExecutionCoordinator and its TradeManagers.
    """

    def __init__(
        self,
        data_provider,
        interval_s: int | None = None,
        detail_top_n: int | None = None,
        min_quote_volume: float | None = None,
        universe_refresh_s: int | None = None,
    ) -> None:
        self._client = data_provider.market_client

        self._interval = interval_s if interval_s is not None else settings.SCANNER_INTERVAL_SECONDS
        self._detail_top_n = detail_top_n if detail_top_n is not None else settings.SCANNER_DETAIL_TOP_N
        self._min_quote_volume = (
            min_quote_volume if min_quote_volume is not None else settings.SCANNER_MIN_QUOTE_VOLUME
        )
        self._universe_refresh_s = (
            universe_refresh_s if universe_refresh_s is not None else settings.SCANNER_UNIVERSE_REFRESH_SECONDS
        )

        self._lock = threading.RLock()
        self._snapshots: dict[str, SymbolSnapshot] = {}
        self._universe: list[str] = []
        self._universe_refreshed_at: float = 0.0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cycle_count = 0
        self._last_error: str | None = None
        self._last_cycle_duration: float | None = None
        self._prune_every_n_cycles = max(1, int(3600 / max(self._interval, 1)))  # ~hourly

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("MarketScanner.start() called but already running — ignoring")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="market-scanner")
        self._thread.start()
        logger.info(
            f"MarketScanner started | interval={self._interval}s "
            f"detail_top_n={self._detail_top_n} min_quote_volume={self._min_quote_volume}"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("MarketScanner stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            t0 = time.time()
            try:
                self.run_cycle()
            except Exception as exc:
                self._last_error = str(exc)
                logger.error(f"MarketScanner cycle failed (keeping last-known-good snapshots): {exc}")
            self._last_cycle_duration = time.time() - t0
            sleep_for = max(0.0, self._interval - self._last_cycle_duration)
            self._stop_event.wait(sleep_for)

    # ── One scan cycle ──────────────────────────────────────────────────

    def run_cycle(self) -> dict[str, SymbolSnapshot]:
        """
        Runs one full scan cycle synchronously and returns the new
        snapshot map. Safe to call directly (e.g. from a test, or an
        on-demand "refresh now" API call) without starting the background
        thread — it does not touch `self._snapshots` unless the fetch
        succeeds, so a failure never wipes out good prior data.
        """
        t0 = time.time()
        self._maybe_refresh_universe()

        bulk = self._fetch_bulk()
        candidates = self._select_detail_candidates(bulk)
        details = self._fetch_details(candidates)
        merged = self._merge(bulk, details)

        with self._lock:
            self._snapshots = merged
        self._cycle_count += 1
        duration = time.time() - t0

        self._persist(merged, duration)
        get_heartbeat().beat(
            "market_scanner",
            meta={"symbols": len(merged), "detail": len(details), "cycle": self._cycle_count},
        )
        logger.info(
            f"MarketScanner cycle #{self._cycle_count} | universe={len(self._universe)} "
            f"bulk={len(bulk)} detail={len(details)} | {duration:.2f}s"
        )
        return merged

    # ── Universe ─────────────────────────────────────────────────────────

    def _maybe_refresh_universe(self) -> None:
        now = time.time()
        if self._universe and (now - self._universe_refreshed_at) < self._universe_refresh_s:
            return
        try:
            self._universe = self._fetch_universe()
            self._universe_refreshed_at = now
        except Exception as exc:
            if self._universe:
                logger.warning(f"Universe refresh failed, keeping {len(self._universe)} cached symbols: {exc}")
            else:
                raise  # no fallback on the very first call — nothing to scan

    @retry_api_call(retries=2, delay=1.0, backoff=2.0)
    def _fetch_universe(self) -> list[str]:
        """USDT-margined PERPETUAL contracts currently TRADING."""
        with _SCANNER_BREAKER:
            info = self._client.exchange_info()
        symbols = []
        for s in info.get("symbols", []):
            if (
                s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT"
            ):
                symbols.append(s["symbol"])
        if not symbols:
            raise ValueError("exchange_info returned zero eligible USDT perpetual symbols")
        return symbols

    # ── Bulk pass (full universe, 3 calls total) ────────────────────────

    @retry_api_call(retries=2, delay=1.0, backoff=2.0)
    def _fetch_bulk(self) -> dict[str, dict]:
        with _SCANNER_BREAKER:
            tickers = self._client.ticker_24hr_price_change()
            marks = self._client.mark_price()
            books = self._client.book_ticker()

        universe = set(self._universe)
        ticker_by_symbol = {t["symbol"]: t for t in tickers if t.get("symbol") in universe}
        mark_by_symbol = {m["symbol"]: m for m in marks if m.get("symbol") in universe}
        book_by_symbol = {b["symbol"]: b for b in books if b.get("symbol") in universe}

        out: dict[str, dict] = {}
        for symbol in self._universe:
            t = ticker_by_symbol.get(symbol, {})
            m = mark_by_symbol.get(symbol, {})
            b = book_by_symbol.get(symbol, {})

            mark_price = _safe_float(m.get("markPrice"))
            last_price = _safe_float(t.get("lastPrice"))
            price = mark_price if mark_price else last_price
            if not price:
                continue  # no usable price anywhere — skip this symbol this cycle

            bid = _safe_float(b.get("bidPrice"))
            ask = _safe_float(b.get("askPrice"))
            spread_pct = ((ask - bid) / price) if (bid and ask and price) else 0.0

            out[symbol] = {
                "price": price,
                "price_change_pct_24h": _safe_float(t.get("priceChangePercent")),
                "quote_volume_24h": _safe_float(t.get("quoteVolume")),
                "funding_rate": _safe_float(m.get("lastFundingRate")),
                "spread_pct": spread_pct,
            }
        return out

    # ── Detail pass (top-N candidates only) ─────────────────────────────

    def _select_detail_candidates(self, bulk: dict[str, dict]) -> list[str]:
        eligible = [
            (symbol, d["quote_volume_24h"])
            for symbol, d in bulk.items()
            if d["quote_volume_24h"] >= self._min_quote_volume
        ]
        eligible.sort(key=lambda pair: pair[1], reverse=True)
        return [symbol for symbol, _ in eligible[: self._detail_top_n]]

    def _fetch_details(self, symbols: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for symbol in symbols:
            try:
                out[symbol] = self._fetch_one_detail(symbol)
            except CircuitBreakerOpen:
                logger.debug("Scanner detail pass skipped — circuit open")
                break  # breaker's open for everyone this cycle, stop trying the rest
            except Exception as exc:
                logger.debug(f"MarketScanner detail fetch failed for {symbol}: {exc}")
        return out

    @retry_api_call(retries=1, delay=1.0, backoff=2.0)
    def _fetch_one_detail(self, symbol: str) -> dict:
        with _SCANNER_BREAKER:
            raw_klines = self._client.klines(symbol=symbol, interval=_ATR_INTERVAL, limit=_ATR_KLINE_LIMIT)
            oi_raw = self._client.open_interest(symbol=symbol)
        return {
            "atr_pct": _atr_pct_from_klines(raw_klines),
            "open_interest": _safe_float(oi_raw.get("openInterest")),
        }

    # ── Merge ────────────────────────────────────────────────────────────

    def _merge(self, bulk: dict[str, dict], details: dict[str, dict]) -> dict[str, SymbolSnapshot]:
        now = time.time()
        merged: dict[str, SymbolSnapshot] = {}
        for symbol, d in bulk.items():
            detail = details.get(symbol)
            prev = self._snapshots.get(symbol)
            merged[symbol] = SymbolSnapshot(
                symbol=symbol,
                price=d["price"],
                price_change_pct_24h=d["price_change_pct_24h"],
                quote_volume_24h=d["quote_volume_24h"],
                funding_rate=d["funding_rate"],
                spread_pct=d["spread_pct"],
                open_interest=(detail["open_interest"] if detail else (prev.open_interest if prev else None)),
                atr_pct=(detail["atr_pct"] if detail else (prev.atr_pct if prev else None)),
                scanned_at=now,
                detail_at=(now if detail else (prev.detail_at if prev else None)),
            )
        return merged

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self, merged: dict[str, SymbolSnapshot], duration: float) -> None:
        try:
            detail_count = sum(1 for s in merged.values() if s.detail_at is not None)
            payload = json.dumps({sym: s.to_dict() for sym, s in merged.items()})
            with ManagedConn() as conn:
                conn.execute(
                    "INSERT INTO scanner_snapshots "
                    "(timestamp, scanned_at, symbol_count, detail_count, cycle_duration_s, data) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        time.time(),
                        len(merged),
                        detail_count,
                        duration,
                        payload,
                    ),
                )
                conn.commit()
            if self._cycle_count % self._prune_every_n_cycles == 0:
                self._prune_old_snapshots()
        except Exception as exc:
            logger.error(f"MarketScanner persist failed (non-fatal, in-memory snapshot still updated): {exc}")

    def _prune_old_snapshots(self) -> None:
        try:
            cutoff = time.time() - settings.SCANNER_SNAPSHOT_RETENTION_HOURS * 3600
            with ManagedConn() as conn:
                conn.execute("DELETE FROM scanner_snapshots WHERE scanned_at < ?", (cutoff,))
                conn.commit()
        except Exception as exc:
            logger.debug(f"MarketScanner snapshot pruning failed (non-fatal): {exc}")

    # ── Public read API ──────────────────────────────────────────────────

    def get_snapshots(self) -> dict[str, SymbolSnapshot]:
        """Thread-safe read of the latest full snapshot map."""
        with self._lock:
            return dict(self._snapshots)

    def get_snapshot(self, symbol: str) -> SymbolSnapshot | None:
        with self._lock:
            return self._snapshots.get(symbol)

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "cycle_count": self._cycle_count,
            "universe_size": len(self._universe),
            "snapshot_count": len(self._snapshots),
            "last_cycle_duration_s": self._last_cycle_duration,
            "last_error": self._last_error,
            "interval_s": self._interval,
            "detail_top_n": self._detail_top_n,
        }


# ── Module-level helpers ────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _atr_pct_from_klines(raw_klines: list) -> float | None:
    """
    ATR as a percentage of price, same definition RegimeEngine already
    uses elsewhere in this codebase (ta.volatility.AverageTrueRange,
    atr_normalized = atr / close) — not a new metric, reusing the
    established one for consistency.
    """
    if not raw_klines or len(raw_klines) < 2:
        return None
    try:
        df = pd.DataFrame(
            raw_klines,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "count",
                "taker_buy_vol", "taker_buy_quote_vol", "ignore",
            ],
        )
        for col in ("high", "low", "close"):
            df[col] = df[col].astype(float)
        window = min(_ATR_WINDOW, len(df) - 1)
        if window < 2:
            return None
        atr_ind = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=window)
        atr = atr_ind.average_true_range().iloc[-1]
        price = float(df["close"].iloc[-1])
        if not price or pd.isna(atr):
            return None
        return float(atr / price)
    except Exception as exc:
        logger.debug(f"ATR computation failed: {exc}")
        return None
