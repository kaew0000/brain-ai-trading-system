// ============================================================
// Brain Bot V15 — World HQ Store (Zustand)
// Central state for the 2D pixel-art trading command office.
// ============================================================

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import type {
  WorldStore,
  WorldTheme,
  ModalType,
  DecisionData,
  AgentTelemetry,
  MissionData,
  PaperData,
  IntelligenceData,
  SystemHealthData,
  EventItem,
} from './types/world.types';

const MAX_EVENTS = 50;

export const useWorldStore = create<WorldStore>()(
  subscribeWithSelector((set, get) => ({
    // ── Connection ─────────────────────────────────────────
    wsConnected: false,
    apiBase: (import.meta as any).env?.VITE_API_BASE || 'http://localhost:8000',

    // ── Trading data ───────────────────────────────────────
    decision: null,
    agents: {},
    missions: [],
    paper: null,
    intelligence: null,
    systemHealth: null,
    recentEvents: [],

    // ── World state ────────────────────────────────────────
    activeModal: 'none',
    activeRoomId: null,
    activeNpcId: null,
    playerTileX: 50,
    playerTileY: 28,
    theme: 'cyberpunk',
    audioEnabled: false,

    // ── Actions ────────────────────────────────────────────

    setWsConnected: (v) => set({ wsConnected: v }),

    setDecision: (d) => set({ decision: d }),

    setAgents: (a) => set({ agents: a }),

    setMissions: (m) => set({ missions: m }),

    setPaper: (p) => set({ paper: p }),

    setIntelligence: (i) => set({ intelligence: i }),

    setSystemHealth: (h) => set({ systemHealth: h }),

    addEvent: (e) =>
      set((s) => ({
        recentEvents: [e, ...s.recentEvents].slice(0, MAX_EVENTS),
      })),

    openModal: (type, roomId, npcId) =>
      set({
        activeModal: type,
        activeRoomId: roomId ?? null,
        activeNpcId: npcId ?? null,
      }),

    closeModal: () =>
      set({ activeModal: 'none', activeRoomId: null, activeNpcId: null }),

    setPlayerPos: (tx, ty) => set({ playerTileX: tx, playerTileY: ty }),

    setTheme: (t) => set({ theme: t }),

    toggleAudio: () => set((s) => ({ audioEnabled: !s.audioEnabled })),
  }))
);

// ── Derived selectors ─────────────────────────────────────────────────────────

/** Returns current system severity for global lighting effects */
export const selectSystemSeverity = (s: WorldStore): 'ok' | 'warn' | 'critical' => {
  const health = s.systemHealth?.overall_status;
  if (!s.wsConnected) return 'critical';
  if (health === 'DEAD') return 'critical';
  if (health === 'STALE') return 'warn';
  return 'ok';
};

/** Returns NPC mood based on agent telemetry */
export const selectNpcMood = (agentId: string) => (s: WorldStore) => {
  const agentKey = agentId.replace('_agent', '').replace('_controller', '').replace('_manager', '');
  const agent = s.agents[agentKey] ?? s.agents[agentId];
  if (!agent) return 'neutral';
  if (agent.status === 'DEAD') return 'critical';
  if (agent.status === 'STALE') return 'worried';
  if (agent.confidence > 0.8) return 'happy';
  if (agent.confidence < 0.4) return 'worried';
  return 'neutral';
};

/** Returns CEO mood based on decision confidence */
export const selectCeoMood = (s: WorldStore) => {
  const conf = s.decision?.confidence ?? 0;
  if (!s.wsConnected) return 'worried';
  if (conf >= 0.8) return 'happy';
  if (conf >= 0.5) return 'neutral';
  return 'worried';
};

/** Whether the server room should flash red */
export const selectServerRoomAlert = (s: WorldStore): boolean =>
  !s.wsConnected ||
  s.systemHealth?.overall_status === 'DEAD';

/** Whether open position exists */
export const selectHasOpenPosition = (s: WorldStore): boolean =>
  s.paper?.open_position != null;

/** Mission count by status */
export const selectMissionCounts = (s: WorldStore) => ({
  active: s.missions.filter((m) => m.status === 'active').length,
  completed: s.missions.filter((m) => m.status === 'completed').length,
  failed: s.missions.filter((m) => m.status === 'failed').length,
});

/** Active theme colors for overlays */
export const THEME_COLORS: Record<WorldTheme, {
  bg: string;
  border: string;
  text: string;
  accent: string;
  panel: string;
  danger: string;
  success: string;
}> = {
  dark: {
    bg: '#0d1117',
    border: '#21262d',
    text: '#c9d1d9',
    accent: '#58a6ff',
    panel: '#161b22',
    danger: '#f85149',
    success: '#3fb950',
  },
  cyberpunk: {
    bg: '#070714',
    border: '#1a1a3e',
    text: '#c0c8ff',
    accent: '#00ff88',
    panel: '#0d0d24',
    danger: '#ff4444',
    success: '#00ff88',
  },
  retro: {
    bg: '#000d00',
    border: '#004400',
    text: '#00ff00',
    accent: '#00ff88',
    panel: '#000a00',
    danger: '#ff8800',
    success: '#00ff00',
  },
  light: {
    bg: '#f0f4ff',
    border: '#c8d0e8',
    text: '#1a1a2e',
    accent: '#3355ff',
    panel: '#e0e8ff',
    danger: '#cc2222',
    success: '#228822',
  },
};
