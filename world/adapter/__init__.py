"""Read-only ingestion adapter (Phase W4). Reads via
`world.readers.*`, aggregates into an `EngineSnapshot`
(`engine_snapshot.py`), and `SnapshotBuilder`
(`snapshot_builder.py`) turns that into the stable JSON shapes that
`world.runtime.runtime_manager.RuntimeManager` writes to
`world/data/runtime/`.

Nothing in this package writes a file. Nothing in this package
imports from `agents/`, `execution/`, `portfolio/`, `risk/`,
`journal/`, `api/`, `dashboard/`, `dashboard_src/`, `main.py`,
`config/`, `scanner/`, `pipeline/`, `telemetry/`, or `database/`."""
