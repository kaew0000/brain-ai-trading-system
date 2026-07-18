// ============================================================
// Brain Bot V15 — Tiled Map Builder
// Converts the procedural room/grid data (Room.ts / MapLoader.ts)
// into a genuine Tiled-JSON-format tilemap object, registers it
// with Phaser's tilemap cache, and builds real
// Phaser.Tilemaps.TilemapLayer instances from it — ground, road,
// water and a collision layer. No Canvas/Graphics-drawn terrain.
// ============================================================

import Phaser from 'phaser';
import { packTileset, type PackedTileset } from './TilesetPacker';
import { ROOM_DEFINITIONS, TILE_SIZE, MAP_COLS, MAP_ROWS } from '../Room';
import { getRoomAtTile } from '../MapLoader';
import type { WorldMap, TileType } from '../types/world.types';

// ── Tileset composition ────────────────────────────────────────
// Every physical tile that can appear on Ground/Road/Water layers,
// mapped to its AssetRegistry texture key.
const GROUND_TILE_ENTRIES = [
  { name: 'grass', textureKey: 'tile__grass_plain' },
  { name: 'grass_flowers', textureKey: 'tile__grass_flowers_multi' },
  { name: 'void', textureKey: 'tile__void_tile' },
  { name: 'wall', textureKey: 'tile__wall_tile' },
  { name: 'wall_corner', textureKey: 'tile__wall_corner_tile' },
  { name: 'floor_tech', textureKey: 'tile__floor_tech_plain' },
  { name: 'floor_tech_ornate', textureKey: 'tile__floor_tech_ornate' },
];

const ROAD_TILE_ENTRIES = [
  { name: 'road_straight', textureKey: 'tile__road_straight' },
  { name: 'road_corner', textureKey: 'tile__road_corner' },
  { name: 'road_cross', textureKey: 'tile__road_cross' },
  { name: 'road_tjunction', textureKey: 'tile__road_tjunction' },
  { name: 'road_end', textureKey: 'tile__road_end' },
];

function waterEntries(): Array<{ name: string; textureKey: string }> {
  return Array.from({ length: 9 }, (_, i) => ({
    name: `water_${i}`,
    textureKey: `tile__water_${i}`,
  }));
}

export interface BuiltTilemap {
  groundMap: Phaser.Tilemaps.Tilemap;
  roadMap: Phaser.Tilemaps.Tilemap;
  waterMap: Phaser.Tilemaps.Tilemap;
  collisionMap: Phaser.Tilemaps.Tilemap;
  groundLayer: Phaser.Tilemaps.TilemapLayer;
  roadLayer: Phaser.Tilemaps.TilemapLayer;
  waterLayer: Phaser.Tilemaps.TilemapLayer;
  collisionLayer: Phaser.Tilemaps.TilemapLayer;
  groundTileset: PackedTileset;
  roadTileset: PackedTileset;
  waterTileset: PackedTileset;
  waterFrameIds: number[]; // gid for water_0..water_8, for animation swaps
}

/** Empty (Tiled uses 0 for "no tile") 2D grid, cols x rows, all zero. */
function emptyGrid(): number[][] {
  return Array.from({ length: MAP_ROWS }, () => new Array(MAP_COLS).fill(0));
}

function isWallCorner(tx: number, ty: number): boolean {
  const room = getRoomAtTile(tx, ty, ROOM_DEFINITIONS);
  if (!room) return false;
  const dx = tx - room.tx;
  const dy = ty - room.ty;
  return (dx === 0 || dx === room.tw - 1) && (dy === 0 || dy === room.th - 1);
}

/** Classify a path tile's road piece by looking at its 4 neighbours. */
function roadPieceFor(worldMap: WorldMap, tx: number, ty: number): string {
  const at = (x: number, y: number): boolean =>
    worldMap.tiles[y]?.[x] === 'path';
  const n = at(tx, ty - 1);
  const s = at(tx, ty + 1);
  const e = at(tx + 1, ty);
  const w = at(tx - 1, ty);
  const count = [n, s, e, w].filter(Boolean).length;
  if (count >= 3) return 'road_cross';
  if (count === 2 && ((n && s) || (e && w))) return 'road_straight';
  if (count === 2) return 'road_corner';
  if (count === 1) return 'road_end';
  return 'road_straight';
}

