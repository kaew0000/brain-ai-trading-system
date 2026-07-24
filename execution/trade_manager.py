"""
Execution Layer: TradeManager

Handles full trade lifecycle using binance-futures-connector (UMFutures):
  - Set leverage + margin type
  - Calculate risk-adjusted position size (step-size aware)
  - Place MARKET entry
  - Place STOP_MARKET stop-loss (closePosition=True)
  - Place TAKE_PROFIT_MARKET take-profit (closePosition=True)
  - Cancel all open orders
  - Close position (reduceOnly market)

Adapter pattern: mirrors conor19w TradeManager interface
while using binance-futures-connector directly.
"""

from __future__ import annotations

import math
import time
import uuid

from binance.um_futures import UMFutures
from binance.error import ClientError

from config.settings import settings
from utils.logger import get_logger
from utils.retry import retry_api_call, is_retryable_client_error as _is_retryable_client_error
from system_health.circuit_breaker import get_breaker

# v16 P0-B: reuse the SAME named breaker data/binance_provider.py already
# uses for trade/account-related calls (get_breaker() is a thread-safe
# singleton registry keyed by name — this is the same CircuitBreaker
# instance, not a new one). Order placement and trade-account reads share
# Binance's trade API surface/rate-limit family, so pooling their failure
# tracking is the correct behavior: if the exchange's trade endpoints are
# unhealthy, every trade-surface caller should fast-fail together rather
# than each hammering it independently. See docs/architecture.md §5.
_TRADE_BREAKER = get_breaker("binance_trade", failure_threshold=5, recovery_timeout=60)

logger = get_logger(__name__)

# ── V16 FIX BUG-V16-EXEC-01: idempotent order placement ────────────────────
# Root cause: place_market_order / place_stop_loss / place_take_profit /
# close_position were wrapped in @retry_api_call(retries=5) but sent no
# newClientOrderId. If the exchange received and executed an order but the
# HTTP response was lost (timeout / connection reset — both are in
# retry.py's _RETRYABLE_EXCEPTIONS), the decorator retried by calling
# new_order() again with a brand-new, exchange-generated order id, which
# places a SECOND live order. For place_market_order specifically this
# means an ambiguous network failure at exactly the wrong moment can double
# (or up to 5x) real position size with no error raised.
# Fix: every order-placing call now carries a caller-supplied, stable
# newClientOrderId that is identical across all retry attempts of the same
# logical order. Binance rejects a second order with a client id that's
# already in use (error_code -2010) instead of creating a duplicate — that
# specific error is now treated as "the previous attempt likely succeeded"
# and resolved via query_order(origClientOrderId=...) instead of being
# reported as a plain failure.
_ORDER_ID_PREFIX = "bb"  # short prefix so IDs stay well under Binance's 36-char cap


def new_client_order_id(tag: str) -> str:
    """Generate a short, unique, Binance-safe newClientOrderId for one logical order intent."""
    return f"{_ORDER_ID_PREFIX}{tag}{int(time.time())}{uuid.uuid4().hex[:8]}"


def _is_duplicate_order_error(exc: ClientError) -> bool:
    """True if this ClientError means 'an order with this client id already exists'."""
    code = getattr(exc, "error_code", None)
    msg  = (getattr(exc, "error_message", "") or "").lower()
    return code == -2010 and "duplicate" in msg or code == -4015


