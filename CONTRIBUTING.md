# Contributing

This is currently a single-maintainer trading bot repository. If that
changes, replace this file with a fuller policy; for now:

## Workflow

1. Branch from `main`.
2. Make changes, add/update tests under `tests/`.
3. `pytest tests/ -q` must pass locally before opening a PR.
4. `ruff check .` should not introduce *new* findings (391 pre-existing
   ones are tracked in `TEST_REPORT.md`; don't let the count grow).
5. Open a PR against `main`. CI (`.github/workflows/ci.yml`) runs lint,
   tests, and an advisory `pip-audit` scan automatically.

## Code style

- Follow the existing module layer structure described in
  `docs/architecture.md` (Data → Feature → Regime → Intelligence →
  Decision → Execution → Analytics). New functionality should slot into
  an existing layer or, if genuinely new, get documented there.
- New settings go in `config/settings.py` as `Field(default=...)` with
  a safe, backward-compatible default — see the pattern used for
  `SCANNER_ENABLED`, `API_AUTH_ENABLED`, etc. (default off/inert so
  existing deployments are unaffected).
- Never commit `.env`, real API keys, or the `.db` files — see
  `SECURITY.md` and `.gitignore`.

## Tests

New backend features should ship with tests in `tests/`, following the
existing per-module test file naming (`test_<module>.py`).
