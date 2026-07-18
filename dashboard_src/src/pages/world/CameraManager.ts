// ============================================================
// Brain Bot V15 — Camera Manager
// Smooth camera following, zoom in/out, pixel-perfect
// rendering and cinematic pan on teleport.
// ============================================================

import Phaser from 'phaser';
import { MAP_COLS, MAP_ROWS, TILE_SIZE } from './Room';
import type { Player } from './Player';

const WORLD_W = MAP_COLS * TILE_SIZE;
const WORLD_H = MAP_ROWS * TILE_SIZE;

// Zoom levels
const ZOOM_MIN   = 0.5;
const ZOOM_MAX   = 3.0;
const ZOOM_STEP  = 0.15;
const ZOOM_DEFAULT = 2.0;  // 2× makes 16px tiles look like 32px

// Lerp factor for smooth follow
const LERP_X = 0.08;
const LERP_Y = 0.08;

export class CameraManager {
  private cam: Phaser.Cameras.Scene2D.Camera;
  private player: Player;
  private scene: Phaser.Scene;

  private currentZoom: number;
  private targetZoom: number;
  private baseZoom: number = ZOOM_DEFAULT;
  private manualZoomOffset = 0; // user +/- / scroll adjustments on top of base
  private zoomKeys!: {
    zoomIn: Phaser.Input.Keyboard.Key;
    zoomOut: Phaser.Input.Keyboard.Key;
    zoomReset: Phaser.Input.Keyboard.Key;
  };

  constructor(scene: Phaser.Scene, player: Player) {
    this.scene = scene;
    this.player = player;
    this.cam = scene.cameras.main;

    // Configure world bounds
    this.cam.setBounds(0, 0, WORLD_W, WORLD_H);

    // Set initial zoom
    this.currentZoom = ZOOM_DEFAULT;
    this.targetZoom  = ZOOM_DEFAULT;
    this.cam.setZoom(ZOOM_DEFAULT);

    // Start centered on player
    this.cam.centerOn(player.x, player.y);

    // Pixel-perfect: no rounding artifacts
    this.cam.setRoundPixels(true);

    // Setup zoom keys
    this.setupZoomKeys();
    this.setupMouseWheel();
  }

  private setupZoomKeys(): void {
    const kb = this.scene.input.keyboard!;
    this.zoomKeys = {
      zoomIn:    kb.addKey(Phaser.Input.Keyboard.KeyCodes.PLUS),
      zoomOut:   kb.addKey(Phaser.Input.Keyboard.KeyCodes.MINUS),
      zoomReset: kb.addKey(Phaser.Input.Keyboard.KeyCodes.ZERO),
    };
  }

  private setupMouseWheel(): void {
    this.scene.input.on(
      Phaser.Input.Events.POINTER_WHEEL,
      (_ptr: Phaser.Input.Pointer, _dx: number, _dy: number, dz: number) => {
        if (dz > 0) {
          this.zoomOut();
        } else {
          this.zoomIn();
        }
      },
    );
  }

  zoomIn(): void {
    this.manualZoomOffset = Math.min(ZOOM_MAX - this.baseZoom, this.manualZoomOffset + ZOOM_STEP);
    this.targetZoom = this.baseZoom + this.manualZoomOffset;
  }

  zoomOut(): void {
    this.manualZoomOffset = Math.max(ZOOM_MIN - this.baseZoom, this.manualZoomOffset - ZOOM_STEP);
    this.targetZoom = this.baseZoom + this.manualZoomOffset;
  }

  resetZoom(): void {
    this.manualZoomOffset = 0;
    this.targetZoom = this.baseZoom;
  }

  /**
   * Called on room enter/exit. Interiors zoom in for a more intimate,
   * readable view of the room; the plaza/outdoors zooms back out to
   * the default overview level. Preserves any manual zoom offset the
   * player had dialed in with +/- or the mouse wheel.
   */
  setInteriorZoom(interior: boolean): void {
    this.baseZoom = interior ? ZOOM_DEFAULT * 1.6 : ZOOM_DEFAULT;
    this.targetZoom = Phaser.Math.Clamp(this.baseZoom + this.manualZoomOffset, ZOOM_MIN, ZOOM_MAX);
  }

  /** Cinematic pan + zoom when teleporting */
  panToPosition(worldX: number, worldY: number): void {
    this.cam.pan(worldX, worldY, 600, 'Sine.easeInOut');
  }

  update(delta: number): void {
    // Smooth zoom interpolation
    const zoomDiff = this.targetZoom - this.currentZoom;
    if (Math.abs(zoomDiff) > 0.001) {
      this.currentZoom += zoomDiff * 0.12;
      this.cam.setZoom(this.currentZoom);
    }

    // Smooth follow
    const lx = LERP_X;
    const ly = LERP_Y;
    const tx = this.player.x;
    const ty = this.player.y;

    const cx = this.cam.scrollX + this.cam.width  / 2 / this.currentZoom;
    const cy = this.cam.scrollY + this.cam.height / 2 / this.currentZoom;

    this.cam.scrollX += (tx - cx) * lx;
    this.cam.scrollY += (ty - cy) * ly;

    // Zoom keyboard
    if (Phaser.Input.Keyboard.JustDown(this.zoomKeys.zoomIn)) this.zoomIn();
    if (Phaser.Input.Keyboard.JustDown(this.zoomKeys.zoomOut)) this.zoomOut();
    if (Phaser.Input.Keyboard.JustDown(this.zoomKeys.zoomReset)) this.resetZoom();
  }

  getZoom(): number { return this.currentZoom; }
  getCamera(): Phaser.Cameras.Scene2D.Camera { return this.cam; }
}
