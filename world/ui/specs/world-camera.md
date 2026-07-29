# UI Panel Spec: World Camera

**Status:** Design only — not implemented in Phase W1.

## Purpose

Free/orbit camera controls for exploring the city.

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.
