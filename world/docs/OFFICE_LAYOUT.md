# Office Layout — Brain AI Headquarters

Status: Phase W2 deliverable. Data-first, engine-neutral (see
`docs/architecture/WORLD_OFFICE_POLICY.md` and `WORLD_DESIGN_LOCK.md` —
those documents are canonical; this file is the human-readable index on
top of `world/data/layout/`).

---

## Headquarters structure

Brain AI Headquarters is a 3-floor modern office building. Every
department on every floor corresponds 1:1 to an existing Phase W1
district definition in `world/districts/definitions/` — this phase
adds a *spatial* layer (floor, position, camera framing, navigation)
on top of that existing data. No department, agent, or connection was
invented; none were removed.

Source of truth for structure:
- `world/data/layout/floors.json` — which rooms sit on which floor
- `world/data/layout/rooms.json` — per-room floor, connections, spawn
  location, camera anchor
- `world/data/characters/placement.json` — which desk/room each
  existing character works from
- `world/data/navigation/graph.json` — the path graph connecting every
  room, including elevators between floors

## Floors

| Floor | Name | Departments |
|---|---|---|
| 1 | Ground Floor — Reception & Support | Reception, Recovery Center, Garden, Training Room |
| 2 | Floor 2 — Trading & Operations | Trading Floor, Risk Department, Command Center, Journal Department, Server Room |
| 3 | Floor 3 — Intelligence & Executive | CEO Office, AI Department, Research Lab, Market Intelligence Center, Simulation Room |

Rationale: public/support functions (onboarding, recovery, wellness,
training) stay on the ground floor near Reception; the trading
engine's live operational core (execution, risk, command, journal,
servers) occupies floor 2; research, strategy, and executive oversight
sit on floor 3, above the operational floor they oversee.

## Departments

Full per-department detail (purpose, visual theme, connected rooms,
future expansion hooks) is in `ROOM_SPECIFICATIONS.md` in this same
folder — generated directly from `world/districts/definitions/` so it
can never drift out of sync with the data.

## Navigation

`world/data/navigation/graph.json` is a plain node/edge path graph:

- **Room nodes** — one per department, tagged with its floor.
- **Elevator nodes** — one per floor (`elevator-floor-1/2/3`), each
  connected to every room on that floor and to the elevator node on
  the adjacent floor. This is how cross-floor connections are
  represented without claiming any single department is "next to"
  another department on a different floor.
- **Edges** are undirected (a corridor works both ways) and carry a
  `distance` weight for a future pathfinding implementation — none is
  implemented in this phase.

Every room is reachable from Reception (`world-gateway`); this is
enforced by `world/tests/test_navigation_validity.py`.

## Explicitly out of scope for W2

No renderer, no sprites, no pixel art, no Phaser/PixiJS/Godot/Unity/
React code. Positions in `rooms.json` are abstract office units for a
future renderer to interpret, not pixel coordinates.
