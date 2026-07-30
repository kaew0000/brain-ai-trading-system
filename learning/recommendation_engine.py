"""
learning/recommendation_engine.py — V16 Phase 4C Step 1: turns
learning/pattern_miner.py's Pattern objects into human-readable
Recommendation text. Produces recommendations ONLY — nothing here (or
anything importing it) changes a setting, a weight, or trading
behavior. "No automatic actions." — this phase's own brief.

Every Recommendation carries `based_on` (the originating Pattern's kind
+ subject + metric) so a human reading learning_report.json can trace
the text back to the exact numbers that produced it — a recommendation
that can't be traced to a real, sample-size-gated Pattern is not
generated.
"""
from __future__ import annotations

from dataclasses import dataclass

from .pattern_miner import Pattern


@dataclass(frozen=True)
class Recommendation:
    text:        str
    category:     str    # "symbol" | "regime" | "confidence" | "agent" | "timing" | "execution" | "risk"
    confidence:   str    # "low" | "medium" | "high" — derived from the underlying pattern's sample size
    based_on:     dict   # {"kind":, "subject":, "metric":} — traces back to the originating Pattern


def _confidence_from_sample_size(n: int) -> str:
    if n >= 30:
        return "high"
    if n >= 10:
        return "medium"
    return "low"


class RecommendationEngine:

    def generate(self, patterns: list[Pattern]) -> list[Recommendation]:
        recs: list[Recommendation] = []
        for p in patterns:
            rec = self._recommend_for(p)
            if rec is not None:
                recs.append(rec)
        return recs

    def _recommend_for(self, p: Pattern) -> Recommendation | None:
        n = p.metric.get("sample_size") or p.metric.get("length") or 0
        conf = _confidence_from_sample_size(n)
        based_on = {"kind": p.kind, "subject": p.subject, "metric": p.metric}

        if p.kind == "worst_symbol_regime_combo":
            symbol, regime = p.subject.split("/", 1)
            return Recommendation(
                text=f"{symbol} performs poorly during {regime} regime.",
                category="symbol", confidence=conf, based_on=based_on,
            )
        if p.kind == "best_symbol_regime_combo":
            symbol, regime = p.subject.split("/", 1)
            return Recommendation(
                text=f"{symbol} performs well during {regime} regime.",
                category="symbol", confidence=conf, based_on=based_on,
            )
        if p.kind == "worst_symbol":
            return Recommendation(
                text=f"{p.subject} is a candidate for reduced allocation or closer review "
                     f"(win rate {p.metric['win_rate']:.0%} over {p.metric['sample_size']} trades).",
                category="symbol", confidence=conf, based_on=based_on,
            )
        if p.kind == "worst_regime":
            return Recommendation(
                text=f"Trading during {p.subject} regime has underperformed "
                     f"(win rate {p.metric['win_rate']:.0%} over {p.metric['sample_size']} trades).",
                category="regime", confidence=conf, based_on=based_on,
            )
        if p.kind == "worst_confidence_range":
            return Recommendation(
                text=f"Confidence range {p.subject} underperforms — reviewing the confidence "
                     f"threshold is a candidate next step (win rate {p.metric['win_rate']:.0%}, "
                     f"n={p.metric['sample_size']}).",
                category="confidence", confidence=conf, based_on=based_on,
            )
        if p.kind == "best_confidence_range" and not p.subject.startswith("80"):
            return Recommendation(
                text=f"The best-performing confidence range ({p.subject}) is not the highest "
                     f"bucket — reduce confidence threshold is a candidate (win rate "
                     f"{p.metric['win_rate']:.0%}, n={p.metric['sample_size']}).",
                category="confidence", confidence=conf, based_on=based_on,
            )
        if p.kind == "losing_streak":
            return Recommendation(
                text=f"A losing streak of {p.metric['length']} trades occurred — worth reviewing "
                     f"whether a circuit-breaker / cooldown threshold is warranted.",
                category="risk", confidence=conf, based_on=based_on,
            )
        if p.kind == "agent_disagreement_quality" and p.severity == "negative":
            label = "CEO" if p.subject == "ceo" else p.subject
            return Recommendation(
                text=f"{label} disagreement correlates with losses "
                     f"(win rate {p.metric['win_rate']:.0%} when it disagreed with the trade "
                     f"direction, n={p.metric['sample_size']}).",
                category="agent", confidence=conf, based_on=based_on,
            )
        if p.kind == "agent_agreement_quality" and p.severity == "negative":
            label = "CEO" if p.subject == "ceo" else p.subject
            return Recommendation(
                text=f"{label} agreement has NOT correlated with wins so far "
                     f"(win rate {p.metric['win_rate']:.0%} when it agreed, n={p.metric['sample_size']}) "
                     f"— worth reviewing this agent's weight.",
                category="agent", confidence=conf, based_on=based_on,
            )
        if p.kind == "latency_trend":
            direction = "increased" if p.metric["change_pct"] > 0 else "decreased"
            return Recommendation(
                text=f"Execution latency {direction}.",
                category="execution", confidence=conf if n else "low", based_on=based_on,
            )
        if p.kind == "risk_adjusted_return_trend":
            direction = "increased" if p.metric["change_pct"] > 0 else "decreased"
            if direction == "decreased":
                return Recommendation(
                    text="Risk-adjusted return decreased.",
                    category="risk", confidence=conf if n else "low", based_on=based_on,
                )
            return Recommendation(
                text="Risk-adjusted return increased.",
                category="risk", confidence=conf if n else "low", based_on=based_on,
            )
        if p.kind == "worst_hour":
            return Recommendation(
                text=f"{p.subject} UTC has underperformed (win rate {p.metric['win_rate']:.0%}, "
                     f"n={p.metric['sample_size']}).",
                category="timing", confidence=conf, based_on=based_on,
            )
        if p.kind == "worst_weekday":
            return Recommendation(
                text=f"{p.subject} has underperformed (win rate {p.metric['win_rate']:.0%}, "
                     f"n={p.metric['sample_size']}).",
                category="timing", confidence=conf, based_on=based_on,
            )

        # Positive-only / informational patterns (best_symbol, best_regime,
        # best_hour, best_weekday, winning_streak, agreement quality that's
        # already good) intentionally produce NO recommendation — a
        # recommendation implies "consider changing something"; "this is
        # already working well" isn't actionable feedback of that kind,
        # and duplicating every positive Pattern as a Recommendation would
        # just double the same information already in the patterns list
        # (see learning_report.py, which reports both).
        return None
