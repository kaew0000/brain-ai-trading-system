// dashboard_src/src/pages/world/lpcAssets.ts
// V16 §93 — pure helpers for the Universal-LPC character sheets (64x64 cells, 13 columns, 54 rows).
// Everything is data-driven from the `lpc` block of public/assets/world/manifest.json (written by
// world/scripts/import_lpc_characters.py): sheet layout, animation rows, behaviour mapping and the
// per-role list of animations that render with a missing garment all come from the manifest, never
// from constants in the scene. Kept free of Phaser so it is unit-testable in jsdom.

export type LpcDirection = 'up' | 'left' | 'down' | 'right'

export interface LpcAnimation {
  /** LPC animation the row comes from (used by the importer to detect unsupported garments). */
  source: string
  /** First row of the animation's 4-direction block (or the single row when not directional). */
  row: number
  frames: number
  startFrame: number
  fps: number
  directional: boolean
}

export interface LpcManifest {
  version: string
  enabled: boolean
  frameSize: number
  columns: number
  rows: number
  displayHeight: number
  anchor: [number, number]
  /** Row order inside a directional block. */
  directions: LpcDirection[]
  defaultFacing: LpcDirection
  animations: Record<string, LpcAnimation>
  behaviorAnimation: Record<string, string>
  fallbackAnimation: string
  /** role -> animation names that draw the character without a garment (use the fallback instead). */
  unsupportedAnimations: Record<string, string[]>
  /** NPC role -> sheet path */
  sheets: Record<string, string>
}

/** True when the LPC art is switched on and `role` has a sheet. */
export function hasLpcCharacter(manifest: LpcManifest | null | undefined, role: string): boolean {
  return !!manifest?.enabled && !!manifest.sheets?.[role]
}

/** Animation for a behaviour. Unknown behaviours and roles whose garment is missing in that animation use the fallback. */
export function lpcAnimationName(manifest: LpcManifest, role: string, behavior: string): string {
  const wanted = manifest.behaviorAnimation[behavior] ?? manifest.fallbackAnimation
  const unsupported = manifest.unsupportedAnimations?.[role] ?? []
  if (unsupported.includes(wanted) || !manifest.animations[wanted]) return manifest.fallbackAnimation
  return wanted
}

/** Screen movement (dx right, dy down) -> facing; the dominant axis wins. Zero movement keeps `fallback`. */
export function lpcDirectionFromDelta(dx: number, dy: number, fallback: LpcDirection = 'down'): LpcDirection {
  if (dx === 0 && dy === 0) return fallback
  if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? 'right' : 'left'
  return dy > 0 ? 'down' : 'up'
}

/** Sheet row of an animation for a facing. */
export function lpcRow(manifest: LpcManifest, animation: string, direction: LpcDirection): number {
  const anim = manifest.animations[animation] ?? manifest.animations[manifest.fallbackAnimation]
  if (!anim.directional) return anim.row
  const i = manifest.directions.indexOf(direction)
  return anim.row + (i >= 0 ? i : manifest.directions.indexOf(manifest.defaultFacing))
}

/** Phaser spritesheet frame index (row * columns + column) of `step` inside an animation. */
export function lpcFrameIndex(manifest: LpcManifest, animation: string, direction: LpcDirection, step = 0): number {
  const anim = manifest.animations[animation] ?? manifest.animations[manifest.fallbackAnimation]
  const col = anim.startFrame + (((step % anim.frames) + anim.frames) % anim.frames)
  return lpcRow(manifest, animation, direction) * manifest.columns + col
}

/** Inclusive frame range of a looping animation for a facing (for Phaser's generateFrameNumbers). */
export function lpcFrameRange(manifest: LpcManifest, animation: string, direction: LpcDirection): { start: number; end: number } {
  const anim = manifest.animations[animation] ?? manifest.animations[manifest.fallbackAnimation]
  const start = lpcFrameIndex(manifest, animation, direction, 0)
  return { start, end: start + anim.frames - 1 }
}

/** Resting frame for a behaviour (facing `defaultFacing`). */
export function lpcStaticFrame(manifest: LpcManifest, role: string, behavior: string): number {
  return lpcFrameIndex(manifest, lpcAnimationName(manifest, role, behavior), manifest.defaultFacing, 0)
}
