# Live Operations Center — Phase W11

Status: implemented. Wires the Phase W4 ingestion pipeline — built but
never connected to real data until now — to the trading engine's own
existing read-only accessors, and schedules it alongside Phase W10's
simulation tick. No new architecture layer, no new dashboard, no
duplicated EventBus/NotificationCenter/Timeline (all three already
existed, from Phase W9 — see §7).

## 1. Architecture Report

Track A gained one new file (`telemetry/world_export.py`) and one small,
additive instrumentation change (`system_health/circuit_breaker.py`'s
`call()` now times itself). Everything else touched is Track B, and is
either a new file or a backward-compatible extension of an existing one.
No file in `agents/`, `execution/`, `risk/`, or `portfolio/`'s decision
logic was modified — `telemetry/world_export.py` only *calls* their
existing read-only accessors.

```
Track A (unchanged decision/execution logic)
    |
    |  telemetry.agent_telemetry.get_telemetry_registry().snapshot()
    |  system_health.heartbeat.get_heartbeat().get_all()
    |  system_health.circuit_breaker.all_snapshots()          (latency: new instrumentation, additive)
    |  missions.mission_tracker.get_mission_tracker().get_active()
    |  portfolio.portfolio_history.get_latest_decisions(limit=1)
    |  journal_v2.get_daily_stats()                            (instance from main.py's components dict)
    |  events.event_bus.get_event_bus().get_recent()
    |  psutil.cpu_percent() / psutil.virtual_memory()          (the one genuinely new source)
    v
telemetry/world_export.py  (NEW — Track A side, read-only, one-way)
    |  export_snapshot() writes 5 JSON files
    v
world/data/runtime_input/{telemetry,events,missions,portfolio,journal}.json
    |
    v
world/readers/*.py  (Phase W4, unchanged — JSONFileSource + 5 Readers)
    v
world/adapter/adapter.py — ReadOnlyIngestionAdapter.capture_snapshot() (unchanged, +1 field read)
    v
world/adapter/snapshot_builder.py — SnapshotBuilder (unchanged, +1 optional field per file)
    v
world/data/runtime/{telemetry,events,missions,portfolio,notifications,world}.json
    (RuntimeManager.run_once() — Phase W4, unchanged, atomic write-if-changed)
    v
world/runtime/state_builder.py — StateBuilder.build() (unchanged, +1 optional field)
    v
world.runtime.api.get_world_state() -> WorldState  (Phase W5, unchanged)
    v
api/world_api.py (REST) + api/world_ws.py (WebSocket)   (Phase W10, unchanged)
    v
dashboard_src (React) — Office World tab                (Phase W10, unchanged)
```

`main.py` gained two things, both additive and both mirroring Phase
W10's `_tick_world_simulation()` pattern exactly:

- `_get_world_runtime_manager()` — lazily builds and caches the
  `ReadOnlyIngestionAdapter` + `RuntimeManager` wiring (five readers,
  each bound to a `JSONFileSource` in the staging directory). Pure
  object wiring — no I/O at construction time.
- `_run_world_runtime_manager(components)` — calls
  `telemetry.world_export.export_snapshot()` then
  `RuntimeManager.run_once()`, wrapped in the same
  `try/except Exception: logger.debug(...)` pattern as
  `_tick_world_simulation()`. Scheduled at the same
  `schedule.every(settings.LOOP_INTERVAL).seconds` cadence, right after
  the existing simulation tick.

## 2. Data Flow

Two independent stages, both one-way, both file-based (no shared
process memory, no sockets, no new IPC mechanism):

1. **Track A -> staging** (`telemetry/world_export.py`, new): calls the
   eight accessors listed in §1, maps each into the raw row shape its
   matching Phase W4 reader already expects, and atomically writes
   (`os.replace` from a `.tmp` file — never a half-written JSON file) five
   files into `world/data/runtime_input/`.
2. **Staging -> runtime output** (`RuntimeManager.run_once()`, Phase W4,
   unchanged): reads the five staging files via the existing readers,
   builds an `EngineSnapshot`, and writes `world/data/runtime/*.json`
   only for files whose content actually changed (`SnapshotCache`'s
   existing write-if-changed behavior).

Both stages run once per `LOOP_INTERVAL` (same cadence as every other
per-cycle Track A work), driven by the trading loop's own `schedule`
instance — no new thread, no new event loop, no polling interval
independent of the trading cycle.

## 3. Synchronization Design

There is no live push/subscribe channel between Track A and Track B —
deliberately. `events.event_bus.get_event_bus()` is a real pub/sub bus
with a `subscribe()` API, but `world_export.py` uses only its pull-based
`get_recent()` method. This keeps the *whole* pipeline (both stages
above) on the same "poll once per cycle, write only on change" model
Phase W4 already built and Phase W10 already proved safe in production
— rather than adding a second, architecturally different live-push path
alongside it. A true push channel (e.g. subscribing and broadcasting
straight over `api/world_ws.py`) is a reasonable future direction but is
new architecture, not wiring, and was out of scope for "connect the
existing systems" (Krush's framing for this phase).

