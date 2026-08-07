# Live Operations Workspace & Command Console — Phase W12

Status: implemented. Supersedes the narrower "W12 (proposed)" placeholder
in `world/docs/roadmap.md` (closing W11's two documented gaps) — that
placeholder was never built or committed, only suggested; this is the
real, authoritative Phase W12, commissioned with a much larger, detailed
spec. The two gaps it named (event->room mapping, exchange-position
accessor) remain open and are proposed as part of Phase W13 below.

## 1. Architecture Report

Every one of the 10 features in this phase's brief reduces to: read
`WorldState`/`SimulationState`/`world.interaction`, compose it into a
workspace-shaped view, optionally track a small piece of purely-UI state
(pinned/read notifications, panel layout, navigation history) that has no
equivalent anywhere in Track A. Nothing here duplicates business logic —
"CEO panel status" is Phase W7's `SimulationState.characters[i].behavior`
under a business-friendly label, not a second status computation.

```
world.runtime (W5) + world.simulation (W7) + world.interaction (W9)
        |  read only
        v
world/workspace/  (10 feature modules + api.py facade)
        |
        v
api/workspace_api.py  (REST, /api/workspace/*, additive into api/app.py)
        |
        v
dashboard_src/.../components/WorkspacePanel.tsx  (new "Workspace" tab,
                                                    Office World page)
```

No new polling loop bypasses the existing runtime: the frontend polls
`/api/workspace/*` the same way every other panel in this dashboard
already polls its own REST endpoints (2-5s intervals); nothing here adds
a server-side scheduled job.

## 2. Folder Tree / File List

```
world/workspace/
  models.py                 # PanelLayout, WorkspaceLayout, AgentPanelState,
                             # OperationsSummary, NotificationDockItem,
                             # MissionWorkspaceItem, SearchResult,
                             # HistoryEntry, PerformanceOverlayState
  layout_manager.py          # Feature 1
  agent_workspace.py          # Feature 2
  operations_dashboard.py      # Feature 3
  notification_dock.py          # Feature 4
  mission_workspace.py           # Feature 5
  search_index.py                 # Feature 6
  quick_nav.py                     # Feature 7
  history.py                        # Feature 8
  performance_overlay.py             # Feature 9
  api.py                              # Feature 10 -- public facade

api/workspace_api.py         # REST layer, additive into api/app.py
tests/test_workspace_router.py  # REST layer tests (Track A tests/ dir,
                                 # matching tests/test_world_api.py's own
                                 # placement convention)
world/tests/test_workspace_*.py # 9 files, one per feature + api.py

world/data/schemas/workspace.schema.json
world/data/samples/workspace.sample.json
world/data/runtime/workspace.json   # UI layout state, not a Phase W4
                                     # RuntimeManager snapshot -- lives in
                                     # the same directory per this
                                     # phase's own explicit instruction

dashboard_src/src/pages/world/
  workspaceApi.ts                    # REST client
  components/WorkspacePanel.tsx       # the "Workspace" tab
  tests/workspace.test.ts              # frontend tests
```

## 3. Compatibility Report

- `ruff check world/ api/`: clean.
- `vulture`: zero new findings outside the same two already-tolerated
  categories used throughout this project -- FastAPI route handlers
  (`@router.get`/`.post` decorators vulture can't see through) and pytest
  `autouse` fixtures. Confirmed by diffing against a pre-phase baseline.
- Backend: 531/531 `world/tests`, existing suite 1966/1966 (was 1915
  before this phase -- the delta is exactly this phase's own new tests).
- Frontend: 26/26 vitest (16 pre-existing + 10 new), `tsc --noEmit` shows
  only the same pre-existing, unrelated `src/lib/api.ts` error every
  prior phase's report has noted, `vite build` succeeds.
- **A real regression was caught and fixed, not hidden**: Phase W4's own
  `test_all_six_runtime_files_present` broke once `workspace.json` joined
  `world/data/runtime/` (this phase's own explicit persistence path).
  Fixed by adding `workspace.json` to that test's known-files map and
  renaming it `test_all_seven_runtime_files_present` -- an honest update
  to an existing test given a legitimate, intentional expansion, not a
  workaround.
- **A real bug in this project's own earlier Phase W10 work was found
  and fixed while building this phase**: the frontend `NotificationItem`
  type and `NotificationsPanel.tsx` assumed a `timestamp`/`severity`/
  `read` shape for `world.interaction.api.get_notifications()` results
  that never existed -- the real `InteractionNotification` (Phase W9) has
  `category`/`roomId`/`tickNumber` instead. Caught by actually reading
  the real dataclass before writing this phase's own tests against it
  (see Section 9), rather than reusing the earlier assumption
  uncritically. Fixed in both `types.ts` and `NotificationsPanel.tsx`.

## 4. Migration Notes

Nothing in W1-W11 was modified except: one existing test file
(`world/tests/test_runtime_schema.py`, updated honestly per Section 3)
and the Phase W10 notification-shape bug fix (Section 3, also Section 9).
`api/app.py` gained one more `include_router` call, same additive pattern
as W10's own two.

## 5. Risk Analysis

- **Documented gaps, not fabricated data** (same discipline Phase W11's
  own `SEPARATION_POLICY.md` amendment established): no verified Track
  B-visible signal exists for Paper vs. Live trading mode, or for account
  equity -- `operations_dashboard.py`'s own module docstring explains
  exactly why `mode` can only be `"emergency"` or `"unknown"`, and why
  `account_equity` is always `None` today. A future telemetry export
  accessor would close this.
- **Agent panel telemetry (heartbeat/latency) is best-effort**: no
  verified mapping exists from Phase W11's dynamically-registered
  telemetry keys to this phase's 7 business-facing panel names, so those
  two fields are legitimately `None` in this test environment (no
  `DataSource` points at a real engine path yet -- true since Phase W4).
- **"Resizable/dockable panels" scoped down**: +/- buttons and a collapse
  toggle, not free-form mouse drag-resize -- see `WorkspacePanel.tsx`'s
  own scoping-note comment. Consistent with Phase W10's own "Window
  Manager" scoping decision; no drag-and-drop framework exists anywhere
  else in this codebase either.
- **Mission dependency/blocked detection is a status mapping, not a real
  graph**: `missions.schema.json` has no dependency field yet -- see
  `mission_workspace.py`'s own docstring.

## 6. Performance Report

Every `world/workspace/` module reads already-cached `WorldState`/
`SimulationState` (Phase W5/W7's own hash-gated caches) -- no new
per-request rebuild cost beyond composing already-computed data. The one
genuinely new measurement, `performance_overlay.py`'s
`simulation_update_seconds`, is a real `time.perf_counter()` wrap around
one `get_simulation_state()` call, consistently sub-millisecond in this
test environment (see `world/tests/test_workspace_performance.py`).

## 7. Test Report

- `world/tests/test_workspace_layout.py` -- 12 tests
- `world/tests/test_workspace_agent_panels.py` -- 6 tests
- `world/tests/test_workspace_operations_dashboard.py` -- 10 tests
- `world/tests/test_workspace_notifications.py` -- 8 tests
- `world/tests/test_workspace_missions.py` -- 7 tests
- `world/tests/test_workspace_search.py` -- 10 tests
- `world/tests/test_workspace_history.py` -- 10 tests
- `world/tests/test_workspace_performance.py` -- 7 tests
- `world/tests/test_workspace_api.py` -- 13 tests
- `tests/test_workspace_router.py` -- 21 tests (REST layer)
- `dashboard_src/.../tests/workspace.test.ts` -- 10 tests (frontend)

100% pass, no flaky tests (every test either uses real, deterministic
`WorldState`/synthetic fixtures, or `monkeypatch`/`vi.stubGlobal` for
anything with a genuinely external dependency).

## 8. Future W13 Proposal

**Phase W13** -- close the two gaps this phase inherited from the earlier
roadmap placeholder: (a) a verified event->room mapping (Phase W11's own
documented gap), (b) an exchange-positions accessor for real
`account_equity`. Both would directly improve this phase's own
`operations_dashboard.py` and `agent_workspace.py` honesty gaps (Section
5) from "documented `None`" to real figures.

## 9. A note on verifying assumptions

This phase's own notification-dock feature was built once against a
*wrong* assumption about `InteractionNotification`'s shape (copied from
Phase W10's earlier, also-wrong assumption) and once against the real
dataclass, after actually reading `world/interaction/models.py` rather
than trusting the earlier code. Both the wrong version and the fix are
visible in this phase's own build history -- recorded here rather than
quietly erased, since the corrected fix (Section 3) is the more useful
part.
