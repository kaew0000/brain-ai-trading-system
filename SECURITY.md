# Security Policy

This system executes live trades against Binance Futures using API
keys with (potentially) withdrawal/trading permissions. Treat any
compromise as financially serious, not just a code-quality issue.

## Secrets

- Real credentials belong only in `.env` (gitignored). Never commit
  `.env`, only `.env.example`.
- Dashboard API authentication (`API_AUTH_ENABLED`, `API_KEYS`,
  `JWT_SECRET`) is **off by default**. `api/app.py` logs a warning at
  startup when auth is disabled — don't expose the dashboard beyond
  localhost until it's turned on and `JWT_SECRET` is set to a real,
  random value of at least 32 bytes (see `TEST_REPORT.md`'s note on
  the test suite's `InsecureKeyLengthWarning`).
- Rotate any Binance API key that may have been present in a `.env`
  file that ever got committed to a public repo, immediately.

## Reporting a vulnerability

Since this is currently a single-maintainer repository, open a private
security advisory on GitHub (Security tab → "Report a vulnerability")
rather than a public issue, especially for anything related to
credential handling, order execution, or the dashboard auth flow.

## Known items to review before production/public exposure

- `API_AUTH_ENABLED` defaults to `False` — intentional for local/dev
  use, but confirm it's `True` with a real `JWT_SECRET` before exposing
  `api/app.py` beyond localhost.
- `pip-audit` runs in CI in advisory mode only (`|| true`) — it doesn't
  currently block merges. Tighten this once you've triaged the current
  dependency set.
