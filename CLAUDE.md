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

Ensemble Decision Engine — Phase 4A DONE (architecture.md §26:
ConfidenceEngine fused into `agents/ceo_agent.py`'s weighted vote instead
of overriding it, plus agreement/disagreement scoring). Phase 4B Step 1
DONE (architecture.md §27: `journal/journal_v2.py`'s
`get_agent_performance()` + `main.py` wiring — per-agent win/loss now
attributable via the existing `agent_decisions.signal_id` /
`trades.signal_id` linkage). Phase 4B proper (actually using these
win-rates to adjust `CEOAgent.WEIGHTS`) still open, and **only covers the
legacy single-symbol `main.py` pipeline** — `execution/
execution_orchestrator.py` (V16 multi-symbol path) does not write to the
journal at all yet (no `save_trade`/`update_trade_result` calls
anywhere in `execution/` or `portfolio/`), discovered while scoping this
phase. Wiring journal persistence into the multi-symbol path is a
separate, larger, Execution-Layer-touching gap — see architecture.md §27
"Next up" — not folded into this phase per the "never modify Execution
Layer blindly" rule.

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
