"""Machine-readable JSON + human-readable Markdown reports. Everything is secret-redacted before it is written."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from ..schemas import EvaluationResult, RankingReport, Recommendation, ResearchReport
from ..security import redact, redact_obj


def _fmt(x: Any, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def _banner(label: str) -> list[str]:
    return (
        ["> **SYNTHETIC DATA - machinery demonstration only; says nothing about real markets.**", ""]
        if "SYNTHETIC" in label.upper()
        else []
    )


def render_evaluation(ev: EvaluationResult) -> tuple[str, str]:
    js = json.dumps(redact_obj(ev.model_dump(mode="json")), indent=2)
    md = [
        f"# Evaluation {ev.strategy_id} v{ev.strategy_version}",
        "",
        *_banner(ev.data_label),
        f"- Evaluation id: `{ev.evaluation_id}`",
        f"- Data: **{ev.data_label}** ({ev.symbol} {ev.timeframe})",
        f"- Status: **{ev.status}**",
    ]
    if ev.incomplete_reasons:
        md += ["", "## Why incomplete", *[f"- {r}" for r in ev.incomplete_reasons]]
    for title, m in (("In-sample", ev.in_sample), ("Validation", ev.validation), ("Out-of-sample", ev.out_of_sample)):
        if m:
            md += [
                "",
                f"## {title}",
                f"- Net PnL {_fmt(m.net_pnl)} | return {_fmt(m.return_pct)}% | max DD {_fmt(m.max_drawdown_pct)}%",
                f"- Trades {m.trade_count} | win rate {_fmt(m.win_rate)} | profit factor {_fmt(m.profit_factor)} | expectancy {_fmt(m.expectancy)}",
                f"- Avg win {_fmt(m.avg_win)} | avg loss {_fmt(m.avg_loss)} | payoff {_fmt(m.payoff_ratio)}",
                f"- Exposure {_fmt(m.exposure)} | turnover {_fmt(m.turnover)}x | benchmark buy&hold {_fmt(m.benchmark_return_pct)}%",
                f"- Costs: fees {_fmt(m.fees_paid)}, slippage {_fmt(m.slippage_cost)}, funding {_fmt(m.funding_paid)}",
            ]
    if ev.walk_forward:
        w = ev.walk_forward
        md += [
            "",
            "## Walk-forward",
            f"- Windows {len(w.windows)} | profitable fraction {_fmt(w.profitable_fraction)} | "
            f"total test PnL {_fmt(w.total_test_net_pnl)} | test trades {w.total_test_trades}",
        ]
    if ev.sensitivity:
        s = ev.sensitivity
        md += [
            "",
            "## Parameter sensitivity",
            f"- Neighbours {len(s.neighbours)} | profitable fraction {_fmt(s.positive_neighbour_fraction)} | "
            f"max relative change {_fmt(s.max_relative_change)}",
        ]
    if ev.warnings:
        md += ["", "## Warnings", *[f"- {x}" for x in ev.warnings]]
    md += ["", "## Assumptions", *[f"- {a}" for a in ev.assumptions]]
    return js, redact("\n".join(md) + "\n")


def render_ranking(rep: RankingReport) -> tuple[str, str]:
    js = json.dumps(redact_obj(rep.model_dump(mode="json")), indent=2)
    md = ["# Strategy ranking", "", "Weights: " + ", ".join(f"{k}={v}" for k, v in rep.weights.items()), ""]
    if any("SYNTHETIC" in e.data_label.upper() for e in rep.entries):
        md += _banner("SYNTHETIC")
    for e in rep.entries:
        head = (
            f"{e.rank}. **{e.strategy_id} v{e.strategy_version}** - score {_fmt(e.score, 3)}"
            if e.status == "RANKED"
            else f"- (unranked) **{e.strategy_id} v{e.strategy_version}**"
        )
        md += [head, f"   - validation status: {e.validation_status.value}; data: {e.data_label}"]
        if e.breakdown:
            md.append("   - components: " + ", ".join(f"{k}={_fmt(v, 2)}" for k, v in e.breakdown.items()))
        md += [f"   - {r}" for r in e.reasons] + [f"   - limitation: {x}" for x in e.limitations]
    return js, redact("\n".join(md) + "\n")


def render_research(rep: ResearchReport) -> tuple[str, str]:
    js = json.dumps(redact_obj(rep.model_dump(mode="json")), indent=2)
    md = [
        f"# Research report {rep.symbol}",
        "",
        f"- Mode: **{rep.mode}** (provider: {rep.provider})",
        f"- Missing data: {rep.missing_data or 'none'}",
        f"- Uncertainty: {rep.uncertainty or 'n/a'}",
        "",
    ]
    for i in rep.items:
        md += [
            f"## {i.strategy_id} (regime fit {i.regime_fit:.2f}, backtest recommended: {i.recommend_backtest})",
            *[f"- supports: {x}" for x in i.supporting_evidence],
            *[f"- contradicts: {x}" for x in i.contradicting_evidence],
            *[f"- invalidated if: {x}" for x in i.invalidation_conditions],
            "",
        ]
    if rep.warnings:
        md += ["## Warnings", *[f"- {w}" for w in rep.warnings]]
    return js, redact("\n".join(md) + "\n")


def render_recommendation(rec: Recommendation) -> tuple[str, str]:
    js = json.dumps(redact_obj(rec.model_dump(mode="json")), indent=2)
    md = [
        f"# Recommendation: {rec.status}",
        "",
        "_Advisory only. This output cannot place orders._",
        "",
        f"- Symbol: {rec.symbol}",
        f"- Research mode: {rec.research_mode}",
        f"- Config fingerprint: `{rec.config_fingerprint}`",
    ]
    for c in rec.candidates:
        md.append(
            f"- {c.strategy_id} v{c.strategy_version}: status={c.validation_status.value}, eval={c.evaluation_status}, "
            f"rank={c.rank}, fit={_fmt(c.regime_fit)}, backtest_recommended={c.recommend_backtest}"
        )
    md += [f"- WARNING: {w}" for w in rec.warnings]
    return js, redact("\n".join(md) + "\n")


def render_learning(summary: dict[str, Any]) -> tuple[str, str]:
    js = json.dumps(redact_obj(summary), indent=2, default=str)
    md = [
        "# Trade outcome learning report",
        "",
        f"- Verified closed trades: {summary['verified_trades']}",
        f"- Excluded (unverified/open): {summary['excluded_unverified_or_open']}",
        f"- {summary['note']}",
        "",
    ]
    for r in summary["strategies"]:
        md += [
            f"## {r['strategy_id']} v{r['version']}",
            f"- trades {r['trades']} | win rate {_fmt(r['win_rate'])} | "
            f"net PnL {_fmt(r['net_pnl'])} | expectancy {_fmt(r['expectancy'])}",
            f"- failure classes: {r['failure_classes'] or 'none'}",
        ]
        if r["low_sample"]:
            md.append("- LOW SAMPLE: conclusions are not statistically reliable")
        md.append("")
    return js, redact("\n".join(md) + "\n")


_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


def write_report(output_dir: str | Path, basename: str, json_text: str, md_text: str) -> tuple[Path, Path]:
    """Atomic write (temp file + replace) of <basename>.json and <basename>.md. The name is sanitised."""
    d = Path(output_dir)
    d.mkdir(parents=True, exist_ok=True)
    base = _SAFE.sub("_", basename).replace("..", "_").lstrip(".")[:100] or "report"
    paths = []
    for ext, text in (("json", json_text), ("md", md_text)):
        target = d / f"{base}.{ext}"
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        paths.append(target)
    return paths[0], paths[1]
