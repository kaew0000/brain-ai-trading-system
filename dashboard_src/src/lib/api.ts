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

// ── Auth (V16 Track W14-1 Item 7) ───────────────────────────────────────────
//
// In-memory only — never localStorage/sessionStorage (fails a page
// reload, same as a real session token should), never baked into the
// build (this is runtime state set by login(), not a build-time env
// var). See api/auth.py's module docstring for the two-credential-type
// design this bootstraps against: the OPERATOR enters their long-lived
// API key once via the login form, and this module holds only the
// resulting short-lived Bearer JWT for the rest of the session.
let _authToken: string | null = null
let _authRole: string | null = null
let _authExpiresAt: number | null = null

function authHeaders(): Record<string, string> {
  return _authToken ? { Authorization: `Bearer ${_authToken}` } : {}
}

/** Exchanges an API key for a session Bearer token via the existing
 *  POST /api/auth/token (api/app.py — already implemented, not a new
 *  auth system). Throws with the backend's own error message on
 *  failure (invalid key, etc.) — callers must show this as a real
 *  failure, never treat it as success. */
async function login(apiKey: string): Promise<{ role: string; expiresAt: number }> {
  const controller = new AbortController()
  const tid = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(`${BASE}/api/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
      signal: controller.signal,
    })
    clearTimeout(tid)
    const body = await r.json().catch(() => null)
    if (!r.ok) {
      const msg = body?.error || body?.detail || `login failed (HTTP ${r.status})`
      throw new Error(msg)
    }
    const data = body?.data ?? {}
    if (!data.token) throw new Error('login response missing token')
    _authToken = data.token
    _authRole = data.role ?? null
    _authExpiresAt = data.expires_at ?? null
    return { role: _authRole as string, expiresAt: _authExpiresAt as number }
  } catch (err) {
    clearTimeout(tid)
    throw err
  }
}

function logout(): void {
  _authToken = null
  _authRole = null
  _authExpiresAt = null
}

function authSnapshot(): { authenticated: boolean; role: string | null; expiresAt: number | null } {
  return { authenticated: _authToken !== null, role: _authRole, expiresAt: _authExpiresAt }
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const controller = new AbortController()
  const tid = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(`${BASE}${path}`, { signal: controller.signal, headers: authHeaders() })
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
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
  // V16 Track W14-1 Item 4/5 — real account/position telemetry, replaces
  // the MockPortfolioProvider Portfolio.tsx previously used.
  accountState:   () => get('/api/account/state'),
  // V16 Track W14-1 Item 7 — OPERATOR auth bootstrap for START/STOP.
  login,
  logout,
  authSnapshot,
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
          // V16 BUG-LIVE-RISK: process.env is Node-only and doesn't exist in
          // the browser/Vite runtime (caused TS2580 build failure). Vite
          // exposes import.meta.env.DEV/.PROD natively, statically replaced
          // at build time, no @types/node dependency needed.
          if (import.meta.env.DEV) {
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
// Phase W10 — Live Command Center UI. Same ManagedWS reconnect/backoff
// every other channel above already gets; no new WebSocket client code.
export const wsWorld     = new ManagedWS('/ws/world')

;[wsEvents, wsDecision, wsAgents, wsMissions, wsML, wsSignals, wsWorld].forEach(w => w.connect())
