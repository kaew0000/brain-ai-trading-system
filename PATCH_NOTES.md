# PATCH NOTES — World usable on phones / narrow screens (V16 §95)

Branch: `fix/world-responsive-layout-s95`
Base: `main` at `71bb682` (PR #135, §94 merged)
Commit: `fix(world): responsive Office World and Studio layout (V16 §95)` (exactly one)

## Root cause (reproduced before any change)
Ran the real app (paper mode, auth on, built dashboard) in headless Chromium at 390x844. `WorldPage` (Office tab) used `grid-cols-[240px,1fr,280px]` and `StudioView`
`grid-cols-[200px,1fr,340px]` at every width. At 390 px the middle column got ~172 px and started at x=335, i.e. the world canvas was a sliver beyond the right edge;
the tab bar and Studio overflowed horizontally. Desktop (1400 px) was fine: WebSocket LIVE, avatar walks, room change, tab cycling without errors.

## Files
`dashboard_src/src/pages/world/WorldPage.tsx`, `components/StudioView.tsx`, `components/TileWorldScene.tsx` (class names / one style only), `CHANGELOG.md`,
`docs/architecture.md` (§95), this file, `MIGRATION.md`.

## Impact
CSS only. No logic, endpoint, wire format, execution, risk or journal change. At >= 1024 px the rendered layout is identical.
After the fix at 390 px the canvas is ~299 px wide inside the viewport; Studio fits without horizontal scroll (checked in Chromium).

## Not changed / limitations
- `API_AUTH_ENABLED=false`: `lib/api.ts` `ManagedWS.connect()` returns early without a token, while `enforce_ws_role()` accepts unauthenticated sockets when auth is off,
  so no `/ws/*` channel connects and the World shows DISCONNECTED. Reproduced; shared auth code, so left for a separate decision. Auth-on setups are unaffected.
- No on-screen joystick: phones use tap-to-move.
- Between 1024 and ~1280 px the 3-column layout is tight (unchanged from before).
- The layout is verified in a real browser, not by a unit test (jsdom does not evaluate Tailwind breakpoints).
