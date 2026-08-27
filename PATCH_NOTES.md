# PATCH NOTES — V16 Phase 4C §51: HFT Flow Enabling-for-Live Switch (HFT-6b)

Branch: `feature/hft-6b-live-enable-switch`
Base: `main` @ `884278d` (merge of PR #80, training-lane restore-on-restart)

## Scope note

Requested directly: "ต้องการให้ระบบตรวจจับสภาพคล่อง liquidity เพื่อช่วยตัดสินใจเทรด"
(want the system to detect liquidity to help trade decisions), narrowed
after inspection to: activate the real order-book depth signal that
HFT-1 through HFT-6 (`docs/architecture.md` §45) already built and
fully tested, but deliberately left inert. Confirmed via fresh clone +
grep across `agents/`, `ranking/`, `decision/`, `execution/`, `risk/`
that this repo already has three separate "liquidity" concepts (SMC
liquidity pools for TP targeting, a volume+spread proxy in the scanner
ranking factor, and this real depth-based HFT flow signal) plus one
confirmed gap (no pre-trade slippage/depth guard in `execution/` or
`risk/` — out of scope for this patch, `execution_orchestrator.py`'s
`_compute_slippage()` remains post-fill measurement only, unchanged).

Two explicit choices confirmed before writing any code:
- `HFT_FLOW_LIVE_WEIGHT = 5.0` (the conservative value HFT-6 already
  named for live use, not HFT-5's own 20.0 paper-testing example)
- `HFT_FLOW_CONTRADICTION_ENABLED = true` alongside it, not staged separately

Applied to the currently-running `EXECUTION_MODE=paper` deployment —
this is exactly the safe lane HFT-6's own docstring says this evidence
should be gathered in before any live-money config profile.

Track A only (Python backend). No `dashboard_src/`/frontend changes,
no database schema changes.

## Context

`decision/confidence_engine.py`'s `DEFAULT_WEIGHTS["hft_flow"]` has been
hardcoded to `0.0` since HFT-5, and `config/settings.py::HFT_FLOW_LIVE_WEIGHT`
existed only as "a named, auditable config value... nothing in this
codebase reads it automatically" — HFT-6's own scope was deliberately
"config value + docs only, no other new logic." The documented
"Enabling for live" procedure (`docs/architecture.md` §45) required a
manual, untested, one-off edit at whichever `ConfidenceEngine()` call
site an operator was using. Verified by inspection that
`main.py:414`'s `confidence_engine = ConfidenceEngine()` is the single
live construction site in the entire repo (injected into
`PortfolioSignalProvider` via `build_strategy()`, covering both the
legacy single-symbol loop and the multi-symbol `ExecutionScheduler`
path) — `pipeline/brain_pipeline_v13.py`'s own `ConfidenceEngine(weights=weights)`
is dead code, imported by nothing else. `.env.example` never listed
`HFT_WS_ENABLED`, `HFT_FLOW_LIVE_WEIGHT`, or `HFT_FLOW_CONTRADICTION_ENABLED`
at all, so none of this was discoverable from the VPS without reading
source.

## What changed

| File | Change |
|---|---|
| `config/settings.py` | `+HFT_FLOW_LIVE_ENABLED: bool` (default `False`) — the actual opt-in switch, separate from `HFT_FLOW_LIVE_WEIGHT` so a candidate weight can sit in config without silently taking effect. Updated the now-stale "nothing reads it automatically" comment on `HFT_FLOW_LIVE_WEIGHT`. |
| `decision/confidence_engine.py` | `+resolve_confidence_weights()` — returns `DEFAULT_WEIGHTS` untouched unless `HFT_FLOW_LIVE_ENABLED` is `True`, else a copy with `hft_flow` set to `HFT_FLOW_LIVE_WEIGHT`. Never mutates the shared `DEFAULT_WEIGHTS` constant. Module docstring's "HFT Flow integration" section updated to document it. |
| `main.py` | `build_system()`'s Decision Layer: `ConfidenceEngine()` → `ConfidenceEngine(weights=resolve_confidence_weights())`, plus a startup log line (only when the live weight is active) echoing `HFT_FLOW_LIVE_WEIGHT`/`HFT_FLOW_CONTRADICTION_ENABLED`/`HFT_WS_ENABLED` together, so an operator can see at a glance whether the *whole* chain — not just this one flag — is actually live. |
| `.env.example` | New "HFT Flow" section documenting all four previously-undiscoverable flags, each at its existing safe default. |
| `tests/test_hft_flow_live_enable_switch.py` | New, 6 tests: switch off (returns `DEFAULT_WEIGHTS`), switch on (applies live weight), custom weight value, `DEFAULT_WEIGHTS` never mutated, `ConfidenceEngine` construction with resolved weights both ways, and the new setting's shipped default. |

No changes to `RiskEngine`, `ExecutionCoordinator`,
`execution/ceo_gated_signal_provider.py`, `commander/control_state.py`,
journal schema, or `database/db.py` — verified by direct inspection,
matching HFT-1 through HFT-6's own scope boundary.

## Testing

- New: 6/6 passed (`tests/test_hft_flow_live_enable_switch.py`)
- Regression, HFT-suite: 156/156 passed (`test_hft_flow_live_weight_config.py`,
  `test_hft_shadow_mode.py`, `test_phase3.py`, `test_hft_flow_scorer.py`,
  `test_hft_flow_confidence_integration.py`, plus the new file)
- Full backend suite: 2922 passed, 45 deselected — same 3 pre-existing
  `tests/test_dashboard_serving.py` failures (no frontend build present
  in this environment; confirmed unrelated, present on unmodified `main`)
- `ruff check`: clean on all 4 touched files
- `vulture --min-confidence 80`: clean on all 4 touched files (the one
  finding, `main.py:76` unused `frame` arg, is a pre-existing standard
  signal-handler parameter, not part of this diff)
- `python3 -c "import main"`: succeeds

## Activation (operator action required — not automatic)

Add to the live-running `.env` on the VPS, then restart:
```
HFT_WS_ENABLED=true
HFT_FLOW_LIVE_ENABLED=true
HFT_FLOW_CONTRADICTION_ENABLED=true
```
`HFT_FLOW_LIVE_WEIGHT` already defaults to `5.0` — no need to add it
unless a different value is wanted. See `MIGRATION.md` for what to
expect after restart.
