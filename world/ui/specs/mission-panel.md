# UI Panel Spec: Mission Panel

**Status:** Design only — not implemented in Phase W1.

## Purpose

Lists narrative missions derived from engine objectives (flavor, read-only).

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.

## Phase W3 Renderer Mapping

Data-only panel — no dedicated renderer interface; reads `missions.json` directly and renders on the `ui_overlay` layer.
