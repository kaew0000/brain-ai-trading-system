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
      credentials: 'include', // V16 Phase 4C — must receive the httpOnly refresh cookie
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
    _scheduleRotate()
    _notifyAuthChange('login')
    return { role: _authRole as string, expiresAt: _authExpiresAt as number }
  } catch (err) {
    clearTimeout(tid)
    throw err
  }
}

/** V16 Phase 4C — Dashboard Session Persistence.
 *
 *  Root cause this fixes: _authToken above is deliberately in-memory
 *  only (see this module's docstring above for why — never
 *  localStorage/sessionStorage), so a page refresh always wiped it
 *  and forced the operator to re-enter their API key, every time, even
 *  seconds after they'd just logged in. That in-memory design is
 *  unchanged by this fix.
 *
 *  What changed: login() above now also receives an httpOnly
 *  refresh-token cookie (set by the backend — this module never reads
 *  or writes it directly, the browser handles that automatically on
 *  every same-origin request). This function silently exchanges that
 *  cookie for a fresh Bearer token via POST /api/auth/session. Call it
 *  once when the app mounts (see components/layout/Layout.tsx) —
 *  before the operator does anything — so an existing session picks
 *  back up automatically instead of showing the LOGIN button.
 *
 *  Because the cookie is httpOnly, this code (and any XSS payload
 *  that might end up running in this page) still cannot read the
 *  underlying credential value — only the browser can attach it to a
 *  request. That's what keeps this from reopening the exact risk the
 *  in-memory-only Bearer token design above was written to avoid.
 *
 *  Resolves true if a session was restored (role/expiresAt are now
 *  populated exactly as after login()) or false if there was nothing
 *  to restore (first-ever visit, cookie expired/revoked, or auth
 *  disabled server-side). False is the ordinary, expected outcome for
 *  most page loads — never throws for it, only a genuine network
 *  failure propagates as a rejected promise... actually not even
 *  that: network failures also resolve false, so callers never need
 *  a try/catch around this. */
async function restoreSession(): Promise<boolean> {
  const controller = new AbortController()
  const tid = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(`${BASE}/api/auth/session`, {
      method: 'POST',
      credentials: 'include',
      signal: controller.signal,
    })
    clearTimeout(tid)
    if (!r.ok) return false // 401 no/expired/revoked cookie, or 400 auth disabled — both mean "not logged in"
    const body = await r.json().catch(() => null)
    const data = body?.data ?? {}
    if (!data.token) return false
    _authToken = data.token
    _authRole = data.role ?? null
    _authExpiresAt = data.expires_at ?? null
    // V16 dashboard-auth-fix parity: a restored session is exactly as
    // "logged in" as one from login() above — it needs the same
    // proactive-rotation scheduling (or this session would silently die
    // at JWT_EXPIRY_MINUTES with nothing ever refreshing it, the exact
    // bug that fix closed) and the same 'login' notification (or
    // ManagedWS's onAuthChange listener below never learns a token now
    // exists and every /ws/* channel stays disconnected for the rest of
    // the session, since it only (re)connects on an authenticated
    // transition).
    _scheduleRotate()
    _notifyAuthChange('login')
    return true
  } catch {
    clearTimeout(tid)
    return false // network error on a silent background restore — fail closed to "not logged in", never surface as a hard error
  }
}

/** Ends the session. Revokes the refresh-token cookie server-side via
 *  POST /api/auth/logout (V16 Phase 4C) — clearing local state alone,
 *  which is all this did before that phase, left the cookie itself
 *  still valid and replayable. Local state is cleared first,
 *  synchronously, so the UI reflects "logged out" immediately; the
 *  revoke call is fire-and-forget best-effort after that — if it
 *  never reaches the server (offline, server restarting), the cookie
 *  simply expires on its own after JWT_REFRESH_EXPIRY_DAYS. */
