// ============================================================
// Brain Bot V15 — AssetRegistry
// Loads the manifest.json, registers every PNG with Phaser's
// texture manager, and exposes typed getters.  Single source
// of truth — no other file hard-codes asset file-names.
// ============================================================

import Phaser from 'phaser';
import { WORLD_CONFIG } from '../config/world.config';

// ── Types ────────────────────────────────────────────────────

export interface WorldManifest {
  version: string;
  assetRoot: string;
  tileSize: number;
  npcFrameWidth: number;
  npcFrameHeight: number;
  npcDirections: Record<string, number>;
  tiles: Record<string, string>;
  buildings: Record<string, string>;
  props: Record<string, string>;
  npc: Record<string, string>;
  ui: Record<string, string>;
  decorations: Record<string, string>;
}

// ── NPC agent-id → sheet-role mapping ───────────────────────
const AGENT_TO_ROLE: Record<string, string> = {
  ceo_agent:          'ceo',
  risk_agent:         'risk_manager',
  smc_agent:          'quant_researcher',
  ml_agent:           'ml_scientist',
  futures_agent:      'data_analyst',
  trader_agent:       'trader',
  portfolio_agent:    'office_worker',
  regime_agent:       'security_officer',
  mission_controller: 'visitor_1',
  journal_agent:      'visitor_2',
};

// ── Module state ─────────────────────────────────────────────
let _manifest: WorldManifest | null = null;
let _registeredKeys = new Set<string>();

// ── Helpers ──────────────────────────────────────────────────

function makeKey(category: string, name: string): string {
  return `${category}__${name}`;
}

/** Return a 1×1 solid-colour fallback texture, creating it once. */
function getFallbackTexture(
  scene: Phaser.Scene,
  key: string,
  color = WORLD_CONFIG.fallback.tile as number,
): string {
  if (!scene.textures.exists(key)) {
    const g = scene.add.graphics();
    g.fillStyle(color, 1);
    g.fillRect(0, 0, WORLD_CONFIG.tileSize * 2, WORLD_CONFIG.tileSize * 2);
    g.generateTexture(key, WORLD_CONFIG.tileSize * 2, WORLD_CONFIG.tileSize * 2);
    g.destroy();
  }
  return key;
}

// ── Public API ───────────────────────────────────────────────

/**
 * Fetch manifest.json and store it.  Call once before preload().
 */
export async function loadManifest(): Promise<WorldManifest> {
  if (_manifest) return _manifest;
  const res = await fetch(WORLD_CONFIG.manifestPath);
  if (!res.ok) throw new Error(`AssetRegistry: failed to fetch manifest (${res.status})`);
  _manifest = (await res.json()) as WorldManifest;
  return _manifest;
}

/**
 * Register every PNG from the manifest as a Phaser texture load.
 * Call inside Phaser Scene.preload().
 */
export function registerAssets(scene: Phaser.Scene): void {
  if (!_manifest) {
    console.warn('AssetRegistry.registerAssets: manifest not loaded yet, call loadManifest() first');
    return;
  }

  const categories: Array<[string, Record<string, string>]> = [
    ['tile',  _manifest.tiles],
    ['building', _manifest.buildings],
    ['prop',  _manifest.props],
    ['npc',   _manifest.npc],
    ['ui',    _manifest.ui],
    ['deco',  _manifest.decorations],
  ];

  for (const [cat, entries] of categories) {
    for (const [name, path] of Object.entries(entries)) {
      const key = makeKey(cat, name);
      if (!_registeredKeys.has(key)) {
        scene.load.image(key, path);
        _registeredKeys.add(key);
      }
    }
  }

  // NPC sheets are spritesheet-style (4-frame horizontal, 1 row)
  const fw = _manifest.npcFrameWidth;
  const fh = _manifest.npcFrameHeight;
  for (const [name, path] of Object.entries(_manifest.npc)) {
    const key = makeKey('npc', name);
    // Also load as spritesheet for frame access
    const ssKey = `npc_ss__${name}`;
    if (!_registeredKeys.has(ssKey)) {
      scene.load.spritesheet(ssKey, path, { frameWidth: fw, frameHeight: fh });
      _registeredKeys.add(ssKey);
    }
  }
}

