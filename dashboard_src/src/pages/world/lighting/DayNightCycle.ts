// ============================================================
// Brain Bot V15 — Day/Night Cycle
// Drives a repeating in-game clock and interpolates ambient
// light color + an exterior darkness overlay alpha across
// dawn -> day -> dusk -> night. Interiors stay lit via
// LightingSystem point lights regardless of outdoor phase.
// ============================================================

import type { LightingSystem } from './LightingSystem';

export type DayPhase = 'dawn' | 'day' | 'dusk' | 'night';

interface KeyFrame {
  t: number; // 0..1 fraction of the full cycle
  ambient: number; // 0xRRGGBB
  overlayAlpha: number; // exterior darkening overlay (0..1)
  phase: DayPhase;
}

const KEYFRAMES: KeyFrame[] = [
  { t: 0.00, ambient: 0x1c1c30, overlayAlpha: 0.55, phase: 'night' },
  { t: 0.20, ambient: 0x6a5a55, overlayAlpha: 0.25, phase: 'dawn' },
  { t: 0.30, ambient: 0xffffff, overlayAlpha: 0.00, phase: 'day' },
  { t: 0.70, ambient: 0xffffff, overlayAlpha: 0.00, phase: 'day' },
  { t: 0.80, ambient: 0x8a5a4a, overlayAlpha: 0.28, phase: 'dusk' },
  { t: 1.00, ambient: 0x1c1c30, overlayAlpha: 0.55, phase: 'night' },
];

function lerpColor(a: number, b: number, t: number): number {
  const ar = (a >> 16) & 0xff, ag = (a >> 8) & 0xff, ab = a & 0xff;
  const br = (b >> 16) & 0xff, bg = (b >> 8) & 0xff, bb = b & 0xff;
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bch = Math.round(ab + (bb - ab) * t);
  return (r << 16) | (g << 8) | bch;
}

export class DayNightCycle {
  /** Full cycle duration in real-world ms (default 8 minutes = a "day"). */
  private cycleDurationMs: number;
  private elapsed = 0;
  private lighting: LightingSystem | null;
  private currentPhase: DayPhase = 'day';
  private onPhaseChange?: (phase: DayPhase) => void;
  private paused = false;

  constructor(
    lighting: LightingSystem | null,
    cycleDurationMs = 8 * 60 * 1000,
    onPhaseChange?: (phase: DayPhase) => void,
  ) {
    this.lighting = lighting;
    this.cycleDurationMs = cycleDurationMs;
    this.onPhaseChange = onPhaseChange;
    // Start at "day" so the world is fully lit on load.
    this.elapsed = 0.5 * cycleDurationMs;
  }

  setPaused(p: boolean): void { this.paused = p; }
  getPhase(): DayPhase { return this.currentPhase; }

  /** 0..1 progress through the current cycle. */
  getT(): number {
    return (this.elapsed % this.cycleDurationMs) / this.cycleDurationMs;
  }

  update(delta: number): { ambient: number; overlayAlpha: number } {
    if (!this.paused) this.elapsed += delta;
    const t = this.getT();

    let k0 = KEYFRAMES[0];
    let k1 = KEYFRAMES[KEYFRAMES.length - 1];
    for (let i = 0; i < KEYFRAMES.length - 1; i++) {
      if (t >= KEYFRAMES[i].t && t <= KEYFRAMES[i + 1].t) {
        k0 = KEYFRAMES[i];
        k1 = KEYFRAMES[i + 1];
        break;
      }
    }
    const span = k1.t - k0.t || 1;
    const localT = (t - k0.t) / span;

    const ambient = lerpColor(k0.ambient, k1.ambient, localT);
    const overlayAlpha = k0.overlayAlpha + (k1.overlayAlpha - k0.overlayAlpha) * localT;

    this.lighting?.setAmbient(ambient);

    const phase = localT < 0.5 ? k0.phase : k1.phase;
    if (phase !== this.currentPhase) {
      this.currentPhase = phase;
      this.onPhaseChange?.(phase);
    }

    return { ambient, overlayAlpha };
  }
}