/**
 * Build the full Tiled-compatible JSON document for the world, pack
 * the tilesets, register everything with Phaser, and create the
 * TilemapLayers. Call after AssetRegistry textures are loaded
 * (i.e. inside create(), not preload()).
 */
export function buildTiledWorldMap(
  scene: Phaser.Scene,
  worldMap: WorldMap,
  cacheKey = 'worldmap',
): BuiltTilemap {
  // ── 1. Pack tilesets from already-loaded AssetRegistry textures ──
  const groundTileset = packTileset(scene, 'tileset__ground', TILE_SIZE, GROUND_TILE_ENTRIES);
  const roadTileset = packTileset(scene, 'tileset__road', TILE_SIZE, ROAD_TILE_ENTRIES);
  const waterTileset = packTileset(scene, 'tileset__water', TILE_SIZE, waterEntries());

  // ── 2. Build per-layer index grids from the room/grid data ──────
  const groundGrid = emptyGrid();
  const roadGrid = emptyGrid();
  const waterGrid = emptyGrid();
  const collisionGrid = emptyGrid();

  for (let ty = 0; ty < MAP_ROWS; ty++) {
    for (let tx = 0; tx < MAP_COLS; tx++) {
      const tile: TileType = worldMap.tiles[ty][tx];

      if (tile === 'water') {
        waterGrid[ty][tx] = waterTileset.idByName.get('water_0') ?? 0;
        continue;
      }

      if (tile === 'path') {
        roadGrid[ty][tx] = roadTileset.idByName.get(roadPieceFor(worldMap, tx, ty)) ?? 0;
        groundGrid[ty][tx] = groundTileset.idByName.get('grass') ?? 0;
        continue;
      }

      if (tile === 'wall') {
        const name = isWallCorner(tx, ty) ? 'wall_corner' : 'wall';
        groundGrid[ty][tx] = groundTileset.idByName.get(name) ?? 0;
        collisionGrid[ty][tx] = 1; // any non-zero = solid
        continue;
      }

      if (tile.startsWith('floor_')) {
        groundGrid[ty][tx] = groundTileset.idByName.get('floor_tech') ?? 0;
        continue;
      }

      if (tile === 'void') {
        groundGrid[ty][tx] = groundTileset.idByName.get('void') ?? 0;
        collisionGrid[ty][tx] = 1;
        continue;
      }

      // grass (default)
      groundGrid[ty][tx] = groundTileset.idByName.get('grass') ?? 0;
    }
  }

  // ── 3. Assemble one genuine Tiled-JSON document per tile layer ───
  // Each layer gets its own single-tileset map (firstgid always 1).
  // This sidesteps Tiled's global-GID-namespace rules entirely — no
  // risk of one layer's tile indices accidentally being resolved
  // against another layer's tileset image.
  function singleLayerTiledJson(
    layerName: string,
    data: number[],
    tileset: PackedTileset,
    opacity: number,
  ) {
    return {
      compressionlevel: -1,
      width: MAP_COLS,
      height: MAP_ROWS,
      tilewidth: TILE_SIZE,
      tileheight: TILE_SIZE,
      infinite: false,
      orientation: 'orthogonal',
      renderorder: 'right-down',
      type: 'map',
      version: '1.10',
      tiledversion: '1.10.2',
      nextlayerid: 2,
      nextobjectid: 1,
      tilesets: [
        {
          firstgid: 1,
          name: layerName.toLowerCase(),
          image: tileset.textureKey,
          imagewidth: tileset.columns * TILE_SIZE,
          imageheight: tileset.rows * TILE_SIZE,
          tilewidth: TILE_SIZE,
          tileheight: TILE_SIZE,
          columns: tileset.columns,
          tilecount: tileset.columns * tileset.rows,
          margin: 0,
          spacing: 0,
        },
      ],
      layers: [
        { id: 1, name: layerName, type: 'tilelayer', width: MAP_COLS, height: MAP_ROWS, opacity, visible: true, x: 0, y: 0, data },
      ],
    };
  }

  const groundJson = singleLayerTiledJson('Ground', groundGrid.flat(), groundTileset, 1);
  const roadJson = singleLayerTiledJson('Road', roadGrid.flat(), roadTileset, 1);
  const waterJson = singleLayerTiledJson('Water', waterGrid.flat(), waterTileset, 1);
  // Collision reuses the ground tileset image (irrelevant — layer stays
  // invisible) purely so it's a valid Tiled document.
  const collisionJson = singleLayerTiledJson('Collision', collisionGrid.flat(), groundTileset, 0);

  // ── 4. Register each with Phaser's tilemap cache & instantiate ──
  const groundKey = `${cacheKey}__ground`;
  const roadKey = `${cacheKey}__road`;
  const waterKey = `${cacheKey}__water`;
  const collisionKey = `${cacheKey}__collision`;

  for (const [key, json] of [
    [groundKey, groundJson], [roadKey, roadJson],
    [waterKey, waterJson], [collisionKey, collisionJson],
  ] as const) {
    if (scene.cache.tilemap.exists(key)) scene.cache.tilemap.remove(key);
    scene.cache.tilemap.add(key, { format: Phaser.Tilemaps.Formats.TILED_JSON, data: json });
  }

  const groundMap = scene.make.tilemap({ key: groundKey });
  const roadMap = scene.make.tilemap({ key: roadKey });
  const waterMap = scene.make.tilemap({ key: waterKey });
  const collisionMap = scene.make.tilemap({ key: collisionKey });

  const groundImgTileset = groundMap.addTilesetImage('ground', groundTileset.textureKey, TILE_SIZE, TILE_SIZE)!;
  const roadImgTileset = roadMap.addTilesetImage('road', roadTileset.textureKey, TILE_SIZE, TILE_SIZE)!;
  const waterImgTileset = waterMap.addTilesetImage('water', waterTileset.textureKey, TILE_SIZE, TILE_SIZE)!;
  const collisionImgTileset = collisionMap.addTilesetImage('collision', groundTileset.textureKey, TILE_SIZE, TILE_SIZE)!;

  const groundLayer = groundMap.createLayer('Ground', groundImgTileset, 0, 0)!;
  const roadLayer = roadMap.createLayer('Road', roadImgTileset, 0, 0)!;
  const waterLayer = waterMap.createLayer('Water', waterImgTileset, 0, 0)!;
  const collisionLayer = collisionMap.createLayer('Collision', collisionImgTileset, 0, 0)!;

  groundLayer.setDepth(0);
  roadLayer.setDepth(0.5);
  waterLayer.setDepth(0.6);
  collisionLayer.setDepth(0).setAlpha(0).setVisible(false);

  // Real Arcade Physics collision — every wall/void tile gets a body.
  collisionLayer.setCollisionByExclusion([0]);

  const waterFrameIds = Array.from(
    { length: 9 },
    (_, i) => waterTileset.idByName.get(`water_${i}`) ?? 0,
  );

  return {
    groundMap, roadMap, waterMap, collisionMap,
    groundLayer, roadLayer, waterLayer, collisionLayer,
    groundTileset, roadTileset, waterTileset, waterFrameIds,
  };
}

/** Swap the whole Water layer to the given animation frame (0-8). */
export function setWaterFrame(built: BuiltTilemap, frame: number): void {
  const gid = built.waterFrameIds[frame] ?? built.waterFrameIds[0];
  built.waterLayer.forEachTile((tile) => {
    if (tile.index !== 0) tile.index = gid;
  });
}
