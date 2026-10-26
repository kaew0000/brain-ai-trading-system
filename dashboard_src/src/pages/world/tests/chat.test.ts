// V16 §83 — chat client + pure helper tests (mocked fetch, no DOM).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHANNEL_MEETING, MEETING_TURNS, canStartMeeting, chatApi, clampTurns, dmChannel, insertMention,
  isMeetingActive, mergeMessages, type ChatMessage,
} from '../chatApi'

const { authHeadersMock } = vi.hoisted(() => ({
  authHeadersMock: vi.fn((): Record<string, string> => ({})),
}))
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, getAuthHeaders: authHeadersMock, whenAuthSettled: () => Promise.resolve() }
})

const msg = (id: string): ChatMessage => ({
  id, channel: 'office', senderId: 'u', senderName: 'You', senderKind: 'user', text: id, ts: 't', mentions: [],
})

describe('chat helpers', () => {
  it('dmChannel / clampTurns', () => {
    expect(dmChannel('primus')).toBe('dm:primus')
    expect(clampTurns(1)).toBe(MEETING_TURNS.min)
    expect(clampTurns(999)).toBe(MEETING_TURNS.max)
    expect(clampTurns(12.4)).toBe(12)
    expect(clampTurns(Number.NaN)).toBe(MEETING_TURNS.default)
  })

  it('insertMention keeps a single separating space', () => {
    expect(insertMention('', { panelLabel: 'CEO' })).toBe('@[CEO] ')
    expect(insertMention('hi  ', { panelLabel: 'Risk' })).toBe('hi @[Risk] ')
  })

  it('canStartMeeting needs topic and participants', () => {
    expect(canStartMeeting(' ', ['a'])).toBe(false)
    expect(canStartMeeting('t', [])).toBe(false)
    expect(canStartMeeting('t', ['a'])).toBe(true)
  })

  it('isMeetingActive', () => {
    expect(isMeetingActive(null)).toBe(false)
    expect(isMeetingActive({ status: 'paused' })).toBe(true)
    expect(isMeetingActive({ status: 'finished' })).toBe(false)
  })

  it('mergeMessages dedupes by id and caps', () => {
    const a = [msg('1'), msg('2')]
    expect(mergeMessages(a, [msg('2'), msg('3')]).map((m) => m.id)).toEqual(['1', '2', '3'])
    expect(mergeMessages(a, [], 5)).toBe(a)
    expect(mergeMessages(a, [msg('3'), msg('4')], 3).map((m) => m.id)).toEqual(['2', '3', '4'])
  })
})

describe('chatApi', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    authHeadersMock.mockReset()
    authHeadersMock.mockReturnValue({ Authorization: 'Bearer t' })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('sends the Bearer header and unwraps the envelope', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, data: [msg('1')] }) })
    const out = await chatApi.getMessages(CHANNEL_MEETING, 'x')
    expect(out[0].id).toBe('1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/world/chat/messages?channel=meeting&after=x')
    expect(init.headers).toEqual({ Authorization: 'Bearer t' })
  })

  it('POST sends JSON body with auth', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, data: { message: msg('1'), replies: [] } }) })
    await chatApi.postMessage('office', 'hi')
    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ channel: 'office', text: 'hi' })
    expect(init.headers).toEqual({ 'Content-Type': 'application/json', Authorization: 'Bearer t' })
  })

  it("surfaces the server's detail message on failure", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: 'a meeting is already active' }) })
    await expect(chatApi.next()).rejects.toThrow('a meeting is already active')
  })

  it('falls back to status when the body is not JSON', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, json: async () => { throw new Error('x') } })
    await expect(chatApi.getRoster()).rejects.toThrow('GET /api/world/chat/roster failed: 401')
  })
})
