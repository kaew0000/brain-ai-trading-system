// ============================================================
// Brain Bot V15 — Map Loader
// Procedurally generates the full HQ tile map using room
// definitions. Fills paths between rooms with stone paths.
// ============================================================

import { ROOM_DEFINITIONS, TILE_SIZE, MAP_COLS, MAP_ROWS } from './Room';
import type { TileType, RoomDefinition, WorldMap } from './types/world.types';
import { NPC_DEFINITIONS } from './Room';

// ── Tile ID constants ─────────────────────────────────────────────────────────

const TILE_MAP: Record<TileType, number> = {
  void:               0,
  grass:              1,
  path:               2,
  water:              3,
  wall:               4,
  floor_ceo:          5,
  floor_mission:      6,
  floor_risk:         7,
  floor_intelligence: 8,
  floor_futures:      9,
  floor_ml:           10,
  floor_command:      11,
  floor_portfolio:    12,
  floor_replay:       13,
  floor_server:       14,
  floor_data:         15,
  floor_training:     16,
  floor_meeting:      17,
  floor_emergency:    18,
  floor_teleport:     19,
  floor_plaza:        20,
};

export const TILE_ID = TILE_MAP;

// Room ID → floor tile type
const ROOM_FLOOR: Record<string, TileType> = {
  ceo:          'floor_ceo',
  mission:      'floor_mission',
  risk:         'floor_risk',
  intelligence: 'floor_intelligence',
  futures:      'floor_futures',
  ml_lab:       'floor_ml',
  command:      'floor_command',
  portfolio:    'floor_portfolio',
  replay:       'floor_replay',
  server:       'floor_server',
  data_center:  'floor_data',
  training:     'floor_training',
  meeting:      'floor_meeting',
  emergency:    'floor_emergency',
  teleport:     'floor_teleport',
  plaza:        'floor_plaza',
};

// ── Grid ──────────────────────────────────────────────────────────────────────

function createGrid(cols: number, rows: number, fill: TileType = 'grass'): TileType[][] {
  return Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => fill)
  );
}

function setTile(grid: TileType[][], x: number, y: number, type: TileType): void {
  if (x >= 0 && x < MAP_COLS && y >= 0 && y < MAP_ROWS) {
    grid[y][x] = type;
  }
}

function getTile(grid: TileType[][], x: number, y: number): TileType {
  if (x < 0 || x >= MAP_COLS || y < 0 || y >= MAP_ROWS) return 'void';
  return grid[y][x];
}

// ── Room placement ────────────────────────────────────────────────────────────

function placeRoom(grid: TileType[][], room: RoomDefinition): void {
  const floorType: TileType = ROOM_FLOOR[room.id] ?? 'floor_plaza';

  for (let dy = 0; dy < room.th; dy++) {
    for (let dx = 0; dx < room.tw; dx++) {
      const x = room.tx + dx;
      const y = room.ty + dy;

      // Wall border (1 tile thick)
      const isWall =
        dx === 0 || dx === room.tw - 1 || dy === 0 || dy === room.th - 1;

      setTile(grid, x, y, isWall ? 'wall' : floorType);
    }
  }

  // Door opening at bottom center
  const doorX = room.tx + Math.floor(room.tw / 2);
  const doorY = room.ty + room.th - 1;
  setTile(grid, doorX, doorY, floorType);
  setTile(grid, doorX + 1, doorY, floorType);

  // Door opening at top center (for rooms not on top edge)
  if (room.ty > 3) {
    setTile(grid, doorX, room.ty, floorType);
    setTile(grid, doorX + 1, room.ty, floorType);
  }
}

// ── Path drawing ──────────────────────────────────────────────────────────────

function drawHorizontalPath(
  grid: TileType[][],
  x1: number,
  x2: number,
  y: number,
  width = 2,
): void {
  const startX = Math.min(x1, x2);
  const endX = Math.max(x1, x2);
  for (let x = startX; x <= endX; x++) {
    for (let w = 0; w < width; w++) {
      if (getTile(grid, x, y + w) === 'grass' || getTile(grid, x, y + w) === 'void') {
        setTile(grid, x, y + w, 'path');
      }
    }
  }
}

