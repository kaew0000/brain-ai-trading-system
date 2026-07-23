"""
CEO Agent

Consumes ALL agent reports and produces the final trading decision.

The CEO is the orchestrator. It:
  1. Collects AgentReport from each AI employee
  2. Weighs their signals and confidence scores
  3. Cross-validates with the existing ConfidenceEngine output
  4. Produces a final CEODecision with full explainability
  5. Answers any chat question by delegating to the appropriate agent

CEODecision schema
------------------
{
  "action":       "LONG" | "SHORT" | "WAIT" | "BLOCKED",
  "direction":    str,
  "confidence":   float 0-100,
  "score_breakdown": {
    "smc":     float,
    "futures": float,
    "regime":  float,
    "risk":    float,
    "journal": float,
    "confidence_engine": float,
  },
  "reasons":    [str, ...],
  "agent_reports": { agent_name: AgentReport.to_dict() },
  "agreement_score": float 0-1,
  "weights_used": { weight_key: float },   # Phase 4B — static or blended
  "timestamp":  str,
}

Does NOT replace ConfidenceEngine — fuses it in as one more weighted vote
in the agent layer (Phase 4A), rather than letting it override the agent
layer's own opinion outright. A ConfidenceEngine hard block still vetoes
unconditionally, same as the risk manager's circuit breaker.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from events.event_bus import conf_pub
from telemetry.agent_telemetry import get_telemetry_registry
from reasoning.reasoning_stream import get_reasoning_stream
from utils.logger import get_logger
from config.settings import settings
from .base_agent import BaseAgent, AgentReport

logger = get_logger("agents.ceo_agent")


@dataclass
class CEODecision:
    action:          str  = "WAIT"
    direction:       str  = ""
    confidence:      float = 0.0
    score_breakdown: dict  = field(default_factory=dict)
    reasons:         list  = field(default_factory=list)
    agent_reports:   dict  = field(default_factory=dict)
    # Phase 4A: weighted fraction of directional (LONG/SHORT) votes that
    # agree with `action`. 1.0 = unanimous. Only meaningful when action is
    # itself directional; stays at the default 1.0 for WAIT/BLOCKED.
    agreement_score: float = 1.0
    # Phase 4B: the weights actually used this cycle — equal to
    # CEOAgent.WEIGHTS unless DYNAMIC_AGENT_WEIGHTS_ENABLED blended them
    # toward measured per-agent win-rate. Exposed for dashboard/audit
    # visibility into which mode produced this decision.
    weights_used:    dict  = field(default_factory=dict)
    timestamp:       str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "action":          self.action,
            "direction":       self.direction,
            "confidence":      self.confidence,
            "score_breakdown": self.score_breakdown,
            "reasons":         self.reasons,
            "agent_reports":   self.agent_reports,
            "agreement_score": self.agreement_score,
            "weights_used":    self.weights_used,
            "timestamp":       self.timestamp,
        }

    def npc_speech(self) -> str:
        """One-line summary for CEO NPC speech bubble."""
        if self.action == "WAIT":
            return f"Waiting. Confidence {self.confidence:.0f}%."
        return f"{self.action} signal. Confidence {self.confidence:.0f}%. {self.reasons[0] if self.reasons else ''}"


class CEOAgent(BaseAgent):
    """
    AI CEO — orchestrates all agent reports into a final decision.

    Parameters
    ----------
    agents : dict of agent_name -> BaseAgent instance
    """

    AGENT_NAME = "CEO_AGENT"

    # Weights for CEO's fused scoring. "confidence_engine" is the existing
    # ConfidenceEngine's own opinion (Phase 4A) — folded in as one more
    # weighted vote instead of overriding the agent layer outright. Sums
    # to 1.0; rebalanced from the pre-4A {smc:.30 futures:.25 regime:.20
    # risk:.15 journal:.10} to make room for it.
    WEIGHTS = {
        "smc":               0.25,
        "futures":           0.20,
        "regime":            0.15,
        "risk":              0.15,
        "journal":           0.10,
        "confidence_engine": 0.15,
    }

    # Confidence damping floor when the agent layer is split on direction:
    # 1.0 = no damping (unanimous), this value = damping at zero agreement.
    # A floor rather than zeroing out — a winning vote that barely cleared
    # the 40-point action threshold shouldn't be double-punished down to 0.
    AGREEMENT_FLOOR_MULTIPLIER = 0.5

    def __init__(self, agents: Optional[dict] = None, journal=None) -> None:
        super().__init__()
        self._agents: dict = agents or {}
        self._last_ceo:  Optional[CEODecision] = None
        # Phase 4B: optional TradeJournalV2 (or compatible) instance used
        # for dynamic weighting. None (the default) means CEOAgent behaves
        # exactly as before Phase 4B — _effective_weights() always falls
        # back to the static WEIGHTS in that case regardless of the
        # DYNAMIC_AGENT_WEIGHTS_ENABLED setting.
        self._journal = journal
        self._perf_cache:    Optional[dict] = None
        self._perf_cache_ts: float = 0.0

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        self._agents[name] = agent

    def _get_agent_performance_cached(self) -> dict:
        """
        TTL-cached wrapper around journal.get_agent_performance() — keyed
        by agent display name (matches AgentReport.agent) for direct lookup
        from _effective_weights(). Re-fetched at most once per
        DYNAMIC_WEIGHT_REFRESH_SECONDS so dynamic weighting never adds a DB
        round-trip to every single decision cycle.
        """
        now = time.time()
        if (self._perf_cache is not None and
                now - self._perf_cache_ts < settings.DYNAMIC_WEIGHT_REFRESH_SECONDS):
            return self._perf_cache
        rows = self._journal.get_agent_performance()
        self._perf_cache    = {r["agent"]: r for r in rows}
        self._perf_cache_ts = now
        return self._perf_cache

    def _effective_weights(self, reports: dict) -> dict:
        """
        Phase 4B: blend the static WEIGHTS toward each agent's measured
        win-rate (journal_v2.get_agent_performance(), Phase 4B Step 1),
        once that agent has at least DYNAMIC_WEIGHT_MIN_SAMPLES closed,
        direction-matching trades. Always returns a dict summing to 1.0.

        Deliberately defensive: returns self.WEIGHTS unchanged (b) when
        disabled, (b) when no journal was configured, (c) for any agent
        below the sample-size floor, and (d) on ANY exception fetching
        performance — dynamic weighting must never be able to break a
        decision cycle. Renormalizes after blending so the long/short
        scoring and the >=40 action threshold keep meaning the same thing
        they did before Phase 4B, regardless of whether blending is active.
        """
        if not settings.DYNAMIC_AGENT_WEIGHTS_ENABLED or self._journal is None:
            return self.WEIGHTS

        try:
            perf_by_agent = self._get_agent_performance_cached()
        except Exception as exc:
            logger.warning(f"Dynamic weighting: performance fetch failed, using static WEIGHTS: {exc}")
            return self.WEIGHTS

        blend = settings.DYNAMIC_WEIGHT_BLEND
        min_n = settings.DYNAMIC_WEIGHT_MIN_SAMPLES
        blended: dict[str, float] = {}
        for key, static_w in self.WEIGHTS.items():
            rep  = reports.get(key)
            perf = perf_by_agent.get(rep.agent) if rep is not None else None
            if perf is None or perf.get("total_trades", 0) < min_n:
                blended[key] = static_w
                continue
            # win_rate in [0,1] -> multiplier in [0.5, 1.5]: an agent that's
            # never won still keeps half its static weight (blend-scaled),
            # an agent that's never lost can at most 1.5x it — bounded so no
            # single agent's streak can dominate or zero out the vote.
            multiplier   = 0.5 + float(perf.get("win_rate", 0.5))
            blended[key] = static_w * ((1 - blend) + blend * multiplier)

        total = sum(blended.values())
        if total <= 0:
            return self.WEIGHTS
        return {k: v / total for k, v in blended.items()}

    def decide(
        self,
        market_context: dict,
        confidence_result=None,    # ConfidenceResult (or legacy DecisionResult) from existing engine (optional)
    ) -> CEODecision:
        """
        Run all agents, fuse their signals (plus ConfidenceEngine's own
        opinion, if provided) into one weighted vote, produce a CEODecision.

        Phase 4A change: `confidence_result` used to *override* the agent
        layer's decision outright whenever provided — the agent layer's
        votes only ever showed up in `reasons` text, never in the actual
        action/confidence returned. It is now wrapped as one more
        AgentReport under the "confidence_engine" WEIGHTS key, so it
        competes in the same weighted vote as every other agent — a strong
        agent-layer disagreement can now actually pull the final action
        away from what ConfidenceEngine alone would have said.

        The one exception is a genuine ConfidenceEngine *hard block*
        (`blocked=True` / `action == "BLOCKED"`) — like the risk manager's
        circuit breaker, that's a business-rule veto, not an opinion to be
        outvoted, so it still short-circuits straight to BLOCKED.

        Also computes `agreement_score` (Phase 4A): the weighted fraction
        of directional (LONG/SHORT) votes that agree with the winning
        side. Used to damp `confidence` when the agent layer is split —
        see AGREEMENT_FLOOR_MULTIPLIER.

        Telemetry (v14 Phase 2): each sub-agent already records its own
        telemetry via BaseAgent.run(). This method additionally records
        telemetry for the CEO_AGENT itself, timing the full orchestration
        (sub-agent loop + aggregation + decision construction).
        """
        _telemetry_start = time.perf_counter()

        # ── Run all agents ────────────────────────────────────────────────
        reports: dict[str, AgentReport] = {}
        for name, agent in self._agents.items():
            try:
                reports[name] = agent.run(market_context)
            except Exception as exc:
                logger.warning(f"Agent {name} failed: {exc}")

        # ── Fold ConfidenceEngine's opinion in as one more report (4A) ──────
        # Wrapping it as an AgentReport means the weighted loop below treats
        # it exactly like any other agent's vote — no separate code path.
        ce_blocked = False
        ce_conf    = 0.0
        if confidence_result is not None:
            ce_action  = getattr(confidence_result, "action", "WAIT")
            ce_conf    = float(getattr(confidence_result, "confidence", 0.0))
            ce_blocked = bool(getattr(confidence_result, "blocked", False)) or ce_action == "BLOCKED"
            reports["confidence_engine"] = AgentReport(
                agent      = "CONFIDENCE_ENGINE",
                signal     = getattr(confidence_result, "direction", "") or "NEUTRAL",
                confidence = ce_conf,
                summary    = f"ConfidenceEngine: {ce_action} @ {ce_conf:.0f}%",
                raw        = confidence_result.to_dict() if hasattr(confidence_result, "to_dict") else {},
            )

        # ── Aggregate signals (weighted vote across every WEIGHTS key) ──────
        # Phase 4B: `weights` is either self.WEIGHTS unchanged, or a
        # performance-blended variant — see _effective_weights(). Computed
        # once per cycle and reused below for agreement_score and
        # score_breakdown too, so every number in this decision reflects
        # the same weights that actually drove long_score/short_score.
        weights = self._effective_weights(reports)

        long_score  = 0.0
        short_score = 0.0
        reasons     = []
        directional_votes: list[tuple[str, str]] = []   # (weight_key, "LONG"|"SHORT")

        for key, weight in weights.items():
            rep = reports.get(key)
            if rep is None:
                continue
            w_conf = rep.confidence / 100 * weight * 100  # weighted pts

            if rep.signal == "LONG":
                long_score  += w_conf
                reasons.append(f"{rep.agent}: {rep.summary[:60]}")
                directional_votes.append((key, "LONG"))
            elif rep.signal == "SHORT":
                short_score += w_conf
                reasons.append(f"{rep.agent}: {rep.summary[:60]}")
                directional_votes.append((key, "SHORT"))

        # Risk manager veto — business rule, not an opinion, always wins
        # over the vote (but not over a ConfidenceEngine hard block, which
        # is checked first below).
        risk_rep = reports.get("risk")
        risk_blocked = (risk_rep is not None and
                        risk_rep.raw.get("can_trade") is False)

        # ── Determine action ──────────────────────────────────────────────
        if ce_blocked:
            action, direction, conf = "BLOCKED", "", ce_conf
            block_reasons = getattr(confidence_result, "block_reasons", None) or ["blocked"]
            reasons.insert(0, "CONFIDENCE_ENGINE: hard block — " + "; ".join(block_reasons))
        elif risk_blocked:
            action, direction, conf = "WAIT", "", 0.0
            reasons.insert(0, "RISK_MANAGER: circuit breaker active")
        elif long_score > short_score and long_score >= 40:
            action, direction, conf = "LONG", "LONG", min(100.0, long_score)
        elif short_score > long_score and short_score >= 40:
            action, direction, conf = "SHORT", "SHORT", min(100.0, short_score)
        else:
            action, direction, conf = "WAIT", "", max(long_score, short_score)

        # ── Agreement / disagreement scoring (Phase 4A) ─────────────────────
        # 1.0 = every directional vote agrees with the winning action;
        # lower = the agent layer is split. Only meaningful for a
        # directional action — WAIT/BLOCKED don't need one.
        agreement_score = 1.0
        if action in ("LONG", "SHORT") and directional_votes:
            total_dir_w = sum(weights[k] for k, _ in directional_votes)
            agree_w     = sum(weights[k] for k, s in directional_votes if s == action)
            agreement_score = round(agree_w / total_dir_w, 4) if total_dir_w > 0 else 1.0

            if agreement_score < 1.0:
                dissenters = [k for k, s in directional_votes if s != action]
                reasons.insert(0, f"AGREEMENT {agreement_score*100:.0f}% "
                                   f"— dissent from: {', '.join(dissenters)}")
                multiplier = (self.AGREEMENT_FLOOR_MULTIPLIER +
                              (1 - self.AGREEMENT_FLOOR_MULTIPLIER) * agreement_score)
                conf = conf * multiplier

        # ── Publish CEO decision event ─────────────────────────────────────
        payload = {
            "action":          action,
            "confidence":      conf,
            "long_score":      long_score,
            "short_score":     short_score,
            "agreement_score": agreement_score,
        }
        if action in ("LONG", "SHORT"):
            conf_pub.info("CEO_DECISION",
                          f"CEO says {action} @ {conf:.0f}% confidence "
                          f"(agreement {agreement_score*100:.0f}%)",
                          payload)
        else:
            conf_pub.debug("CEO_WAIT",
                           f"CEO waiting — not enough signal ({conf:.0f}%)",
                           payload)

        dec = CEODecision(
            action          = action,
            direction       = direction,
            confidence      = round(conf, 2),
            score_breakdown = {
                "long_weighted":  round(long_score, 2),
                "short_weighted": round(short_score, 2),
                "smc":     round(reports.get("smc",    AgentReport("")).confidence * weights.get("smc", 0), 2),
                "futures": round(reports.get("futures",AgentReport("")).confidence * weights.get("futures", 0), 2),
                "regime":  round(reports.get("regime", AgentReport("")).confidence * weights.get("regime", 0), 2),
                "risk":    round(reports.get("risk",   AgentReport("")).confidence * weights.get("risk", 0), 2),
                "journal": round(reports.get("journal",AgentReport("")).confidence * weights.get("journal", 0), 2),
                "confidence_engine": round(reports.get("confidence_engine", AgentReport("")).confidence * weights.get("confidence_engine", 0), 2),
            },
            reasons         = reasons[:5],
            agent_reports   = {k: v.to_dict() for k, v in reports.items()},
            agreement_score = agreement_score,
            weights_used    = {k: round(v, 4) for k, v in weights.items()},
        )

        self._last_ceo = dec

        # ── Record CEO telemetry ────────────────────────────────────────────
        _latency_ms = round((time.perf_counter() - _telemetry_start) * 1000, 2)
        get_telemetry_registry().record(
            agent=self.AGENT_NAME,
            status="OK",
            confidence=dec.confidence,
            last_signal=dec.action if dec.action != "WAIT" else "NEUTRAL",
            latency_ms=_latency_ms,
            decision=dec.npc_speech(),
        )

        # ── Record CEO reasoning (v14 Phase 2.5) ────────────────────────────
        # "reasoning" = concatenated per-agent reasons already collected above;
        # falls back to a neutral statement when no agent contributed a signal.
        get_reasoning_stream().record(
            agent=self.AGENT_NAME,
            thought=dec.npc_speech(),
            reasoning="; ".join(reasons) if reasons else "No dominant signal from any sub-agent.",
            decision=dec.action,
            confidence=dec.confidence,
        )

        return dec

    def analyse(self, market_context: dict) -> AgentReport:
        """BaseAgent interface — wraps decide() without ConfidenceResult."""
        dec = self.decide(market_context)
        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = dec.action if dec.action != "WAIT" else "NEUTRAL",
            confidence = dec.confidence,
            summary    = dec.npc_speech(),
            raw        = dec.to_dict(),
        )

    def answer(self, question: str, market_context: Optional[dict] = None) -> str:
        """
        CEO answers by delegating to the appropriate agent.
        """
        q = question.lower()

        # Route to specific agent
        routing = {
            ("bos","choch","fvg","order block","structure","liquidity","smc"):          "smc",
            ("funding","oi","open interest","liquidation","long short","futures"):       "futures",
            ("regime","trend","adx","rsi","ema"):                                        "regime",
            ("risk","drawdown","daily loss","consecutive","circuit breaker","position size"): "risk",
            ("win rate","profit factor","expectancy","journal","history","performance"): "journal",
            ("entry","stop","take profit","position","pnl","unrealised"):               "trader",
        }

        for keywords, agent_key in routing.items():
            if any(kw in q for kw in keywords):
                agent = self._agents.get(agent_key)
                if agent and agent.last_report:
                    return agent.answer(question, market_context)

        # Generic CEO answer
        if self._last_ceo:
            d = self._last_ceo
            return (f"CEO decision: {d.action} @ {d.confidence:.0f}% confidence. "
                    f"Top reason: {d.reasons[0] if d.reasons else 'no strong signal'}.")
        return "CEO: No decision available yet. Waiting for first analysis cycle."

    @property
    def last_decision(self) -> Optional[CEODecision]:
        return self._last_ceo
