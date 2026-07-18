# TEST_REPORT

Executed for real in a fresh virtualenv (Python 3.12.3) against the
merged repository — this is not a copied-forward claim from any prior
patch bundle's own documentation.

```
python -m pip install -r requirements.txt
python -m pytest tests/ -q
```

## Result

```
1001 passed, 12 warnings in 10.72s
```

**0 failed, 0 skipped.**

## Warnings (non-blocking, noted for awareness)

- `StarletteDeprecationWarning`: `starlette.testclient` using `httpx`
  is deprecated upstream; recommends `httpx2`. Cosmetic, not urgent.
- `InsecureKeyLengthWarning` (PyJWT, 4 occurrences in
  `test_api_auth.py`): the test suite's dummy JWT secret is 30 bytes,
  below PyJWT's recommended 32-byte minimum for HS256. Test-only value;
  confirm `JWT_SECRET` used in real deployments is ≥32 bytes/256 bits.
- `ConvergenceWarning` / `UserWarning` (scikit-learn, in
  `test_phase3_complete.py`): the outcome-predictor tests train a
  `LogisticRegression`/`GradientBoostingClassifier` on small synthetic
  data; the solver not converging within `max_iter=500` and the missing
  feature-name warning are artifacts of the test fixtures, not the
  production training pipeline.

## Test files executed (34 files, 1001 collected items)

`test_agent_graph.py`, `test_agents.py`, `test_api.py`,
`test_api_auth.py`, `test_audit_fixes.py`, `test_commander.py`,
`test_data.py`, `test_decision.py`, `test_execution.py`,
`test_execution_coordinator.py`, `test_execution_factory.py`,
`test_features.py`, `test_market_intelligence.py`,
`test_market_scanner.py`, `test_mission_pipeline_integration.py`,
`test_mission_tracker.py`, `test_opportunity_ranker.py`,
`test_p1b1_dynamic_risk.py`, `test_phase3.py`,
`test_phase3_complete.py`, `test_phase4c.py`,
`test_reasoning_stream.py`, `test_regime.py`, `test_telemetry.py`,
`test_v15_production.py`, `test_v16_execution_idempotency.py`.

## Coverage

Not measured in this pass — `pytest-cov` is included in
`.github/workflows/ci.yml` for ongoing coverage tracking, but running
it here wasn't part of this merge verification. Run
`pytest --cov=. --cov-report=term` locally if you want a number now.

## Static analysis (ruff)

```
ruff check . --exclude dashboard_src --exclude dashboard
```

**391 findings, 0 errors that block a merge** (all style/lint-level,
not correctness bugs — no undefined names, no syntax errors):

| Code | Count | Meaning |
|---|---|---|
| E702 | 143 | multiple statements on one line (semicolon) |
| E701 | 139 | multiple statements on one line (colon) — mostly `trend/trend_engine.py`'s compact scoring blocks |
| F401 | 58 | unused import (72 fixable automatically with `ruff check --fix`) |
| F841 | 26 | unused variable |
| E401 | 13 | multiple imports on one line |
| E402 | 4 | import not at top of file |
| E722 | 4 | bare `except:` |
| E731 | 2 | lambda assigned to a variable |
| E741 | 1 | ambiguous variable name |
| F541 | 1 | f-string with no placeholders |

None of these were introduced by the merge — they're pre-existing style
debt in the codebase carried over from the patch snapshot. Recommend a
follow-up `ruff check --fix` pass as a separate, reviewable commit
rather than folding auto-fixes silently into this merge.

## Dead code (vulture, ≥80% confidence)

```
api/app.py:71: unused import '_cb_snapshots'
database/db.py:166: unused variable 'tb'
database/db.py:199: unused variable 'tb'
decision/causal_explainer.py:204: unused variable 'weight_pct'
system_health/circuit_breaker.py:107: unused variable 'exc_tb'
telemetry/agent_telemetry.py:217: unused variable 'exc_tb'
```

Six low-risk findings, all unused local names (several are `exc_tb`
from `except ... as (exc_type, exc_val, exc_tb)`-style unpacking where
the traceback isn't used) — safe cleanup candidates, not merged/fixed
here to keep this merge's diff focused.

## mypy

No `mypy.ini`, `mypy` section in a config file, or `pyproject.toml`
exists in the repository, so per the task's own instruction ("mypy if
configured") this was skipped rather than run with invented settings.
If you want type checking in CI, let me know your preferred strictness
and I'll add a config.
