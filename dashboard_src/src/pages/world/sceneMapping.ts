// dashboard_src/src/pages/world/sceneMapping.ts
// Phase W10 — pure functions mapping Phase W7 behavior/activity strings to
// display colors and labels. Deliberately separate from OfficeScene.tsx
// (the Phaser canvas component) so this logic is unit-testable in jsdom
// without needing a real WebGL/Canvas context.

import type { CharacterActivity, RoomActivity } from './types'

export const BEHAVIOR_COLORS: Record<CharacterActivity['behavior'], number> = {
  idle: 0x64748b, // slate
  walking: 0x38bdf8, // sky
  working: 0x22c55e, // green
  meeting: 0xa855f7, // purple
  emergency: 0xef4444, // red
  celebration: 0xf59e0b, // amber
  resting: 0x94a3b8, // muted slate
}

export const ACTIVITY_COLORS: Record<RoomActivity['activity'], number> = {
  quiet: 0x334155,
  busy: 0x2563eb,
  meeting: 0xa855f7,
  alert: 0xf59e0b,
  critical: 0xef4444,
  celebration: 0xfacc15,
}

export function behaviorColorHex(behavior: CharacterActivity['behavior']): string {
  return `#${BEHAVIOR_COLORS[behavior].toString(16).padStart(6, '0')}`
}

export function activityColorHex(activity: RoomActivity['activity']): string {
  return `#${ACTIVITY_COLORS[activity].toString(16).padStart(6, '0')}`
}

export function behaviorLabel(behavior: CharacterActivity['behavior']): string {
  return behavior.charAt(0).toUpperCase() + behavior.slice(1)
}

export function activityLabel(activity: RoomActivity['activity']): string {
  return activity.charAt(0).toUpperCase() + activity.slice(1)
}

/** Furniture command asset ids look like "furniture.desk" / "furniture.chair"
 * — this strips the category prefix for a clean display label, purely a
 * presentation concern (the backend's asset ids are the source of truth,
 * this never changes what's rendered, only its on-screen caption). */
export function assetDisplayName(assetId: string | undefined): string {
  if (!assetId) return ''
  const parts = assetId.split('.')
  return parts[parts.length - 1].replace(/-/g, ' ')
}

// ---- Phase W-ISO-1: isometric presentation helpers (pure, jsdom-testable) ----

/** Depth for a draw command. Floors always sit beneath everything; furniture and
 * characters share one depth axis (their screenY) so a character standing
 * "behind" a desk is correctly occluded. A tiny bias makes characters win
 * exact ties against furniture on the same row. */
export const ISO_FLOOR_DEPTH = -1_000_000
export const ISO_CHARACTER_TIE_BIAS = 0.1

export function isoDepth(layer: string, screenY: number): number {
  if (layer === 'floor') return ISO_FLOOR_DEPTH
  return layer === 'characters' ? screenY + ISO_CHARACTER_TIE_BIAS : screenY
}

/** Four corners of the isometric floor diamond centred on (cx, cy). halfWidth is
 * the horizontal half-diagonal in px; the vertical half-diagonal is
 * halfWidth * ratio (0.5 = classic 2:1). Order: top, right, bottom, left. */
export function isoDiamondPoints(cx: number, cy: number, halfWidth: number, ratio: number): Array<[number, number]> {
  const halfHeight = halfWidth * ratio
  return [
    [cx, cy - halfHeight],
    [cx + halfWidth, cy],
    [cx, cy + halfHeight],
    [cx - halfWidth, cy],
  ]
}

export function isIsometric(frame: { viewport: { projection?: string } } | null | undefined): boolean {
  return frame?.viewport?.projection === 'isometric'
}
