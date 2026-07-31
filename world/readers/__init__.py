"""Generic, source-agnostic readers for Phase W4 (read-only ingestion
adapter). No reader in this package imports from, calls into, or
knows the real file layout of `agents/`, `execution/`, `portfolio/`,
`risk/`, `journal/`, `api/`, `dashboard/`, `dashboard_src/`,
`main.py`, `config/`, `scanner/`, `pipeline/`, `telemetry/`, or
`database/` — every reader is constructed with an injected
`DataSource` pointing at wherever the caller chooses; no path is
hardcoded anywhere in this package."""
