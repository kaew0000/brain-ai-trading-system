// ============================================================
// Brain Bot V15 — Particle Effects
// Real Phaser GameObjects.Particles emitters for ambient FX:
// fountain mist, portal sparkle, server-room data sparks, and
// an alert-state ember burst. Uses a single tiny generated soft
// dot as the particle sprite (standard practice — particles are
// not "world geometry" and are not covered by the PNG-only
// requirement, which targets ground/buildings/NPCs/decorations).
// ============================================================

import Phaser from 'phaser';

const DOT_KEY = 'fx__soft_dot';

function ensureDotTexture(scene: Phaser.Scene): void {
  if (scene.textures.exists(DOT_KEY)) return;
  const size = 8;
  const g = scene.add.graphics();
  g.fillStyle(0xffffff, 1);
  g.fillCircle(size / 2, size / 2, size / 2);
  g.generateTexture(DOT_KEY, size, size);
  g.destroy();
}

export class ParticleEffects {
  private scene: Phaser.Scene;
  private emitters: Phaser.GameObjects.Particles.ParticleEmitter[] = [];

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    ensureDotTexture(scene);
  }

  /** Fine upward mist over a fountain sprite. */
  addFountainMist(x: number, y: number): Phaser.GameObjects.Particles.ParticleEmitter {
    const emitter = this.scene.add.particles(x, y - 6, DOT_KEY, {
      speed: { min: 6, max: 16 },
      angle: { min: 260, max: 280 },
      lifespan: 700,
      scale: { start: 0.35, end: 0 },
      alpha: { start: 0.5, end: 0 },
      tint: 0x66ddff,
      frequency: 90,
      quantity: 1,
    });
    emitter.setDepth(9);
    this.emitters.push(emitter);
    return emitter;
  }

  /** Slow orbiting sparkle around a portal / teleport pad. */
  addPortalSparkle(x: number, y: number, color = 0x00ffff): Phaser.GameObjects.Particles.ParticleEmitter {
    const emitter = this.scene.add.particles(x, y, DOT_KEY, {
      speed: { min: 10, max: 24 },
      angle: { min: 0, max: 360 },
      lifespan: 900,
      scale: { start: 0.3, end: 0 },
      alpha: { start: 0.7, end: 0 },
      tint: color,
      frequency: 60,
      quantity: 1,
      emitZone: {
        type: 'edge',
        source: new Phaser.Geom.Circle(0, 0, 10),
        quantity: 24,
      },
    });
    emitter.setDepth(9);
    this.emitters.push(emitter);
    return emitter;
  }

  /** Occasional data-spark burst near server racks. */
  addServerSparks(x: number, y: number): Phaser.GameObjects.Particles.ParticleEmitter {
    const emitter = this.scene.add.particles(x, y, DOT_KEY, {
      speed: { min: 4, max: 18 },
      angle: { min: 0, max: 360 },
      lifespan: 350,
      scale: { start: 0.25, end: 0 },
      alpha: { start: 0.9, end: 0 },
      tint: [0x22ff44, 0x66ffaa],
      frequency: -1, // manual bursts only
      quantity: 4,
    });
    emitter.setDepth(9);
    this.emitters.push(emitter);

    // Random-interval burst loop (re-schedules itself each time,
    // since Phaser TimerEvents need a fixed delay per call).
    const scheduleNext = () => {
      const delay = 800 + Math.random() * 2200;
      this.scene.time.delayedCall(delay, () => {
        if (!emitter.active) return;
        emitter.explode(4, x, y);
        scheduleNext();
      });
    };
    scheduleNext();

    return emitter;
  }

  /** Short-lived red ember burst for critical alert states. */
  alertBurst(x: number, y: number): void {
    const emitter = this.scene.add.particles(x, y, DOT_KEY, {
      speed: { min: 20, max: 60 },
      angle: { min: 0, max: 360 },
      lifespan: 500,
      scale: { start: 0.4, end: 0 },
      tint: 0xff3333,
      quantity: 12,
    });
    emitter.setDepth(50);
    emitter.explode(12, x, y);
    this.scene.time.delayedCall(600, () => emitter.destroy());
  }

  destroy(): void {
    for (const e of this.emitters) e.destroy();
    this.emitters = [];
  }
}
