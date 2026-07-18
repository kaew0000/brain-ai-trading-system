// ============================================================
// Brain Bot V15 — NPC  (PNG-asset version)
// Uses AssetRegistry PNG sprite sheets instead of
// procedurally generated canvas textures.
// Sheet layout: 4 frames wide (F|B|L|R), 1 row tall.
// ============================================================

import Phaser from 'phaser';
import { TILE_SIZE } from './Room';
import { tileToPx, isBlocking } from './MapLoader';
import type { NPCDefinition, NPCMood, WorldMap } from './types/world.types';
import { useWorldStore, selectNpcMood, selectCeoMood } from './worldStore';
import { getNPC, getNPCFrame } from '../../game/assets/AssetRegistry';
import { WORLD_CONFIG } from '../../game/config/world.config';

const INTERACTION_RANGE_SQ = (TILE_SIZE * 2.2) ** 2;
const WALK_SPEED   = 28;
const IDLE_DURATION_MS = [1500, 4000];
const WALK_DURATION_MS = [ 800, 2000];

// ── Mood visual config ────────────────────────────────────────

const MOOD_COLORS: Record<NPCMood, number> = {
  happy:    0x00ff88,
  neutral:  0xaaaaff,
  worried:  0xff8800,
  critical: 0xff0000,
};

const MOOD_ICONS: Record<NPCMood, string> = {
  happy:    '😊',
  neutral:  '',
  worried:  '😟',
  critical: '🚨',
};

// Direction → spritesheet column index
const DIR_FRAME: Record<string, number> = {
  down: 0, up: 1, left: 2, right: 3,
};

// ── NPC ───────────────────────────────────────────────────────

export class NPC {
  public readonly def: NPCDefinition;

  private scene:          Phaser.Scene;
  private map:            WorldMap;
  private sprite:         Phaser.GameObjects.Image;
  private shadow:         Phaser.GameObjects.Ellipse;
  private nameTag:        Phaser.GameObjects.Text;
  private moodIndicator:  Phaser.GameObjects.Arc;
  private moodText:       Phaser.GameObjects.Text;
  private promptText:     Phaser.GameObjects.Text;
  private exclamation:    Phaser.GameObjects.Text;

  public worldX: number;
  public worldY: number;

  private state:       'idle' | 'walking' = 'idle';
  private stateTimer  = 0;
  private targetX     = 0;
  private targetY     = 0;
  private facing:     'up' | 'down' | 'left' | 'right' = 'down';
  private walkFrame   = 0;
  private walkTimer   = 0;

  private promptVisible = false;
  private currentMood: NPCMood = 'neutral';
  private bouncePhase = Math.random() * Math.PI * 2;

  // Sprite-sheet metadata
  private readonly frameW: number;
  private readonly frameH: number;
  private readonly npcScale: number;

  constructor(scene: Phaser.Scene, map: WorldMap, def: NPCDefinition) {
    this.scene = scene;
    this.map   = map;
    this.def   = def;

    const { x, y } = tileToPx(def.startTx, def.startTy);
    this.worldX = x;
    this.worldY = y;
    this.targetX = x;
    this.targetY = y;

    this.frameW = WORLD_CONFIG.npcFrameWidth;
    this.frameH = WORLD_CONFIG.npcFrameHeight;
    // Scale: render NPC at ~2× tile size (32×32 logical pixels)
    this.npcScale = (TILE_SIZE * 2) / this.frameH;

    // ── Shadow ────────────────────────────────────────────────
    this.shadow = scene.add.ellipse(x, y + 6, 8, 3, 0x000000, 0.3);
    this.shadow.setDepth(1);

    // ── Sprite: use PNG sheet from AssetRegistry ──────────────
    const texKey = getNPC(scene, def.id);
    this.sprite = scene.add.image(x, y, texKey);
    this.sprite.setScale(this.npcScale);
    // Show only the "front/down" frame initially (left-crop to one cell)
    this._applyCrop(0);
    this.sprite.setDepth(9);

    // ── Mood indicator ────────────────────────────────────────
    this.moodIndicator = scene.add.arc(x, y - TILE_SIZE - 2, 3, 0, 360, false, MOOD_COLORS.neutral, 0.9);
    this.moodIndicator.setDepth(21);

    this.moodText = scene.add.text(x, y - TILE_SIZE - 14, '', {
      fontSize: '10px', fontFamily: 'Arial',
    });
    this.moodText.setOrigin(0.5, 1).setDepth(22);

    // ── Name tag ──────────────────────────────────────────────
    this.nameTag = scene.add.text(x, y - TILE_SIZE - 8, def.name, {
      fontSize: '7px',
      color: '#c0c8ff',
      fontFamily: 'monospace',
      backgroundColor: '#000000bb',
      padding: { x: 2, y: 1 },
    });
    this.nameTag.setOrigin(0.5, 1).setDepth(20);

    // ── Interaction prompt ─────────────────────────────────────
    this.promptText = scene.add.text(x, y - TILE_SIZE * 2 - 8, 'Press E', {
      fontSize: '8px',
      color: '#00ff88',
      fontFamily: 'monospace',
      backgroundColor: '#000000cc',
      padding: { x: 4, y: 2 },
    });
    this.promptText.setOrigin(0.5, 1).setDepth(30).setVisible(false);

    // ── Exclamation mark ──────────────────────────────────────
    this.exclamation = scene.add.text(x + 6, y - TILE_SIZE - 2, '', {
      fontSize: '10px', color: '#ffee00', fontFamily: 'monospace', fontStyle: 'bold',
    });
    this.exclamation.setOrigin(0, 1).setDepth(23);

    this.startIdleState();
  }

