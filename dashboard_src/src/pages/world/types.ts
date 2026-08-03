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
  viewport: { width: number; height: number; scale: number }
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
  timestamp: string
  message: string
  severity: 'info' | 'success' | 'warning' | 'critical'
  read: boolean
  category?: string
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
