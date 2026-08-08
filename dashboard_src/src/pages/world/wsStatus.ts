// dashboard_src/src/pages/world/wsStatus.ts
// Phase W13-3 — presentation-only mapping from ManagedWS.readyState
// (src/lib/api.ts) to the three connection states the World header
// shows. Deliberately a pure function, separate from WorldPage.tsx's
// polling useEffect, so it's unit-testable in jsdom without a real
// WebSocket or @testing-library/react (not a dependency of this
// project — see world.test.ts's own note on this).
//
// This is frontend transport state only — it must never be read as
// trading state (per this phase's own explicit instruction). It does
// not touch, wrap, or replace ManagedWS itself; WorldPage.tsx still
// owns the one existing /ws/world connection and polls its
// `readyState` exactly as it always has.

export type WsConnectionStatus = 'LIVE' | 'RECONNECTING' | 'DISCONNECTED'

/**
 * `readyState` — ManagedWS.readyState's current string ('OPEN' |
 * 'CONNECTING' | 'CLOSING' | 'CLOSED' | 'NONE' | 'UNKNOWN').
 * `hasEverConnected` — true once this socket has reached OPEN at
 * least once. Distinguishes "still trying the very first connection"
 * (DISCONNECTED — nothing to reconnect to yet) from "was live, lost
 * it, backing off before retrying" (RECONNECTING) — the suggested
 * semantics this phase specifies.
 */
export function deriveWsStatus(readyState: string, hasEverConnected: boolean): WsConnectionStatus {
  if (readyState === 'OPEN') return 'LIVE'
  if (readyState === 'CONNECTING' && hasEverConnected) return 'RECONNECTING'
  return 'DISCONNECTED'
}

export const WS_STATUS_LABEL: Record<WsConnectionStatus, string> = {
  LIVE: 'Live',
  RECONNECTING: 'Reconnecting…',
  DISCONNECTED: 'Disconnected',
}

export const WS_STATUS_CLASSNAME: Record<WsConnectionStatus, string> = {
  LIVE: 'bg-green-900 text-green-300',
  RECONNECTING: 'bg-amber-900 text-amber-300',
  DISCONNECTED: 'bg-slate-800 text-slate-400',
}
