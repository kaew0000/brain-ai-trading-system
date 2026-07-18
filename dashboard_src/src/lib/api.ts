/**
 * Brain Bot V15 — Frontend API client + WebSocket manager
 *
 * V14 bugs fixed
 * --------------
 * BUG-V15-FE-01: ManagedWS reconnect had fixed 2000ms delay with no backoff.
 *   Under network instability all clients reconnected simultaneously
 *   (thundering herd), overloading the FastAPI server.
 *   Fix: Exponential backoff: 1s → 2s → 4s → 8s … capped at 30s, ±20% jitter.
 *
 * BUG-V15-FE-02: ManagedWS.stopped flag not reset after manual disconnect.
 *   Once disconnect() was called, reconnects were silently skipped even
 *   when the component remounted.
 *   Fix: Added reconnect() public method; stopped is only set by explicit
 *   disconnect().
 *
 * BUG-V15-FE-03: WebSocket message parse errors swallowed silently.
 *   A corrupted frame would cause the handler to throw, but the error
 *   was caught and ignored — no visibility.
 *   Fix: Logs parse errors at debug level; continues processing.
 *
 * BUG-V15-FE-04: fetch() calls had no timeout protection.
 *   A slow API server response would hang the polling hook indefinitely,
 *   blocking the setInterval from firing the next cycle correctly.
 *   Fix: AbortController with 8s timeout on all fetch() calls.
 */

const BASE = ''
const FETCH_TIMEOUT_MS = 8_000

// ── HTTP helpers ──────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const controller = new AbortController()
  const tid = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(`${BASE}${path}`, { signal: controller.signal })
    clearTimeout(tid)
    if (!r.ok) throw new Error(`${path} → ${r.status}`)
    const body = await r.json()
    return body.data as T
  } catch (err) {
    clearTimeout(tid)
    throw err
  }
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  const controller = new AbortController()
  const tid = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    clearTimeout(tid)
    return r.json()
  } catch (err) {
    clearTimeout(tid)
    throw err
  }
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  health:         () => get('/api/health'),
  systemHealth:   () => get('/api/system/health'),
  reconciliation: () => get('/api/system/reconciliation'),
  decision:       () => get('/api/decision'),
  missions:       (l = 50)   => get(`/api/missions?limit=${l}`),
  missionDetail:  (id: string) => get(`/api/missions/${id}`),
  agents:         () => get('/api/agents'),
  agentDetail:    (n: string)  => get(`/api/agents/${n}`),
  agentMemory:    (n: string)  => get(`/api/agents/${n}/memory`),
  agentTelemetry: () => get('/api/agents/telemetry'),
  agentGraph:     () => get('/api/agents/graph'),
  reasoning:      () => get('/api/agents/reasoning'),
  intelligence:   () => get('/api/intelligence'),
  futures:        () => get('/api/futures'),
  regime:         () => get('/api/regime'),
  signals:        (l = 100)  => get(`/api/signals?limit=${l}`),
  journal:        () => get('/api/journal'),
  paper:          () => get('/api/paper'),
  paperMetrics:   () => get('/api/paper/metrics'),
  paperTrades:    () => get('/api/paper/trades'),
  mlStatus:       () => get('/api/ml/status'),
  mlModels:       () => get('/api/ml/models'),
  mlPerformance:  () => get('/api/ml/performance'),
  forwardTest:    () => get('/api/forward_test'),
  commandState:   () => get('/api/command/state'),
  sendCommand:    (cmd: string, params?: Record<string, unknown>) =>
    post('/api/command', { command: cmd, params }),
  chat:           (message: string) => post('/api/chat', { message }),
}

// ── WebSocket manager (V15: exponential backoff) ──────────────────────────────

type WsHandler = (data: unknown) => void

/** Minimum reconnect delay in ms */
const WS_DELAY_MIN = 1_000
/** Maximum reconnect delay in ms */
const WS_DELAY_MAX = 30_000
/** Jitter fraction (±20%) */
const WS_JITTER    = 0.2

function withJitter(ms: number): number {
  const spread = ms * WS_JITTER
  return ms + (Math.random() * 2 - 1) * spread
}

export class ManagedWS {
  private ws:       WebSocket | null = null
  private handlers  = new Set<WsHandler>()
  private url:      string
  private stopped   = false
  private delay     = WS_DELAY_MIN
  private retryTimer: ReturnType<typeof setTimeout> | null = null

  constructor(path: string) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    this.url = `${proto}://${window.location.host}${path}`
  }

  connect(): void {
    if (this.stopped) return
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        // Reset backoff on successful connection
        this.delay = WS_DELAY_MIN
      }

      this.ws.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data as string)
          this.handlers.forEach(h => h(d))
        } catch (err) {
          // V15: log parse errors rather than silently ignoring
          if (process.env.NODE_ENV !== 'production') {
            console.debug('[ManagedWS] parse error:', err)
          }
        }
      }

      this.ws.onclose = () => {
        if (this.stopped) return
        // V15: exponential backoff with jitter
        const wait = Math.min(withJitter(this.delay), WS_DELAY_MAX)
        this.delay  = Math.min(this.delay * 2, WS_DELAY_MAX)
        this.retryTimer = setTimeout(() => this.connect(), wait)
      }

      this.ws.onerror = () => {
        // onerror is always followed by onclose; close triggers reconnect
        this.ws?.close()
      }
    } catch {
      // new WebSocket() can throw in SSR / test environments
    }
  }

  /** Register an event handler. Returns an unsubscribe function. */
  on(h: WsHandler): () => void {
    this.handlers.add(h)
    return () => this.handlers.delete(h)
  }

  /** Permanently stop this connection (does not reconnect). */
  disconnect(): void {
    this.stopped = true
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    this.ws?.close()
  }

  /** Re-enable and reconnect after a previous disconnect(). */
  reconnect(): void {
    this.stopped = false
    this.delay   = WS_DELAY_MIN
    this.connect()
  }

  /** Current ready state string. */
  get readyState(): string {
    if (!this.ws) return 'NONE'
    const states = ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']
    return states[this.ws.readyState] ?? 'UNKNOWN'
  }
}

// ── Module-level WS singletons (connect on module load) ───────────────────────

export const wsEvents   = new ManagedWS('/ws/events')
export const wsDecision = new ManagedWS('/ws/decision')
export const wsAgents   = new ManagedWS('/ws/agents')
export const wsMissions = new ManagedWS('/ws/missions')
export const wsML       = new ManagedWS('/ws/ml')
export const wsSignals  = new ManagedWS('/ws/signals')

;[wsEvents, wsDecision, wsAgents, wsMissions, wsML, wsSignals].forEach(w => w.connect())
