"""Renderer-agnostic interfaces for Brain AI Command World, Phase W3.

Every class in this package is an `abc.ABC` with no rendering
implementation. A future renderer (PixiJS via a Python bridge, a
Godot export, a React Canvas driver, or anything else) implements
these interfaces; nothing in `world/` ever imports a specific engine.

Read-only presentation layer: nothing here imports from, calls into,
or depends on `agents/`, `execution/`, `risk/`, `portfolio/`,
`journal/`, `api/`, `dashboard/`, `dashboard_src/`, or `main.py`.
"""