function drawVerticalPath(
  grid: TileType[][],
  x: number,
  y1: number,
  y2: number,
  width = 2,
): void {
  const startY = Math.min(y1, y2);
  const endY = Math.max(y1, y2);
  for (let y = startY; y <= endY; y++) {
    for (let w = 0; w < width; w++) {
      if (getTile(grid, x + w, y) === 'grass' || getTile(grid, x + w, y) === 'void') {
        setTile(grid, x + w, y, 'path');
      }
    }
  }
}

function connectRooms(
  grid: TileType[][],
  r1: RoomDefinition,
  r2: RoomDefinition,
): void {
  const cx1 = r1.tx + Math.floor(r1.tw / 2);
  const cy1 = r1.ty + Math.floor(r1.th / 2);
  const cx2 = r2.tx + Math.floor(r2.tw / 2);
  const cy2 = r2.ty + Math.floor(r2.th / 2);

  // L-shaped path: horizontal then vertical
  drawHorizontalPath(grid, cx1, cx2, cy1, 2);
  drawVerticalPath(grid, cx2, cy1, cy2, 2);
}

// ── Water borders ─────────────────────────────────────────────────────────────

function addWaterBorder(grid: TileType[][]): void {
  // Left and right edges
  for (let y = 0; y < MAP_ROWS; y++) {
    for (let x = 0; x < 2; x++) {
      setTile(grid, x, y, 'water');
      setTile(grid, MAP_COLS - 1 - x, y, 'water');
    }
  }
  // Top and bottom edges
  for (let x = 0; x < MAP_COLS; x++) {
    setTile(grid, x, 0, 'water');
    setTile(grid, x, 1, 'water');
    setTile(grid, x, MAP_ROWS - 1, 'water');
    setTile(grid, x, MAP_ROWS - 2, 'water');
  }
}

// ── Decorative elements ───────────────────────────────────────────────────────

function addDecoration(grid: TileType[][]): void {
  // Add some water ponds in grass areas
  const ponds = [
    { x: 30, y: 20, w: 5, h: 3 },
    { x: 75, y: 40, w: 4, h: 4 },
    { x: 15, y: 52, w: 3, h: 3 },
    { x: 85, y: 20, w: 5, h: 3 },
  ];
  for (const pond of ponds) {
    for (let dy = 0; dy < pond.h; dy++) {
      for (let dx = 0; dx < pond.w; dx++) {
        const x = pond.x + dx;
        const y = pond.y + dy;
        if (getTile(grid, x, y) === 'grass') {
          setTile(grid, x, y, 'water');
        }
      }
    }
  }
}

// ── Main export ───────────────────────────────────────────────────────────────

