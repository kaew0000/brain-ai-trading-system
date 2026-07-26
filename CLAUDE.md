# Brain Bot V16

This repository is the canonical source of Brain Bot V16 Autonomous AI Trading Platform.

---

# Project Mission

Build a production-grade autonomous AI trading platform capable of:

- Multi-symbol trading
- AI-assisted decision making
- Dynamic risk management
- Portfolio optimization
- Autonomous monitoring
- Continuous self-improvement

Reliability and capital preservation are always higher priority than trading frequency.

---

# Current Development Status

Completed

- Fix #1 Risk Consolidation
- Fix #2 Watchdog Supervisor
- Dashboard Authentication
- Dynamic Risk Engine V2
- Multi Symbol Foundation
- Market Scanner
- Opportunity Ranker
- Portfolio Manager (Intelligence Core + Orchestrator + API — see architecture.md §17-19)
- Bundle Manager
- Execution Wiring & Live Orchestrator
- Execution Scheduler + Multi-Symbol Signals
- Strategy Plugin System (architecture.md §25 — `execution/strategy_registry.py`)
- Ensemble Decision Engine Phase 4A — ConfidenceEngine fusion + agreement
  scoring (architecture.md §26 — `agents/ceo_agent.py`)
- Ensemble Decision Engine Phase 4B Step 1 — per-agent outcome attribution
  (architecture.md §27 — `journal/journal_v2.py` + `main.py`)
- Ensemble Decision Engine Phase 4B proper — dynamic per-agent weighting
  (architecture.md §28 — `agents/ceo_agent.py`, off by default via
  `DYNAMIC_AGENT_WEIGHTS_ENABLED`)
- Ensemble Decision Engine Phase 4B Step 2 — execution attribution +
  portfolio integration (architecture.md §29 — `journal/trade_attribution.py`,
  `execution/execution_orchestrator.py`, `portfolio/portfolio_manager.py`)
- Ensemble Decision Engine Phase 4B Step 3A — symbol isolation prep
  (`AgentReport.symbol`, `CEODecision.symbol`, `RegimeEngine` per-symbol
  HMM models — merged, not separately documented in architecture.md by
  that PR; see §30's "Background" for the record)
- Ensemble Decision Engine Phase 4B Step 3B — CEO decision context +
  multi-symbol signal integration (architecture.md §30 —
  `agents/decision_context.py`, `agents/multi_symbol_adapter.py`,
  `execution/portfolio_signal_provider.py`'s `get_signal_with_context()`,
  `CEOAgent.decide_from_context()`)

In Progress

- (none — see Current Priorities below for the next scoped phase)

Planned — re-scoped 2026-07-23 around a production AI trading platform
direction (each pillar below is its own future phase, scoped against
existing code before implementation — see architecture.md §25 "Next up"
for what already exists under each pillar):

- Ensemble Decision Engine (extends `agents/ceo_agent.py` + `decision/`
  + `ranking/confidence_fusion.py` — already substantially exists)
- Multi-Agent Framework enhancements (extends `agents/` +
  `graph/agent_graph.py` + `commander/` — already substantially exists;
  NOT the Anthropic MCP protocol unless later specified otherwise)
- Quant Research Pipeline (extends `research/`)
- Research/Optimization Framework (extends `ml/trainer.py` +
  `ml/model_registry.py` — needs a scoping pass to separate from the
  pillar above)
- AI Self-Improvement, human-approved only (adds an approval gate on
  top of `ml/learning_mode.py`'s existing auto-promotion logic)
- Correlation Engine / Sector Engine (real correlation tracking,
  sector-cap capital redistribution — carried forward from earlier
  phases, still open)
- Portfolio Dashboard (execution + scheduler panel — carried forward,
  still open)

---

# Architecture

Core Pipeline

Scanner

↓

Ranking Engine

↓

Portfolio Manager

↓

Risk Engine

↓

Decision Engine

↓

Execution Layer

↓

Trade Journal

↓

Dashboard

Never bypass this pipeline.

---

# Engineering Principles

Always preserve backwards compatibility.

Never rewrite completed modules.

Prefer additive changes.

Inspect existing implementation before modifying.

Never invent APIs.

Never invent class names.

Never invent method signatures.

Always inspect architecture.md before coding.

Always update architecture.md after major changes.

Always update CHANGELOG.md.

Always run tests before delivery.

Never remove tests.

Never decrease test coverage.

Never commit secrets.

Never commit databases.

Never modify RiskEngine without full inspection.

Never modify Execution Layer blindly.

Always explain architectural conflicts before implementation.

---

# Coding Workflow

Before coding

1. Read architecture.md

2. Read CLAUDE_RULES.md

3. Read ROADMAP.md

4. Inspect imports

5. Search existing implementation

6. Explain proposed design

7. Wait if architecture conflict exists

After coding

Run Ruff

Run Pytest

Update Docs

Produce unified diff

Summarize changes

---

# Current Priorities

(Portfolio Manager, Capital Allocation, and Execution Scheduler are
done — see Completed above. Priorities below re-scoped 2026-07-23.)

Priority 1

Strategy Plugin System — DONE (architecture.md §25)

Priority 2

Ensemble Decision Engine — Phase 4A DONE (architecture.md §26). Phase 4B
Step 1 DONE (architecture.md §27). Phase 4B proper DONE (architecture.md
§28). Phase 4B Step 2 DONE (architecture.md §29: journal wiring for the
multi-symbol execution path). Phase 4B Step 3A DONE (symbol isolation
prep — `AgentReport.symbol`, `CEODecision.symbol`, per-symbol
`RegimeEngine` HMM models). Phase 4B Step 3B DONE (architecture.md §30:
`agents/multi_symbol_adapter.py` bridges `PortfolioSignalProvider` ->
`CEODecisionContext` -> `CEOAgent` -> `CEODecision` with zero duplicate
MarketContextBuilder/ConfidenceEngine computation — but CEOAgent is
still NOT wired into `main.py`'s live scheduler bootstrap; the adapter
exists, nothing calls it yet in production). What's still open, scoped
precisely in §30 "Next up" rather than re-described here: 1) actually
wiring `MultiSymbolCEOAdapter` into the live `ExecutionScheduler`
bootstrap, 2) passing `symbol=` to `RegimeEngine.classify()` from
`PortfolioSignalProvider` (Step 3A's per-symbol HMM capability exists
but isn't used by the one caller that would need it — cross-symbol HMM
contamination is still live on the multi-symbol path today), 3) giving
CEOAgent's 6 sub-agents per-symbol instance state before one shared
CEOAgent safely services many symbols in a loop, 4) Phase 4C itself.

Priority 3

Multi-Agent Framework enhancements (extend `agents/` + `graph/` + `commander/`)

Priority 4

Quant Research Pipeline / Research-Optimization Framework (extend `research/` + `ml/`)

Priority 5

AI Self-Improvement, human-approved only (gate on top of `ml/learning_mode.py`)

Priority 6

Correlation Engine / Sector Engine

Priority 7

Portfolio Dashboard

---

# Do NOT

Do not rewrite the whole project.

Do not delete working code.

Do not duplicate managers.

Do not hardcode secrets.

Do not reduce modularity.

Do not break public interfaces.

Do not silently change business logic.

Do not disable tests.

Do not ignore failed tests.

---

# Success Criteria

Every feature must be:

Backward compatible

Tested

Documented

Modular

Reviewable

Production ready
