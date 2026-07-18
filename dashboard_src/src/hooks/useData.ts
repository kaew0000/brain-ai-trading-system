/**
 * Brain Bot V15 — Data hooks
 *
 * ── V15 original fixes ──────────────────────────────────────────────────────
 * BUG-V15-FE-05: usePoll() fn dependency missing → stale interval on fn change.
 *   Fix: fn is now in dep array; useCallback ensures stable identity.
 *
 * BUG-V15-FE-06: useJournalData() polled paper metrics even when disabled.
 *   Fix: stable paperDisabledRef; only stop after explicit enabled=false.
 *
 * BUG-V15-FE-07: useAllData() double-subscribed in React StrictMode.
 *   Fix: each useEffect cleanup calls unsub().
 *
 * ── V15.1 anti-flicker fixes ─────────────────────────────────────────────────
 * BUG-V15-FE-08 (ROOT CAUSE of flicker): /ws/decision backend pushes a new
 *   frame every 1 second with a fresh `timestamp` field even when decision
 *   data is unchanged (action/confidence/regime stay the same between
 *   60-second trading cycles). Every push called setData() which created a
 *   new object → Zustand notified all subscribers → entire page re-rendered
 *   every second → all ConfBars, StatCards, motion elements re-animated.
 *   Fix: compare the semantically-meaningful fields before calling setData().
 *   Only update when action/confidence/score/mtf_aligned/blocked changes.
 *
 * BUG-V15-FE-09: wsMissions handler checked for type 'init'|'mission_update'
 *   but backend broadcasts type 'missions' → type never matched → handler
 *   was dead code; missions only polled every 5s via HTTP.
 *   Fix: add 'missions' to the handler match list so live WS updates work.
 *   Also add data-level equality check: only call f() when mission count or
 *   any mission stage has changed.
 *
 * BUG-V15-FE-10: /ws/agents backend broadcasts type 'telemetry' every 1s.
 *   Frontend only matches 'agent_update'|'init' → dead code path; but the
 *   wsAgents WS message still consumed CPU on every frame.
 *   Fix: add 'telemetry' to match; skip HTTP re-fetch on telemetry frames
 *   (use the payload directly) to avoid a redundant round-trip.
 *
 * BUG-V15-FE-11: useDecisionData HTTP poll ran every 5s AND WS pushed every
 *   1s → two competing update paths caused micro-flicker on poll coinciding
 *   with WS update. Fix: raise HTTP poll to 30s (WS is primary for decision).
 */

import { useEffect, useCallback, useRef } from 'react'
import { api, wsEvents, wsDecision, wsAgents, wsMissions, wsML } from '@/lib/api'
import {
  useDecision, useHealth, useMissions, useAgents,
  useMarket, useJournal, useML, useCommander, useUI, useEventLog,
} from '@/stores'
import type { BusEvent } from '@/types/api'

// ── Core polling primitive ────────────────────────────────────────────────────

function usePoll(fn: () => Promise<void>, ms = 5000, stop = false) {
  useEffect(() => {
    if (stop) return
    fn()
    const id = setInterval(fn, ms)
    return () => clearInterval(id)
  }, [fn, ms, stop])
}

// ── Equality helpers ──────────────────────────────────────────────────────────

/**
 * Shallow equality on the semantically-meaningful decision fields.
 * Intentionally ignores `timestamp` so a 1s heartbeat push with an unchanged
 * decision doesn't trigger a Zustand state update and therefore no re-render.
 */
function decisionChanged(prev: any, next: any): boolean {
  if (!prev || !next) return true
  const ps = prev.signal
  const ns = next.signal
  if (!ps && !ns) return false
  if (!ps || !ns) return true
  return (
    ps.action      !== ns.action      ||
    ps.confidence  !== ns.confidence  ||
    ps.score       !== ns.score       ||
    ps.regime      !== ns.regime      ||
    ps.mtf_aligned !== ns.mtf_aligned ||
    ps.blocked     !== ns.blocked     ||
    ps.entry_price !== ns.entry_price ||
    ps.stop_loss   !== ns.stop_loss   ||
    ps.take_profit !== ns.take_profit
  )
}

/**
 * Mission-level equality: only update if count or any stage changed.
 */
function missionsChanged(prev: any, next: any): boolean {
  if (!prev || !next) return true
  if (prev.mission_count !== next.mission_count) return true
  const pm = prev.missions ?? []
  const nm = next.missions ?? []
  if (pm.length !== nm.length) return true
  for (let i = 0; i < pm.length; i++) {
    if (pm[i]?.stage !== nm[i]?.stage || pm[i]?.id !== nm[i]?.id) return true
  }
  return false
}

// ── Per-domain hooks ──────────────────────────────────────────────────────────

