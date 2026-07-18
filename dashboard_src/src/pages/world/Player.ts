// ============================================================
// Brain Bot V15 — Player  (PNG-asset version)
// WASD/Arrow movement, click-to-move, collision detection.
// Sprite uses PNG sheet from AssetRegistry (same format as NPC):
// 4 columns (F/B/L/R), 1 row, frameWidth=140 frameHeight=160.
// ============================================================

import Phaser from 'phaser';
import { TILE_SIZE, MAP_COLS, MAP_ROWS } from './Room';
import { isBlocking, tileToPx, pxToTile } from './MapLoader';
import type { TileType, WorldMap } from './types/world.types';
import { useWorldStore } from './worldStore';
import { getPlayer } from '../../game/assets/AssetRegistry';
import { WORLD_CONFIG } from '../../game/config/world.config';
import { findPath, simplifyPath } from './pathfinding/PathFinder';

// ── NetworkEntity base (multiplayer-ready abstraction) ────────

export abstract class NetworkEntity {
  public tileX:    number;
  public tileY:    number;
  public worldX:   number;
  public worldY:   number;
  public readonly entityId: string;

  constructor(id: string, tx: number, ty: number) {
    this.entityId = id;
    this.tileX = tx;
    this.tileY = ty;
    const { x, y } = tileToPx(tx, ty);
    this.worldX = x;
    this.worldY = y;
  }

  abstract update(delta: number): void;
}

// ── Constants ─────────────────────────────────────────────────

const SPEED_PX          = 90;
const WALK_LERP         = 8;
const CLICK_PROXIMITY_SQ = 4;

const DIR_FRAME: Record<string, number> = {
  down: 0, up: 1, left: 2, right: 3,
};

// ── Player ────────────────────────────────────────────────────

export class Player extends NetworkEntity {
  private scene:  Phaser.Scene;
  private map:    WorldMap;
  private sprite: Phaser.GameObjects.Image;
  private shadow: Phaser.GameObjects.Ellipse;
  private glowCircle: Phaser.GameObjects.Arc;
  private nameTag:    Phaser.GameObjects.Text;

  private keys!: {
    up: Phaser.Input.Keyboard.Key; down: Phaser.Input.Keyboard.Key;
    left: Phaser.Input.Keyboard.Key; right: Phaser.Input.Keyboard.Key;
    w:  Phaser.Input.Keyboard.Key; s: Phaser.Input.Keyboard.Key;
    a:  Phaser.Input.Keyboard.Key; d: Phaser.Input.Keyboard.Key;
  };

  private facing:   'up' | 'down' | 'left' | 'right' = 'down';
  private isMoving  = false;
  private walkFrame = 0;
  private walkTimer = 0;
  private clickPath: Array<{ x: number; y: number }> = [];

  private readonly frameW: number;
  private readonly frameH: number;
  private readonly npcScale: number;

  constructor(scene: Phaser.Scene, map: WorldMap, startTx: number, startTy: number) {
    super('local_player', startTx, startTy);
    this.scene = scene;
    this.map   = map;

    this.frameW   = WORLD_CONFIG.npcFrameWidth;
    this.frameH   = WORLD_CONFIG.npcFrameHeight;
    this.npcScale = (TILE_SIZE * 2) / this.frameH;

    const { x, y } = tileToPx(startTx, startTy);
    this.worldX = x;
    this.worldY = y;

    // Shadow
    this.shadow = scene.add.ellipse(x, y + 7, 10, 4, 0x000000, 0.35);
    this.shadow.setDepth(1);

    // Sprite — PNG sheet from AssetRegistry
    const texKey = getPlayer(scene);
    this.sprite  = scene.add.image(x, y, texKey);
    this.sprite.setScale(this.npcScale);
    this._applyCrop(DIR_FRAME.down);
    this.sprite.setDepth(10);

    // Interaction glow
    this.glowCircle = scene.add.arc(x, y, TILE_SIZE * 1.5, 0, 360, false, 0x00ff88, 0.04);
    this.glowCircle.setDepth(2);

    // Name tag
    this.nameTag = scene.add.text(x, y - TILE_SIZE - 4, 'YOU', {
      fontSize: '7px',
      color: '#00ff88',
      fontFamily: 'monospace',
      backgroundColor: '#000000aa',
      padding: { x: 2, y: 1 },
    });
    this.nameTag.setOrigin(0.5, 1).setDepth(20);

    this.setupKeys();
    this.setupClickToMove();
  }

  // ── Sprite crop helper ────────────────────────────────────────

