# PATCH NOTES — V16 Phase 2C + feat(world-performance-v1)

## Backend: Phase 2C — Portfolio API

Branch: `feature/phase2c-portfolio-api`
Base: `main` @ `6dd7f21` (Phase 2B merged)

### Summary

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

### New modules

| File | Purpose |
|---|---|
| `api/portfolio_api.py` | REST endpoints (`APIRouter`, included into the existing `api/app.py` singleton) |
| `api/portfolio_ws.py` | `/ws/portfolio` — hooks into `api/app.py`'s existing `_broadcast_loop()`, no new poll loop |
| `api/portfolio_serializers.py` | Pure row-dict → JSON shaping, `source`/`live` marker on every payload |

### Changes to existing modules

| File | Change |
|---|---|
| `portfolio/portfolio_history.py` | + `query_decisions()`, `count_decisions()`. `get_latest_decisions()` untouched — same signature, same one existing caller. |
| `api/app.py` | + 3 import lines, + `app.include_router()` x2, + one `await _portfolio_ws_check()` call inside the existing broadcast loop, + module docstring endpoint list update. No existing route/behavior changed. |
| `docs/architecture.md` | New §19 (design + the conflict above); old §19 "Next up" renumbered to §20, with one stale bullet updated to reflect this phase now existing. |
| `CHANGELOG.md` | New entry. |

**Nothing was removed or had its public signature changed.** Every Phase
2A/2B module (`CapitalManager`, `CorrelationEngine`, `PortfolioState`,
`PortfolioManager`, `SectorEngine`, `portfolio_history`) is untouched.

### Test results

- 92 new tests added. Full suite: 1188 → **1280 passed, 0 failed**.
- `test_portfolio_serializers.py` 33, `test_portfolio_history_query.py` 14,
  `test_portfolio_api.py` 27, `test_portfolio_ws.py` 18.

---

## Frontend: feat(world-performance-v1)

Branch: `feature/world-performance-v1`
Base: `main` @ `fc9afa1` (Phase 2C merged)

### Summary

Frontend performance and UX pass for Brain Bot V16 Dashboard. Introduces
React.lazy code-splitting, Zustand store equality guards, World HQ Minimap
v2, and a new Portfolio Dashboard backed by MockDataProvider adapters.

### Changes

#### Architecture
- **Code Splitting**: All routes converted to `React.lazy()` with `<Suspense>`
  fallback (`PageLoader`). Initial bundle no longer eagerly loads every page.
- **Error Boundary**: Global `ErrorBoundary` in `main.tsx` prevents white-screen
  crashes and offers a branded recovery UI.
- **Store Equality**: All Zustand stores now use shallow / semantic equality
  guards, eliminating re-render storms caused by 1 Hz WS heartbeats with
  unchanged payloads.

#### World HQ
- **WorldPage**: Wrapped in `React.memo`; NPC position updates throttled to
  200 ms; event listeners use named `off()` cleanup instead of
  `removeAllListeners()`.
- **Minimap v2**: Offscreen canvas caches static terrain; room label tooltips on
  hover; CSS `backdrop-blur` overlay; `willReadFrequently` canvas hint.
- **Asset Pipeline**: New `AssetPipeline.ts` utility for priority-based asset
  preloading (critical / deferred / on-demand).

#### Portfolio Dashboard
- **MockDataProvider**: `MockPortfolioProvider` delivers realistic mock portfolio
  data wrapped
