# PATCH NOTES — V16 Phase 2C: Portfolio API

Branch: `feature/phase2c-portfolio-api`
Base: `main` @ `6dd7f21` (Phase 2B merged)

## Summary

Adds a REST + WebSocket read layer over `portfolio_history` (Phase 2B's
persistence table). Decision-only boundary preserved one layer further:
this phase never calls `PortfolioManager`/`CapitalManager`, never touches
`execution/`/`data/`, never places an order.

**Architecture conflict found and resolved before building (flagged,
not silently overridden):** Phase 2B's own architecture.md §19 "Next up"
said REST/WebSocket should wait for real orchestrator wiring — verified
that's still literally true (`PortfolioManager` is never instantiated
outside tests, so `portfolio_history` is empty in production today) —
but resolved it by building the API as a genuine read layer that is
honest about that emptiness rather than waiting. See architecture.md
§19 for the full writeup.

## New modules

| File | Purpose |
|---|---|
| `api/portfolio_api.py` | REST endpoints (`APIRouter`, included into the existing `api/app.py` singleton) |
| `api/portfolio_ws.py` | `/ws/portfolio` — hooks into `api/app.py`'s existing `_broadcast_loop()`, no new poll loop |
| `api/portfolio_serializers.py` | Pure row-dict → JSON shaping, `source`/`live` marker on every payload |

## Additive changes to existing files

| File | Change |
|---|---|
| `portfolio/portfolio_history.py` | + `query_decisions()`, `count_decisions()`. `get_latest_decisions()` untouched — same signature, same one existing caller. |
| `api/app.py` | + 3 import lines, + `app.include_router()` x2, + one `await _portfolio_ws_check()` call inside the existing broadcast loop, + module docstring endpoint list update. No existing route/behavior changed. |
| `docs/architecture.md` | New §19 (design + the conflict above); old §19 "Next up" renumbered to §20, with one stale bullet updated to reflect this phase now existing. |
| `CHANGELOG.md` | New entry. |

**Nothing was removed or had its public signature changed.** Every Phase
2A/2B module (`CapitalManager`, `CorrelationEngine`, `PortfolioState`,
`PortfolioManager`, `SectorEngine`, all existing dataclasses) is
byte-for-byte unchanged.

## Endpoints

REST (all under `/api/portfolio`, existing VIEWER-role auth applies
automatically — no `api/auth.py` change needed):

| Method | Path | Returns |
|---|---|---|
| GET | `/state` | Positions implied by the latest persisted decision (NOT a live `PortfolioState`) |
| GET | `/decision/latest` | Full latest persisted `OrchestratedDecision` |
| GET | `/history` | Paginated decision history — `limit`, `offset`, `symbol`, `sector` query params |
| GET | `/sectors` | Sector exposure + diversification score from the latest decision |
| GET | `/allocations` | `selected` list from the latest decision |

WebSocket: `WS /ws/portfolio` — `init` frame on connect (always,
regardless of dedup state — reconnect-safe), then `decision`/`state`/
`sectors`/`allocations`/`replacement_proposal` events only when a new
row appears in `portfolio_history` (deduped by row id — a row id can
only newly appear once, so this is the entire dedup mechanism), plus a
`heartbeat` every 5s regardless.

## Why every payload says "not live"

Rule from this phase's brief: never fabricate runtime state, never
invent a live `PortfolioState`. Every serializer output carries
`"source": "latest_persisted_decision"` and `"live": false` explicitly,
and `/state`'s payload shape is deliberately not a mirror of
`PortfolioState` — it's "positions the latest persisted decision
selected", which is real, just not continuously live. See
`api/portfolio_serializers.py`'s module docstring for the full reasoning.

## No decision ever persisted → real empty state, not a 404

Every endpoint returns 200 with `null`/`[]`/`{}` (never a synthesized
placeholder), matching this codebase's existing `/api/paper` convention.
The WebSocket's `init` frame does the same, then the connection simply
stays idle apart from its heartbeat.

## Test results

```
pytest tests/ -m unit -q
1280 passed, 0 failed   (1188 baseline + 92 new)

ruff check . --exclude dashboard_src --exclude dashboard
All checks passed!
```

New test files: `tests/test_portfolio_serializers.py` (33),
`tests/test_portfolio_history_query.py` (14), `tests/test_portfolio_api.py`
(27), `tests/test_portfolio_ws.py` (18).

## Known limitations / follow-up (documented, not hidden)

- `portfolio_history` is empty in production until a future orchestrator
  phase calls `PortfolioManager.decide()` on a schedule — every endpoint
  here already handles that honestly today; no code change needed once
  that phase lands.
- `GET /history`'s symbol/sector filter is applied in Python over
  decoded JSON, not SQL `WHERE` (no indexed column for either in
  `portfolio_history`'s one-JSON-blob-per-row schema). `pagination.total`
  is `null` whenever a filter is active, for the same reason — an exact
  filtered count isn't cheap without decoding the whole table.
- No dashboard page consumes this API yet.

See `MIGRATION.md` for upgrade/rollback notes.