## 4. Operations Center Design

No new "Operations Center" module was built. Phase W9's
`world/interaction/` package already has everything that name would
describe — `EventBus`, `NotificationCenter`, `Timeline`,
`relationship_resolver` (department ownership) — and Phase W10 already
serves all of it through one dashboard. W11's job was narrower and is
now done: give those already-built consumers real data instead of an
idle placeholder. Building a *second* "Operations Center" on top would
have been exactly the duplicate-module outcome the project's own rules
rule out.

## 5. Event Flow

```
Track A agent/subsystem code -> events.event_bus.get_event_bus().publish(agent, event, message, severity)
    v
EventBus's in-memory ring buffer (1000 events, already existed)
    v
world_export.event_rows() -- get_recent(limit=100), maps BusEvent -> EventReader's raw row shape
    v
world/data/runtime_input/events.json
    v
EventReader.read() (Phase W4, unchanged) -> world/data/runtime/events.json
    v
StateBuilder -> WorldState.events
    v
world/interaction/notification_center.py (Phase W9, UNCHANGED) already turns
warning/critical severity events into notifications automatically --
no new code needed here, confirmed by test_interaction_notifications.py
staying green with zero modifications.
```

Two vocabulary translations happen in `world_export.event_rows()`, both
documented in code and in `docs/architecture/SEPARATION_POLICY.md`'s W11
amendment rather than silently guessed:

- `BusEvent.severity` (`debug`/`info`/`warning`/`error`) ->
  `EventReader.VALID_SEVERITIES` (`info`/`success`/`warning`/`critical`):
  `error` -> `critical`, everything else passes through or defaults to
  `info`.
- District placement: no mapping exists between `BusEvent.agent`'s real
  subsystem names (`RISK_MANAGER`, `SMC_ANALYST`, ...) and the Phase W1
  district `assignedAgents` codenames (`PRIMUS`, `BASTION`, ...). Every
  bus-sourced event is placed in `command-hall` (Command Center) as a
  neutral, always-valid fallback; the real agent name is preserved
  as-is in the event's `agent` field, so labels are still correct even
  though room placement isn't agent-specific yet. See §8.

## 6. Timeline Design

No changes to `world/interaction/` timeline code. Phase W9's Timeline
already merges `SimulationState.events` chronologically and supports
replay; it was already agnostic to *where* an event came from. Once
`WorldState.events` started containing real trading events (via the
flow in §5) instead of only simulation-generated ones, the Timeline
started showing both automatically.

## 7. Compatibility Report

