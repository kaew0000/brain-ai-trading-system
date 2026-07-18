// ============================================================
// Brain Bot V15 — AssetLoader  (PNG-asset version)
// Replaces all runtime canvas-drawn textures with PNG assets
// loaded from public/assets/world/ via AssetRegistry.
//
// Backward-compatible: all texture keys used by WorldScene,
// NPC.ts and Player.ts continue to resolve correctly.
// ============================================================

import Phaser from 'phaser';
import { WORLD_CONFIG } from '../../game/config/world.config';
import {
  loadManifest,
  registerAssets,
  getTile,
  getBuilding,
  getNPC,
  getPlayer,
  getProp,
  getDecoration,
  getUI,
} from '../../game/assets/AssetRegistry';
import { ROOM_DEFINITIONS } from './Room';

// Re-export helpers so existing consumers don't need to change imports
export {
  getTile, getBuilding, getNPC, getPlayer,
  getProp, getDecoration, getUI,
  loadManifest, registerAssets,
};

// ── TextureManager shim ───────────────────────────────────────────────────────
// WorldScene accesses scene.textures.addCanvas(key, canvas) in the old code.
// We no longer use canvas textures; this shim provides a no-op so that any
// residual addCanvas calls are silently ignored and the existing texture keys
// are re-pointed to the correct PNG keys from AssetRegistry.
export class PNGTextureManager {
  private scene: Phaser.Scene;
  private keyMap: Map<string, string> = new Map();

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  /** Map a legacy canvas key → the real PNG texture key already loaded. */
  map(legacyKey: string, pngKey: string): void {
    this.keyMap.set(legacyKey, pngKey);
  }

  /** Resolve a legacy key to its PNG counterpart (or itself). */
  resolve(key: string): string {
    return this.keyMap.get(key) ?? key;
  }

  /** No-op: ignore canvas additions — all textures come from PNGs now. */
  addCanvas(_key: string, _canvas: HTMLCanvasElement): void { /* no-op */ }
}

// ── Room floor / wall colour palette (kept for minimap tinting only) ─────────
export const ROOM_PALETTE: Record<string, { bg: number; accent: number }> = {
  ceo:         { bg: 0x12124a, accent: 0x4444ff },
  mission:     { bg: 0x2e0a3f, accent: 0xaa44ff },
  risk:        { bg: 0x3f0a0a, accent: 0xff4444 },
  intelligence:{ bg: 0x0a2510, accent: 0x00ff88 },
  futures:     { bg: 0x251500, accent: 0xff8800 },
  ml_lab:      { bg: 0x0f0f40, accent: 0x4488ff },
  command:     { bg: 0x002020, accent: 0x00cccc },
  portfolio:   { bg: 0x251e00, accent: 0xddaa00 },
  replay:      { bg: 0x250025, accent: 0xff44ff },
  server:      { bg: 0x101010, accent: 0x22ff44 },
  data_center: { bg: 0x0f0f18, accent: 0x6666ff },
  training:    { bg: 0x0a2020, accent: 0x00ffaa },
  meeting:     { bg: 0x222235, accent: 0x8888ff },
  emergency:   { bg: 0x500000, accent: 0xff0000 },
  teleport:    { bg: 0x003030, accent: 0x00ffff },
  plaza:       { bg: 0x22222a, accent: 0x44ddff },
};

// ── Main registration ─────────────────────────────────────────────────────────

/**
 * Call from WorldScene.preload().
 * 1. Loads manifest.json (async, awaited before scene starts)
 * 2. Queues all PNG loads via Phaser's loader
 * 3. Returns a PNGTextureManager that maps legacy keys → PNG keys
 */
export async function initAssets(scene: Phaser.Scene): Promise<PNGTextureManager> {
  await loadManifest();
  registerAssets(scene);

  const tm = new PNGTextureManager(scene);

  // ── Tile key mappings ─────────────────────────────────────────────────────
  tm.map('tile_void',        getTile(scene, 'void_tile'));
  tm.map('tile_grass',       getTile(scene, 'grass_plain'));
  tm.map('tile_path',        getTile(scene, 'road_straight'));
  tm.map('tile_wall',        getTile(scene, 'wall_tile'));
  tm.map('tile_wall_corner', getTile(scene, 'wall_corner_tile'));

  // Water animation frames
  for (let i = 0; i < WORLD_CONFIG.waterFrames; i++) {
    tm.map(`tile_water_${i}`, getTile(scene, `water_${i}`));
  }

  // Room-specific floor tiles (tinted floor_tech variants per room)
  for (const room of ROOM_DEFINITIONS) {
    tm.map(`tile_floor_${room.id}`,    getTile(scene, 'floor_tech_plain'));
    tm.map(`tile_wall_top_${room.id}`, getTile(scene, 'wall_tile'));
  }

  // ── Prop key mappings ────────────────────────────────────────────────────
  tm.map('prop_tree',     getProp(scene, 'tree_medium'));
  tm.map('prop_tree_lg',  getProp(scene, 'tree_large'));
  tm.map('prop_lamp',     getDecoration(scene, 'street_lamp_a'));
  tm.map('prop_computer', getProp(scene, 'terminal_a'));
  tm.map('prop_server',   getProp(scene, 'server_rack_lg'));
  tm.map('prop_flower_0', getDecoration(scene, 'flower_a'));
  tm.map('prop_flower_1', getDecoration(scene, 'flower_b'));
  tm.map('prop_flower_2', getDecoration(scene, 'flower_c'));

  // ── Hologram / interactive props ─────────────────────────────────────────
  tm.map('hologram_0', getDecoration(scene, 'hologram_a'));
  tm.map('hologram_1', getDecoration(scene, 'hologram_b'));
  tm.map('hologram_2', getDecoration(scene, 'hologram_c'));

  // ── Prompt indicator ─────────────────────────────────────────────────────
  // "Press E" indicator — generated at runtime as a small graphic
  if (!scene.textures.exists('prompt_e')) {
    const g = scene.add.graphics();
    g.fillStyle(0xffffff, 0.9);
    g.fillRoundedRect(0, 0, 18, 12, 3);
    g.fillStyle(0x000000, 1);
    g.fillRect(4, 3, 10, 6);
    g.generateTexture('prompt_e', 18, 12);
    g.destroy();
    tm.map('prompt_e', 'prompt_e');
  }

  // ── NPC / Player ─────────────────────────────────────────────────────────
  tm.map('char_player', getPlayer(scene));

  return tm;
}

// ── Building texture key helper ───────────────────────────────────────────────

/**
 * Map a room id → building PNG key.
 * Used by WorldScene when placing building sprites on room tiles.
 */
export function getBuildingKeyForRoom(scene: Phaser.Scene, roomId: string): string {
  const buildingMap: Record<string, string> = {
    ceo:          'ceo_room',
    mission:      'mission_board_center',
    risk:         'risk_center',
    ml_lab:       'ml_lab',
    intelligence: 'intelligence_lab',
    futures:      'futures_trading_lab',
    portfolio:    'portfolio_vault',
    replay:       'replay_theater',
    command:      'command_center',
    teleport:     'teleport_entrance',
    server:       'server_room',
    data_center:  'data_center',
    training:     'intelligence_lab',    // reuse closest
    meeting:      'mission_board_center', // reuse closest
    emergency:    'risk_center',          // reuse closest
    plaza:        'fountain_large',       // open plaza
  };
  const bName = buildingMap[roomId] ?? 'ceo_room';
  // Try building first, then tile decorations
  return getBuilding(scene, bName) || getDecoration(scene, bName) || getTile(scene, bName);
}
