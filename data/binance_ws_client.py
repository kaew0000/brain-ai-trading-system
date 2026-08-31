"""data/binance_ws_client.py — V16 Phase 4C Track B, HFT-1: Binance USDT-M
Futures WebSocket ingestion (bookTicker + diff-depth + aggTrade), per symbol.

Scope discipline (HFT-1 only — see the Phase 4C Track B design review):
  This module's job ends at producing a validated, in-memory snapshot per
  symbol (best bid/ask, reconstructed order-book top levels, a raw recent-
  trade buffer, and validity/connectivity state). It does NOT compute
  depth_imbalance, aggressive buy/sell volume, CVD, trade_intensity, or any
  HFT_FLOW_SCORE — those are HFT-2 and HFT-3, separate, not-yet-approved
  phases. It is also NOT wired into config/settings.py's HFT_WS_ENABLED
  consumer (api/app.py's lifespan()) doing anything beyond starting/
  stopping this client — no ConfidenceEngine, RiskEngine, or execution
  import appears anywhere in this file, by design, and that absence is
  meant to be mechanically verifiable (see design review §11/§23).

Architectural isolation (hard constraint, not a suggestion):
  This module must never import anything from `execution.*` or
  `risk.risk_engine`. It only ever writes into its own in-memory state,
  read via get_snapshot()/get_all_snapshots() by whatever the future
  decision-cycle integration (HFT-3/HFT-4) turns out to be — no callback
  in this file calls out to any order-placement code, directly or
  indirectly.

Supervision pattern:
  Mirrors api/app.py's `_supervised_broadcast()` — a self-restarting outer
  loop that catches CancelledError (re-raised, for clean shutdown) and logs
  + backs off on any other exception rather than letting one bad message
  or dropped connection kill ingestion permanently.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import threading
import time
from dataclasses import dataclass, field

import certifi
import websockets

from config.settings import settings
from data.local_order_book import DepthDiff, DepthSnapshot, LocalOrderBook, OrderBookError
from utils.logger import get_logger

logger = get_logger(__name__)


def _build_ssl_context() -> ssl.SSLContext:
    """Explicit certifi-backed TLS context for the WS connection.

    Bug-fix follow-up (2026-08-31 VPS incident): without an explicit
    `ssl=` argument, `websockets.connect()` falls back to
    `ssl.create_default_context()`, which on Windows validates against
    the OS's local Root CA store. Every REST call in this codebase goes
    through `binance-futures-connector` -> `requests`, which validates
    against the `certifi` package's bundled CA file instead -- a
    completely different, independently-updated trust chain. On a VPS
    where Windows' Automatic Root Certificate Update is disabled or
    can't reach the network, the OS store can be missing an intermediate
    CA that `certifi`'s bundle already has, so REST calls succeed while
    this WS connection fails with CERTIFICATE_VERIFY_FAILED on the exact
    same machine, in the exact same process, at the exact same time.
    Building the context from `certifi.where()` here makes both network
    paths use the same trust source, removing the OS-store dependency
    entirely rather than requiring a Windows-side fix on every VPS this
    project is deployed to.
    """
    return ssl.create_default_context(cafile=certifi.where())


@dataclass
class TradeEvent:
    """One parsed aggTrade event."""
    price: float
    qty: float
    is_buyer_maker: bool   # True => aggressor was the SELLER (per Binance's
                            # aggTrade semantics: `m`=true means the buyer is
                            # the market maker, i.e. a resting bid was hit by
                            # an incoming sell)
    trade_time_ms: int


@dataclass
class SymbolWSSnapshot:
    """Immutable-by-convention read of one symbol's current WS-derived
    state. Callers should treat this as a point-in-time copy, not a live
    view — get_snapshot() constructs a fresh one on every call rather than
    handing out internal mutable structures, so a caller holding onto one
    of these can't be affected by concurrent updates (see design review
    §16's "read once, reuse" requirement for exactly this reason)."""
    symbol: str
    best_bid: float | None
    best_ask: float | None
    bid_levels: list[tuple[float, float]]
    ask_levels: list[tuple[float, float]]
    recent_trades: list[TradeEvent]
    book_valid: bool
    sequence_valid: bool
    stream_connected: bool
    data_age_ms: int
    snapshot_taken_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class _SymbolState:
    """Internal per-symbol mutable state. Not exposed directly — callers
    only ever see SymbolWSSnapshot copies via get_snapshot()."""

    def __init__(self, symbol: str, max_levels: int, trade_buffer_seconds: int) -> None:
        self.symbol = symbol
        self.book = LocalOrderBook(symbol, max_levels=max_levels)
        self.trade_buffer_seconds = trade_buffer_seconds
        self.trades: list[TradeEvent] = []
        self.sequence_valid = False   # becomes True once a snapshot is
                                       # applied and the first straddling
                                       # diff is successfully applied
        self.stream_connected = False
        self.pending_diffs: list[DepthDiff] = []   # depthUpdate events that
                                                     # arrived while book.synced
                                                     # was False (initial sync
                                                     # or mid-resync), held so
                                                     # _resync_symbol() can
                                                     # replay them against the
                                                     # fresh snapshot instead of
                                                     # them being lost — see
                                                     # HFT_WS_MAX_PENDING_DIFFS_
                                                     # PER_SYMBOL's docstring
        self.lock = threading.Lock()   # protects reads from get_snapshot()
                                        # against the asyncio task's writes;
                                        # cheap since both sides hold it only
                                        # briefly (dict/list ops, no I/O)

    def prune_trades(self, now_ms: int) -> None:
        cutoff = now_ms - self.trade_buffer_seconds * 1000
        while self.trades and self.trades[0].trade_time_ms < cutoff:
            self.trades.pop(0)


