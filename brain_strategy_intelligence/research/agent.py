"""ResearchAgent: provider-independent strategy research with a deterministic offline fallback.

Safety properties (each covered by tests):
* works with no provider / no API key (offline_rules mode);
* `missing_data` is computed by code, never trusted from the LLM;
* LLM output must parse as JSON AND validate against a strict schema; unknown strategy ids are dropped;
* any evidence string citing a number that is not in the snapshot or the candidate parameters is dropped;
* bounded retries with exponential backoff, per-call timeout; failure falls back to offline rules (never raises to the caller).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable

from pydantic import ValidationError

from ..config import Config
from ..errors import InvalidLLMOutput, ProviderUnavailable
from ..interfaces import LLMProvider
from ..schemas import LLMResearchOutput, MarketSnapshot, ResearchItem, ResearchReport, StrategyDefinition
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .providers import NullProvider

log = logging.getLogger(__name__)
_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _allowed_numbers(snapshot: MarketSnapshot, candidates: list[StrategyDefinition]) -> list[float]:
    nums = snapshot.numeric_values()
    for c in candidates:
        nums += [float(v) for v in c.parameters.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return nums


def _cites_unknown_number(text: str, allowed: list[float]) -> bool:
    for tok in _NUM.findall(text):
        v = float(tok)
        if not any(abs(v - a) <= 1e-9 * max(1.0, abs(a)) for a in allowed):
            return True
    return False


class ResearchAgent:
    def __init__(
        self, provider: LLMProvider | None, config: Config, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self.provider = provider or NullProvider()
        self.cfg = config
        self._sleep = sleep

    # ------------------------------------------------------------ offline
    @staticmethod
    def offline_items(snapshot: MarketSnapshot, candidates: list[StrategyDefinition]) -> list[ResearchItem]:
        items = []
        for c in candidates:
            if snapshot.regime is None:
                fit, sup, con = 0.5, [], ["market regime unknown; declared-condition match cannot be assessed"]
            elif snapshot.regime in c.market_conditions:
                fit = 1.0
                sup = [f"declared suitable for regime {snapshot.regime} (author's claim, not verified)"]
                con = []
            else:
                fit = 0.0
                sup = []
                con = [f"regime {snapshot.regime} is not among the declared conditions {c.market_conditions}"]
            items.append(
                ResearchItem(
                    strategy_id=c.id,
                    regime_fit=fit,
                    supporting_evidence=sup,
                    contradicting_evidence=con,
                    invalidation_conditions=list(c.invalidation_conditions)[:8],
                    recommend_backtest=fit >= 0.5 and c.validation_status.value in ("unvalidated", "backtested"),
                )
            )
        return sorted(items, key=lambda i: (-i.regime_fit, i.strategy_id))

    # ------------------------------------------------------------ LLM path
    @staticmethod
    def parse_llm_output(raw: str) -> LLMResearchOutput:
        text = _FENCE.sub("", raw.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidLLMOutput(f"not valid JSON: {exc.msg}") from exc
        try:
            return LLMResearchOutput.model_validate(data)
        except ValidationError as exc:
            raise InvalidLLMOutput(f"schema violation: {exc.error_count()} error(s)") from exc

    def _sanitize(
        self,
        out: LLMResearchOutput,
        snapshot: MarketSnapshot,
        candidates: list[StrategyDefinition],
        warnings: list[str],
    ) -> list[ResearchItem]:
        ids = {c.id for c in candidates}
        allowed = _allowed_numbers(snapshot, candidates)
        items: list[ResearchItem] = []
        seen: set[str] = set()
        for it in out.items:
            if it.strategy_id not in ids:
                warnings.append(f"dropped item for unknown strategy_id '{it.strategy_id[:40]}'")
                continue
            if it.strategy_id in seen:
                warnings.append(f"dropped duplicate item for '{it.strategy_id}'")
                continue
            seen.add(it.strategy_id)
            fields: dict[str, list[str]] = {}
            for name in ("supporting_evidence", "contradicting_evidence", "invalidation_conditions"):
                kept = []
                for s in getattr(it, name):
                    if _cites_unknown_number(s, allowed):
                        warnings.append(f"dropped {name} text citing a number absent from the snapshot/parameters")
                    else:
                        kept.append(s)
                fields[name] = kept
            items.append(it.model_copy(update=fields))
        if not items:
            raise InvalidLLMOutput("no valid items after validation")
        return items

    def _ask_llm(
        self, snapshot: MarketSnapshot, candidates: list[StrategyDefinition], missing: list[str]
    ) -> LLMResearchOutput:
        llm = self.cfg.llm
        user = build_user_prompt(snapshot, candidates, missing)
        last: Exception | None = None
        for attempt in range(llm.max_retries + 1):
            try:
                return self.parse_llm_output(self.provider.complete(SYSTEM_PROMPT, user, timeout=llm.timeout_seconds))
            except (ProviderUnavailable, InvalidLLMOutput) as exc:
                last = exc
                log.warning("LLM attempt %d/%d failed: %s", attempt + 1, llm.max_retries + 1, type(exc).__name__)
                if (
                    isinstance(exc, ProviderUnavailable)
                    and type(exc) is ProviderUnavailable
                    and "no LLM provider" in str(exc)
                ):
                    break  # not configured: retrying is pointless
                if attempt < llm.max_retries:
                    self._sleep(min(0.5 * 2**attempt, 4.0))
        raise last if last else ProviderUnavailable("LLM failed")

    # ------------------------------------------------------------ public
    def research(self, snapshot: MarketSnapshot, candidates: list[StrategyDefinition]) -> ResearchReport:
        candidates = candidates[: self.cfg.research.max_candidates]
        missing = snapshot.missing_fields()  # computed by code
        warnings: list[str] = []
        uncertainty = (
            "Declared-condition matching only; no backtest evidence is implied." if self.provider.name == "none" else ""
        )
        mode, items = "offline_rules", None
        if isinstance(self.provider, NullProvider) or self.provider.name == "none":
            items = self.offline_items(snapshot, candidates)
        else:
            try:
                out = self._ask_llm(snapshot, candidates, missing)
                items = self._sanitize(out, snapshot, candidates, warnings)
                mode, uncertainty = "llm", out.uncertainty
                extra = [m for m in out.missing_data if m not in missing]
                if extra:
                    warnings.append(f"LLM listed additional missing data (unverified): {extra[:5]}")
            except (ProviderUnavailable, InvalidLLMOutput) as exc:
                warnings.append(f"LLM unavailable or invalid ({type(exc).__name__}); used offline rules")
                items, mode = self.offline_items(snapshot, candidates), "offline_rules_fallback"
                uncertainty = "LLM analysis unavailable; declared-condition matching only."
        if missing:
            uncertainty = (uncertainty + f" Missing snapshot data: {missing}.").strip()
        if "SYNTHETIC" in str(snapshot.extras.get("data_label", "")).upper():
            warnings.append("snapshot is labelled SYNTHETIC")
        return ResearchReport(
            symbol=snapshot.symbol,
            mode=mode,
            items=items,
            missing_data=missing,  # type: ignore[arg-type]
            uncertainty=uncertainty,
            warnings=warnings,
            provider=self.provider.name,
        )
