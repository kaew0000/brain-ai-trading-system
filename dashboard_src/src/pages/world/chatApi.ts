// dashboard_src/src/pages/world/chatApi.ts
// V16 §83 — REST client + pure helpers for /api/world/chat/*. Same
// auth plumbing as workspaceApi.ts (Bearer header + whenAuthSettled).

import { getAuthHeaders, whenAuthSettled } from '@/lib/api'
import type { AgentPanel } from './workspaceApi'

export const CHANNEL_OFFICE = 'office'
export const CHANNEL_MEETING = 'meeting'
export const DM_PREFIX = 'dm:'

// Mirrors backend settings (WORLD_MEETING_MIN/MAX/DEFAULT_TURNS); the
// server is authoritative and rejects out-of-range values with 400.
export const MEETING_TURNS = { min: 5, max: 50, default: 20 } as const

export type MeetingMode = 'auto' | 'manual'
export type MeetingStatus = 'idle' | 'running' | 'paused' | 'finished' | 'stopped'

export interface ChatMessage {
  id: string
  channel: string
  senderId: string
  senderName: string
  senderKind: 'user' | 'npc' | 'system'
  text: string
  ts: string
  mentions: string[]
}

export interface Meeting {
  meetingId: string
  topic: string
  participants: string[]
  maxTurns: number
  mode: MeetingMode
  hybrid: boolean
  status: MeetingStatus
  turn: number
  startedAt: string | null
  endedAt: string | null
}

export interface Roster {
  engine: string
  agents: AgentPanel[]
}

export interface PostResult {
  message: ChatMessage
  replies: ChatMessage[]
}

export interface StartMeetingInput {
  topic: string
  participants: string[]
  maxTurns: number
  mode: MeetingMode
  hybrid: boolean
}

interface Envelope<T> {
  ok: boolean
  data: T
}

async function failure(method: string, path: string, res: Response): Promise<Error> {
  let detail = ''
  try {
    const body = (await res.json()) as { detail?: unknown; error?: unknown }
    detail = String(body.detail ?? body.error ?? '')
  } catch {
    // body was not JSON — status alone is the message
  }
  return new Error(detail || `${method} ${path} failed: ${res.status}`)
}

async function get<T>(path: string): Promise<T> {
  await whenAuthSettled()
  const res = await fetch(path, { headers: getAuthHeaders() })
  if (!res.ok) throw await failure('GET', path, res)
  return ((await res.json()) as Envelope<T>).data
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  await whenAuthSettled()
  const res = await fetch(path, {
    method: 'POST',
    headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...getAuthHeaders() },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw await failure('POST', path, res)
  return ((await res.json()) as Envelope<T>).data
}

export const chatApi = {
  getRoster: () => get<Roster>('/api/world/chat/roster'),
  getMessages: (channel: string, after?: string) => {
    const qs = new URLSearchParams({ channel })
    if (after) qs.set('after', after)
    return get<ChatMessage[]>(`/api/world/chat/messages?${qs.toString()}`)
  },
  postMessage: (channel: string, text: string) =>
    post<PostResult>('/api/world/chat/messages', { channel, text }),
  getMeeting: () => get<Meeting>('/api/world/chat/meeting'),
  startMeeting: (input: StartMeetingInput) => post<Meeting>('/api/world/chat/meeting/start', input),
  next: () => post<Meeting>('/api/world/chat/meeting/next'),
  pause: () => post<Meeting>('/api/world/chat/meeting/pause'),
  resume: () => post<Meeting>('/api/world/chat/meeting/resume'),
  stop: () => post<Meeting>('/api/world/chat/meeting/stop'),
}

// ── pure helpers (unit-tested) ──────────────────────────────────────────

export function dmChannel(agentId: string): string {
  return `${DM_PREFIX}${agentId}`
}

export function clampTurns(value: number): number {
  if (!Number.isFinite(value)) return MEETING_TURNS.default
  return Math.min(MEETING_TURNS.max, Math.max(MEETING_TURNS.min, Math.round(value)))
}

export function mentionToken(agent: Pick<AgentPanel, 'panelLabel'>): string {
  return `@[${agent.panelLabel}]`
}

/** Appends a mention to a draft with exactly one separating space. */
export function insertMention(draft: string, agent: Pick<AgentPanel, 'panelLabel'>): string {
  const token = mentionToken(agent)
  if (draft.length === 0) return `${token} `
  return `${draft.replace(/\s+$/, '')} ${token} `
}

export function canStartMeeting(topic: string, participants: string[]): boolean {
  return topic.trim().length > 0 && participants.length > 0
}

export function isMeetingActive(m: Pick<Meeting, 'status'> | null): boolean {
  return m !== null && (m.status === 'running' || m.status === 'paused')
}

/** Merge newly fetched messages into the list by id, keeping order and a cap. */
export function mergeMessages(prev: ChatMessage[], incoming: ChatMessage[], cap = 500): ChatMessage[] {
  if (incoming.length === 0) return prev
  const seen = new Set(prev.map((m) => m.id))
  const merged = [...prev, ...incoming.filter((m) => !seen.has(m.id))]
  return merged.length > cap ? merged.slice(merged.length - cap) : merged
}
