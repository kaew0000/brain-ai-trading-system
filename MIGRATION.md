# MIGRATION — V16 Phase 2C + feat(world-performance-v1)

## Backend: Phase 2C — Portfolio API

### Do you need to do anything?

**No code changes required for existing callers.** Nothing in Phase 2A
or Phase 2B (`CapitalManager`, `CorrelationEngine`, `PortfolioState`,
`PortfolioManager`, `SectorEngine`, `portfolio_history.save_decision()`/
`get_latest_decisions()`, every existing dataclass) changed signature,
behavior, or default. This phase only adds new files plus new,
additive functions — nothing existing was touched in a way that affects
any current caller.

### If you want to start using the API

It's already live once this branch is deployed — `api/app.py` includes
both routers unconditionally, no feature flag or config change needed.

```bash
curl http://localhost:8000/api/portfolio/state
# {"ok": true, "data": {"positions": [], "total_capital_allocated": 0.0,
#   "blocked": null, "source": "latest_persisted_decision", "live": false,
#   "as_of": null, "note": "No portfolio decision has ever been persisted yet..."}}
