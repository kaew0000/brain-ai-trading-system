# MIGRATION — V16 Phase 3A: Strategy Plugin System

## Do you need to do anything?

**No code changes required for existing callers.** Existing behavior
is byte-for-byte unaffected:

- `config/settings.py`'s new `STRATEGY_NAME` defaults to
  `"portfolio_signal_provider"` — resolves to the exact same
  `PortfolioSignalProvider` class `main.py` constructed directly
  before this phase, with the exact same constructor arguments.
- `execution/strategy.py`, `execution/portfolio_signal_provider.py`,
  and `execution/execution_orchestrator.py` are all completely
  unmodified.
- `main.py`'s single-symbol trading loop is untouched.
- No `.env` change is required to deploy this phase.

## If you want to select a different strategy

It's opt-in only. To change it:

```bash
# .env
STRATEGY_NAME=portfolio_signal_provider   # default — safe for ExecutionScheduler
```

`"smc_oi_regime"` is also registered but **not recommended for the
scheduler path** — see PATCH_NOTES.md "Known limitation" and
`docs/architecture.md` §25 "Scope boundary" before selecting it.
Setting `STRATEGY_NAME` to any unregistered name causes
`ExecutionScheduler` startup to fail with a clear, logged
`KeyError: Unknown strategy '...'` message — the same non-fatal,
logged-and-skipped pattern `SCHEDULER_ENABLED=true but
SCANNER_ENABLED=false` already uses (see main.py's existing
`try/except` around this whole block, unchanged by this phase).

## Adding your own strategy (for future phases / plugin authors)

```python
from execution.strategy_registry import register_strategy

def my_strategy_factory(**kwargs):
    # kwargs superset: data_provider, regime_engine, smc_engine,
    # volume_engine, context_builder, confidence_engine
    return MySignalProvider(data_provider=kwargs["data_provider"])

register_strategy(
    "my_strategy",
    my_strategy_factory,
    description="What it does and what it needs.",
)
```

Then set `STRATEGY_NAME=my_strategy` in `.env`. See
`execution/strategy_registry.py`'s module docstring for the full
contract (`Callable[[str], Optional[ExecutionSignal]]`).

## Roadmap note

This phase is the first of a re-scoped, six-pillar roadmap (Ensemble
Decision Engine, Multi-Agent Framework, Strategy Plugin System — done,
Quant Research Pipeline, Research/Optimization Framework, AI
Self-Improvement). See `docs/architecture.md` §25 "Next up" and
`CLAUDE.md`'s "Current Priorities" for what already exists under each
remaining pillar — each is planned as its own scoped phase, not a
single combined commit.