class BinanceWSClient:
    """Multi-symbol Binance USDT-M Futures market-data WebSocket client.

    One instance manages one combined-stream connection covering all
    configured symbols (bookTicker + depth@<speed> + aggTrade per symbol),
    per Binance's documented combined-stream endpoint
    (`<base>/stream?streams=...`), rather than one connection per symbol —
    this matches data/binance_provider.py's own stated principle of
    avoiding "a redundant ... connection per symbol for no reason"
    (see get_market_data_for()'s docstring), applied here to the WS
    transport instead of the REST client.
    """

    def __init__(
        self,
        symbols: list[str],
        rest_snapshot_fn,
        *,
        max_levels: int = 50,
    ) -> None:
        """
        symbols: symbols to subscribe to — callers should pass
            config.settings.settings.symbol_list, not hardcode a list, per
            project convention (see settings.symbol_list's own docstring).
        rest_snapshot_fn: callable(symbol: str) -> dict, the raw Binance
            depth response shape (as returned by
            data.binance_provider.BinanceDataProvider.get_order_book_snapshot).
            Injected rather than importing BinanceDataProvider directly, so
            this module has exactly one reason to touch the network (the
            WS connection itself) and REST snapshot fetching stays owned by
            the existing provider class — this also makes the class
            trivially testable with a fake snapshot function, no network
            mocking required for that path.
        """
        if not symbols:
            raise ValueError("BinanceWSClient requires at least one symbol")
        self._symbols = list(symbols)
        self._rest_snapshot_fn = rest_snapshot_fn
        self._max_levels = max_levels
        self._states: dict[str, _SymbolState] = {
            s: _SymbolState(s, max_levels, settings.HFT_WS_TRADE_BUFFER_SECONDS)
            for s in self._symbols
        }
        self._resyncing: set[str] = set()   # in-flight guard so repeated
                                             # gaps on the same symbol don't
                                             # fire concurrent REST resyncs
        self._ssl_context = _build_ssl_context()   # built once, not per
                                                     # reconnect -- reading
                                                     # certifi's cacert.pem
                                                     # is disk I/O, no need
                                                     # to repeat it on every
                                                     # reconnect attempt

    # ── Public read API ─────────────────────────────────────────────────

    def get_snapshot(self, symbol: str) -> SymbolWSSnapshot:
        state = self._states.get(symbol)
        if state is None:
            raise KeyError(f"BinanceWSClient not configured for symbol {symbol!r}")
        with state.lock:
            now_ms = int(time.time() * 1000)
            book_valid = state.book.is_valid(settings.HFT_WS_DATA_AGE_LIMIT_MS, now_ms=now_ms)
            bids, asks = state.book.top_levels(self._max_levels)
            return SymbolWSSnapshot(
                symbol=symbol,
                best_bid=state.book.best_bid(),
                best_ask=state.book.best_ask(),
                bid_levels=bids,
                ask_levels=asks,
                recent_trades=list(state.trades),
                book_valid=book_valid,
                sequence_valid=state.sequence_valid,
                stream_connected=state.stream_connected,
                data_age_ms=state.book.age_ms(now_ms=now_ms),
            )

    def get_all_snapshots(self) -> dict[str, SymbolWSSnapshot]:
        return {s: self.get_snapshot(s) for s in self._symbols}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Self-restarting supervised loop — mirrors api/app.py's
        `_supervised_broadcast()` exactly. Intended to be started with
        `asyncio.create_task(client.run_forever())` from the same place
        (api/app.py's `lifespan()`) that already runs the dashboard
        broadcast loop, so no second asyncio event loop is created (see
        design review §12's discovery that uvicorn's event loop, running
        in main.py's api-server thread, is the existing place for exactly
        this kind of supervised background task)."""
        delay = settings.HFT_WS_RECONNECT_DELAY_SECONDS
        while True:
            try:
                await self._connect_and_listen()
                delay = settings.HFT_WS_RECONNECT_DELAY_SECONDS   # reset after a clean run
            except asyncio.CancelledError:
                for state in self._states.values():
                    state.stream_connected = False
                raise
            except Exception as exc:
                logger.error(
                    f"BinanceWSClient connection lost, reconnecting in {delay:.1f}s: {exc}",
                    exc_info=True,
                )
                for state in self._states.values():
                    state.stream_connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, settings.HFT_WS_RECONNECT_MAX_DELAY_SECONDS)

    async def _connect_and_listen(self) -> None:
        streams = []
        for s in self._symbols:
            sym_lower = s.lower()
            streams.append(f"{sym_lower}@bookTicker")
            streams.append(f"{sym_lower}@depth@{settings.HFT_WS_DEPTH_SPEED}")
            streams.append(f"{sym_lower}@aggTrade")
        url = f"{settings.hft_ws_url}?streams={'/'.join(streams)}"

        # Fetch fresh REST snapshots for every symbol before/around the
        # connection, per the Binance-documented handshake in
        # data/local_order_book.py's module docstring. Done per-connection
        # (not just at client construction) so a reconnect always resyncs
        # cleanly rather than trusting old snapshot state across a gap.
        for symbol, state in self._states.items():
            with state.lock:
                state.sequence_valid = False
        await self._resync_all()

        async with websockets.connect(
            url, ssl=self._ssl_context, ping_interval=20, ping_timeout=20
        ) as ws:
            for state in self._states.values():
                state.stream_connected = True
            logger.info(f"BinanceWSClient connected — symbols={self._symbols}")
            async for raw_message in ws:
                self._handle_message(raw_message)

    async def _resync_all(self) -> None:
        for symbol, state in self._states.items():
            await self._resync_symbol(symbol, state)

    async def _resync_symbol(self, symbol: str, state: _SymbolState) -> None:
        if symbol in self._resyncing:
            return
        self._resyncing.add(symbol)
        still_gapped = False
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, self._rest_snapshot_fn, symbol)
            snap = _parse_rest_snapshot(raw)
            with state.lock:
                state.book.apply_snapshot(snap)
                # sequence_valid stays False until the first diff that
                # straddles this snapshot is successfully applied — see
                # _handle_depth_diff below.
                replayed = self._replay_pending_diffs(state)
                still_gapped = not state.book.synced
            logger.debug(
                f"HFT-1 resync | {symbol} | lastUpdateId={snap.last_update_id} "
                f"replayed={replayed}"
                + (" (still gapped after replay, re-resyncing)" if still_gapped else "")
            )
        finally:
            self._resyncing.discard(symbol)
        if still_gapped:
            # The buffered diffs collected during this resync couldn't
            # bridge to the fresh snapshot's lastUpdateId (e.g. the
            # HFT_WS_MAX_PENDING_DIFFS_PER_SYMBOL cap was hit during an
            # unusually slow REST fetch, so the earliest buffered diff no
            # longer straddles). Try again immediately with a brand-new
            # snapshot rather than waiting for the next live diff, which
            # would just get buffered against a book already known to be
            # unsynced (see _handle_depth_diff's `if not state.book.synced`
            # branch below).
            asyncio.ensure_future(self._resync_symbol(symbol, state))

    def _replay_pending_diffs(self, state: _SymbolState) -> int:
        """Must be called with state.lock held, immediately after
        state.book.apply_snapshot(). Replays depthUpdate events buffered
        while this symbol's book was unsynced, per Binance's documented
        handshake (data/local_order_book.py's module docstring, steps
        1-4): buffer while the REST snapshot is in flight, drop anything
        entirely behind the snapshot, use the straddle rule for the first
        relevant one, then require exact chaining after that.

        Returns the number of buffered diffs actually applied. If a real
        gap remains even after replay (buffer overflow, or the feed
        itself skipped a sequence), state.book.synced is left False by
        LocalOrderBook.apply_diff() exactly as it would be for a live
        diff — the caller (_resync_symbol) checks for that and re-resyncs
        rather than this method special-casing it.
        """
        pending, state.pending_diffs = state.pending_diffs, []
        applied_count = 0
        for diff in pending:
            if state.book.is_stale(diff):
                continue   # covered by the new snapshot already
            if not state.book.synced:
                # A prior diff in this same batch already broke
                # continuity — stop; the remaining buffered diffs are
                # covered by whatever resync this triggers next.
                break
            if state.book.apply_diff(diff):
                applied_count += 1
                if not state.sequence_valid and state.book.synced:
                    # Mirrors _handle_depth_diff's live-diff path: the
                    # first replayed diff that successfully applies after
                    # a (re)snapshot is what actually proves continuity,
                    # not the snapshot alone.
                    state.sequence_valid = True
            else:
                state.sequence_valid = False
                break
        return applied_count

    # ── Message handling (sync, pure parsing + dispatch — no I/O here) ──

    def _handle_message(self, raw_message: str | bytes) -> None:
        try:
            envelope = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(f"BinanceWSClient dropped malformed frame: {exc}")
            return

        stream = envelope.get("stream", "")
        payload = envelope.get("data")
        if payload is None or "@" not in stream:
            logger.warning(f"BinanceWSClient dropped unexpected frame shape: stream={stream!r}")
            return

        symbol_lower, _, kind = stream.partition("@")
        symbol = symbol_lower.upper()
        state = self._states.get(symbol)
        if state is None:
            return   # stream for a symbol we didn't subscribe to (shouldn't
                     # happen; defensive only)

        try:
            if kind == "bookTicker":
                self._handle_book_ticker(state, payload)
            elif kind.startswith("depth"):
                self._handle_depth_diff(symbol, state, payload)
            elif kind == "aggTrade":
                self._handle_agg_trade(state, payload)
        except (OrderBookError, KeyError, ValueError, TypeError) as exc:
            logger.warning(f"BinanceWSClient dropped malformed {kind} payload for {symbol}: {exc}")

    def _handle_book_ticker(self, state: _SymbolState, payload: dict) -> None:
        # HFT-1 intentionally does not maintain a separate bookTicker-only
        # best-bid/ask field — best_bid()/best_ask() are read straight off
        # the reconstructed depth book (LocalOrderBook), which is the more
        # complete source of truth once synced. bookTicker is still
        # subscribed to (cheap, low-latency top-of-book confirmation) but
        # its main use is left to HFT-2 (e.g. as a staleness cross-check
        # against the depth-derived best bid/ask) rather than invented here
        # without a concrete consumer.
        return

    def _handle_depth_diff(self, symbol: str, state: _SymbolState, payload: dict) -> None:
        diff = _parse_depth_diff(payload)
        with state.lock:
            if not state.book.synced:
                # Waiting on the initial REST snapshot or a resync already
                # in flight — buffer rather than drop, so _resync_symbol()
                # can replay this once the fresh snapshot's lastUpdateId is
                # known (dropping here was the original HFT-1 bug: it made
                # the very next live diff responsible for straddling the
                # new snapshot, which reliably failed under load or a
                # rate-limit-slowed REST fetch and caused a resync loop).
                self._buffer_diff(state, diff)
                return
            if state.book.is_stale(diff):
                return   # covered by current snapshot already — normal, not a gap
            applied = state.book.apply_diff(diff)
            if not applied:
                logger.warning(
                    f"HFT-1 sequence gap detected for {symbol} — invalidating book, "
                    f"resync required"
                )
                state.sequence_valid = False
                # This diff itself wasn't applied — buffer it too, since it
                # may still be relevant once a fresh snapshot lands.
                self._buffer_diff(state, diff)
                asyncio.ensure_future(self._resync_symbol(symbol, state))
            elif not state.sequence_valid and state.book.synced:
                # First diff successfully applied after a (re)snapshot —
                # per Binance's own handshake this confirms the book is now
                # provably continuous, not just snapshot-fresh.
                state.sequence_valid = True

    def _buffer_diff(self, state: _SymbolState, diff: DepthDiff) -> None:
        """Append a depthUpdate to this symbol's pending-replay buffer.
        Caller must already hold state.lock (not re-acquired here —
        threading.Lock is non-reentrant)."""
        state.pending_diffs.append(diff)
        cap = settings.HFT_WS_MAX_PENDING_DIFFS_PER_SYMBOL
        if len(state.pending_diffs) > cap:
            dropped = state.pending_diffs.pop(0)
            logger.warning(
                f"HFT-1 pending-diff buffer overflow for {state.symbol} "
                f"(cap={cap}) — dropping oldest buffered diff "
                f"(first_update_id={dropped.first_update_id}); the REST "
                f"resync fetch may be abnormally slow (e.g. rate-limit "
                f"backoff)."
            )

    def _handle_agg_trade(self, state: _SymbolState, payload: dict) -> None:
        trade = TradeEvent(
            price=float(payload["p"]),
            qty=float(payload["q"]),
            is_buyer_maker=bool(payload["m"]),
            trade_time_ms=int(payload["T"]),
        )
        with state.lock:
            state.trades.append(trade)
            state.prune_trades(trade.trade_time_ms)


# ── Parsing helpers (pure functions, unit-testable without a client) ───────

def _parse_rest_snapshot(raw: dict) -> DepthSnapshot:
    return DepthSnapshot(
        last_update_id=int(raw["lastUpdateId"]),
        bids=[(float(p), float(q)) for p, q in raw.get("bids", [])],
        asks=[(float(p), float(q)) for p, q in raw.get("asks", [])],
    )


def _parse_depth_diff(payload: dict) -> DepthDiff:
    return DepthDiff(
        first_update_id=int(payload["U"]),
        final_update_id=int(payload["u"]),
        prev_final_update_id=int(payload["pu"]) if "pu" in payload else None,
        bids=[(float(p), float(q)) for p, q in payload.get("b", [])],
        asks=[(float(p), float(q)) for p, q in payload.get("a", [])],
        event_time_ms=int(payload.get("E", int(time.time() * 1000))),
    )
