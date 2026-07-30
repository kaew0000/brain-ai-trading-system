# UI Panel Spec: Notification Center

**Status:** Design only — not implemented in Phase W1.

## Purpose

Aggregated notifications with severity and read state.

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.

## Phase W3 Renderer Mapping

Rendered on the `notification` layer (`LayerType.NOTIFICATION`, `world/frontend/scene/layer.py`) via `LayerRenderer`.
