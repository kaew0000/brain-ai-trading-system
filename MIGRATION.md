# MIGRATION — V16 ML Extensions Integration Layer (observe-only)

## Do you need to do anything?

**Only if you want the feature active.** This patch is purely additive
and off by default — `ML_EXTENSIONS_ENABLED` defaults to `False`, so
`build_system()` skips the entire integration block and every existing
component (`CEOAgent`, `ExecutionOrchestrator`, the dashboard) is
byte-identical to before this phase. An existing `.env` with none of
the new keys sees no behavior change at all.

To activate:
1. Install `ml/extensions/`'s optional dependencies:
   ```
   pip install -r ml/extensions/requirements.txt
   ```
   (gymnasium, stable-baselines3, torch, river, optuna — not part of
   the main `requirements.txt`; a fresh production deployment does not
   have these unless installed explicitly.)
2. Add to `.env` and restart:
   ```
   ML_EXTENSIONS_ENABLED=true
   ```

## What to expect after activating

- Startup: `build_system()` constructs an `ExtensionsOrchestrator` and
  registers an `MLExtensionsAgent` with the live `CEOAgent` under the
  key `"ml_extensions"`. This key is **not** one of `CEOAgent.WEIGHTS`'
  6 keys — the agent runs every cycle (visible in telemetry, the
  reasoning stream, and the dashboard's agent panel) but cannot change
  `LONG`/`SHORT`/`WAIT` or any confidence score. Verified with a
  worst-case automated test (a stub agent reporting `LONG` at 100%
  confidence under this same key changes nothing about the decided
  action).
- `GET /api/ml_extensions/status` will report `enabled: true,
  agent_registered: true`.
- `GET /api/ml_extensions/rl/status`, `/online/metrics`, `/hpo/status`
  will all report `ready: false` until `train_rl()` /
  `start_online_learning()` / `optimize_strategy()` are explicitly
  called on the orchestrator — **this phase does not train or run any
  model**, it only wires the plumbing. Calling those training methods
  is separate, future work.
- `GET /api/ml_extensions/agent/last-report` shows the most recent
  `AgentReport` from `MLExtensionsAgent` — signal `NEUTRAL` (action 0)
  until a real RL/online model exists, since `ExtensionsOrchestrator.
  get_action()` gracefully returns `HOLD` with no trained components.
- No data is fetched from Binance until the integration is enabled AND
  a `data_provider`/historical OHLCV source is actually available in
  `main.py`'s `build_system()` scope; without one, `MLExtensionsAgent`
  reports `status: not_ready` instead of erroring.
- If any part of wiring fails (missing optional dependency, a
  transient error, anything) it is caught and logged as a warning —
  `ml_extensions_components` becomes `None`/`{"enabled": False}` and
  the rest of the bot boots and trades exactly as before this phase.

## Rollback

Set `ML_EXTENSIONS_ENABLED=false` and restart — reverts to
byte-identical pre-patch behavior. No code rollback or database change
needed either way; nothing in this patch touches the database.

## Note on the optional dependency install

Without `ml/extensions/requirements.txt` installed, `wire_all()` fails
non-fatally the moment it tries to import `ml.extensions.orchestrator`
(that import itself requires gymnasium — see `docs/architecture.md`
§53's "Post-commit fix" addendum) — logged as a warning, never raised.
`GET /api/ml_extensions/status` will show `enabled: false` in that case
even with `ML_EXTENSIONS_ENABLED=true` set. This is expected, not a
bug: install the optional requirements first if you want the feature
to actually activate, not just be toggled on.