  // ── Sprite-sheet crop helper ──────────────────────────────────

  /**
   * setCrop on the image to show only the column for `directionCol`
   * (0=front/down, 1=back/up, 2=left, 3=right).
   * The PNG sheet is frameW*4 wide × frameH tall.
   */
  private _applyCrop(directionCol: number): void {
    const srcW = this.frameW * 4;
    const srcH = this.frameH;
    this.sprite.setCrop(
      directionCol * this.frameW, 0,
      this.frameW, srcH,
    );
    // Re-center origin so the cropped region renders centred
    this.sprite.setOrigin(
      (directionCol * this.frameW + this.frameW / 2) / srcW,
      1.0,
    );
  }

  // ── Walk AI ───────────────────────────────────────────────────

  private startIdleState(): void {
    this.state = 'idle';
    const ms = IDLE_DURATION_MS[0] + Math.random() * (IDLE_DURATION_MS[1] - IDLE_DURATION_MS[0]);
    this.stateTimer = ms;
  }

  private startWalkState(): void {
    this.state = 'walking';
    const ms = WALK_DURATION_MS[0] + Math.random() * (WALK_DURATION_MS[1] - WALK_DURATION_MS[0]);
    this.stateTimer = ms;

    const room = this.map.rooms.find((r) => r.id === this.def.roomId);
    if (!room) return;

    const dirs = [
      { dx: 1, dy: 0 }, { dx: -1, dy: 0 },
      { dx: 0, dy: 1 }, { dx: 0, dy: -1 },
    ];
    const dir      = dirs[Math.floor(Math.random() * dirs.length)];
    const stepTiles = 1 + Math.floor(Math.random() * 3);
    const curTx     = Math.floor(this.worldX / TILE_SIZE);
    const curTy     = Math.floor(this.worldY / TILE_SIZE);
    const newTx     = curTx + dir.dx * stepTiles;
    const newTy     = curTy + dir.dy * stepTiles;

    const clampedTx = Math.max(room.tx + 1, Math.min(room.tx + room.tw - 2, newTx));
    const clampedTy = Math.max(room.ty + 1, Math.min(room.ty + room.th - 2, newTy));

    const { x, y } = tileToPx(clampedTx, clampedTy);
    if (!isBlocking(this.map.tiles[clampedTy]?.[clampedTx] ?? 'void')) {
      this.targetX = x;
      this.targetY = y;
      const dx = this.targetX - this.worldX;
      const dy = this.targetY - this.worldY;
      if (Math.abs(dx) > Math.abs(dy)) {
        this.facing = dx > 0 ? 'right' : 'left';
      } else {
        this.facing = dy > 0 ? 'down' : 'up';
      }
    }
  }

  // ── Mood ──────────────────────────────────────────────────────

  private updateMood(): void {
    const state = useWorldStore.getState();
    const mood: NPCMood = this.def.id === 'ceo_agent'
      ? selectCeoMood(state)
      : (selectNpcMood(this.def.id)(state) as NPCMood);

    if (mood !== this.currentMood) {
      this.currentMood = mood;
      this.moodIndicator.setFillStyle(MOOD_COLORS[mood], 0.9);
      this.moodText.setText(MOOD_ICONS[mood]);

      if (mood === 'critical') {
        this.exclamation.setText('!');
        this.scene.tweens.add({
          targets: this.exclamation,
          alpha: { from: 1, to: 0.2 },
          duration: 300, yoyo: true, repeat: 3,
        });
      } else {
        this.exclamation.setText('');
      }
    }
  }

