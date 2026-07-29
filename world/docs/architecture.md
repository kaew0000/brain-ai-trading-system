# Architecture Overview

See the root [WORLD.md](../WORLD.md) for the full Phase W1 report. This file
mirrors the key points for readers browsing `docs/` directly.

Brain AI Command World is a one-directional, read-only reflection of engine
state:

```
Trading Engine -> world/data snapshots -> renderer (any engine) -> UI panels
```

No arrow points back into the engine. See `naming-conventions.md`,
`coding-standards.md`, and `asset-conventions.md` for how contributions to
this folder should be structured.

**Visual theme (Phase W2):** Brain AI Command World is a modern office
headquarters, not a fantasy setting — this is locked, see
`docs/architecture/WORLD_OFFICE_POLICY.md` and `WORLD_DESIGN_LOCK.md`
(canonical) and `OFFICE_LAYOUT.md` in this folder for the current floor
plan and department list.
