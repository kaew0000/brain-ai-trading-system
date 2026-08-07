"""
learning/application/recommendation_context.py — V16 Phase 4C Step 3
Part A: Recommendation Application Layer.

Read-only. Loads validated recommendations, filters them for one
current market context, and produces ONE canonical `RecommendationSet`
— never modifies a Recommendation (validation's `dataclasses.replace()`
copies already happened in recommendation_validator.py before this
module ever sees them).

Filter order (first matching reason wins — every excluded
recommendation gets exactly one reason, never zero, never more than
one, satisfying Part C's "if ignored, show WHY"):

  1. validator_status != "valid"   -> reason "validator_status=<x>"
  2. symbol mismatch                -> reason "symbol_mismatch"
  3. regime mismatch                 -> reason "regime_mismatch"
  4. direction mismatch               -> reason "direction_mismatch"
  5. below min_confidence              -> reason "below_min_confidence"
  6. contradicted by another applied
     recommendation                    -> reason "contradicted_by=<id>"

Symbol/regime/direction matching is honestly asymmetric: a
recommendation whose own `.symbol`/`.regime`/`.direction` is `None`
(i.e. the underlying pattern wasn't scoped to one — see
recommendation_engine.py's `_extract_symbol_and_regime()`) is treated
as applying REGARDLESS of the current context's symbol/regime/
direction, not excluded. A `worst_regime` recommendation about
HIGH_VOL, for example, has no `.symbol` — it's not "for" any one
symbol, so it isn't symbol-filtered out; it IS regime-filtered against
whatever regime the caller passes.

`direction` filtering is real but, as of this phase, a no-op in
practice: no Recommendation this engine has ever produced has a
non-None `.direction` (see recommendation_engine.py's module
docstring for why that field wasn't fabricated). The filter is
implemented anyway so a future phase that adds direction-conditioned
patterns doesn't require touching this module.

Contradiction detection (Part A/G) is deliberately narrow: two
CANDIDATE recommendations (already past filters 1-5) are contradictory
only if they share the same `category` and the same `symbol` (or both
are symbol-agnostic) AND one's `based_on.kind` starts with "best_"
while the other's starts with "worst_" — e.g. a `worst_confidence_range`
recommendation ("raise the threshold") and a `best_confidence_range`
recommendation ("the best bucket isn't the top one, consider lowering
it") for the same symbol really do give opposite guidance. This is a
narrow, explainable rule, not a general-purpose text-contradiction
detector — it will not catch every possible disagreement, and doesn't
claim to. When a contradiction is found, BOTH sides are moved to
`skipped` (neither is arbitrarily kept) — see Part H: an advisory layer
that can't resolve a genuine disagreement on its own should abstain,
not guess.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ..recommendation_engine import Recommendation
from .recommendation_validator import validate_all

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _as_aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SkippedRecommendation:
    recommendation_id: str | None
    reason:              str
    recommendation:       Recommendation

    def to_dict(self) -> dict:
        return {"recommendation_id": self.recommendation_id, "reason": self.reason,
                "recommendation": asdict(self.recommendation)}


@dataclass(frozen=True)
class RecommendationSet:
    """One canonical, context-scoped recommendation set — the deliverable
    Part A asks for. `applied` is what the caller (Part B's advisor) may
    actually use; `skipped` carries every excluded recommendation and
    exactly why, for Part C's explanation surface."""
    symbol:        str | None
    regime:        str | None
    direction:      str | None
    generated_at:    str
    applied:          list[Recommendation]          = field(default_factory=list)
    skipped:           list[SkippedRecommendation]   = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "regime": self.regime, "direction": self.direction,
            "generated_at": self.generated_at,
            "applied": [asdict(r) for r in self.applied],
            "skipped": [s.to_dict() for s in self.skipped],
        }


def _kind_polarity(rec: Recommendation) -> str | None:
    kind = rec.based_on.get("kind", "") if isinstance(rec.based_on, dict) else ""
    if kind.startswith("best_"):
        return "best"
    if kind.startswith("worst_"):
        return "worst"
    return None


def _find_contradictions(candidates: list[Recommendation]) -> dict[str, str]:
    """Returns {recommendation_id: reason} for every candidate involved in
    a same-category/same-symbol best-vs-worst disagreement with another
    candidate. O(n^2) over `candidates`, which is expected to be small
    (one learning cycle's worth of recommendations, typically well under
    a few dozen) — not the ~1,000-row-plus scale that
    get_ensemble_learning_dataset()'s own documented N+1 ceiling
    (CHANGELOG.md, Phase 4C Step 1) applies to."""
    contradictions: dict[str, str] = {}
    for i, a in enumerate(candidates):
        pol_a = _kind_polarity(a)
        if pol_a is None or a.id is None:
            continue
        for b in candidates[i + 1:]:
            pol_b = _kind_polarity(b)
            if pol_b is None or b.id is None or pol_b == pol_a:
                continue
            if a.category != b.category or a.symbol != b.symbol:
                continue
            contradictions[a.id] = f"contradicted_by={b.id}"
            contradictions[b.id] = f"contradicted_by={a.id}"
    return contradictions


def build_recommendation_set(
    recommendations: list[Recommendation],
    *,
    symbol:            str | None = None,
    regime:             str | None = None,
    direction:           str | None = None,
    min_confidence:       str | None = None,
    now:                   datetime | None = None,
    already_validated:      bool = False,
    min_sample_size:          int | None = None,
) -> RecommendationSet:
    """Builds one canonical RecommendationSet for the given context.

    `already_validated=True` skips re-running the validator (use when
    the caller already has freshly-validated recommendations, e.g. from
    a LearningSnapshot built moments ago in the same process, to avoid
    redundant work) — recommendations are trusted to already carry an
    accurate `validator_status` in that case."""
    now = _as_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    recs = recommendations if already_validated else validate_all(recommendations, now=now, min_sample_size=min_sample_size)

    candidates: list[Recommendation] = []
    skipped: list[SkippedRecommendation] = []

    for rec in recs:
        if rec.validator_status != "valid":
            skipped.append(SkippedRecommendation(rec.id, f"validator_status={rec.validator_status}", rec))
            continue
        if symbol is not None and rec.symbol is not None and rec.symbol != symbol:
            skipped.append(SkippedRecommendation(rec.id, "symbol_mismatch", rec))
            continue
        if regime is not None and rec.regime is not None and rec.regime != regime:
            skipped.append(SkippedRecommendation(rec.id, "regime_mismatch", rec))
            continue
        if direction is not None and getattr(rec, "direction", None) not in (None, direction):
            skipped.append(SkippedRecommendation(rec.id, "direction_mismatch", rec))
            continue
        if min_confidence is not None and _CONFIDENCE_RANK.get(rec.confidence, -1) < _CONFIDENCE_RANK.get(min_confidence, 0):
            skipped.append(SkippedRecommendation(rec.id, "below_min_confidence", rec))
            continue
        candidates.append(rec)

    contradictions = _find_contradictions(candidates)
    applied = []
    for rec in candidates:
        if rec.id in contradictions:
            skipped.append(SkippedRecommendation(rec.id, contradictions[rec.id], rec))
        else:
            applied.append(rec)

    return RecommendationSet(
        symbol=symbol, regime=regime, direction=direction,
        generated_at=now.isoformat(), applied=applied, skipped=skipped,
    )