- **No existing file's public return type changed.** `PortfolioReader.
  read()` still returns `list[PortfolioPosition]`; the new
  `PortfolioSummary` is exposed via a side-channel attribute
  (`reader.last_summary`), read by the adapter only via `getattr(...,
  default=None)` — a reader stub without that attribute (e.g. an older
  test double) behaves exactly as before.
- **No schema field became required.** `portfolio.schema.json`'s new
  `summary` object, and every field inside it, is optional.
  `SnapshotBuilder.build_portfolio()` omits the `summary` key entirely
  (not `null`, not zeros) when there's nothing to report — verified by
  `test_build_portfolio_has_no_summary_key_when_snapshot_has_none`.
- **No existing test was modified to make it pass.** All new coverage
  is additive (see §11).
- **`main.py`'s trading loop is untouched except two lines**: one new
  `schedule.every(...).do(...)` call and the missing `import os` the new
  code needed. `_run_world_runtime_manager()`'s own body is a single
  `try/except Exception: logger.debug(...)`, identical in shape to the
  pre-existing `_tick_world_simulation()`.

## 8. Known Gaps (documented, not silently worked around)

- **No agent-codename mapping.** See §5 — a real mapping between Track
  A's subsystem names and Track B's district `assignedAgents` codenames
  doesn't exist anywhere in the codebase. Proposed as W12 (§13 of
  `world/docs/roadmap.md`).
- **No live open-exchange-positions accessor.** `portfolio.json`'s
  `positions` array remains empty. What *is* wired
  (`portfolio_history.get_latest_decisions()`) reflects the Portfolio
  Manager's most recent *decision cycle*, not necessarily positions
  currently open on the exchange — these are related but not proven
  identical, so no proxy value was fabricated in its place.
- **Mission stage -> status mapping is a simplification.** Track A's six
  mission stages collapse into Track B's two active statuses
  (`proposed`/`active`) — `SIGNAL_FOUND` -> `proposed`, everything else
  active-but-not-closed -> `active`. `complete`/`aborted` never appear
  from this path since `get_active()` already excludes `CLOSED` missions
  at the source.
- **True exchange/API call latency is not separately exported.**
  `CircuitBreaker.call()`'s new `last_latency_ms` covers every call site
  that already goes through a named breaker; call sites that use the
  `with breaker:` context-manager form directly (bypassing `.call()`)
  are not timed — an explicit, requested scope boundary, not an
  oversight.

## 9. Performance Considerations

- One export cycle touches: 2 in-memory registry reads (telemetry,
  heartbeat), 1 dict copy (circuit breaker snapshots), 1 in-memory list
  read (missions, ring-buffer-backed), 1 SQLite read
  (`get_latest_decisions(limit=1)`, indexed, single row), 1 SQLite read
  (`get_daily_stats()`, single day aggregate), 1 in-memory ring-buffer
  read (`get_recent(limit=100)`), and 2 `psutil` calls. All in-memory
  or single-row/indexed reads; no full-table scans.
- Five small JSON files (typically a few KB total) are written per
  cycle via `os.replace` (atomic rename, no partial-read risk for any
  concurrent reader). `RuntimeManager.run_once()`'s existing
  write-if-changed cache means the *next* stage (staging ->
  `world/data/runtime/`) only writes a file when its content actually
  differs from last cycle.
- Cadence is `settings.LOOP_INTERVAL` — the same cycle the trading loop
  and the Phase W10 simulation tick already run on. No new timer, no
  sub-cycle polling.
- `psutil.cpu_percent(interval=None)` is intentionally non-blocking
  (compares against the last call rather than sleeping to sample) — it
  never adds latency to the trading loop it rides alongside.

## 10. Risk Analysis

- **Correctness risk:** every accessor's exact signature and return
  shape was read from source before being called (not assumed) — see
  each accessor's citation in `telemetry/world_export.py`'s own
  docstring. Two genuine vocabulary mismatches were found in the
  process (§8) and handled with a documented, conservative fallback
  rather than a guess.
- **Availability risk:** none of the eight new/changed dependencies can
  block or fail the trading loop — `_run_world_runtime_manager()`'s
  `try/except Exception` matches `_tick_world_simulation()`'s existing,
  already-production-proven pattern, and every individual accessor
  inside `world_export.py` is separately wrapped so one failing source
  (e.g. `psutil` unavailable) doesn't blank out the other four.
- **Data-integrity risk:** the one deliberate policy exception (real
  PnL/drawdown/win-rate crossing the Track A/B boundary) is documented
  in `docs/architecture/SEPARATION_POLICY.md`, not silently introduced;
  every summary field is independently optional and omitted (never
  fabricated as 0) when the trading engine didn't supply it.
- **Regression risk:** full existing suites re-run clean after every
  change in this phase (Track A 1942/1942, World 447/447 — see the W11
  Test Report), not just the new tests.

## 11. Testing

New, additive coverage (existing test files were extended, not
rewritten, except by adding new test functions):

- `tests/test_circuit_breaker_latency.py` (new) — `call()`'s latency
  instrumentation: recorded on success and on failure, existing
  return-value/exception/state-transition behavior unchanged.
- `tests/test_world_export.py` (new) — every `telemetry/world_export.py`
  function, against the *real* registries (not mocks) wherever no SQLite
  dependency is involved, plus round-trip tests proving each output file
  is directly consumable by its matching Phase W4 reader.
- `world/tests/test_portfolio_reader_summary.py` (new) — both raw shapes
  `PortfolioReader` now accepts, side by side, including the
  Phase-W4-bare-list backward-compatibility case.
- `world/tests/test_adapter.py` (+3 tests) — `portfolio_summary`
  propagation, including the never-fatal case.
- `world/tests/test_snapshot_builder.py` (+3 tests) — `summary` object
  present/absent/partial, each validated against the updated JSON
  Schema.
- `world/tests/test_state_builder.py` (+3 tests) — `portfolio.json`'s
  `summary` parses through to `WorldState.portfolio_summary` and
  `to_dict()`.

## 12. Failure Handling

Every new failure mode degrades to "this cycle's export is incomplete,"
never to "the trading loop stops" or "a stale/wrong value is shown":

- A single broken accessor (e.g. a locked SQLite file) -> that one
  section of the payload is empty/omitted this cycle; the other four
  stay populated (`_safe()` wrapper, tested in
  `test_telemetry_rows_survive_a_broken_source`).
- The whole export failing -> caught by `_run_world_runtime_manager()`'s
  `try/except`, logged at debug level, trading loop continues
  unaffected — same empirically-proven pattern as Phase W10.
- A partially-written staging file -> impossible by construction
  (`os.replace` from a temp file is atomic on POSIX).
- A reader encountering a missing/malformed staging file ->
  Phase W4's existing behavior, unchanged: `ReadOnlyIngestionAdapter`
  already treats any reader exception as "no data this capture," not a
  crash.