export function useDecisionData() {
  const { setData, data: currentData } = useDecision()
  const currentRef = useRef(currentData)
  currentRef.current = currentData

  // BUG-V15-FE-11: WS is primary; HTTP is fallback/recovery only → 30s
  const f = useCallback(async () => {
    try {
      const next = await api.decision() as any
      if (decisionChanged(currentRef.current, next)) {
        setData(next)
      }
    } catch {}
  }, [setData])

  usePoll(f, 30_000)

  useEffect(() => {
    const unsub = wsDecision.on((m: any) => {
      if (m.type === 'decision' || m.type === 'init') {
        const raw = m.data ?? m
        if (raw && (raw.action || raw.decision)) {
          const signal = {
            action:               raw.action,
            direction:            raw.direction ?? raw.action,
            confidence:           raw.confidence ?? 0,
            score:                raw.raw_score  ?? raw.confidence ?? 0,
            regime:               raw.regime     ?? '',
            mtf_aligned:          raw.mtf_aligned ?? false,
            blocked:              raw.blocked     ?? false,
            block_reasons:        raw.block_reasons ?? [],
            entry_price:          raw.entry_price  ?? 0,
            stop_loss:            raw.stop_loss    ?? 0,
            take_profit:          raw.take_profit  ?? 0,
            confidence_breakdown: raw.breakdown    ?? {},
          }
          const next = { signal, decision: raw, timestamp: m.timestamp ?? new Date().toISOString() }
          // BUG-V15-FE-08: only update store if something meaningful changed
          if (decisionChanged(currentRef.current, next)) {
            setData(next as any)
          }
        }
      }
    })
    return () => { unsub() }
  }, [setData])
}

export function useHealthData() {
  const { setData, setRecon } = useHealth()
  const { setConnected } = useUI()

  const f = useCallback(async () => {
    try { setData(await api.systemHealth() as any); setConnected(true) }
    catch { setConnected(false) }
  }, [setData, setConnected])

  const r = useCallback(async () => {
    try { setRecon(await api.reconciliation() as any) } catch {}
  }, [setRecon])

  usePoll(f, 8000)
  usePoll(r, 15000)
}

export function useMissionsData() {
  const { setData, data: currentData } = useMissions()
  const currentRef = useRef(currentData)
  currentRef.current = currentData

  const f = useCallback(async () => {
    try {
      const next = await api.missions() as any
      if (missionsChanged(currentRef.current, next)) {
        setData(next)
      }
    } catch {}
  }, [setData])

  usePoll(f, 5000)

  useEffect(() => {
    const unsub = wsMissions.on((m: any) => {
      // BUG-V15-FE-09: backend sends type='missions'; also keep 'init'|'mission_update'
      if (m.type === 'init' || m.type === 'mission_update' || m.type === 'missions') {
        // Use inline WS data when available to avoid HTTP round-trip
        if (m.data && m.type === 'missions') {
          const next = m.data
          if (missionsChanged(currentRef.current, next)) {
            setData(next)
          }
        } else {
          f()
        }
      }
    })
    return () => { unsub() }
  }, [f, setData])
}

export function useAgentsData() {
  const { setAgents, setTelemetry } = useAgents()

  const fa = useCallback(async () => {
    try { setAgents(await api.agents() as any) } catch {}
  }, [setAgents])

  const ft = useCallback(async () => {
    try { setTelemetry(await api.agentTelemetry() as any) } catch {}
  }, [setTelemetry])

  usePoll(fa, 6000)
  usePoll(ft, 8000)

  useEffect(() => {
    const unsub = wsAgents.on((m: any) => {
      if (m.type === 'agent_update' || m.type === 'init') {
        fa()
      } else if (m.type === 'telemetry' && m.data) {
        // BUG-V15-FE-10: use payload directly; avoid redundant HTTP call
        setTelemetry(m.data)
      }
    })
    return () => { unsub() }
  }, [fa, setTelemetry])
}

export function useMarketData() {
  const { setIntelligence, setFutures, setRegime, setSignals } = useMarket()

  const f = useCallback(async () => {
    try { setIntelligence(await api.intelligence() as any) } catch {}
    try { setFutures(await api.futures() as any) } catch {}
    try { setRegime(await api.regime() as any) } catch {}
    try { setSignals(await api.signals(50) as any) } catch {}
  }, [setIntelligence, setFutures, setRegime, setSignals])

  usePoll(f, 10000)
}

export function useJournalData() {
  const { setJournal, setPaper } = useJournal()
  const paperDisabledRef = useRef(false)

  const fj = useCallback(async () => {
    try { setJournal(await api.journal() as any) } catch {}
  }, [setJournal])

  const fp = useCallback(async () => {
    try {
      const data = await api.paperMetrics() as any
      setPaper(data)
      if (data?.enabled === false) paperDisabledRef.current = true
    } catch {}
  }, [setPaper])

  usePoll(fj, 10000)
  usePoll(fp, 8000, paperDisabledRef.current)
}

export function useMLData() {
  const { setStatus, setPerformance } = useML()

  const f = useCallback(async () => {
    try { setStatus(await api.mlStatus() as any) } catch {}
    try { setPerformance(await api.mlPerformance() as any) } catch {}
  }, [setStatus, setPerformance])

  usePoll(f, 15000)

  useEffect(() => {
    const unsub = wsML.on((m: any) => { if (m.status) setStatus(m.status) })
    return () => { unsub() }
  }, [setStatus])
}

export function useEventStream() {
  const { addEvent } = useEventLog()

  useEffect(() => {
    const unsub = wsEvents.on((m: any) => {
      if (m.type === 'init' && Array.isArray(m.events))
        m.events.slice(0, 50).forEach((e: BusEvent) => addEvent(e))
      else if (m.type === 'event' && m.data)
        addEvent(m.data as BusEvent)
    })
    return () => { unsub() }
  }, [addEvent])
}

export function useCommanderData() {
  const { setState } = useCommander()

  const f = useCallback(async () => {
    try { setState(await api.commandState() as any) } catch {}
  }, [setState])

  usePoll(f, 5000)
}

export function useAllData() {
  useDecisionData()
  useHealthData()
  useMissionsData()
  useAgentsData()
  useMarketData()
  useJournalData()
  useMLData()
  useEventStream()
  useCommanderData()
}
