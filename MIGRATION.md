# MIGRATION — World usable on phones / narrow screens (V16 §95)

## Required
None. Frontend-only (CSS classes). No schema, config or API change. Rebuild the dashboard (`ensure_dashboard` / §84 does this on start).

## What you will notice
- Below 1024 px wide (phones, small tablets) the Office tab and Studio show the world first, full width; the room list / roster, inspector and chat follow beneath it.
  Tap a spot to walk there; the Talk button replaces `E`.
- At 1024 px and above the layout is exactly as before.

## Rollback
`git revert` the commit (no data involved).
