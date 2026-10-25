# PATCH NOTES — World live monitoring (V16 §82)

Branch: `feature/world-live-monitoring`
Base: `main` @ `9913aea` (PR #120 merged)
Commit: `feat(world): World live monitoring (V16 §82)` (exactly one)

## Root cause (verified in code)
1. The selected room's frame was fetched once per room selection (`WorldPage.tsx`); `/ws/world` only refreshed the room list.
2. The simulation ticked once per `LOOP_INTERVAL` (60 s) via `schedule` on the main thread: slow cycles froze it, and
   `STEP_DISTANCE_PER_TICK=0.2` meant NPCs barely moved.
3. `OfficeScene.draw()` cleared and rebuilt every sprite per frame: no glide, so any movement would have teleported.
4. No real system numbers were visible in the World UI (the data existed in `/api/world/state` but nothing rendered it).

## Changes
- Backend: `world/simulation/ticker.py` (new), `api/world_api.py` (`GET /api/world/ticker`), `main.py` (start/stop, fallback),
  `config/settings.py` + `.env.example` (2 settings), `world/simulation/{timeline,engine,api}.py` (`set_history_window`).
- Frontend: `useLiveFrame.ts` (new), `pulse.ts` + `components/SystemPulse.tsx` (new), `components/OfficeScene.tsx` (glide, skip
  identical frames), `sceneMapping.ts` (`frameSignature`, `characterTweenOffset`), `WorldPage.tsx`, `api.ts`, `types.ts`,
  `game/config/world.config.ts` (live-view constants).
- Docs: `docs/architecture.md` §82, `CHANGELOG.md`, this file, `MIGRATION.md`.

## Verification (actually executed)
`ruff check .` clean; `pytest tests/` 3463 passed / 0 failed; `pytest world/tests -m ""` (as CI) 580 passed;
`npx tsc --noEmit` clean; `npx vitest run` 168/168; `npm run build` ok. Mutation checks: removing the hook's in-flight guard
and letting the ticker propagate step errors each make the new tests fail.
Not verified: the visual smoothness of the glide in a real browser (Phaser needs a canvas; the pure offset/signature logic,
the hook and the build are tested, the on-screen result needs a manual look).

## Limitations / follow-up
- P&L, win rate, avg R:R are journal figures across ALL execution lanes (live + paper-training); a live-only split needs a
  change to the world export (`telemetry/world_export.py`).
- Open exchange positions and floating P&L are not exported to the World (existing gap); not shown.
- NPC step is still 0.2 logical units per tick (about 2-3 px/s at the 2 s default): visible but a slow stroll; making it
  configurable is a small follow-up.
- Each open dashboard tab refetches the selected room's frame once per tick (about 0.5 request/s).
- Pausing/seeking in the Timeline tab freezes the Office scene on that state (existing design).
