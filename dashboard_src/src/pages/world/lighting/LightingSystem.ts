// ============================================================
// Brain Bot V15 — Lighting System
// Enables Phaser's WebGL Lights2D pipeline and manages point
// lights (street lamps, building glow, portals, player torch).
// Ground/road/water tilemap layers and sprites opt in via
// setPipeline('Light2D'); UI elements stay unlit.
// ============================================================

import Phaser from 'phaser';

export interface LightHandle {
  light: Phaser.GameObjects.Light;
  baseRadius: number;
  baseIntensity: number;
  flicker?: { speed: number; amount: number; t: number };
}

export class LightingSystem {
  private scene: Phaser.Scene;
  private lights: LightHandle[] = [];
  private enabled: boolean;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    // WebGL only — gracefully no-op under Canvas renderer.
    this.enabled = scene.renderer.type === Phaser.WEBGL;
    if (this.enabled) {
      scene.lights.enable();
      scene.lights.setAmbientColor(0x4a4a68);
    }
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  /** Make a game object react to point lights (normal-map-free lit shading). */
  makeLit(obj: Phaser.GameObjects.Components.Pipeline): void {
    if (!this.enabled) return;
    obj.setPipeline('Light2D');
  }

  addLight(
    x: number, y: number, radius: number, color = 0xffee88, intensity = 1.2,
    flicker?: { speed: number; amount: number },
  ): LightHandle | null {
    if (!this.enabled) return null;
    const light = this.scene.lights.addLight(x, y, radius, color, intensity);
    const handle: LightHandle = {
      light,
      baseRadius: radius,
      baseIntensity: intensity,
      flicker: flicker ? { ...flicker, t: Math.random() * 1000 } : undefined,
    };
    this.lights.push(handle);
    return handle;
  }

  removeLight(handle: LightHandle | null): void {
    if (!handle || !this.enabled) return;
    this.scene.lights.removeLight(handle.light);
    this.lights = this.lights.filter((l) => l !== handle);
  }

  /** Global ambient tint — driven by DayNightCycle. */
  setAmbient(color: number): void {
    if (!this.enabled) return;
    this.scene.lights.setAmbientColor(color);
  }

  update(delta: number): void {
    if (!this.enabled) return;
    for (const h of this.lights) {
      if (!h.flicker) continue;
      h.flicker.t += delta;
      const wobble = Math.sin(h.flicker.t * h.flicker.speed) * h.flicker.amount;
      h.light.setIntensity(h.baseIntensity + wobble);
    }
  }

  destroy(): void {
    if (!this.enabled) return;
    this.scene.lights.destroy();
  }
}
