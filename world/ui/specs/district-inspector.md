# UI Panel Spec: District Inspector

**Status:** Design only — not implemented in Phase W1.

## Purpose

Detail panel for a selected district: purpose, assigned agents, current theme.

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.

## Phase W3 Renderer Mapping

`DistrictRenderer` (`world/frontend/interfaces/district_renderer.py`) draws the room this panel describes; room/floor data is `world/data/layout/rooms.json`.
