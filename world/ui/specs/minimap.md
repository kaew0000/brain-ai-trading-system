# UI Panel Spec: Minimap

**Status:** Design only — not implemented in Phase W1.

## Purpose

Top-down graph of districts and connections, click to travel.

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.

## Phase W3 Renderer Mapping

`NavigationRenderer` (`world/frontend/interfaces/navigation_renderer.py`) draws the graph this panel displays; node/edge data is `world/data/navigation/graph.json`.
