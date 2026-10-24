"""tools/benchmark_ensemble_dataset.py — V16 §77.

Measures how ``TradeJournalV2.get_ensemble_learning_dataset()`` scales with
the number of closed trades, so a future regression back to an N+1 read
pattern (§63 fixed one; see docs/architecture.md §63 / §77) is *measurable*
rather than anecdotal.

For each size it populates a throw-away journal DB (real ``save_signal`` /
``save_trade`` / ``save_agent_decision`` / ``update_trade_result`` — the same
public write API the live system uses), then reports:

* ``ms``             best-of-N wall time of one dataset read (``limit`` = size)
* ``sql_statements`` SQL statements executed by one read (traced via sqlite3's
                     trace callback). Must be CONSTANT across sizes: that is the
                     direct, hardware-independent signature of "no N+1".
* ``ms_per_trade``   ``ms / trades`` — roughly flat when scaling is linear.
* ``reference_ms``   (``--with-reference`` only) the old per-trade shape,
                     ``get_trade_attribution()`` once per row, for contrast.

Usage (from the repo root)::

    python -m tools.benchmark_ensemble_dataset
    python -m tools.benchmark_ensemble_dataset --sizes 100,1000,5000 --check
    python -m tools.benchmark_ensemble_dataset --json --with-reference

``--check`` exits 1 if the statement count varies with size, a read returns
the wrong row count, or per-trade cost at the largest size exceeds
``--max-per-trade-ratio`` x the smallest size's. Timing thresholds are
deliberately loose (machine noise); the statement-count check is exact.

Read-only against its own temp DB: never touches the live journal.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

DEFAULT_SIZES: tuple[int, ...] = (100, 1000, 5000)
DEFAULT_AGENTS: tuple[str, ...] = ("trend", "smc", "regime", "futures", "news")
DEFAULT_REPS = 3
DEFAULT_MAX_PER_TRADE_RATIO = 3.0
_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


@dataclass(frozen=True)
class BenchResult:
    trades: int
    rows: int
    ms: float
    sql_statements: int
    ms_per_trade: float
    reference_ms: float | None = None


def populate(journal, n: int, agents: tuple[str, ...] = DEFAULT_AGENTS) -> None:
    """Write ``n`` closed (WIN/LOSS) trades, each with a real signal row and
    one agent_decisions row per entry in ``agents``."""
    from analytics.trade_journal import TradeRecord

    for i in range(n):
        symbol = _SYMBOLS[i % len(_SYMBOLS)]
        rec = TradeRecord()
        rec.timestamp = f"2026-07-{1 + i % 28:02d}T{i % 24:02d}:00:00+00:00"
        rec.symbol = symbol
        rec.direction = "LONG" if i % 2 else "SHORT"
        rec.entry_price, rec.stop_loss, rec.take_profit, rec.quantity = 100.0, 99.0, 102.0, 1.0
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE", symbol=symbol)
        trade_id = journal.save_trade(rec, signal_id=sig_id, execution_lane="LIVE")
        for agent in agents:
            journal.save_agent_decision(
                agent=agent, decision="LONG", execution_lane="LIVE", symbol=symbol,
                score=0.5, weight=0.2, details={"i": i}, signal_id=sig_id,
            )
        win = bool(i % 3)
        journal.update_trade_result(trade_id, "WIN" if win else "LOSS", 101.0 if win else 99.0, 1.0 if win else -1.0)


def count_statements(fn: Callable[[], object]) -> tuple[object, int]:
    """Run ``fn`` and return ``(its result, number of SQL statements executed
    on any sqlite3 connection opened during the call)``. Self-contained
    save/restore of ``sqlite3.connect`` (a Connection's own methods are
    immutable C slots, so the module-level factory is wrapped instead)."""
    counter = {"n": 0}
    original = sqlite3.connect

    def counting_connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(lambda _sql: counter.__setitem__("n", counter["n"] + 1))
        return conn

    sqlite3.connect = counting_connect
    try:
        result = fn()
    finally:
        sqlite3.connect = original
    return result, counter["n"]


def best_of(fn: Callable[[], object], reps: int) -> float:
    """Best (minimum) wall time in seconds over ``reps`` runs."""
    best = float("inf")
    for _ in range(max(1, reps)):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def run_benchmark(
    sizes: tuple[int, ...] = DEFAULT_SIZES,
    agents: tuple[str, ...] = DEFAULT_AGENTS,
    reps: int = DEFAULT_REPS,
    with_reference: bool = False,
) -> list[BenchResult]:
    from journal.journal_v2 import TradeJournalV2

    results: list[BenchResult] = []
    for n in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            journal = TradeJournalV2(db_path=os.path.join(tmp, "bench.db"))
            populate(journal, n, agents)
            rows, statements = count_statements(lambda: journal.get_ensemble_learning_dataset(limit=n))
            seconds = best_of(lambda: journal.get_ensemble_learning_dataset(limit=n), reps)
            reference_ms = None
            if with_reference:
                ids = [r["trade_id"] for r in rows]  # type: ignore[union-attr]
                reference_ms = best_of(lambda: [journal.get_trade_attribution(t) for t in ids], 1) * 1000
            results.append(BenchResult(
                trades=n, rows=len(rows),  # type: ignore[arg-type]
                ms=round(seconds * 1000, 2), sql_statements=statements,
                ms_per_trade=round(seconds * 1000 / n, 4),
                reference_ms=None if reference_ms is None else round(reference_ms, 1),
            ))
    return results


def check(results: list[BenchResult], max_per_trade_ratio: float = DEFAULT_MAX_PER_TRADE_RATIO) -> list[str]:
    """Return a list of problems (empty == healthy scaling)."""
    problems: list[str] = []
    for r in results:
        if r.rows != r.trades:
            problems.append(f"{r.trades} trades: read returned {r.rows} rows")
    counts = {r.sql_statements for r in results}
    if len(counts) > 1:
        problems.append(
            "SQL statement count varies with size "
            f"({', '.join(f'{r.trades}->{r.sql_statements}' for r in results)}): N+1 read pattern"
        )
    if len(results) >= 2:
        small, large = results[0], results[-1]
        if small.ms_per_trade > 0 and large.ms_per_trade / small.ms_per_trade > max_per_trade_ratio:
            problems.append(
                f"per-trade cost grew {large.ms_per_trade / small.ms_per_trade:.1f}x from {small.trades} to "
                f"{large.trades} trades (limit {max_per_trade_ratio}x): super-linear scaling"
            )
    return problems


def format_table(results: list[BenchResult]) -> str:
    has_ref = any(r.reference_ms is not None for r in results)
    head = f"{'trades':>7} {'rows':>7} {'ms':>10} {'sql_stmts':>10} {'ms/trade':>10}" + (f" {'reference_ms':>13}" if has_ref else "")
    lines = [head]
    for r in results:
        line = f"{r.trades:>7} {r.rows:>7} {r.ms:>10.2f} {r.sql_statements:>10} {r.ms_per_trade:>10.4f}"
        if has_ref:
            line += f" {r.reference_ms:>13.1f}" if r.reference_ms is not None else f" {'-':>13}"
        lines.append(line)
    return "\n".join(lines)


def _parse_sizes(text: str) -> tuple[int, ...]:
    sizes = tuple(int(x) for x in text.split(",") if x.strip())
    if not sizes or any(s < 1 for s in sizes):
        raise argparse.ArgumentTypeError("--sizes needs positive integers, e.g. 100,1000,5000")
    return sizes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark get_ensemble_learning_dataset() read scaling (V16 §77).")
    p.add_argument("--sizes", type=_parse_sizes, default=DEFAULT_SIZES, help="comma-separated trade counts (default 100,1000,5000)")
    p.add_argument("--agents", type=int, default=len(DEFAULT_AGENTS), help="agent_decisions rows per trade")
    p.add_argument("--reps", type=int, default=DEFAULT_REPS, help="timing repetitions, best-of")
    p.add_argument("--with-reference", action="store_true", help="also time the old per-trade get_trade_attribution() loop (slow)")
    p.add_argument("--check", action="store_true", help="exit 1 if scaling is unhealthy")
    p.add_argument("--max-per-trade-ratio", type=float, default=DEFAULT_MAX_PER_TRADE_RATIO)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    if args.check and len(args.sizes) < 2:
        print("--check needs at least two --sizes", file=sys.stderr)
        return 2
    logging.disable(logging.INFO)  # journal logs a line per connection setup
    agents = tuple(f"agent{i}" for i in range(args.agents)) if args.agents != len(DEFAULT_AGENTS) else DEFAULT_AGENTS
    results = run_benchmark(args.sizes, agents, args.reps, args.with_reference)
    problems = check(results, args.max_per_trade_ratio) if args.check else []
    if args.json:
        print(json.dumps({"results": [asdict(r) for r in results], "problems": problems}, indent=2))
    else:
        print(format_table(results))
        for msg in problems:
            print(f"PROBLEM: {msg}")
        if args.check and not problems:
            print("OK: statement count constant, per-trade cost within limit")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
