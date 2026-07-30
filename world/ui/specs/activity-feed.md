# UI Panel Spec: Activity Feed

**Status:** Design only — not implemented in Phase W1.

## Purpose

Scrolling log of recent events across all districts.

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.

## Phase W3 Renderer Mapping

Rendered on the `ui_overlay` layer (`world/frontend/scene/layer.py`) via `LayerRenderer`.
