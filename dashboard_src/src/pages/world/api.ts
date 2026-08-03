// dashboard_src/src/pages/world/api.ts
// Phase W10 — thin fetch layer over /api/world/*, plus the shared
// ManagedWS('/ws/world') instance (src/lib/api.ts). Deliberately its own
// small get/post rather than extending the shared `api` object in
// src/lib/api.ts, to keep this page's backend surface self-contained and
// easy to review as one Track-B-facing unit.

import { wsWorld } from '@/lib/api'
import type {
  CharacterActivity,
  CommandResult,
  HoverInfo,
  InspectorReport,
  NotificationItem,
  RenderFrame,
  RoomActivity,
  SimulationState,
  TimelineStatus,
  WorldEnvelope,
} from './types'

export { wsWorld }

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  const envelope = (await res.json()) as WorldEnvelope<T>
  return envelope.data
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'POST' })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`)
  const envelope = (await res.json()) as WorldEnvelope<T>
  return envelope.data
}

export const worldApi = {
  getSimulationState: () => get<SimulationState>('/api/world/simulation'),
  listRooms: () => get<RoomActivity[]>('/api/world/rooms'),
  getRoom: (roomId: string) => get<RoomActivity>(`/api/world/rooms/${roomId}`),
  getCharacter: (agentId: string) => get<CharacterActivity>(`/api/world/characters/${agentId}`),
  getRoomFrame: (roomId: string) => get<RenderFrame>(`/api/world/rooms/${roomId}/frame`),

  select: (kind: string, targetId: string) =>
    post<{ kind: string; targetId: string }>(`/api/world/select/${kind}/${targetId}`),
  hover: (kind: string, targetId: string) =>
    post<{ kind: string; targetId: string; label: string }>(`/api/world/hover/${kind}/${targetId}`),
  inspect: (kind: string, targetId: string) =>
    get<InspectorReport>(`/api/world/inspect/${kind}/${targetId}`),
  search: (q: string) => get<HoverInfo[]>(`/api/world/search?q=${encodeURIComponent(q)}`),

  getNotifications: (category?: string) =>
    get<NotificationItem[]>(
      category ? `/api/world/notifications?category=${encodeURIComponent(category)}` : '/api/world/notifications',
    ),

  getTimeline: () => get<TimelineStatus>('/api/world/timeline'),
  timelinePlay: () => post<{ isPlaying: boolean }>('/api/world/timeline/play'),
  timelinePause: () => post<{ isPlaying: boolean }>('/api/world/timeline/pause'),
  timelineResume: () => post<{ isPlaying: boolean }>('/api/world/timeline/resume'),
  timelineSeek: (tick: number) => post<SimulationState>(`/api/world/timeline/seek?tick=${tick}`),

  focusRoom: (roomId: string) => post<CommandResult>(`/api/world/command/focus_room?target=${roomId}`),
  followCharacter: (agentId: string) =>
    post<CommandResult>(`/api/world/command/follow_character?target=${agentId}`),
  setSimulationSpeed: (speed: number) =>
    post<CommandResult>(`/api/world/command/set_simulation_speed?speed=${speed}`),
  pauseSimulation: () => post<CommandResult>('/api/world/command/pause_simulation'),
  resumeSimulation: () => post<CommandResult>('/api/world/command/resume_simulation'),
}
