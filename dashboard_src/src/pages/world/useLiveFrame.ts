// dashboard_src/src/pages/world/useLiveFrame.ts
// V16 §82 — keeps the selected room's RenderFrame fresh.
//
// Before: the frame was fetched once per room selection, so the scene never
// changed after that (NPCs could not visibly move). Now: fetch on selection,
// refetch on every /ws/world "simulation" (and "init") message, and fall back
// to a slow poll while the socket is not LIVE. At most one refresh is in
// flight at a time, and a response for a room that is no longer selected is
// dropped, so a slow request can never overwrite a newer frame.
import { useCallback, useEffect, useRef, useState } from 'react'
import { WORLD_CONFIG } from '../../game/config/world.config'
import { worldApi, wsWorld } from './api'
import type { RenderFrame } from './types'

type WsState = 'LIVE' | 'RECONNECTING' | 'DISCONNECTED'

export function useLiveFrame(roomId: string | null, wsStatus: WsState): RenderFrame | null {
  const [frame, setFrame] = useState<RenderFrame | null>(null)
  const roomIdRef = useRef<string | null>(roomId)
  roomIdRef.current = roomId
  const inflightRef = useRef(false)
  const seqRef = useRef(0)

  // Room selection: load immediately; a failure clears the frame (prior behaviour).
  useEffect(() => {
    if (!roomId) return
    const seq = ++seqRef.current
    worldApi
      .getRoomFrame(roomId)
      .then((f) => {
        if (seq === seqRef.current && roomIdRef.current === roomId) setFrame(f)
      })
      .catch(() => {
        if (seq === seqRef.current && roomIdRef.current === roomId) setFrame(null)
      })
  }, [roomId])

  // Live refresh: keep the last good frame on failure (a blip must not blank the scene).
  const refresh = useCallback(() => {
    const id = roomIdRef.current
    if (!id || inflightRef.current) return
    inflightRef.current = true
    const seq = ++seqRef.current
    worldApi
      .getRoomFrame(id)
      .then((f) => {
        if (seq === seqRef.current && roomIdRef.current === id) setFrame(f)
      })
      .catch((err) => console.debug('world: live frame refresh failed', err))
      .finally(() => {
        inflightRef.current = false
      })
  }, [])

  useEffect(
    () =>
      wsWorld.on((msg: unknown) => {
        const type = (msg as { type?: string } | null)?.type
        if (type === 'simulation' || type === 'init') refresh()
      }),
    [refresh],
  )

  useEffect(() => {
    if (wsStatus === 'LIVE') return
    const id = setInterval(refresh, WORLD_CONFIG.frameFallbackPollMs)
    return () => clearInterval(id)
  }, [wsStatus, refresh])

  return frame
}
