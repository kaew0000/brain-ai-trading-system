"""data/local_order_book.py — V16 Phase 4C Track B, HFT-1: local order-book
reconstruction from a Binance USDT-M Futures REST depth snapshot + diff-depth
WebSocket updates.

Scope discipline (HFT-1 only — see docs Phase 4C Track B design review):
  This module ONLY reconstructs and validates order-book state. It does NOT
  compute depth_imbalance, CVD, microprice, or any scored/directional
  feature — that is HFT-2 (microstructure features) and HFT-3 (HFT Flow
  Score), both explicitly out of scope here. Keeping this module free of any
  scoring logic is intentional: it lets HFT-1 be reviewed, tested, and
  merged with zero possible effect on ConfidenceEngine/RiskEngine/execution,
  since nothing here is consumed by them yet.

Why a separate pure-Python, no-asyncio module:
  Deliberately kept free of any `asyncio`/`websockets` import so that every
  code path here is a plain synchronous function/method, testable with
  ordinary pytest (no pytest-asyncio dependency, matching the project's
  existing tests/ conventions — see tests/test_binance_provider_c1_additions.py).
  data/binance_ws_client.py (the async transport layer) is a thin wrapper
  that feeds parsed messages into this class; this class has no knowledge
  of sockets, reconnects, or the network at all.

Binance diff-depth sequencing (per Binance USDT-M Futures docs):
  1. Buffer depthUpdate events while fetching a REST snapshot (lastUpdateId=L).
  2. Drop any buffered event where `u` (final update ID) <= L.
  3. The first event applied must satisfy `U <= L+1 <= u` (U = first update ID
     in event, u = final update ID in event).
  4. Every subsequent event's `pu` (previous event's final update ID) must
     equal the last-applied event's `u`. This is the Futures-specific
     continuity check, and it is authoritative when `pu` is present in the
     payload. Unlike the SPOT stream (where `U` must equal the previous
     event's `u + 1` exactly), Futures diff events legitimately have `U`
     jump ahead of `prev_u + 1` with no update actually missed — Binance
     documents this explicitly and it is routine on real traffic. Checking
     `U == prev_u + 1` as the primary/only rule (this module's original
     design) misreads normal Futures behavior as a gap on nearly every
     diff, triggering constant false-positive resyncs. `U`-continuity is
     used only as a fallback for payloads that omit `pu` entirely. A real
     mismatch (via either check) means an update was actually missed — the
     local book is no longer provably correct and must be treated as
     invalid until a fresh REST snapshot resynchronizes it
     (BOOK_INVALID_UNTIL_RESYNC below).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class OrderBookError(Exception):
    """Raised for malformed depth-update payloads. Callers should catch this,
    log it, and treat the book as invalid — never let a malformed message
    silently corrupt reconstructed state."""


@dataclass
class DepthSnapshot:
    """A REST GET /fapi/v1/depth response, already parsed to floats."""
    last_update_id: int
    bids: list[tuple[float, float]]   # (price, qty), qty==0 rows dropped
    asks: list[tuple[float, float]]
    fetched_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class DepthDiff:
    """A single depthUpdate WebSocket message, already parsed to floats."""
    first_update_id: int   # "U"
    final_update_id: int   # "u"
    prev_final_update_id: int | None  # "pu" — present on futures streams;
                                       # None if the exchange payload omits it
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    event_time_ms: int


class LocalOrderBook:
    """Reconstructs one symbol's top-of-book state from a snapshot + a
    stream of diffs. Not thread-safe by itself — callers (the async WS
    client) are responsible for serializing access, e.g. by only ever
    calling into one instance from one asyncio task."""

    def __init__(self, symbol: str, max_levels: int = 50) -> None:
        self.symbol = symbol
        self.max_levels = max_levels
        self._bids: dict[float, float] = {}   # price -> qty
        self._asks: dict[float, float] = {}
        self._last_update_id: int | None = None
        self._synced = False
        self._last_applied_at_ms: int = 0
        self._awaiting_first_diff = False   # see apply_diff()'s docstring

    # ── Snapshot application ────────────────────────────────────────────

    def apply_snapshot(self, snap: DepthSnapshot) -> None:
        """Replace all local state with a fresh REST snapshot. Called at
        startup and any time sequence validation fails (resync)."""
        self._bids = {p: q for p, q in snap.bids if q > 0}
        self._asks = {p: q for p, q in snap.asks if q > 0}
        self._last_update_id = snap.last_update_id
        self._synced = True
        self._last_applied_at_ms = snap.fetched_at_ms
        self._awaiting_first_diff = True   # next apply_diff() uses the
                                            # straddle rule, not exact-U

    # ── Diff application ────────────────────────────────────────────────

    def can_apply(self, diff: DepthDiff) -> bool:
        """Per Binance's own sequencing rule: the first diff applied after
        a snapshot must straddle the snapshot's lastUpdateId. Diffs whose
        final_update_id is at or before the snapshot are stale and should
        be silently dropped by the caller (not an error, not a resync
        trigger — this is expected/normal during the sync handshake)."""
        if not self._synced or self._last_update_id is None:
            return False
        return diff.first_update_id <= self._last_update_id + 1 <= diff.final_update_id

    def is_stale(self, diff: DepthDiff) -> bool:
        """True if this diff is entirely behind the current snapshot and
        should be dropped without affecting sequence validity."""
        return self._last_update_id is not None and diff.final_update_id <= self._last_update_id

    def apply_diff(self, diff: DepthDiff) -> bool:
        """Apply one depthUpdate. Returns True if applied, False if the
        sequence is broken (caller must resync via a fresh REST snapshot —
        this method does NOT resync itself, it only detects the need).

        Sequence check has two modes, per Binance's own documented
        handshake (see this module's docstring):

        - First diff after a snapshot (`_awaiting_first_diff`): uses the
          STRADDLE rule (`U <= last_update_id+1 <= u`), NOT an exact-match
          check — the first diff that arrives after a snapshot is not
          guaranteed to start exactly at last_update_id+1, only to cover
          it. Requiring exact equality here was an earlier bug in this
          module: it would incorrectly treat every valid first-diff as a
          gap unless its U happened to land exactly on last_update_id+1,
          which is not what Binance's own spec requires or what real
          traffic reliably does.
        - Every subsequent diff: when `pu` is present, it is the
          AUTHORITATIVE continuity check — `pu` must equal the last
          applied diff's `u`. `U` is not required to equal `prev_u + 1` on
          Futures (it legitimately jumps ahead with no update missed; see
          module docstring), so `U`-continuity is used only as a fallback
          when a payload omits `pu`. This was this module's second bug:
          checking `U == prev_u + 1` as the primary rule (with `pu` only
          as a secondary corroborating check reached after the U-check
          already passed) meant real Futures traffic — where `U` jumps
          are normal — was misread as a gap on nearly every diff, forcing
          a REST resync that itself could never catch up before the next
          false gap. `pu`, when present, now fully replaces the `U`-based
          check rather than supplementing it.
        """
        if self._last_update_id is None or not self._synced:
            raise OrderBookError(
                f"apply_diff called before any snapshot applied for {self.symbol}"
            )

        if diff.final_update_id <= self._last_update_id:
            # Stale diff, already covered by current state — no-op, not a gap.
            return True

        if self._awaiting_first_diff:
            if not (diff.first_update_id <= self._last_update_id + 1 <= diff.final_update_id):
                # Doesn't straddle the snapshot — continuity from the
                # snapshot forward can't be established from this event.
                self._synced = False
                return False
        elif diff.prev_final_update_id is not None:
            # `pu` present -> authoritative Futures continuity check.
            # `U` is deliberately NOT also checked here: a legitimate
            # Futures event can have `U` far ahead of `prev_u + 1` with
            # zero updates missed, so requiring both would reintroduce
            # the same false-positive gap this fix removes.
            if diff.prev_final_update_id != self._last_update_id:
                self._synced = False
                return False
        else:
            # `pu` absent -> fall back to the stricter exact-U-continuity
            # rule, since it's the only sequencing signal this payload has.
            expected_first = self._last_update_id + 1
            if diff.first_update_id != expected_first:
                # Gap detected: we're missing update(s) between what we have
                # and what this diff starts from. The book can no longer be
                # trusted.
                self._synced = False
                return False

        for price, qty in diff.bids:
            if qty <= 0:
                self._bids.pop(price, None)
            else:
                self._bids[price] = qty
        for price, qty in diff.asks:
            if qty <= 0:
                self._asks.pop(price, None)
            else:
                self._asks[price] = qty

        self._last_update_id = diff.final_update_id
        self._last_applied_at_ms = diff.event_time_ms
        self._awaiting_first_diff = False
        return True

    # ── Validity ─────────────────────────────────────────────────────────

    @property
    def synced(self) -> bool:
        return self._synced

    def is_crossed(self) -> bool:
        """A crossed book (best bid >= best ask) should never happen on a
        correctly-reconstructed book. If it does, treat it as corrupted
        state — force a resync rather than trusting derived features
        computed from it (see design review §22 test case)."""
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is None or ba is None:
            return False
        return bb >= ba

    def is_valid(self, max_age_ms: int, now_ms: int | None = None) -> bool:
        """Combines every invalidity condition this class knows about into
        one check. Callers (the WS client's snapshot builder) should treat
        `book_valid=False` as "contribute nothing", per the design review's
        explicit requirement that stale/incomplete book state must never
        reach a live trading decision."""
        if not self._synced:
            return False
        if not self._bids or not self._asks:
            return False
        if self.is_crossed():
            return False
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        if now_ms - self._last_applied_at_ms > max_age_ms:
            return False
        return True

    # ── Read accessors ───────────────────────────────────────────────────

    def best_bid(self) -> float | None:
        return max(self._bids) if self._bids else None

    def best_ask(self) -> float | None:
        return min(self._asks) if self._asks else None

    def top_levels(self, n: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Returns (bids, asks) each sorted best-first, at most n levels."""
        bids = sorted(self._bids.items(), key=lambda kv: -kv[0])[:n]
        asks = sorted(self._asks.items(), key=lambda kv: kv[0])[:n]
        return bids, asks

    def last_update_id(self) -> int | None:
        return self._last_update_id

    def age_ms(self, now_ms: int | None = None) -> int:
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        if self._last_applied_at_ms == 0:
            return now_ms
        return max(0, now_ms - self._last_applied_at_ms)
