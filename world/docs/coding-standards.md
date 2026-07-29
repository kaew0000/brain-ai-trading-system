# Coding Standards (world/)

- Python placeholder scripts/tests must pass `ruff check world/`.
- No dependency on the trading engine's internal modules — `world/` code may
  only read plain files (JSON) that the engine happens to produce; it must
  never `import` from `agents/`, `execution/`, `portfolio/`, `journal/`,
  `risk/`, `api/`, or `dashboard/`.
- Keep schema files framework-neutral: no engine-specific types.
- Prefer small, additive JSON Schema changes over breaking changes.
