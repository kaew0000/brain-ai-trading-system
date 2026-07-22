# Brain Bot V16.5.0

An automated BTCUSDT (and, as of V16, optionally multi-symbol) Binance
Futures trading system. Full pipeline:

```
Data → Feature → Regime → Intelligence → Decision → Execution → Analytics
```

See `docs/architecture.md` for the full dependency graph and layer-by-layer
breakdown, and `docs/V16_PHASE1_MULTISYMBOL_MIGRATION.md` for the
multi-symbol migration notes.

This repository is the result of merging ten development-phase patch
bundles (Fix #1/#2, P1-A, P1-B1, Multi-Symbol Foundation, Scanner,
Opportunity Ranker, and related architecture/doc/test updates) back into
one clean tree, since extended through V16 Phase 2A-2E (Portfolio
Intelligence, Manager, API, and Execution Orchestrator — see
`docs/architecture.md` §17-21). See `MERGE_REPORT.md` for exactly what
was merged from where and why.

## Requirements

- Python 3.12+
- Node.js 18+ (dashboard frontend only, in `dashboard_src/`)

## Setup

```bash
python install.py        # installs requirements.txt, clones vendors/, copies .env.example -> .env
# then edit .env with your Binance API keys and settings
```

## Running

```bash
python main.py                     # live/testnet per EXECUTION_MODE in .env
uvicorn api.app:app --reload       # dashboard API
```

Convenience scripts for common modes are provided: `run_paper.sh`,
`run_testnet.sh`, `run_live.sh` (and `.bat` equivalents for Windows).

## Dashboard (frontend)

```bash
cd dashboard_src
npm install
npm run dev
```

`dashboard/` contains the pre-built static output for production serving;
`dashboard_src/` is the source. Rebuild with `npm run build` inside
`dashboard_src/` when the source changes.

## Testing

```bash
pytest tests/ -q
```

1512 tests, all passing as of V16 Phase 2F (see `docs/architecture.md`
§24) — grown from 1478 after the Bundle Manager + Phase 2E merge (§21,
§23), which itself grew from the earlier V16.5.0 merge baseline in
`TEST_REPORT.md`.

## Repository layout

Key backend packages: `agents/`, `api/` (incl. `portfolio_api.py`/`portfolio_ws.py`
from V16 Phase 2C and `execution_api.py` from V16 Phase 2E), `commander/`, `config/`, `data/`,
`decision/`, `execution/` (incl. `execution_orchestrator.py`/`execution_state.py`/
`execution_events.py`/`execution_metrics.py` from V16 Phase 2E, and
`execution_scheduler.py`/`portfolio_signal_provider.py` from V16 Phase 2F),
`features/`, `intelligence/`, `journal/`,
`ml/`, `paper/`, `pipeline/`, `portfolio/` (V16 Phase 2A/2B), `ranking/`
(V16 Phase 2), `regime/`, `risk/`, `scanner/` (V16 Phase 2),
`system_health/`, `telemetry/`, `trend/`, `utils/`.

See `docs/architecture.md` for the authoritative, generated dependency
graph — the list above is a quick orientation, not a substitute for it.

## Documentation index

- `docs/architecture.md` — package/import/execution graph
- `docs/V16_AUDIT_REPORT.md`, `docs/V16_PHASE1_MULTISYMBOL_MIGRATION.md` — V16 phase notes
- `reports/` — historical audits (V14/V15, security, performance, production-readiness)
- `MERGE_REPORT.md`, `CONFLICT_REPORT.md`, `ARCHITECTURE_REPORT.md`,
  `TEST_REPORT.md`, `CLEANUP_REPORT.md`, `GITHUB_READY_CHECKLIST.md` —
  this merge's paperwork

## License

See `LICENSE`.

