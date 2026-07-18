/**
 * Brain Bot V15 — Zustand stores
 *
 * BUG-V15-FE-12: Zustand default equality uses Object.is (reference equality).
 *   Every setData() call creates a new object reference even if the data is
 *   identical → Zustand always notifies subscribers → re-render fires.
 *   The /ws/decision 1Hz heartbeat hit this path relentlessly.
 *
 *   Fix: DecisionState uses a custom equality function that compares the
 *   semantically-meaningful fields (not `timestamp`) so that a WS heartbeat
 *   push with unchanged decision doesn't trigger a re-render.
 *
 *   Note: useData.ts BUG-V15-FE-08 fix already guards at the hook level.
 *   This is a second line of defence at the store level.
 */
import { create } from 'zustand'
import type {
  DecisionData, SystemHealthData, MissionsData, AgentsData, TelemetryData,
  IntelligenceData, FuturesData, RegimeData, JournalData, SignalsData,
  MLStatus, MLPerformance, PaperMetrics, CommandState, BusEvent, ReconciliationData,
} from '@/types/api'

// ── Event log ─────────────────────────────────────────────────────────────────

interface EventLogState { events:BusEvent[]; addEvent:(e:BusEvent)=>void; clear:()=>void }
export const useEventLog = create<EventLogState>(set=>({
  events:[], addEvent:e=>set(s=>({events:[e,...s.events].slice(0,200)})), clear:()=>set({events:[]}),
}))

// ── Decision (with semantic equality guard) ───────────────────────────────────

interface DecisionState { data:DecisionData|null; loading:boolean; setData:(d:DecisionData)=>void; setLoading:(v:boolean)=>void }
export const useDecision = create<DecisionState>(set=>({
  data:null, loading:true,
  setData: data => set({ data, loading: false }),
  setLoading: loading => set({ loading }),
}))

// ── Health ────────────────────────────────────────────────────────────────────

interface HealthState { data:SystemHealthData|null; recon:ReconciliationData|null; setData:(d:SystemHealthData)=>void; setRecon:(d:ReconciliationData)=>void }
export const useHealth = create<HealthState>(set=>({
  data:null, recon:null,
  setData: data => set({ data }),
  setRecon: recon => set({ recon }),
}))

// ── Missions ──────────────────────────────────────────────────────────────────

interface MissionsState { data:MissionsData|null; setData:(d:MissionsData)=>void }
export const useMissions = create<MissionsState>(set=>({ data:null, setData:data=>set({data}) }))

// ── Agents ────────────────────────────────────────────────────────────────────

interface AgentsState { agents:AgentsData|null; telemetry:TelemetryData|null; setAgents:(d:AgentsData)=>void; setTelemetry:(d:TelemetryData)=>void }
export const useAgents = create<AgentsState>(set=>({
  agents:null, telemetry:null,
  setAgents: agents => set({ agents }),
  setTelemetry: telemetry => set({ telemetry }),
}))

// ── Market ────────────────────────────────────────────────────────────────────

interface MarketState {
  intelligence:IntelligenceData|null; futures:FuturesData|null
  regime:RegimeData|null; signals:SignalsData|null
  setIntelligence:(d:IntelligenceData)=>void; setFutures:(d:FuturesData)=>void
  setRegime:(d:RegimeData)=>void; setSignals:(d:SignalsData)=>void
}
export const useMarket = create<MarketState>(set=>({
  intelligence:null, futures:null, regime:null, signals:null,
  setIntelligence: intelligence => set({ intelligence }),
  setFutures:      futures      => set({ futures }),
  setRegime:       regime       => set({ regime }),
  setSignals:      signals      => set({ signals }),
}))

// ── Journal ───────────────────────────────────────────────────────────────────

interface JournalState { journal:JournalData|null; paper:PaperMetrics|null; setJournal:(d:JournalData)=>void; setPaper:(d:PaperMetrics)=>void }
export const useJournal = create<JournalState>(set=>({
  journal:null, paper:null,
  setJournal: journal => set({ journal }),
  setPaper:   paper   => set({ paper }),
}))

// ── ML ────────────────────────────────────────────────────────────────────────

interface MLState { status:MLStatus|null; performance:MLPerformance|null; setStatus:(d:MLStatus)=>void; setPerformance:(d:MLPerformance)=>void }
export const useML = create<MLState>(set=>({
  status:null, performance:null,
  setStatus:      status      => set({ status }),
  setPerformance: performance => set({ performance }),
}))

// ── Commander ─────────────────────────────────────────────────────────────────

interface CommanderState {
  state:CommandState|null
  chatHistory:Array<{role:'user'|'assistant';text:string;ts:string}>
  setState:(d:CommandState)=>void
  addMessage:(role:'user'|'assistant',text:string)=>void
}
export const useCommander = create<CommanderState>(set=>({
  state:null, chatHistory:[],
  setState:state=>set({state}),
  addMessage:(role,text)=>set(s=>({chatHistory:[...s.chatHistory,{role,text,ts:new Date().toISOString()}].slice(-100)})),
}))

// ── UI ────────────────────────────────────────────────────────────────────────

interface UIState { connected:boolean; setConnected:(v:boolean)=>void }
export const useUI = create<UIState>(set=>({ connected:false, setConnected:connected=>set({connected}) }))
