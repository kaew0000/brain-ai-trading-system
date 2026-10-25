// dashboard_src/src/pages/world/types.ts
// Phase W10 — types mirroring api/world_api.py's JSON responses exactly
// (camelCase, matching world/runtime/simulation/interaction/frontend's own
// to_dict() conventions established since Phase W5).

export interface Position {
  x: number
  y: number
}

export interface RoomActivity {
  roomId: string
  activity: 'quiet' | 'busy' | 'meeting' | 'alert' | 'critical' | 'celebration'
  occupantCount: number
}

export interface CharacterActivity {
  agentId: string
  agentRef: string
  behavior: 'idle' | 'walking' | 'working' | 'meeting' | 'emergency' | 'celebration' | 'resting'
  roomId: string
  position: Position
  targetPosition: Position | null
}

export interface EventDescriptor {
  eventId: string
  kind: string
  roomId: string
  agentId: string
  timestamp: string
  message: string
}

export interface SimulationTick {
  tickNumber: number
  simulatedSeconds: number
  worldSequence: number
}

export interface SimulationState {
  tick: SimulationTick
  running: boolean
  characters: CharacterActivity[]
  rooms: RoomActivity[]
  events: EventDescriptor[]
}

export interface RenderCommand {
  commandType: 'tile' | 'sprite' | 'overlay'
  entityId: string
  layer: 'floor' | 'furniture' | 'characters' | 'ui_overlay'
  zOrder: number
  screenX: number
  screenY: number
  assetId?: string
  metadata: Record<string, unknown>
}

export interface RenderFrame {
  sceneId: string
  roomId: string
  sequence: number
  camera: { x: number; y: number; zoom: number; focusMode: string }
  viewport: { width: number; height: number; scale: number; projection?: 'orthographic' | 'isometric'; isoTileRatio?: number }
  commands: RenderCommand[]
}

export interface Selection {
  kind: string
  targetId: string
}

export interface HoverInfo {
  kind: string
  targetId: string
  label: string
}

export interface InspectorReport {
  kind: string
  targetId: string
  [key: string]: unknown
}

export interface NotificationItem {
  id: string
  category: 'emergency' | 'meeting' | 'alert' | 'mission' | 'celebration' | 'system_status'
  roomId: string
  tickNumber: number
  message: string
  agentId: string
}

export interface TimelineStatus {
  length: number
  isPlaying: boolean
  current: SimulationState | null
}

export interface CommandResult {
  command: string
  ok: boolean
  detail: string
  data: Record<string, unknown>
}

export interface WorldEnvelope<T> {
  ok: boolean
  data: T
}

// ── Live monitoring (V16 §82) ───────────────────────────────────────────
// Wire shapes of GET /api/world/state (world.runtime WorldState.to_dict())
// and GET /api/world/ticker. Only the fields the System Pulse reads.

export interface WorldPortfolioSummary {
  dailyPnl: number | null
  floatingPnl: number | null
  drawdown: number | null
  winRate: number | null
  avgRr: number | null
}

export interface WorldStateSnapshot {
  engineStatus: string
  capturedAt: string
  sequence: number
  missions: { missionId: string; status: string; title?: string }[]
  portfolioSummary: WorldPortfolioSummary | null
  notifications: { id: string; timestamp: string; message: string; severity: string; read: boolean }[]
  events: { id: string; timestamp: string; type: string; district: string; severity: string; agent: string; message: string }[]
  telemetry: { name: string; value: number; unit: string; district: string }[]
  orders: { symbol: string; state: string | null }[]
  reconciliation: {
    lastRun: string | null
    lastResult: string | null
    eventCount: number | null
    suppressedRepeatCount: number | null
  } | null
}

export type TickerStatus = 'ok' | 'degraded' | 'stalled' | 'stopped' | 'disabled'

export interface TickerHealth {
  status: TickerStatus
  running: boolean
  intervalSeconds?: number
  tickCount?: number
  failureCount?: number
  consecutiveFailures?: number
  lastTickAt?: string | null
  lastTickAgeSeconds?: number | null
  lastError?: string | null
}
