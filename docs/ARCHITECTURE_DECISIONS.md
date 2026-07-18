# Brain Bot V16 Architecture Decisions

Version: 16.5

---

# ADR-001

Title

ExecutionCoordinator Architecture

Status

Accepted

Decision

TradeManager will remain symbol-per-instance.

ExecutionCoordinator owns multiple TradeManager instances.

Reason

Avoid shared mutable state.

Reduce synchronization complexity.

Enable per-symbol execution.

Consequences

Easy to scale to 100+ symbols.

PortfolioManager communicates only with ExecutionCoordinator.

TradeManager stays simple.

---

# ADR-002

Scanner Design

Status

Accepted

Decision

Scanner runs as independent daemon.

Reason

Never block trading loop.

Allow background market discovery.

Consequences

Trading continues if scanner fails.

---

# ADR-003

Ranking Pipeline

Decision

Scanner

↓

Opportunity Ranker

↓

Portfolio Manager

↓

Risk Engine

↓

Decision Engine

↓

Execution

Ranking never sends orders directly.

---

# ADR-004

Risk Engine

Decision

RiskEngine is the single source of truth.

No duplicated risk calculations.

Reason

Prevent inconsistent behavior.

---

# ADR-005

Portfolio Manager

Decision

PortfolioManager owns

Capital Allocation

Exposure

Correlation

Sector Diversification

Trade Replacement

Cooldown

Execution never performs allocation logic.

---

# ADR-006

Dynamic Leverage

Decision

Leverage is determined by RiskEngine.

TradeManager only applies leverage.

---

# ADR-007

Market Scanner

Decision

Scanner fetches

Price

Volume

Funding

Spread

ATR

Open Interest

Reason

All higher layers consume scanner output only.

---

# ADR-008

Dashboard

Decision

Dashboard is read-only.

Trading commands go through authenticated API.

---

# ADR-009

Future AI

Decision

AI never bypasses RiskEngine.

AI produces recommendations.

RiskEngine approves.

---

# ADR-010

Backwards Compatibility

Never break

Public APIs

Database schema

Execution interface

Trade journal

without migration.