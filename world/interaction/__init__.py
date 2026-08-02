"""world.interaction — Phase W9, Interactive Command Center.

Read-only interaction layer over Phase W5 (`world.runtime`) and Phase W7
(`world.simulation`) state, plus a Phase W8-aligned camera wrapper
(`world.frontend.camera`). No trading engine code (`agents/`,
`execution/`, `portfolio/`, `learning/`, `risk/`, `exchange/`) is
imported anywhere in this package. See `world/docs/INTERACTION_LAYER.md`.
"""
