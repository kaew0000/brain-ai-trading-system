/**
 * Brain Bot V16 — Zustand stores
 *
 * All stores now use shallow equality guards to prevent re-renders
 * when data is reference-identical or semantically unchanged.
 */
import { create } from 'zustand'
import { api } from '@/lib/api'
import type {
  DecisionData, SystemHealthData, MissionsData, AgentsData, TelemetryData,
  IntelligenceData, FuturesData, RegimeData, JournalData, SignalsData,
  MLStatus, MLPerformance, PaperMetrics, CommandState, BusEvent, ReconciliationData,
  AccountStateData,
} from '@/types/api'

// ── Equality helpers ─────────────────────────────────────────────────────────

function shallowEqual<T extends Record<string, any>>(a: T | null, b: T | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  const keysA = Object.keys(a)
  const keysB = Object.keys(b)
  if (keysA.length !== keysB.length) return false
  for (const key of keysA) {
    if (a[key] !== b[key]) return false
  }
  return true
}

function decisionEqual(a: DecisionData | null, b: DecisionData | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  const sa = a.signal
  const sb = b.signal
  if (!sa || !sb) return false
  return (
    sa.action === sb.action &&
    sa.confidence === sb.confidence &&
    sa.score === sb.score &&
    sa.regime === sb.regime &&
    sa.mtf_aligned === sb.mtf_aligned &&
    sa.blocked === sb.blocked &&
    sa.entry_price === sb.entry_price &&
    sa.stop_loss === sb.stop_loss &&
    sa.take_profit === sb.take_profit
  )
}

// ── Event log ─────────────────────────────────────────────────────────────────

interface EventLogState { events: BusEvent[]; addEvent: (e: BusEvent) => void; clear: () => void }
export const useEventLog = create<EventLogState>(set => ({
  events: [],
  addEvent: e => set(s => ({ events: [e, ...s.events].slice(0, 200) })),
  clear: () => set({ events: [] }),
}))

// ── Decision (with semantic equality guard) ───────────────────────────────────

interface DecisionState { data: DecisionData | null; loading: boolean; setData: (d: DecisionData) => void; setLoading: (v: boolean) => void }
export const useDecision = create<DecisionState>(set => ({
  data: null,
  loading: true,
  setData: data => set(s => decisionEqual(s.data, data) ? s : { data, loading: false }),
  setLoading: loading => set({ loading }),
}))

// ── Health ────────────────────────────────────────────────────────────────────

interface HealthState { data: SystemHealthData | null; recon: ReconciliationData | null; setData: (d: SystemHealthData) => void; setRecon: (d: ReconciliationData) => void }
export const useHealth = create<HealthState>(set => ({
  data: null,
  recon: null,
  setData: data => set(s => shallowEqual(s.data, data) ? s : { data }),
  setRecon: recon => set(s => shallowEqual(s.recon, recon) ? s : { recon }),
}))

// ── Missions ──────────────────────────────────────────────────────────────────

interface MissionsState { data: MissionsData | null; setData: (d: MissionsData) => void }
export const useMissions = create<MissionsState>(set => ({
  data: null,
  setData: data => set(s => shallowEqual(s.data, data) ? s : { data }),
}))

// ── Agents ────────────────────────────────────────────────────────────────────

interface AgentsState { agents: AgentsData | null; telemetry: TelemetryData | null; setAgents: (d: AgentsData) => void; setTelemetry: (d: TelemetryData) => void }
export const useAgents = create<AgentsState>(set => ({
  agents: null,
  telemetry: null,
  setAgents: agents => set(s => shallowEqual(s.agents, agents) ? s : { agents }),
  setTelemetry: telemetry => set(s => shallowEqual(s.telemetry, telemetry) ? s : { telemetry }),
}))

// ── Market ────────────────────────────────────────────────────────────────────

