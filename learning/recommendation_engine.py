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

V16 Phase 4C Step 3 (Part A prerequisite): five fields were added below
— `id`, `symbol`, `regime`, `generated_at`, `expires_at`,
`validator_status` — needed by the new `learning/application/` package
(recommendation filtering, scoring, validation, decision-integration)
introduced in that phase. All six are additive with defaults, so every
pre-existing keyword construction of `Recommendation` in this file
(the 12 return points in `_recommend_for()`, all keyword-only) and
every pre-existing reader (asdict()/to_dict() in learning_snapshot.py)
is unaffected. Two fields are deliberately honest rather than
fabricated:

- `direction` was requested by Step 3's brief but is NOT added here.
  No pattern kind this engine reads is conditioned on trade direction
  (LONG vs SHORT) anywhere in `pattern_miner.py` or the underlying
  `LearningDataset` — adding a field with no real data behind it would
  mean inventing values. `learning/application/recommendation_context.py`
  documents and handles this gap explicitly instead.
- `id` is a deterministic hash of (category, based_on.kind,
  based_on.subject) — NOT a random UUID — so the "recommendation about
  BTCUSDT's worst_symbol pattern" keeps the same identity across
  regenerated snapshots. A random id would break Part G's
  cross-cycle contradiction/expiry tracking on every single run.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from .pattern_miner import Pattern

# V16 Phase 4C Step 3: TTL for how long a generated Recommendation is
# considered current before RecommendationValidator marks it "expired".
# Local import (not top-level) avoids a hard import-time dependency
# from this READ-ONLY analysis package onto config/settings.py for the
# one constant it needs; falls back to a safe default if settings is
# unavailable (e.g. a bare unit-test import of just this module).
_DEFAULT_RECOMMENDATION_TTL_HOURS = 24.0


def _recommendation_ttl_hours() -> float:
    try:
        from config.settings import settings
        return float(getattr(settings, "RECOMMENDATION_TTL_HOURS", _DEFAULT_RECOMMENDATION_TTL_HOURS))
    except Exception:
        return _DEFAULT_RECOMMENDATION_TTL_HOURS


def _stable_recommendation_id(category: str, based_on: dict) -> str:
    """Deterministic, content-derived id — same (category, pattern kind,
    pattern subject) always hashes to the same id, regardless of the
    exact metric numbers this run (those change trade-to-trade; the
    *identity* of "which pattern this recommendation is about" should
    not)."""
    key = f"{category}|{based_on.get('kind', '')}|{based_on.get('subject', '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _extract_symbol_and_regime(based_on: dict) -> tuple[str | None, str | None]:
    """Best-effort, honest extraction from the originating Pattern's
    `kind`/`subject` — returns (None, None) rather than a guess for any
    pattern kind that isn't inherently symbol- or regime-scoped (e.g.
    `losing_streak`, `agent_disagreement_quality`, `latency_trend` are
    portfolio/agent/execution-level facts, not tied to one symbol or
    regime — see pattern_miner.py's own kind list)."""
    kind = based_on.get("kind", "")
    subject = based_on.get("subject", "")
    if kind in ("worst_symbol_regime_combo", "best_symbol_regime_combo") and "/" in subject:
        symbol, regime = subject.split("/", 1)
        return symbol, regime
    if kind == "worst_symbol":
        return subject, None
    if kind == "worst_regime":
        return None, subject
    return None, None


@dataclass(frozen=True)
class Recommendation:
    text:        str
    category:     str    # "symbol" | "regime" | "confidence" | "agent" | "timing" | "execution" | "risk"
    confidence:   str    # "low" | "medium" | "high" — derived from the underlying pattern's sample size
    based_on:     dict   # {"kind":, "subject":, "metric":} — traces back to the originating Pattern

    # V16 Phase 4C Step 3 (Part A prerequisite) — all additive, all defaulted.
    id:               str | None = None
    symbol:           str | None = None   # honest None when the pattern isn't symbol-scoped
    regime:           str | None = None   # honest None when the pattern isn't regime-scoped
    generated_at:     str | None = None   # ISO-8601 UTC; stamped once per generate() batch
    expires_at:       str | None = None   # ISO-8601 UTC; generated_at + RECOMMENDATION_TTL_HOURS
    validator_status: str = "unvalidated"  # set by learning/application/recommendation_validator.py


def _confidence_from_sample_size(n: int) -> str:
    if n >= 30:
        return "high"
    if n >= 10:
        return "medium"
    return "low"


class RecommendationEngine:

    def generate(self, patterns: list[Pattern], *, now: datetime | None = None) -> list[Recommendation]:
        """Unchanged output for every pre-existing caller that only reads
        `.text`/`.category`/`.confidence`/`.based_on` — this just also
        stamps the Step 3 identity/lifecycle fields onto each result via
        `dataclasses.replace()`, in one place, after `_recommend_for()`
        (the 12-branch method below, untouched by this phase) has already
        decided whether/what to recommend.

        `now` is accepted (not read from the clock internally) so a
        caller building a whole LearningSnapshot can pass one consistent
        timestamp for every recommendation in the batch — matches
        `build_learning_snapshot()`'s own "one timestamp per snapshot"
        convention (learning_snapshot.py)."""
        now = now or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_iso = (now + timedelta(hours=_recommendation_ttl_hours())).isoformat()

        recs: list[Recommendation] = []
        for p in patterns:
            rec = self._recommend_for(p)
            if rec is None:
                continue
            symbol, regime = _extract_symbol_and_regime(rec.based_on)
            recs.append(replace(
                rec,
                id=_stable_recommendation_id(rec.category, rec.based_on),
                symbol=symbol,
                regime=regime,
                generated_at=now_iso,
                expires_at=expires_iso,
            ))
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