/**
 * Load assets from the manifest — call inside Phaser Scene.preload().
 * This is an alias for registerAssets(), kept for naming symmetry.
 */
export const loadAssets = registerAssets;

// ── Typed getters ────────────────────────────────────────────

/** Return the Phaser texture key for a tile, or a coloured fallback. */
export function getTile(
  scene: Phaser.Scene,
  name: string,
): string {
  const key = makeKey('tile', name);
  if (_registeredKeys.has(key) && scene.textures.exists(key)) return key;
  return getFallbackTexture(scene, `fallback_tile_${name}`, WORLD_CONFIG.fallback.tile as number);
}

/** Return the Phaser texture key for a building sprite, or fallback. */
export function getBuilding(
  scene: Phaser.Scene,
  name: string,
): string {
  const key = makeKey('building', name);
  if (_registeredKeys.has(key) && scene.textures.exists(key)) return key;
  return getFallbackTexture(scene, `fallback_building_${name}`, WORLD_CONFIG.fallback.building as number);
}

/** Return the Phaser texture key for an NPC direction sheet, or fallback.
 *  Pass the agent id (e.g. "ceo_agent") or role name (e.g. "ceo"). */
export function getNPC(
  scene: Phaser.Scene,
  agentIdOrRole: string,
): string {
  const role = AGENT_TO_ROLE[agentIdOrRole] ?? agentIdOrRole;
  const ssKey = `npc_ss__${role}`;
  if (_registeredKeys.has(ssKey) && scene.textures.exists(ssKey)) return ssKey;
  // Try plain image key as fallback
  const imgKey = makeKey('npc', role);
  if (_registeredKeys.has(imgKey) && scene.textures.exists(imgKey)) return imgKey;
  return getFallbackTexture(scene, `fallback_npc_${role}`, WORLD_CONFIG.fallback.npc as number);
}

/** Return the Phaser texture key for the player sprite sheet. */
export function getPlayer(scene: Phaser.Scene): string {
  return getNPC(scene, 'player');
}

/** Return the Phaser texture key for a prop, or fallback. */
export function getProp(
  scene: Phaser.Scene,
  name: string,
): string {
  const key = makeKey('prop', name);
  if (_registeredKeys.has(key) && scene.textures.exists(key)) return key;
  return getFallbackTexture(scene, `fallback_prop_${name}`, WORLD_CONFIG.fallback.prop as number);
}

/** Return the Phaser texture key for a UI element, or fallback. */
export function getUI(
  scene: Phaser.Scene,
  name: string,
): string {
  const key = makeKey('ui', name);
  if (_registeredKeys.has(key) && scene.textures.exists(key)) return key;
  return getFallbackTexture(scene, `fallback_ui_${name}`, WORLD_CONFIG.fallback.tile as number);
}

/** Return the Phaser texture key for a decoration, or fallback. */
export function getDecoration(
  scene: Phaser.Scene,
  name: string,
): string {
  const key = makeKey('deco', name);
  if (_registeredKeys.has(key) && scene.textures.exists(key)) return key;
  return getFallbackTexture(scene, `fallback_deco_${name}`, WORLD_CONFIG.fallback.prop as number);
}

/**
 * Compute the frame index for an NPC sprite sheet.
 * Sheet layout: 4 frames wide × 1 frame tall.
 * Directions: F=0, B=1, L=2, R=3
 */
export function getNPCFrame(direction: 'F' | 'B' | 'L' | 'R'): number {
  return WORLD_CONFIG.npcDirections[direction] ?? 0;
}

/** Return the raw manifest (after loadManifest resolves). */
export function getManifest(): WorldManifest | null {
  return _manifest;
}