class TradeManager:

    def __init__(self, data_provider, symbol: str | None = None) -> None:
        """
        Parameters
        ----------
        data_provider : BinanceDataProvider
            We reuse its authenticated UMFutures client (self.client below).
            Note we only ever read `.client` off it — never anything
            symbol-specific — so the SAME data_provider instance can safely
            be shared across multiple TradeManagers for different symbols
            (see execution/execution_coordinator.py, V16 Phase 1).
        symbol : str, optional
            V16 Multi-Symbol Foundation: explicit symbol for this manager
            instance. Defaults to settings.SYMBOL when omitted, which
            reproduces pre-V16 behavior exactly — every existing call site
            (`TradeManager(data_provider)`, no second arg) is unaffected.
        """
        self.client: UMFutures = data_provider.client
        self.symbol             = symbol or settings.SYMBOL
        logger.info(f"TradeManager ready | symbol={self.symbol}")

    # ── Exchange info helpers ─────────────────────────────────────────────

    @retry_api_call(retries=3, delay=2.0)
    def _symbol_info(self) -> dict:
        try:
            info = self.client.exchange_info()
            for s in info.get("symbols", []):
                if s["symbol"] == self.symbol:
                    return s
            return {}
        except ClientError as exc:
            logger.error(f"exchange_info error: {exc}")
            return {}

    def _lot_size(self) -> dict:
        """LOT_SIZE filter for the symbol."""
        for f in self._symbol_info().get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                return f
        return {"stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"}

    def _price_filter(self) -> dict:
        for f in self._symbol_info().get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                return f
        return {"tickSize": "0.10"}

    def _round_qty(self, qty: float) -> float:
        """Round down to valid lot stepSize."""
        lot   = self._lot_size()
        step  = float(lot.get("stepSize", "0.001"))
        min_q = float(lot.get("minQty",   "0.001"))
        if step == 0:
            step = 0.001
        prec  = max(0, int(round(-math.log10(step))))
        qty   = math.floor(qty / step) * step
        return max(round(qty, prec), min_q)

    def _round_price(self, price: float) -> str:
        """Round price to valid tick size and return as string."""
        tick  = float(self._price_filter().get("tickSize", "0.10"))
        if tick == 0:
            tick = 0.10
        prec  = max(0, int(round(-math.log10(tick))))
        rounded = math.floor(price / tick) * tick
        return f"{round(rounded, prec):.{prec}f}"

    # ── Account setup ─────────────────────────────────────────────────────

    @retry_api_call(retries=3, delay=2.0)
    def set_leverage(self, leverage: int = None) -> bool:
        lev = leverage or settings.LEVERAGE
        try:
            self.client.change_leverage(symbol=self.symbol, leverage=lev)
            logger.info(f"Leverage → {lev}×")
            return True
        except ClientError as exc:
            logger.error(f"set_leverage error: {exc}")
            return False

    @retry_api_call(retries=3, delay=2.0)
    def set_margin_type(self, margin_type: str = "ISOLATED") -> bool:
        try:
            self.client.change_margin_type(symbol=self.symbol, marginType=margin_type)
            logger.info(f"Margin type → {margin_type}")
            return True
        except ClientError as exc:
            if "No need to change margin type" in str(exc):
                return True
            logger.error(f"set_margin_type error: {exc}")
            return False

    # ── Position sizing ───────────────────────────────────────────────────

    def calculate_position_size(
        self,
        balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = None,
        leverage: float = None,
    ) -> float:
        """
        Risk-based position size (BTC).

        risk_amount = balance × risk_pct
        qty         = risk_amount / |entry − stop_loss|

        `leverage` (P1-B1): the margin cap below must reflect whatever
        leverage will actually be set on the exchange for this trade, not
        always the static settings.LEVERAGE — otherwise a caller passing a
        volatility-reduced leverage to set_leverage() but not here would
        get a margin cap computed against the *old* (higher) leverage,
        silently allowing a larger notional than the account can actually
        support at the leverage it's really running at. Defaults to
        settings.LEVERAGE when omitted, matching prior behavior exactly.
        """
        risk_pct    = risk_pct or settings.RISK_PER_TRADE_MAX
        leverage    = leverage or settings.LEVERAGE
        risk_amount = balance * risk_pct
        sl_dist     = abs(entry_price - stop_loss)
        if sl_dist == 0:
            logger.warning("SL distance = 0; using minimum qty")
            return self._round_qty(0.001)
        raw = risk_amount / sl_dist

        # ── Margin cap: never use more than MAX_MARGIN_USAGE of balance ───────
        max_margin_pct = getattr(settings, "MAX_MARGIN_USAGE", 0.20)
        max_notional   = balance * max_margin_pct * leverage
        max_by_margin  = max_notional / entry_price if entry_price > 0 else raw
        if raw > max_by_margin:
            logger.warning(
                f"PositionSize capped by margin rule ({max_margin_pct*100:.0f}% cap): "
                f"raw={raw:.6f} → capped={max_by_margin:.6f} BTC "
                f"(max_notional={max_notional:.2f} U)"
            )
            raw = max_by_margin

        qty = self._round_qty(raw)
        logger.info(
            f"PositionSize={qty} BTC | "
            f"risk={risk_amount:.2f}U sl_dist={sl_dist:.2f} entry={entry_price:.2f}"
        )
        return qty

    # ── Order placement ───────────────────────────────────────────────────

    @retry_api_call(retries=5, delay=3.0, breaker=_TRADE_BREAKER)
    def place_market_order(
        self, direction: str, quantity: float, client_order_id: str | None = None
    ) -> dict | None:
        """
        client_order_id should be generated ONCE by the caller (execute_trade)
        and passed in explicitly so every retry attempt of this same logical
        order reuses the identical id — that's what makes retries idempotent.
        A fallback id is generated here only for ad-hoc/direct callers; note
        that fallback would NOT be stable across retries of *this* call
        (each retry re-executes the function body), so production order
        placement must always go through execute_trade's explicit id.
        """
        side = "BUY" if direction == "LONG" else "SELL"
        cid  = client_order_id or new_client_order_id("ENTRY")
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
                newClientOrderId=cid,
            )
            logger.info(
                f"MARKET {side} {quantity} {self.symbol} "
                f"orderId={order.get('orderId')} clientOrderId={cid}"
            )
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(
                    f"market_order: duplicate clientOrderId={cid} — a previous "
                    f"attempt likely already placed this order; recovering "
                    f"state via query_order instead of retrying blind"
                )
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=cid)
                except ClientError as lookup_exc:
                    logger.error(f"market_order: query_order recovery failed: {lookup_exc}")
                    return None
            if not _is_retryable_client_error(exc):
                logger.error(f"market_order error (non-retryable): {exc}")
                return None
            # Retryable Binance error (rate limit / 5xx / timeout) — re-raise
            # so @retry_api_call actually retries it, instead of the old
            # behaviour of swallowing it here and silently returning None
            # (which made retries=5 dead code for every Binance-side error).
            logger.warning(f"market_order error (retryable, propagating): {exc}")
            raise

    @retry_api_call(retries=5, delay=3.0, breaker=_TRADE_BREAKER)
    def place_stop_loss(
        self, direction: str, quantity: float, stop_price: float,
        client_order_id: str | None = None,
    ) -> dict | None:
        """
        Place SL with three-tier fallback to handle exchange limitations:
          1. STOP_MARKET closePosition=True workingType=MARK_PRICE  (preferred)
          2. STOP_MARKET closePosition=True workingType=CONTRACT_PRICE
          3. STOP_MARKET reduceOnly=true with explicit quantity
        Error -4120 means the endpoint doesn't support this type — use
        the next tier automatically.

        Each tier gets its own stable, deterministic client order id
        (derived from client_order_id, or a freshly generated base for
        ad-hoc calls) so a retry of this whole function reuses the exact
        same three ids rather than minting new ones — see
        place_market_order's docstring for why that matters.
        """
        side = "SELL" if direction == "LONG" else "BUY"
        sp   = self._round_price(stop_price)
        qty  = str(self._round_qty(quantity))
        base_cid = client_order_id or new_client_order_id("SL")

        # Tier 1: preferred (MARK_PRICE trigger)
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=sp,
                closePosition="true",
                workingType="MARK_PRICE",
                newClientOrderId=base_cid,
            )
            logger.info(f"SL placed (T1) | {side} stopPrice={sp} MARK_PRICE clientOrderId={base_cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(f"SL T1 duplicate clientOrderId={base_cid} — recovering via query_order")
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=base_cid)
                except ClientError as lookup_exc:
                    logger.error(f"SL T1 query_order recovery failed: {lookup_exc}")
                    return None
            code = getattr(exc, "error_code", None) or getattr(exc, "status_code", None)
            if code not in (-4120, 400):
                if _is_retryable_client_error(exc):
                    logger.warning(f"SL order error (T1, retryable, propagating): {exc}")
                    raise
                logger.error(f"SL order error (T1): {exc}")
                return None
            logger.warning(f"SL T1 failed ({code}), trying T2 CONTRACT_PRICE …")

        # Tier 2: CONTRACT_PRICE trigger
        tier2_cid = f"{base_cid}-t2"
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=sp,
                closePosition="true",
                workingType="CONTRACT_PRICE",
                newClientOrderId=tier2_cid,
            )
            logger.info(f"SL placed (T2) | {side} stopPrice={sp} CONTRACT_PRICE clientOrderId={tier2_cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(f"SL T2 duplicate clientOrderId={tier2_cid} — recovering via query_order")
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=tier2_cid)
                except ClientError as lookup_exc:
                    logger.error(f"SL T2 query_order recovery failed: {lookup_exc}")
                    return None
            code = getattr(exc, "error_code", None) or getattr(exc, "status_code", None)
            if code not in (-4120, 400):
                if _is_retryable_client_error(exc):
                    logger.warning(f"SL order error (T2, retryable, propagating): {exc}")
                    raise
                logger.error(f"SL order error (T2): {exc}")
                return None
            logger.warning(f"SL T2 failed ({code}), trying T3 reduceOnly …")

        # Tier 3: explicit qty + reduceOnly (broadest compatibility)
        tier3_cid = f"{base_cid}-t3"
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=sp,
                quantity=qty,
                reduceOnly="true",
                workingType="CONTRACT_PRICE",
                newClientOrderId=tier3_cid,
            )
            logger.info(f"SL placed (T3) | {side} qty={qty} stopPrice={sp} reduceOnly clientOrderId={tier3_cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(f"SL T3 duplicate clientOrderId={tier3_cid} — recovering via query_order")
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=tier3_cid)
                except ClientError as lookup_exc:
                    logger.error(f"SL T3 query_order recovery failed: {lookup_exc}")
                    return None
            if _is_retryable_client_error(exc):
                logger.warning(f"SL order error (T3, retryable, propagating): {exc}")
                raise
            logger.error(f"SL order FAILED all tiers: {exc}")
            return None

    @retry_api_call(retries=5, delay=3.0, breaker=_TRADE_BREAKER)
    def place_take_profit(
        self, direction: str, quantity: float, tp_price: float,
        client_order_id: str | None = None,
    ) -> dict | None:
        """
        Place TP with three-tier fallback (mirrors place_stop_loss strategy).
          1. TAKE_PROFIT_MARKET closePosition=True workingType=MARK_PRICE
          2. TAKE_PROFIT_MARKET closePosition=True workingType=CONTRACT_PRICE
          3. TAKE_PROFIT_MARKET reduceOnly=true with explicit quantity

        See place_stop_loss for the per-tier idempotency-id contract.
        """
        side = "SELL" if direction == "LONG" else "BUY"
        tp   = self._round_price(tp_price)
        qty  = str(self._round_qty(quantity))
        base_cid = client_order_id or new_client_order_id("TP")

        # Tier 1
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp,
                closePosition="true",
                workingType="MARK_PRICE",
                newClientOrderId=base_cid,
            )
            logger.info(f"TP placed (T1) | {side} stopPrice={tp} MARK_PRICE clientOrderId={base_cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(f"TP T1 duplicate clientOrderId={base_cid} — recovering via query_order")
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=base_cid)
                except ClientError as lookup_exc:
                    logger.error(f"TP T1 query_order recovery failed: {lookup_exc}")
                    return None
            code = getattr(exc, "error_code", None) or getattr(exc, "status_code", None)
            if code not in (-4120, 400):
                if _is_retryable_client_error(exc):
                    logger.warning(f"TP order error (T1, retryable, propagating): {exc}")
                    raise
                logger.error(f"TP order error (T1): {exc}")
                return None
            logger.warning(f"TP T1 failed ({code}), trying T2 CONTRACT_PRICE …")

        # Tier 2
        tier2_cid = f"{base_cid}-t2"
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp,
                closePosition="true",
                workingType="CONTRACT_PRICE",
                newClientOrderId=tier2_cid,
            )
            logger.info(f"TP placed (T2) | {side} stopPrice={tp} CONTRACT_PRICE clientOrderId={tier2_cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(f"TP T2 duplicate clientOrderId={tier2_cid} — recovering via query_order")
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=tier2_cid)
                except ClientError as lookup_exc:
                    logger.error(f"TP T2 query_order recovery failed: {lookup_exc}")
                    return None
            code = getattr(exc, "error_code", None) or getattr(exc, "status_code", None)
            if code not in (-4120, 400):
                if _is_retryable_client_error(exc):
                    logger.warning(f"TP order error (T2, retryable, propagating): {exc}")
                    raise
                logger.error(f"TP order error (T2): {exc}")
                return None
            logger.warning(f"TP T2 failed ({code}), trying T3 reduceOnly …")

        # Tier 3
        tier3_cid = f"{base_cid}-t3"
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp,
                quantity=qty,
                reduceOnly="true",
                workingType="CONTRACT_PRICE",
                newClientOrderId=tier3_cid,
            )
            logger.info(f"TP placed (T3) | {side} qty={qty} stopPrice={tp} reduceOnly clientOrderId={tier3_cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(f"TP T3 duplicate clientOrderId={tier3_cid} — recovering via query_order")
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=tier3_cid)
                except ClientError as lookup_exc:
                    logger.error(f"TP T3 query_order recovery failed: {lookup_exc}")
                    return None
            if _is_retryable_client_error(exc):
                logger.warning(f"TP order error (T3, retryable, propagating): {exc}")
                raise
            logger.error(f"TP order FAILED all tiers: {exc}")
            return None

    @retry_api_call(retries=3, delay=2.0)
    def cancel_all_orders(self) -> bool:
        try:
            self.client.cancel_open_orders(symbol=self.symbol)
            logger.info(f"All orders cancelled for {self.symbol}")
            return True
        except ClientError as exc:
            logger.error(f"cancel_all_orders error: {exc}")
            return False

    @retry_api_call(retries=2, delay=2.0)
    def close_position(
        self, direction: str, quantity: float, client_order_id: str | None = None
    ) -> dict | None:
        """Market close with reduceOnly. See place_market_order for the
        idempotency contract — pass a stable client_order_id from the caller
        when this is part of a retried/critical path (e.g. SL-failed
        emergency close)."""
        side = "SELL" if direction == "LONG" else "BUY"
        cid  = client_order_id or new_client_order_id("CLOSE")
        try:
            order = self.client.new_order(
                symbol=self.symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
                reduceOnly="true",
                newClientOrderId=cid,
            )
            logger.info(f"Position closed | {side} {quantity} {self.symbol} clientOrderId={cid}")
            return order
        except ClientError as exc:
            if _is_duplicate_order_error(exc):
                logger.warning(
                    f"close_position: duplicate clientOrderId={cid} — recovering via query_order"
                )
                try:
                    return self.client.query_order(symbol=self.symbol, origClientOrderId=cid)
                except ClientError as lookup_exc:
                    logger.error(f"close_position: query_order recovery failed: {lookup_exc}")
                    return None
            if not _is_retryable_client_error(exc):
                logger.error(f"close_position error (non-retryable): {exc}")
                return None
            logger.warning(f"close_position error (retryable, propagating): {exc}")
            raise

    # ── Full trade execution sequence ─────────────────────────────────────

    def execute_trade(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        balance: float,
        risk_pct: float = None,
        leverage: float = None,
    ) -> dict:
        """
        Complete execution sequence:
          1. Set leverage + ISOLATED margin
          2. Cancel stale orders
          3. Calculate position size
          4. Market entry
          5. SL order
          6. TP order

        `leverage` (P1-B1, new, optional): overrides settings.LEVERAGE for
        both the exchange call and the position-size margin cap. Defaults
        to None, which reproduces prior behavior exactly (settings.LEVERAGE
        used throughout) — this parameter is purely additive.

        Pre-P1-B1, this method always called self.set_leverage(settings.LEVERAGE)
        even though set_leverage() itself already accepted an override — the
        override path existed but nothing ever used it. Fixed as part of
        wiring dynamic leverage through, since leaving it as dead code while
        adding a leverage param elsewhere in the same call chain would be
        actively misleading.

        Returns
        -------
        {
          success: bool,
          direction, entry_price, stop_loss, take_profit,
          quantity, entry_order, sl_order, tp_order,
          error: str | None
        }
        """
        result = {
            "success":     False,
            "direction":   direction,
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "quantity":    0.0,
            "entry_order": None,
            "sl_order":    None,
            "tp_order":    None,
            "error":       None,
        }

        try:
            self.set_leverage(leverage or settings.LEVERAGE)
            self.set_margin_type("ISOLATED")
            self.cancel_all_orders()

            qty = self.calculate_position_size(
                balance, entry_price, stop_loss, risk_pct, leverage
            )
            if qty <= 0:
                raise ValueError(f"Invalid qty={qty}")

            result["quantity"] = qty

            # V16 FIX BUG-V16-EXEC-01: one stable id per logical order,
            # generated here (outside the retried functions) so every
            # retry attempt of the same order reuses it — see
            # place_market_order's docstring.
            entry_cid = new_client_order_id("ENTRY")
            entry_ord = self.place_market_order(direction, qty, client_order_id=entry_cid)
            if not entry_ord:
                raise RuntimeError("Entry order rejected by exchange")
            result["entry_order"] = entry_ord

            # ── SL (CRITICAL — abort + close if fails) ────────────────────────
            sl_cid   = new_client_order_id("SL")
            sl_order = self.place_stop_loss(direction, qty, stop_loss, client_order_id=sl_cid)
            result["sl_order"] = sl_order
            if sl_order is None:
                logger.critical(
                    "SL placement FAILED after all fallbacks — "
                    "closing naked position immediately to protect account"
                )
                self.close_position(direction, qty, client_order_id=new_client_order_id("EMERGCLOSE"))
                raise RuntimeError(
                    "SL order rejected by exchange (all tiers exhausted); "
                    "naked position closed for safety"
                )

            # ── TP (non-critical — SL still protects) ────────────────────────
            tp_cid   = new_client_order_id("TP")
            tp_order = self.place_take_profit(direction, qty, take_profit, client_order_id=tp_cid)
            result["tp_order"] = tp_order
            if tp_order is None:
                logger.warning(
                    "TP placement failed — position is protected by SL only. "
                    "Monitor manually."
                )

            result["success"] = True
            logger.info(
                f"Trade EXECUTED | {direction} qty={qty} "
                f"entry={entry_price:.2f} SL={stop_loss:.2f} TP={take_profit:.2f}"
            )

        except Exception as exc:
            result["error"] = str(exc)
            logger.error(f"execute_trade failed: {exc}", exc_info=True)

        return result
