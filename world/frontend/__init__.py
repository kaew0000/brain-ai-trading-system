"""Brain AI Command World — renderer foundation (Phase W3).

Engine-agnostic abstraction layer. No Phaser/PixiJS/Godot/Unity/React
code anywhere in this package — see `world/frontend/README.md`.

Read-only presentation layer: nothing here imports from, calls into,
or depends on `agents/`, `execution/`, `risk/`, `portfolio/`,
`journal/`, `api/`, `dashboard/`, `dashboard_src/`, or `main.py`.
"""