function logout(): void {
  _clearRotateTimer()
  const hadSession = _authToken !== null
  _authToken = null
  _authRole = null
  _authExpiresAt = null
  _notifyAuthChange('logout')
  if (!hadSession) return
  // Promise.resolve(...) wraps the fetch() call defensively — a test
  // double or non-standard fetch shim that doesn't return a real
  // Promise (e.g. a bare vi.fn() with no configured resolved value)
  // would otherwise throw synchronously on .catch() here and take the
  // rest of logout()'s already-completed local cleanup down with it,
  // even though local state is fully cleared by this point regardless
  // of what fetch() does or doesn't return.
  Promise.resolve(fetch(`${BASE}/api/auth/logout`, { method: 'POST', credentials: 'include' })).catch(() => {
    // best-effort — local state above is already cleared regardless
  })
}

function authSnapshot(): { authenticated: boolean; role: string | null; expiresAt: number | null } {
  return { authenticated: _authToken !== null, role: _authRole, expiresAt: _authExpiresAt }
}

// ── Auth-change notifications (V16 dashboard-auth-fix) ──────────────────────
//
// Two independent bugs used to share one symptom: an unbroken stream of
// `UNAUTHORIZED ... token expired` / `... missing credentials` WARNINGs in
// the backend log (api/auth.py's log_unauthorized()) — self-inflicted by
// this dashboard, not real intrusion attempts.
//   1. ManagedWS (below) never carried a token at all, so every /ws/*
//      handshake was rejected from the moment the page loaded, forever,
//      login or not.
//   2. Once a Bearer token's JWT_EXPIRY_MINUTES elapsed, nothing ever
//      refreshed it, so every subsequent GET/POST kept sending the same
//      dead token forever.
// This pub/sub is the shared trigger both fixes hang off: ManagedWS
// reconnects/disconnects on authenticated transitions, and useAuth
// (stores/index.ts) reflects a forced expiry so the UI stops claiming
// "signed in" once the session is actually dead.
export type AuthChangeReason = 'login' | 'logout' | 'rotate' | 'rotate_failed'
export interface AuthChangeEvent {
  authenticated: boolean
  role: string | null
  expiresAt: number | null
  reason: AuthChangeReason
}
const _authListeners = new Set<(e: AuthChangeEvent) => void>()

function _notifyAuthChange(reason: AuthChangeReason): void {
  const evt: AuthChangeEvent = {
    authenticated: _authToken !== null,
    role: _authRole,
    expiresAt: _authExpiresAt,
    reason,
  }
  _authListeners.forEach(h => h(evt))
}

/** Subscribe to auth state transitions (login/logout/rotate/forced
 *  expiry). Returns an unsubscribe function. */
export function onAuthChange(h: (e: AuthChangeEvent) => void): () => void {
  _authListeners.add(h)
  return () => _authListeners.delete(h)
}

// ── Proactive token rotation ─────────────────────────────────────────────────
//
// POST /api/auth/rotate (api/app.py — already implemented, not new) trades
// the current Bearer token for a fresh one. It must run BEFORE
// JWT_EXPIRY_MINUTES elapses: api/auth.py's rotate_token() decodes the
// presented token first, so an already-expired token can't be rotated —
// only re-issued via login(), and the raw API key is deliberately never
// kept around client-side to do that automatically (see module docstring
// above). ROTATE_MARGIN_S is how long before expiry we swap it out.
const ROTATE_MARGIN_S = 60
let _rotateTimer: ReturnType<typeof setTimeout> | null = null

function _clearRotateTimer(): void {
  if (_rotateTimer !== null) {
    clearTimeout(_rotateTimer)
    _rotateTimer = null
  }
}

function _scheduleRotate(): void {
  _clearRotateTimer()
  if (!_authToken || !_authExpiresAt) return
  const delayS = Math.max(_authExpiresAt - Math.floor(Date.now() / 1000) - ROTATE_MARGIN_S, 1)
  _rotateTimer = setTimeout(_rotate, delayS * 1000)
}

