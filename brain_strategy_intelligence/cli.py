"""Command line interface: `bsi <command>`. Everything runs offline; nothing contacts an exchange."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config, load_config
from .errors import BSIError
from .evaluation.data import CSVDataAdapter, SyntheticDataAdapter
from .evaluation.evaluator import StrategyEvaluator
from .integration.brain_bot_adapter import BrainBotAdapter
from .knowledge.loader import load_strategy_files
from .knowledge.retrieval import Retriever
from .learning.outcome_analyzer import OutcomeAnalyzer
from .ranking.ranker import StrategyRanker
from .reporting import reports as R
from .schemas import MarketSnapshot, TradeRecord, utcnow

DEFAULT_EXAMPLES = str(Path(__file__).resolve().parent / "strategies")


def _config(args: argparse.Namespace) -> Config:
    over: dict[str, Any] = {}
    if getattr(args, "data_dir", None):
        d = Path(args.data_dir)
        over = {
            "storage": {"sqlite_path": str(d / "knowledge.sqlite3")},
            "learning": {"db_path": str(d / "outcomes.sqlite3")},
            "reporting": {"output_dir": str(d / "reports")},
        }
    cfg = load_config(args.config, overrides=over)
    logging.basicConfig(level=cfg.logging.level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return cfg


def _candles(args: argparse.Namespace):
    if args.csv:
        a = CSVDataAdapter(args.csv)
        return a.get_candles(), a.label, args.symbol or "UNKNOWN", args.timeframe or "15m"
    a = SyntheticDataAdapter(n=args.bars, seed=args.seed)
    print("*** SYNTHETIC DATA - not market data; demonstrates the machinery only ***")
    return a.get_candles(), a.label, "SYNUSDT", "15m"


def cmd_init_kb(args, cfg: Config) -> int:
    adapter = BrainBotAdapter.from_config(cfg)
    strategies, errors = load_strategy_files(args.examples)
    added, skipped = adapter.repo.load_many(strategies)
    print(f"added {added} strategies; skipped {len(skipped)}; invalid files {len(errors)}")
    for line in [*skipped, *errors]:
        print("  -", line)
    return 0


def cmd_list(args, cfg: Config) -> int:
    for s in BrainBotAdapter.from_config(cfg).repo.list():
        print(f"{s.id:28} v{s.version} {s.category.value:28} {s.validation_status.value:12} engine={s.engine}")
    return 0


def cmd_search(args, cfg: Config) -> int:
    repo = BrainBotAdapter.from_config(cfg).repo
    for r in Retriever(repo).search(args.query, regime=args.regime, limit=args.limit):
        print(f"{r.score:.3f}  {r.strategy.id}  ({r.strategy.category.value})")
    return 0


def cmd_evaluate(args, cfg: Config) -> int:
    adapter = BrainBotAdapter.from_config(cfg)
    s = adapter.repo.get(args.strategy_id)
    if s is None:
        print(f"unknown strategy {args.strategy_id}", file=sys.stderr)
        return 2
    candles, label, symbol, tf = _candles(args)
    ev = StrategyEvaluator(cfg).evaluate(s, candles, symbol=symbol, timeframe=tf, data_label=label)
    adapter.repo.record_evaluation(ev)
    js, md = R.render_evaluation(ev)
    jp, mp = R.write_report(cfg.reporting.output_dir, f"evaluation_{s.id}_{ev.evaluation_id}", js, md)
    print(f"status={ev.status} reasons={ev.incomplete_reasons}\nreports: {jp}\n         {mp}")
    return 0


def cmd_rank(args, cfg: Config) -> int:
    adapter = BrainBotAdapter.from_config(cfg)
    candles, label, symbol, tf = _candles(args)
    evaluator, items = StrategyEvaluator(cfg), []
    for s in adapter.repo.list():
        ev = evaluator.evaluate(s, candles, symbol=symbol, timeframe=tf, data_label=label)
        adapter.repo.record_evaluation(ev)
        items.append((s, ev))
    rep = StrategyRanker(cfg.ranking).rank(items)
    js, md = R.render_ranking(rep)
    jp, mp = R.write_report(cfg.reporting.output_dir, "ranking_latest", js, md)
    for e in rep.entries:
        print(f"{e.rank or '-':>2} {e.strategy_id:28} {e.status:9} score={e.score}")
    print(f"reports: {jp}\n         {mp}")
    return 0


def cmd_research(args, cfg: Config) -> int:
    adapter = BrainBotAdapter.from_config(cfg)
    try:
        raw = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read snapshot: {exc}", file=sys.stderr)
        return 2
    rec = adapter.recommend(raw)
    js, md = R.render_recommendation(rec)
    jp, mp = R.write_report(cfg.reporting.output_dir, f"recommendation_{rec.symbol or 'none'}", js, md)
    print(md)
    print(f"reports: {jp}\n         {mp}")
    return 0 if rec.status == "OK" else 1


def cmd_report(args, cfg: Config) -> int:
    adapter = BrainBotAdapter.from_config(cfg)
    declared = {s.id: s.market_conditions for s in adapter.repo.list()}
    summary = OutcomeAnalyzer(cfg.learning).performance_report(adapter.recorder.verified_trades(), declared)
    js, md = R.render_learning(summary)
    jp, mp = R.write_report(cfg.reporting.output_dir, "learning_latest", js, md)
    print(md)
    print(f"reports: {jp}\n         {mp}")
    return 0


def cmd_demo(args, cfg: Config) -> int:
    summary = run_demo(cfg)
    print(json.dumps(summary, indent=2))
    return 0


def run_demo(cfg: Config) -> dict[str, Any]:
    """End-to-end offline demo on SYNTHETIC data. Returns a small summary dict."""
    adapter = BrainBotAdapter.from_config(cfg)
    strategies, errors = load_strategy_files(DEFAULT_EXAMPLES)
    added, _ = adapter.repo.load_many(strategies)
    a = SyntheticDataAdapter(n=3000, seed=7)
    candles = a.get_candles()
    ev = StrategyEvaluator(cfg)
    items = []
    for s in adapter.repo.list():
        r = ev.evaluate(s, candles, symbol="SYNUSDT", timeframe="15m", data_label=a.label)
        adapter.repo.record_evaluation(r)
        items.append((s, r))
    ranking = StrategyRanker(cfg.ranking).rank(items)
    jp, mp = R.write_report(cfg.reporting.output_dir, "demo_ranking", *R.render_ranking(ranking))
    snap = MarketSnapshot(
        symbol="SYNUSDT",
        timestamp=utcnow(),
        timeframe="15m",
        mark_price=100.0,
        regime="TREND",
        trend_bias="LONG_BIAS",
        risk={"trading_allowed": True, "max_leverage": 1, "risk_pct": 0.01},
        extras={"data_label": a.label},
    )
    rec = adapter.recommend(snap)
    R.write_report(cfg.reporting.output_dir, "demo_recommendation", *R.render_recommendation(rec))
    t0 = utcnow() - timedelta(days=1)
    recorded = []
    for i in range(3):  # SYNTHETIC trades, labelled by id prefix
        tr = TradeRecord(
            trade_id=f"SYNTHETIC-{i}",
            strategy_id="trend-sma-cross",
            strategy_version=1,
            symbol="SYNUSDT",
            regime="TREND",
            direction="LONG",
            status="CLOSED",
            verified=True,
            entry_time=t0,
            exit_time=t0 + timedelta(hours=i + 1),
            entry_price=100,
            exit_price=100 + (1 if i != 1 else -1),
            quantity=1,
            fees=0.1,
            funding=0.0,
            realized_pnl=(1 if i != 1 else -1),
        )
        recorded.append(adapter.record_closed_trade(tr).status)
    declared = {s.id: s.market_conditions for s in adapter.repo.list()}
    lj, lm = R.render_learning(
        OutcomeAnalyzer(cfg.learning).performance_report(adapter.recorder.verified_trades(), declared)
    )
    R.write_report(cfg.reporting.output_dir, "demo_learning", lj, lm)
    return {
        "data": "SYNTHETIC",
        "strategies_loaded": added,
        "invalid_files": len(errors),
        "ranked": [e.strategy_id for e in ranking.entries if e.status == "RANKED"],
        "unranked": [e.strategy_id for e in ranking.entries if e.status == "UNRANKED"],
        "recommendation_status": rec.status,
        "advisory_only": rec.advisory_only,
        "may_execute": rec.may_execute,
        "synthetic_trades_recorded": recorded,
        "reports": [str(jp.parent)],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m brain_strategy_intelligence", description="Brain Strategy Intelligence (research-only)")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="path to a YAML config (default: built-in defaults / $BSI_CONFIG)")
    p.add_argument("--data-dir", help="put databases and reports under this directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init-kb", help="load strategy JSON files into the knowledge base")
    s.add_argument("--examples", default=DEFAULT_EXAMPLES)
    s.set_defaults(fn=cmd_init_kb)
    sub.add_parser("list", help="list strategies").set_defaults(fn=cmd_list)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--regime")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(fn=cmd_search)
    for name, fn in (("evaluate", cmd_evaluate), ("rank", cmd_rank)):
        s = sub.add_parser(name)
        if name == "evaluate":
            s.add_argument("strategy_id")
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--csv", help="CSV with ts,open,high,low,close[,volume]")
        g.add_argument("--synthetic", action="store_true", help="use SYNTHETIC demo data")
        s.add_argument("--symbol")
        s.add_argument("--timeframe")
        s.add_argument("--bars", type=int, default=3000)
        s.add_argument("--seed", type=int, default=7)
        s.set_defaults(fn=fn)
    s = sub.add_parser("research", help="recommend strategies for a normalized snapshot JSON file")
    s.add_argument("--snapshot", required=True)
    s.set_defaults(fn=cmd_research)
    sub.add_parser("report", help="learning report from verified recorded trades").set_defaults(fn=cmd_report)
    sub.add_parser("demo", help="offline end-to-end demo on SYNTHETIC data").set_defaults(fn=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = _config(args)
        if not cfg.bundle.enabled:
            print("bundle is disabled (bundle.enabled=false / BSI_ENABLED=false); nothing to do")
            return 0
        return args.fn(args, cfg)
    except BSIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
