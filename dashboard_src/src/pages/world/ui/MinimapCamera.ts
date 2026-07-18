// ============================================================
// Brain Bot V15 — Minimap Camera
// The minimap is a second real Phaser camera viewing the actual
// tilemap/sprites (zoomed out), not a hand-drawn abstraction.
// Renders inside the same WebGL canvas as the main view.
// ============================================================

import Phaser from 'phaser';
import { MAP_COLS, MAP_ROWS, TILE_SIZE } from '../Room';
import { pxToTile, tileToPx } from '../MapLoader';

const WORLD_W = MAP_COLS * TILE_SIZE;
const WORLD_H = MAP_ROWS * TILE_SIZE;

export class MinimapCamera {
  private scene: Phaser.Scene;
  private cam: Phaser.Cameras.Scene2D.Camera;
  private frame: Phaser.GameObjects.Graphics;
  private playerDot: Phaser.GameObjects.Arc;
  private npcDots: Map<string, Phaser.GameObjects.Arc> = new Map();
  private viewport: { x: number; y: number; w: number; h: number };
  private onTeleport: (tx: number, ty: number) => void;
  private visible = true;

  constructor(
    scene: Phaser.Scene,
    onTeleport: (tx: number, ty: number) => void,
    ignoreList: Phaser.GameObjects.GameObject[],
  ) {
    this.scene = scene;
    this.onTeleport = onTeleport;

    const w = 180;
    const h = Math.round((w * MAP_ROWS) / MAP_COLS);
    const margin = 12;
    this.viewport = { x: scene.scale.width - w - margin, y: margin, w, h };

    this.cam = scene.cameras.add(this.viewport.x, this.viewport.y, w, h);
    this.cam.setName('minimap');
    this.cam.setZoom(w / WORLD_W);
    this.cam.centerOn(WORLD_W / 2, WORLD_H / 2);
    this.cam.setBackgroundColor(0x05050c);
    this.cam.setBounds(0, 0, WORLD_W, WORLD_H);
    this.cam.ignore(ignoreList);

    // Border frame (drawn in screen space on the main UI layer)
    this.frame = scene.add.graphics();
    this.frame.setScrollFactor(0).setDepth(1000);
    this.drawFrame();
    // Only the main camera should render the frame chrome, not the minimap
    // itself (avoids a border-within-a-border recursive look).
    this.cam.ignore([this.frame]);

    // Player marker — bright dot, always on top of the minimap camera.
    this.playerDot = scene.add.circle(0, 0, 3, 0x00ff88, 1);
    this.playerDot.setDepth(999);
    scene.cameras.main.ignore(this.playerDot);

    this.setupInput();

    scene.scale.on('resize', () => this.reposition());
  }

  private drawFrame(): void {
    const { x, y, w, h } = this.viewport;
    this.frame.clear();
    this.frame.fillStyle(0x000000, 0.3);
    this.frame.fillRoundedRect(x - 3, y - 3, w + 6, h + 6, 4);
    this.frame.lineStyle(2, 0x2a3550, 1);
    this.frame.strokeRoundedRect(x - 2, y - 2, w + 4, h + 4, 4);
    this.frame.lineStyle(1, 0x00ffcc, 0.5);
    this.frame.strokeRoundedRect(x, y, w, h, 3);
  }

  private reposition(): void {
    const { w, h } = this.viewport;
    const margin = 12;
    this.viewport.x = this.scene.scale.width - w - margin;
    this.viewport.y = margin;
    this.cam.setPosition(this.viewport.x, this.viewport.y);
    this.drawFrame();
  }

  private setupInput(): void {
    this.scene.input.on(Phaser.Input.Events.POINTER_DOWN, (ptr: Phaser.Input.Pointer) => {
      const { x, y, w, h } = this.viewport;
      if (ptr.x < x || ptr.x > x + w || ptr.y < y || ptr.y > y + h) return;
      const localX = (ptr.x - x) / this.cam.zoom + this.cam.scrollX;
      const localY = (ptr.y - y) / this.cam.zoom + this.cam.scrollY;
      const { tx, ty } = pxToTile(localX, localY);
      this.onTeleport(tx, ty);
    });
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.cam.setVisible(v);
    this.frame.setVisible(v);
    this.playerDot.setVisible(v);
  }

  update(
    playerX: number, playerY: number,
    npcs: Array<{ id: string; x: number; y: number; accent: number }>,
  ): void {
    if (!this.visible) return;
    this.cam.centerOn(WORLD_W / 2, WORLD_H / 2); // fixed overview, no follow-jitter

    // Position the player dot in *screen* space matching the minimap camera's
    // own projection so it renders correctly inside its small viewport.
    const { x: vx, y: vy } = this.viewport;
    const px = vx + (playerX - this.cam.scrollX) * this.cam.zoom;
    const py = vy + (playerY - this.cam.scrollY) * this.cam.zoom;
    this.playerDot.setPosition(px, py);

    const seen = new Set<string>();
    for (const npc of npcs) {
      seen.add(npc.id);
      let dot = this.npcDots.get(npc.id);
      if (!dot) {
        dot = this.scene.add.circle(0, 0, 2, npc.accent, 0.9);
        dot.setDepth(998);
        this.scene.cameras.main.ignore(dot);
        this.npcDots.set(npc.id, dot);
      }
      const nx = vx + (npc.x - this.cam.scrollX) * this.cam.zoom;
      const ny = vy + (npc.y - this.cam.scrollY) * this.cam.zoom;
      dot.setPosition(nx, ny).setVisible(this.visible);
    }
    for (const [id, dot] of this.npcDots) {
      if (!seen.has(id)) { dot.destroy(); this.npcDots.delete(id); }
    }
  }

  destroy(): void {
    this.frame.destroy();
    this.playerDot.destroy();
    for (const dot of this.npcDots.values()) dot.destroy();
    this.scene.cameras.remove(this.cam);
  }
}