interface MarketState {
  intelligence: IntelligenceData | null; futures: FuturesData | null
  regime: RegimeData | null; signals: SignalsData | null
  setIntelligence: (d: IntelligenceData) => void; setFutures: (d: FuturesData) => void
  setRegime: (d: RegimeData) => void; setSignals: (d: SignalsData) => void
}
export const useMarket = create<MarketState>(set => ({
  intelligence: null,
  futures: null,
  regime: null,
  signals: null,
  setIntelligence: intelligence => set(s => shallowEqual(s.intelligence, intelligence) ? s : { intelligence }),
  setFutures: futures => set(s => shallowEqual(s.futures, futures) ? s : { futures }),
  setRegime: regime => set(s => shallowEqual(s.regime, regime) ? s : { regime }),
  setSignals: signals => set(s => shallowEqual(s.signals, signals) ? s : { signals }),
}))

// ── Journal ───────────────────────────────────────────────────────────────────

interface JournalState { journal: JournalData | null; paper: PaperMetrics | null; setJournal: (d: JournalData) => void; setPaper: (d: PaperMetrics) => void }
export const useJournal = create<JournalState>(set => ({
  journal: null,
  paper: null,
  setJournal: journal => set(s => shallowEqual(s.journal, journal) ? s : { journal }),
  setPaper: paper => set(s => shallowEqual(s.paper, paper) ? s : { paper }),
}))

// ── ML ────────────────────────────────────────────────────────────────────────

interface MLState { status: MLStatus | null; performance: MLPerformance | null; setStatus: (d: MLStatus) => void; setPerformance: (d: MLPerformance) => void }
export const useML = create<MLState>(set => ({
  status: null,
  performance: null,
  setStatus: status => set(s => shallowEqual(s.status, status) ? s : { status }),
  setPerformance: performance => set(s => shallowEqual(s.performance, performance) ? s : { performance }),
}))

// ── Commander ─────────────────────────────────────────────────────────────────

interface CommanderState {
  state: CommandState | null
  chatHistory: Array<{ role: 'user' | 'assistant'; text: string; ts: string }>
  setState: (d: CommandState) => void
  addMessage: (role: 'user' | 'assistant', text: string) => void
}
export const useCommander = create<CommanderState>(set => ({
  state: null,
  chatHistory: [],
  setState: state => set(s => shallowEqual(s.state, state) ? s : { state }),
  addMessage: (role, text) => set(s => ({
    chatHistory: [...s.chatHistory, { role, text, ts: new Date().toISOString() }].slice(-100),
  })),
}))

// ── UI ────────────────────────────────────────────────────────────────────────

interface UIState { connected: boolean; setConnected: (v: boolean) => void }
export const useUI = create<UIState>(set => ({
  connected: false,
  setConnected: connected => set(s => s.connected === connected ? s : { connected }),
}))

// ── Account (V16 Track W14-1 Item 4/5 — real telemetry) ─────────────────────────

interface AccountState { account: AccountStateData | null; setAccount: (d: AccountStateData) => void }
export const useAccount = create<AccountState>(set => ({
  account: null,
  setAccount: account => set(s => shallowEqual(s.account as any, account as any) ? s : { account }),
}))

// ── Auth (V16 Track W14-1 Item 7) ────────────────────────────────────────────
//
// Reactive mirror of lib/api.ts's in-memory token state, so components
// (LoginModal, LifecycleControl) re-render on login/logout without api.ts
// needing to know about React at all. The token itself never lives here
// (or anywhere in React state) — only role/expiresAt/error, which are
// safe to display. See api.ts's own module docstring for why the token
// is in-memory only (no localStorage/sessionStorage, not baked into the
// build).
interface AuthState {
  role: string | null
  expiresAt: number | null
  error: string | null
  loggingIn: boolean
  login: (apiKey: string) => Promise<boolean>
  logout: () => void
}
export const useAuth = create<AuthState>(set => ({
  role: null,
  expiresAt: null,
  error: null,
  loggingIn: false,
  login: async (apiKey: string) => {
    set({ loggingIn: true, error: null })
    try {
      const { role, expiresAt } = await api.login(apiKey)
      set({ role, expiresAt, loggingIn: false, error: null })
      return true
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed'
      set({ loggingIn: false, error: message, role: null, expiresAt: null })
      return false
    }
  },
  logout: () => {
    api.logout()
    set({ role: null, expiresAt: null, error: null })
  },
}))
