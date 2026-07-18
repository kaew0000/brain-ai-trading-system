# Brain Bot Module Index

Version 16.5

---

Scanner

scanner/

Market discovery

Produces Opportunity objects

↓

Ranking

ranking/

Opportunity scoring

Composite Score

Confidence

↓

Portfolio

portfolio/

Capital allocation

Portfolio optimization

Exposure

Correlation

↓

Risk

risk/

RiskEngine

Daily limits

Dynamic leverage

Position sizing

↓

Decision

decision/

Trading decision

Signal validation

↓

Execution

execution/

ExecutionCoordinator

TradeManager

PaperTrading

LiveTrading

↓

Journal

journal/

Trade history

Performance

Statistics

↓

ML

ml/

Feature engineering

Training

Inference

↓

Agents

agents/

CEO

Risk Manager

Research

ML Scientist

↓

Dashboard

dashboard/

React UI

Charts

Portfolio

World View

↓

API

api/

REST

WebSocket

Authentication

↓

System Health

system_health/

Heartbeat

Watchdog

Recovery

Circuit Breaker

Reconciliation

↓

Database

database/

SQLite

Schema

Migration

↓

Config

config/

Settings

Environment

↓

Utils

utils/

Logging

Retry

Cache

Helpers

---

Dependency Order

Scanner

↓

Ranking

↓

Portfolio

↓

Risk

↓

Decision

↓

Execution

↓

Journal

↓

Dashboard

Never violate this dependency chain.