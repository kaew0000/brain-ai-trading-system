# Runtime Data Flow — Phase W4

```
Trading Engine (agents/ execution/ journal/ portfolio/ risk/ telemetry/ ...)
        |
        | (not wired yet - future DataSource pointed at a real path/table/log)
        v
DataSource   (world/readers/base.py: JSONFileSource | CSVFileSource |
              SQLiteSource | LogFileSource | EventBusSource[interface-only])
        |
        v
Reader       (world/readers/*_reader.py: Journal | Telemetry | Portfolio |
              Mission | Event - each returns plain dataclasses)
        |
        v
ReadOnlyIngestionAdapter.capture_snapshot()   (world/adapter/adapter.py)
        |
        v
EngineSnapshot   (world/adapter/engine_snapshot.py - one timestamped aggregate)
        |
        v
SnapshotBuilder.build_all()   (world/adapter/snapshot_builder.py)
        |
        v
RuntimeManager.run_once()   (world/runtime/runtime_manager.py)
        |  -> SnapshotCache.write_if_changed() per file (world/runtime/cache.py)
        v
world/data/runtime/
    world.json  events.json  missions.json
    portfolio.json  telemetry.json  notifications.json
        |
        v
(Phase W5+) a WorldStateProvider implementation
(world/frontend/interfaces/world_state.py, Phase W3) reads these six
files and constructs a WorldState for the renderer.
```

## Who decides *when* to run

`RuntimeManager` never schedules itself. A `Watcher`
(`world/watchers/filesystem_watcher.py` or
`world/watchers/polling_watcher.py`) answers "has the source at this
path changed since I last checked?" — whoever eventually schedules
`RuntimeManager.run_once()` (a cron-style loop, a Termux service, a
future orchestrator — not designed in this phase) decides whether to
call `Watcher.has_changed(source_path)` first and skip the run
entirely, or just run on a fixed interval regardless. Both are valid;
neither is implemented here.

## Two independent "skip if unchanged" layers

It's worth being explicit that there are two different hash checks in
this pipeline, at two different points, for two different reasons:

1. **`Watcher`** (optional, external to `RuntimeManager`) — checks
   whether the *source* changed, to decide whether it's worth running
   the pipeline at all.
2. **`SnapshotCache`** (inside `RuntimeManager`) — checks whether the
   *resulting output* changed, to decide whether it's worth writing
   each of the six files, even after the pipeline did run (e.g. the
   source changed in a way that doesn't affect a particular output
   file).

Neither layer assumes the other exists; `RuntimeManager.run_once()`
works correctly even if nothing ever calls a `Watcher`.