/** Build the complete world map tile grid */
export function buildWorldMap(): WorldMap {
  const grid = createGrid(MAP_COLS, MAP_ROWS, 'grass');

  // Place all rooms
  for (const room of ROOM_DEFINITIONS) {
    placeRoom(grid, room);
  }

  // Connect rooms with paths
  // Row 1 connections (horizontal)
  const ceo      = ROOM_DEFINITIONS.find((r) => r.id === 'ceo')!;
  const meeting  = ROOM_DEFINITIONS.find((r) => r.id === 'meeting')!;
  const mission  = ROOM_DEFINITIONS.find((r) => r.id === 'mission')!;
  const training = ROOM_DEFINITIONS.find((r) => r.id === 'training')!;
  const risk     = ROOM_DEFINITIONS.find((r) => r.id === 'risk')!;

  connectRooms(grid, ceo, meeting);
  connectRooms(grid, meeting, mission);
  connectRooms(grid, mission, training);
  connectRooms(grid, training, risk);

  // Row 2 connections
  const intel = ROOM_DEFINITIONS.find((r) => r.id === 'intelligence')!;
  const plaza = ROOM_DEFINITIONS.find((r) => r.id === 'plaza')!;
  const mlLab = ROOM_DEFINITIONS.find((r) => r.id === 'ml_lab')!;

  connectRooms(grid, intel, plaza);
  connectRooms(grid, plaza, mlLab);

  // Row 3 connections
  const futures = ROOM_DEFINITIONS.find((r) => r.id === 'futures')!;
  const replay  = ROOM_DEFINITIONS.find((r) => r.id === 'replay')!;
  const teleport = ROOM_DEFINITIONS.find((r) => r.id === 'teleport')!;
  const command = ROOM_DEFINITIONS.find((r) => r.id === 'command')!;

  connectRooms(grid, futures, replay);
  connectRooms(grid, replay, teleport);
  connectRooms(grid, teleport, command);

  // Row 4 connections
  const portfolio = ROOM_DEFINITIONS.find((r) => r.id === 'portfolio')!;
  const emergency = ROOM_DEFINITIONS.find((r) => r.id === 'emergency')!;
  const dataCenter = ROOM_DEFINITIONS.find((r) => r.id === 'data_center')!;
  const server    = ROOM_DEFINITIONS.find((r) => r.id === 'server')!;

  connectRooms(grid, portfolio, emergency);
  connectRooms(grid, emergency, dataCenter);
  connectRooms(grid, dataCenter, server);

  // Vertical connections (row 1 → row 2 → row 3 → row 4)
  connectRooms(grid, ceo, intel);
  connectRooms(grid, intel, futures);
  connectRooms(grid, futures, portfolio);

  connectRooms(grid, mission, plaza);
  connectRooms(grid, plaza, teleport);

  connectRooms(grid, risk, mlLab);
  connectRooms(grid, mlLab, command);
  connectRooms(grid, command, server);

  // Cross connections for reachability
  connectRooms(grid, meeting, intel);
  connectRooms(grid, training, mlLab);
  connectRooms(grid, emergency, replay);
  connectRooms(grid, dataCenter, teleport);

  // Water border
  addWaterBorder(grid);

  // Decorative water ponds
  addDecoration(grid);

  return {
    cols: MAP_COLS,
    rows: MAP_ROWS,
    tileSize: TILE_SIZE,
    tiles: grid,
    rooms: ROOM_DEFINITIONS,
    npcs: NPC_DEFINITIONS,
  };
}

// ── Tile query helpers ────────────────────────────────────────────────────────

/** Returns true if a tile is walkable (floor or path) */
export function isWalkable(tile: TileType): boolean {
  return (
    tile === 'path' ||
    tile.startsWith('floor_')
  );
}

/** Returns true if a tile blocks movement */
export function isBlocking(tile: TileType): boolean {
  return tile === 'wall' || tile === 'water' || tile === 'void';
}

/** Get the room at a tile coordinate, or null */
export function getRoomAtTile(
  tx: number,
  ty: number,
  rooms: RoomDefinition[],
): RoomDefinition | null {
  for (const room of rooms) {
    if (
      tx >= room.tx && tx < room.tx + room.tw &&
      ty >= room.ty && ty < room.ty + room.th
    ) {
      return room;
    }
  }
  return null;
}

/** Get room center in tile coordinates */
export function getRoomCenter(room: RoomDefinition): { tx: number; ty: number } {
  return {
    tx: room.tx + Math.floor(room.tw / 2),
    ty: room.ty + Math.floor(room.th / 2),
  };
}

/** Get room center in pixel coordinates */
export function getRoomCenterPx(room: RoomDefinition): { x: number; y: number } {
  const { tx, ty } = getRoomCenter(room);
  return {
    x: tx * TILE_SIZE + TILE_SIZE / 2,
    y: ty * TILE_SIZE + TILE_SIZE / 2,
  };
}

/** Convert tile coordinates to pixel center */
export function tileToPx(tx: number, ty: number): { x: number; y: number } {
  return {
    x: tx * TILE_SIZE + TILE_SIZE / 2,
    y: ty * TILE_SIZE + TILE_SIZE / 2,
  };
}

/** Convert pixel coordinates to tile */
export function pxToTile(x: number, y: number): { tx: number; ty: number } {
  return {
    tx: Math.floor(x / TILE_SIZE),
    ty: Math.floor(y / TILE_SIZE),
  };
}