  private _applyCrop(directionCol: number): void {
    const srcW = this.frameW * 4;
    const srcH = this.frameH;
    this.sprite.setCrop(
      directionCol * this.frameW, 0,
      this.frameW, srcH,
    );
    this.sprite.setOrigin(
      (directionCol * this.frameW + this.frameW / 2) / srcW,
      1.0,
    );
  }

  // ── Input setup ───────────────────────────────────────────────

  private setupKeys(): void {
    const kb = this.scene.input.keyboard!;
    this.keys = {
      up:    kb.addKey(Phaser.Input.Keyboard.KeyCodes.UP),
      down:  kb.addKey(Phaser.Input.Keyboard.KeyCodes.DOWN),
      left:  kb.addKey(Phaser.Input.Keyboard.KeyCodes.LEFT),
      right: kb.addKey(Phaser.Input.Keyboard.KeyCodes.RIGHT),
      w:     kb.addKey(Phaser.Input.Keyboard.KeyCodes.W),
      s:     kb.addKey(Phaser.Input.Keyboard.KeyCodes.S),
      a:     kb.addKey(Phaser.Input.Keyboard.KeyCodes.A),
      d:     kb.addKey(Phaser.Input.Keyboard.KeyCodes.D),
    };
  }

  private setupClickToMove(): void {
    this.scene.input.on(Phaser.Input.Events.POINTER_UP, (ptr: Phaser.Input.Pointer) => {
      if (ptr.button !== 0) return;
      const cam = this.scene.cameras.main;
      const wx  = ptr.x + cam.scrollX;
      const wy  = ptr.y + cam.scrollY;
      const { tx, ty } = pxToTile(wx, wy);
      if (!this.isTileWalkable(tx, ty)) return;

      const raw = findPath(this.map.tiles, MAP_COLS, MAP_ROWS, this.tileX, this.tileY, tx, ty);
      if (raw === null) return; // unreachable — ignore click
      const waypoints = simplifyPath(raw);
      this.clickPath = waypoints.map((wp) => tileToPx(wp.tx, wp.ty));
    });
  }

  // ── Collision ─────────────────────────────────────────────────

  private isTileWalkable(tx: number, ty: number): boolean {
    if (tx < 0 || tx >= MAP_COLS || ty < 0 || ty >= MAP_ROWS) return false;
    const tile: TileType = this.map.tiles[ty]?.[tx] ?? 'void';
    return !isBlocking(tile);
  }

  private canMoveTo(px: number, py: number): boolean {
    const { tx, ty } = pxToTile(px, py);
    return this.isTileWalkable(tx, ty);
  }

  // ── Teleport ──────────────────────────────────────────────────

  teleportTo(tx: number, ty: number): void {
    const { x, y } = tileToPx(tx, ty);
    this.worldX = x; this.worldY = y;
    this.tileX  = tx; this.tileY = ty;
    this.clickPath = [];
    this.syncSprite();
  }

  // ── Frame selection ───────────────────────────────────────────

  private updateFrame(): void {
    this._applyCrop(DIR_FRAME[this.facing] ?? 0);
    if (this.isMoving) {
      const bob = 1 + Math.sin(this.walkFrame * 0.8) * 0.04;
      this.sprite.setScale(this.npcScale, this.npcScale * bob);
    } else {
      this.sprite.setScale(this.npcScale);
    }
  }

  // ── Sync visuals ──────────────────────────────────────────────

  private syncSprite(): void {
    const spriteH = this.frameH * this.npcScale;
    this.sprite.setPosition(this.worldX, this.worldY - TILE_SIZE / 4);
    this.shadow.setPosition(this.worldX, this.worldY + 4);
    this.glowCircle.setPosition(this.worldX, this.worldY);
    this.nameTag.setPosition(this.worldX, this.worldY - spriteH - 2);
  }

  // ── Update loop ───────────────────────────────────────────────

