"""
Commission/Fee Backfill — background reconciliation job.

Root cause this closes (see docs/architecture.md's Fee Capture section,
added alongside this module): Binance Futures market-order responses
never include commission, so `fees` has been a recognised-but-never-
populated field on execution/execution_orchestrator.py's
open_confirmed()/exit_confirmed() calls since Phase 4B Step 2
(architecture.md §29) — every trade's `fees` has always been None.

Design: background-only, read-only against the exchange, single write
path (journal.save_execution_attribution(), the same merge-only method
every other execution-attribution field already uses). Deliberately
does NOT touch execution/execution_orchestrator.py, execution/
trade_manager.py, or main.py's live open/close code paths at all — this
runs entirely after the fact, on a schedule, exactly like
system_health/reconciliation.py's position reconciliation. Chosen over
fetching fees synchronously right after each fill because (a) it adds
zero latency/failure-risk to the live order path, and (b) one call site
(main.py's classic-loop TP/SL exit detection) never has a close orderId
to fetch against in the first place — see the entry/exit split below.

Entry vs. exit fees — a real, permanent limitation, not a bug:
  - Entry fee is recoverable for every trade: `trades.order_id` (the
    entry order's Binance orderId) is always captured at open time by
    analytics/trade_journal.py's TradeRecord.from_decision().
  - Exit fee is only recoverable when a close orderId was captured,
    which is only true for execution/execution_orchestrator.py's
    replacement-close path (extra_data.attribution.order_id). main.py's
    classic single-symbol loop close (~line 1609) is a mark-price
    heuristic detecting a position Binance already closed server-side
    (via its own resting TP/SL order) — no closing orderId is ever
    captured for it anywhere in this codebase, so exit fees for that
    path are permanently unrecoverable without a design change to how
    closes are detected. This module does not guess: it fetches exit
    fees only where a close orderId exists, and never fuzzy-matches by
    symbol+time window (same "documented gap over fabricated inference"
    principle recovery_engine.py and the bundle_history.json Phase 2E
    record already follow elsewhere in this codebase).

Runs in the same single scheduler thread as every other schedule.every()
job in main.py (see main.py's `while _RUNNING: schedule.run_pending()`)
— so, same as run_position_reconciliation() and every other scheduled
job, a slow or hanging call here would delay the next due job. For that
reason this module makes at most ONE attempt per Binance API call (no
retry_api_call() exponential backoff, which can sleep up to 60s per
attempt) and bounds total candidates per run via
settings.FEE_BACKFILL_MAX_TRADES_PER_RUN — a single bad call costs at
most one HTTP timeout, never a multi-minute stall.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _sum_commission(user_trades: list[dict]) -> tuple[float | None, str | None]:
    """Sum `commission` across fills for one order.

    Returns (total, asset) when every fill shares one commissionAsset
    (the common case — BNB-fee-discount accounts aside, a single order
    is filled in a single commission asset). Returns (None, None) on a
    mixed-asset order rather than silently summing across assets (that
    would misrepresent the total as a single currency) — mixed-asset
    orders are rare enough that skipping them and leaving fees_entry/
    fees_exit unset (retried next run) is preferable to a wrong number.
    """
    if not user_trades:
        return None, None
    assets = {t.get("commissionAsset") for t in user_trades}
    if len(assets) != 1:
        logger.warning(f"fee_backfill: mixed commissionAsset {assets}, skipping order")
        return None, None
    try:
        total = sum(float(t["commission"]) for t in user_trades)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning(f"fee_backfill: malformed commission field: {exc}")
        return None, None
    return round(total, 8), assets.pop()


def _fetch_order_commission(client, symbol: str, order_id: str) -> tuple[float | None, str | None]:
    """One best-effort GET /fapi/v1/userTrades call — no retry, never
    raises. `client` is the raw UMFutures instance (TradeManager.client /
    BinanceDataProvider.client)."""
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return None, None
    try:
        trades = client.get_account_trades(symbol=symbol, orderId=oid)
    except Exception as exc:
        logger.warning(f"fee_backfill: get_account_trades({symbol}, orderId={oid}) failed: {exc}")
        return None, None
    return _sum_commission(trades or [])


def backfill_commission_fees(journal, client) -> dict:
    """Entry point for the scheduled job (see main.py's
    run_fee_backfill_job() wrapper). Returns a summary dict for
    logging — never raises.

    `journal`: journal.journal_v2.TradeJournalV2 instance.
    `client`: raw UMFutures instance (e.g. components["data_provider"].client).
    """
    summary = {"candidates": 0, "entry_filled": 0, "exit_filled": 0, "errors": 0}
    if not settings.FEE_BACKFILL_ENABLED:
        return summary
    if journal is None or client is None:
        logger.warning("fee_backfill: journal or client unavailable, skipping run")
        return summary

    since = (
        datetime.now(timezone.utc) - timedelta(hours=settings.FEE_BACKFILL_LOOKBACK_HOURS)
    ).isoformat()

    try:
        candidates = journal.get_trades_missing_fees(
            since_iso=since, limit=settings.FEE_BACKFILL_MAX_TRADES_PER_RUN
        )
    except Exception as exc:
        logger.error(f"fee_backfill: get_trades_missing_fees error: {exc}")
        return summary

    summary["candidates"] = len(candidates)

    for trade in candidates:
        fields: dict = {}

        entry_fee, entry_asset = _fetch_order_commission(client, trade["symbol"], trade["order_id"])
        if entry_fee is not None:
            fields["fees_entry"] = entry_fee
            fields["fees_entry_asset"] = entry_asset
            summary["entry_filled"] += 1

        # Exit fee — only when a close orderId was actually captured
        # (see module docstring); never fabricated for the classic-loop
        # heuristic-close path.
        if trade.get("close_order_id") and trade.get("fees_exit") is None:
            exit_fee, exit_asset = _fetch_order_commission(
                client, trade["symbol"], trade["close_order_id"]
            )
            if exit_fee is not None:
                fields["fees_exit"] = exit_fee
                fields["fees_exit_asset"] = exit_asset
                summary["exit_filled"] += 1

        if not fields:
            continue

        # Roll up a combined `fees` total only when every known leg is in
        # the same asset — otherwise leave `fees` unset rather than sum
        # across currencies (fees_entry/fees_entry_asset and fees_exit/
        # fees_exit_asset remain available individually either way).
        known_amounts = [v for k, v in fields.items() if k in ("fees_entry", "fees_exit")]
        known_assets = {fields[k] for k in ("fees_entry_asset", "fees_exit_asset") if k in fields}
        if known_amounts and len(known_assets) <= 1:
            fields["fees"] = round(sum(known_amounts), 8)

        try:
            ok = journal.save_execution_attribution(trade["id"], **fields)
            if not ok:
                summary["errors"] += 1
        except Exception as exc:
            logger.error(f"fee_backfill: save_execution_attribution(#{trade['id']}) error: {exc}")
            summary["errors"] += 1

    return summary
