"""
tests/_learning_helpers.py — shared synthetic-trade seeding helper for
tests/test_learning_*.py. Not a test module itself (doesn't match
pytest.ini's `test_*.py` collection pattern) — a plain importable
helper, same role tests/test_portfolio_signal_provider.py's
FakeDataProvider/_full_market_data play for other test files that
import them (e.g. tests/test_multi_symbol_ceo_integration.py).

Seeding real trades through journal.journal_v2.TradeJournalV2 +
journal.trade_attribution.record_trade_outcome() (rather than hand-
building raw dicts) means every learning/ test exercises the REAL
Phase 4B Step 2/3D write path, not a shape the tests merely assume
get_ensemble_learning_dataset() will hand back.
"""
from __future__ import annotations

import random

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2
from journal.trade_attribution import record_trade_outcome


def seed_trades(
    journal: TradeJournalV2,
    n: int,
    *,
    symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    regimes=("TREND_UP", "TREND_DOWN", "HIGH_VOL", "RANGE"),
    seed: int = 42,
    win_rate: float = 0.55,
    with_agents: bool = True,
) -> list[int]:
    """Seeds `n` closed trades with a deterministic RNG (same `seed` ->
    same dataset every run — required for any test asserting exact
    numbers). Returns the list of trade_ids created, in insertion
    order."""
    rng = random.Random(seed)
    trade_ids = []
    for i in range(n):
        sig_id = journal.save_signal({
            "action": "LONG", "direction": "LONG", "confidence": rng.uniform(20, 95),
        })
        if with_agents:
            journal.save_agent_decision("smc", "LONG", score=rng.uniform(30, 90), weight=0.25, signal_id=sig_id)
            journal.save_agent_decision(
                "regime", "LONG" if rng.random() < 0.7 else "SHORT",
                score=rng.uniform(30, 90), weight=0.15, signal_id=sig_id,
            )
            journal.save_agent_decision("ceo", "LONG", score=rng.uniform(30, 90), weight=1.0, signal_id=sig_id)

        rec = TradeRecord()
        day = (i % 28) + 1
        hour = (i * 7) % 24
        rec.timestamp = f"2026-0{1 + (i % 6)}-{day:02d}T{hour:02d}:00:00+00:00"
        rec.symbol = symbols[i % len(symbols)]
        rec.direction = "LONG"
        rec.regime = regimes[i % len(regimes)]
        rec.entry_price = 100.0
        rec.confidence = rng.uniform(20, 95)
        tid = journal.save_trade(rec, signal_id=sig_id)

        is_win = rng.random() < win_rate
        pnl = rng.uniform(5, 90) if is_win else -rng.uniform(5, 60)
        record_trade_outcome(
            journal, tid,
            result="WIN" if pnl > 0 else "LOSS",
            exit_price=100.0 + pnl, pnl=round(pnl, 4),
            execution_id=f"exec-{i}", order_id=str(10_000 + i),
            latency_seconds=rng.uniform(0.05, 0.6),
            slippage=rng.uniform(-2, 2),
            reason="SL_TP", source="trade_lifecycle",
            duration_seconds=rng.uniform(60, 7200),
        )
        trade_ids.append(tid)
    return trade_ids