  update(delta: number): void {
    const dt    = delta / 1000;
    const speed = SPEED_PX * dt;
    let dx = 0, dy = 0;

    const kUp    = this.keys.up.isDown    || this.keys.w.isDown;
    const kDown  = this.keys.down.isDown  || this.keys.s.isDown;
    const kLeft  = this.keys.left.isDown  || this.keys.a.isDown;
    const kRight = this.keys.right.isDown || this.keys.d.isDown;

    if (kUp)    { dy = -speed; this.facing = 'up';    this.clickPath = []; }
    if (kDown)  { dy = +speed; this.facing = 'down';  this.clickPath = []; }
    if (kLeft)  { dx = -speed; this.facing = 'left';  this.clickPath = []; }
    if (kRight) { dx = +speed; this.facing = 'right'; this.clickPath = []; }

    if (dx !== 0 && dy !== 0) {
      const n = 1 / Math.SQRT2;
      dx *= n; dy *= n;
    }

    if (this.clickPath.length > 0 && dx === 0 && dy === 0) {
      const waypoint = this.clickPath[0];
      const diffX = waypoint.x - this.worldX;
      const diffY = waypoint.y - this.worldY;
      const distSq = diffX * diffX + diffY * diffY;
      if (distSq < (TILE_SIZE * CLICK_PROXIMITY_SQ) ** 2) {
        this.clickPath.shift(); // reached this waypoint — advance to the next
      } else {
        const dist = Math.sqrt(distSq);
        dx = (diffX / dist) * speed;
        dy = (diffY / dist) * speed;
        if (Math.abs(diffX) > Math.abs(diffY)) {
          this.facing = diffX > 0 ? 'right' : 'left';
        } else {
          this.facing = diffY > 0 ? 'down' : 'up';
        }
      }
    }

    if (dx !== 0 && this.canMoveTo(this.worldX + dx, this.worldY)) this.worldX += dx;
    if (dy !== 0 && this.canMoveTo(this.worldX, this.worldY + dy)) this.worldY += dy;

    const { tx, ty } = pxToTile(this.worldX, this.worldY);
    const moved = tx !== this.tileX || ty !== this.tileY;
    this.tileX = tx; this.tileY = ty;

    this.isMoving = dx !== 0 || dy !== 0;
    if (this.isMoving) {
      this.walkTimer += delta;
      if (this.walkTimer > 120) { this.walkTimer = 0; this.walkFrame = (this.walkFrame + 1) % 4; }
    } else {
      this.walkFrame = 0;
    }

    this.updateFrame();
    this.syncSprite();

    if (moved) useWorldStore.getState().setPlayerPos(tx, ty);
  }

  // ── Accessors ─────────────────────────────────────────────────

  get x(): number { return this.worldX; }
  get y(): number { return this.worldY; }
  getSprite(): Phaser.GameObjects.Image { return this.sprite; }

  destroy(): void {
    this.sprite.destroy(); this.shadow.destroy();
    this.glowCircle.destroy(); this.nameTag.destroy();
  }
}

// ── RemotePlayer (multiplayer-ready stub) ─────────────────────

export class RemotePlayer extends NetworkEntity {
  private sprite:   Phaser.GameObjects.Image;
  private nameTag:  Phaser.GameObjects.Text;
  private targetX:  number;
  private targetY:  number;
  private readonly frameW: number;
  private readonly frameH: number;
  private readonly npcScale: number;

  constructor(
    scene: Phaser.Scene, id: string, tx: number, ty: number,
    name: string, charKey?: string,
  ) {
    super(id, tx, ty);
    const { x, y } = tileToPx(tx, ty);
    this.worldX = x; this.worldY = y;
    this.targetX = x; this.targetY = y;
    this.frameW   = WORLD_CONFIG.npcFrameWidth;
    this.frameH   = WORLD_CONFIG.npcFrameHeight;
    this.npcScale = (TILE_SIZE * 2) / this.frameH;

    const key = charKey ?? getPlayer(scene);
    this.sprite = scene.add.image(x, y, key);
    this.sprite.setScale(this.npcScale).setDepth(9);
    this.sprite.setCrop(0, 0, this.frameW, this.frameH);

    this.nameTag = scene.add.text(x, y - TILE_SIZE - 4, name, {
      fontSize: '7px', color: '#aaddff', fontFamily: 'monospace',
      backgroundColor: '#000000aa', padding: { x: 2, y: 1 },
    });
    this.nameTag.setOrigin(0.5, 1).setDepth(20);
  }

  receiveNetworkUpdate(x: number, y: number): void {
    this.targetX = x; this.targetY = y;
  }

  update(delta: number): void {
    const factor = Math.min(1, (WALK_LERP * delta) / 1000);
    this.worldX += (this.targetX - this.worldX) * factor;
    this.worldY += (this.targetY - this.worldY) * factor;
    const spriteH = this.frameH * this.npcScale;
    this.sprite.setPosition(this.worldX, this.worldY - TILE_SIZE / 4);
    this.nameTag.setPosition(this.worldX, this.worldY - spriteH - 2);
    const { tx, ty } = pxToTile(this.worldX, this.worldY);
    this.tileX = tx; this.tileY = ty;
  }

  destroy(): void { this.sprite.destroy(); this.nameTag.destroy(); }
}
