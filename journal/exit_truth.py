"""journal/exit_truth.py — V16 §97: the REAL outcome of a closed trade.

Why this exists (BUG R-01 in docs/V16_BUG_AUDIT_S96.md): main.monitor_open_trades()
used to decide WIN/LOSS from the mark price at the moment it noticed the
position was gone ("WIN if mark within 0.5 % of TP"), and priced the trade at
that mark. A TP hit followed by a pullback before the next 60 s check was
journaled as a LOSS; fees were ignored; trailing/manual exits were mislabeled.
That outcome feeds RiskEngine (consecutive-loss gate) and the learning pipeline.

What it does: reads the trade's actual fills from Binance (one best-effort
GET /fapi/v1/userTrades pair, no retries — same single-attempt rule as
journal/fee_backfill.py, because it runs in the single scheduler thread) and
derives exit price, realized PnL and commission from them.

Anchoring (never guesses by time window alone): the ENTRY order id captured at
open time (`trades.order_id`) gives the entry fills and their exact exchange
timestamp; the closing fills are the opposite-side fills AFTER that moment,
accumulated chronologically until the trade's quantity is closed. Fills of any
later trade on the same symbol are therefore never attributed to this one.

Returns None (caller falls back to the old mark-price heuristic) whenever the
fills cannot be attributed with confidence: no/invalid entry order id, API
error, closing quantity not fully reached (e.g. held >7 days — userTrades'
window — or a partial close), or malformed data. Never raises.
"""
from __future__ import annotations

from journal.fee_backfill import _sum_commission
from utils.logger import get_logger

logger = get_logger(__name__)

_QTY_TOLERANCE = 0.995   # closing qty must reach 99.5 % of the journaled qty


def _f(x) -> float:
    return float(x)


def resolve_realized_exit(client, symbol: str, direction: str,
                          entry_order_id, qty: float) -> dict | None:
    try:
        oid = int(entry_order_id)
    except (TypeError, ValueError):
        return None
    if not qty or qty <= 0 or direction not in ("LONG", "SHORT"):
        return None

    try:
        entry_fills = client.get_account_trades(symbol=symbol, orderId=oid) or []
        if not entry_fills:
            return None
        entry_time = min(int(t["time"]) for t in entry_fills)
        later = client.get_account_trades(symbol=symbol, startTime=entry_time, limit=1000) or []
    except Exception as exc:
        logger.warning(f"exit_truth: userTrades({symbol}, entry order {oid}) failed: {exc}")
        return None

    try:
        entry_ids = {t.get("id") for t in entry_fills}
        closing_side = "SELL" if direction == "LONG" else "BUY"
        candidates = sorted(
            (t for t in later
             if t.get("side") == closing_side
             and t.get("id") not in entry_ids
             and int(t["time"]) >= entry_time),
            key=lambda t: (int(t["time"]), int(t.get("id", 0))),
        )

        closing, closed_qty = [], 0.0
        for t in candidates:
            closing.append(t)
            closed_qty += _f(t["qty"])
            if closed_qty >= qty * _QTY_TOLERANCE:
                break
        if closed_qty < qty * _QTY_TOLERANCE:
            return None   # not fully closed / outside window → can't attribute

        notional = sum(_f(t["price"]) * _f(t["qty"]) for t in closing)
        exit_price = notional / closed_qty
        gross = sum(_f(t.get("realizedPnl", 0.0)) for t in closing)

        fees, asset = _sum_commission(list(entry_fills) + closing)
        pnl = gross - fees if fees is not None else gross
    except Exception as exc:
        logger.warning(f"exit_truth: malformed fills for {symbol}: {exc}")
        return None

    return {
        "result":      "WIN" if pnl > 0 else "LOSS",
        "exit_price":  round(exit_price, 8),
        "pnl":         round(pnl, 8),
        "gross_pnl":   round(gross, 8),
        "fees":        fees,
        "fee_asset":   asset,
        "closing_fills": len(closing),
    }