  // ── Interaction prompt ────────────────────────────────────────

  showPrompt(visible: boolean): void {
    if (visible !== this.promptVisible) {
      this.promptVisible = visible;
      this.promptText.setVisible(visible);
      if (visible) {
        this.scene.tweens.add({
          targets: this.promptText,
          y: this.worldY - TILE_SIZE * 2 - 16,
          duration: 200, ease: 'Back.Out',
        });
      }
    }
  }

  isPlayerNearby(playerX: number, playerY: number): boolean {
    const dx = playerX - this.worldX;
    const dy = playerY - this.worldY;
    return dx * dx + dy * dy < INTERACTION_RANGE_SQ;
  }

  // ── Frame selection ───────────────────────────────────────────

  private updateFrame(): void {
    const dirCol = DIR_FRAME[this.facing] ?? 0;
    this._applyCrop(dirCol);
    // Subtle walk-bob via scale variation when moving
    if (this.state === 'walking') {
      const bob = 1 + Math.sin(this.walkFrame * 0.8) * 0.04;
      this.sprite.setScale(this.npcScale, this.npcScale * bob);
    } else {
      this.sprite.setScale(this.npcScale);
    }
  }

  // ── Sync visuals ──────────────────────────────────────────────

  private syncVisuals(): void {
    const sx = this.worldX;
    const sy = this.worldY;
    const bobY = this.state === 'idle'
      ? Math.sin(this.bouncePhase) * 0.8 : 0;
    const spriteH = this.frameH * this.npcScale;

    this.sprite.setPosition(sx, sy - TILE_SIZE / 4 + bobY);
    this.shadow.setPosition(sx, sy + 6);
    this.nameTag.setPosition(sx, sy - spriteH - 4);
    this.moodIndicator.setPosition(sx + 6, sy - spriteH - 1);
    this.moodText.setPosition(sx, sy - spriteH - 12);
    this.promptText.setPosition(sx, sy - spriteH - 12);
    this.exclamation.setPosition(sx + 6, sy - spriteH - 2);
  }

  // ── Update ────────────────────────────────────────────────────

  update(delta: number): void {
    const dt = delta / 1000;
    this.bouncePhase += dt * 2;
    this.stateTimer  -= delta;

    this.updateMood();

    switch (this.state) {
      case 'idle':
        if (this.stateTimer <= 0) this.startWalkState();
        break;

      case 'walking': {
        const dx   = this.targetX - this.worldX;
        const dy   = this.targetY - this.worldY;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 2 || this.stateTimer <= 0) {
          this.worldX = this.targetX;
          this.worldY = this.targetY;
          this.startIdleState();
        } else {
          const speed = Math.min(WALK_SPEED * dt, dist);
          const norm  = 1 / dist;
          this.worldX += dx * norm * speed;
          this.worldY += dy * norm * speed;

          this.walkTimer += delta;
          if (this.walkTimer > 150) {
            this.walkTimer = 0;
            this.walkFrame++;
          }
        }
        break;
      }
    }

    this.updateFrame();
    this.syncVisuals();
  }

  // ── Special behaviours ────────────────────────────────────────

  walkToRoom(targetRoomId: string): void {
    const targetRoom = this.map.rooms.find((r) => r.id === targetRoomId);
    if (!targetRoom) return;
    const cx = targetRoom.tx + Math.floor(targetRoom.tw / 2);
    const cy = targetRoom.ty + Math.floor(targetRoom.th / 2);
    const { x, y } = tileToPx(cx, cy);
    this.targetX = x;
    this.targetY = y;
    this.state = 'walking';
    this.stateTimer = 8000;
  }

  get x(): number { return this.worldX; }
  get y(): number { return this.worldY; }
  getSprite(): Phaser.GameObjects.Image { return this.sprite; }

  destroy(): void {
    this.sprite.destroy();
    this.shadow.destroy();
    this.nameTag.destroy();
    this.moodIndicator.destroy();
    this.moodText.destroy();
    this.promptText.destroy();
    this.exclamation.destroy();
  }
}