async function _rotate(): Promise<void> {
  if (!_authToken) return
  try {
    const r = await fetch(`${BASE}/api/auth/rotate`, { method: 'POST', headers: authHeaders() })
    const body = await r.json().catch(() => null)
    if (!r.ok || !body?.data?.token) {
      throw new Error(body?.error || body?.detail || `rotate failed (HTTP ${r.status})`)
    }
    _authToken = body.data.token
    _authExpiresAt = body.data.expires_at ?? null
    _scheduleRotate()
    _notifyAuthChange('rotate')
  } catch {
    // Couldn't refresh in time (server restart cleared the ephemeral
    // JWT_SECRET, network blip through the whole margin, etc.) — go to a
    // clean logged-out state instead of continuing to send a token that
    // will now just fail with "token expired" on every request forever
    // (the exact bug this fix replaces).
    _authToken = null
    _authRole = null
    _authExpiresAt = null
    _clearRotateTimer()
    _notifyAuthChange('rotate_failed')
  }
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
  // V16 Track W14-1 Item 12 — PortfolioManager's decision-cycle log (Train
  // Monitor's "what did the scanner/CEO consider this cycle" panel). This is
  // NOT real account state — see PortfolioHistoryEntry's doc comment in
  // types/api.ts. Reuses the existing, already-live /api/portfolio/history
  // route (api/portfolio_api.py); no backend change.
  portfolioHistory: (l = 30) => get(`/api/portfolio/history?limit=${l}`),
  // V16 training-lane-visibility phase — Track C background paper-training
  // lane status. `enabled:false` is a normal response body (flag off /
  // not started), not a thrown error — see TrainingLaneStatus in
  // types/api.ts.
  trainingLaneStatus: () => get('/api/training-lane/status'),
  forwardTest:    () => get('/api/forward_test'),
  commandState:   () => get('/api/command/state'),
  // V16 Track W14-1 Item 4/5 — real account/position telemetry, replaces
  // the MockPortfolioProvider Portfolio.tsx previously used.
  accountState:   () => get('/api/account/state'),
  // V16 Track W14-1 Item 7 — OPERATOR auth bootstrap for START/STOP.
  login,
  logout,
  authSnapshot,
  // V16 Phase 4C — Dashboard Session Persistence.
  restoreSession,
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
  private path:     string
  private stopped   = false
  private delay     = WS_DELAY_MIN
  private retryTimer: ReturnType<typeof setTimeout> | null = null

  constructor(path: string) {
    this.path = path
  }

  connect(): void {
    if (this.stopped) return
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    // V16 dashboard-auth-fix: every /ws/* route needs the same credentials
    // as /api/* (api/app.py's enforce_ws_role() sets at least a VIEWER
    // floor on every channel). Browsers can't set a custom header on the
    // WS handshake, so api/auth.py's _ws_credentials() accepts the bearer
    // token as ?token=... instead (see that function's docstring). With no
    // token yet, don't even attempt the handshake — that's the
    // "missing credentials" WARNING loop this replaces. The onAuthChange
    // listener below calls reconnect() the moment a token appears.
    if (!_authToken) return
    try {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${proto}://${window.location.host}${this.path}?token=${encodeURIComponent(_authToken)}`
      this.ws = new WebSocket(url)

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

const _wsChannels = [wsEvents, wsDecision, wsAgents, wsMissions, wsML, wsSignals, wsWorld]
// No-ops per-channel until a token exists — see ManagedWS.connect().
_wsChannels.forEach(w => w.connect())

// V16 dashboard-auth-fix: open every channel the moment a session starts
// (they've been sitting idle with no token, per connect() above), and
// close them the moment it ends. Guarded on the authenticated boolean
// actually transitioning — a routine background rotate() also fires
// onAuthChange while staying authenticated the whole time, and an already
// -open WS doesn't need to be torn down for that (api/auth.py only checks
// credentials once, at the handshake, not per-frame).
let _wsAuthenticated = false
onAuthChange(({ authenticated }) => {
  if (authenticated && !_wsAuthenticated) {
    _wsChannels.forEach(w => w.reconnect())
  } else if (!authenticated && _wsAuthenticated) {
    _wsChannels.forEach(w => w.disconnect())
  }
  _wsAuthenticated = authenticated
})
