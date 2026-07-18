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

In Progress

- Portfolio Manager
- Capital Allocation
- Correlation Engine

Planned

- Adaptive AI
- Learning Engine
- Portfolio Dashboard
- Strategy Evolution
- Self Optimization

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

Priority 1

Portfolio Manager

Priority 2

Capital Allocation

Priority 3

Correlation Engine

Priority 4

Sector Engine

Priority 5

Execution Scheduler

Priority 6

Portfolio Dashboard

Priority 7

Adaptive AI

Priority 8

Learning Engine

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
