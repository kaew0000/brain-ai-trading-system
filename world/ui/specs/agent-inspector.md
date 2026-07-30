# UI Panel Spec: Agent Inspector

**Status:** Design only — not implemented in Phase W1.

## Purpose

Detail panel for a selected character: role, dialogue, current animation state.

## Data Sources (read-only)

Consumes one or more of: `world.json`, `districts.json`, `characters.json`,
`relationships.json`, `events.json`, `missions.json`, `notifications.json`.

## Notes

Engine-neutral: implementable equally in React, PixiJS, Phaser, Godot, or
Unity, since it only reads the JSON contracts in `data/schemas/`.

## Phase W3 Renderer Mapping

`CharacterRenderer` (`world/frontend/interfaces/character_renderer.py`) is what this panel's underlying scene uses to draw the selected character; this panel itself just reads `characters.json` + `AnimationController.current_state`.
