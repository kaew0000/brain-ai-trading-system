// ============================================================
// Brain Bot V15 — World HQ API Service
// Connects the game world to the FastAPI backend.
// Uses WebSocket for realtime + REST for initial hydration.
// ============================================================

import type {
  DecisionData,
  AgentTelemetry,
  MissionData,
  PaperData,
  IntelligenceData,
  SystemHealthData,
  EventItem,
} from './types/world.types';
import { useWorldStore } from './worldStore';

// ── Interval IDs ──────────────────────────────────────────────────────────────
let _wsDecision: WebSocket | null = null;
let _wsAgents: WebSocket | null = null;
let _wsMissions: WebSocket | null = null;
let _wsEvents: WebSocket | null = null;
let _pollInterval: ReturnType<typeof setInterval> | null = null;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _destroyed = false;

// ── Helpers ───────────────────────────────────────────────────────────────────

const apiBase = () => useWorldStore.getState().apiBase;

const wsBase = () => {
  const base = apiBase().replace(/^http/, 'ws');
  return base.endsWith('/') ? base.slice(0, -1) : base;
};

function genEventId(): string {
  return `ev_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function toSeverity(level: string): EventItem['level'] {
  if (level === 'ERROR') return 'error';
  if (level === 'WARN') return 'warn';
  if (level === 'SUCCESS') return 'success';
  return 'info';
}

// ── REST hydration ────────────────────────────────────────────────────────────

async function fetchJSON<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${apiBase()}${path}`, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const body = await res.json();
    return (body.data ?? body) as T;
  } catch {
    return null;
  }
}

async function hydrateAll(): Promise<void> {
  const store = useWorldStore.getState();

  const [health, decision, agents, missions, paper] = await Promise.all([
    fetchJSON<any>('/api/system/health'),
    fetchJSON<any>('/api/decision'),
    fetchJSON<any>('/api/agents/telemetry'),
    fetchJSON<any>('/api/missions'),
    fetchJSON<any>('/api/paper'),
  ]);

  if (health) {
    store.setSystemHealth(health as SystemHealthData);
  }

  if (decision?.decision) {
    const d = decision.decision;
    store.setDecision({
      signal: d.signal ?? d.action ?? 'UNKNOWN',
      confidence: d.confidence ?? 0,
      reasoning: d.reasoning ?? decision.explanation ?? '',
      timestamp: decision.timestamp ?? new Date().toISOString(),
      scores: d.scores,
    });
  }

  if (agents?.agents) {
    const mapped: Record<string, AgentTelemetry> = {};
    for (const [k, v] of Object.entries(agents.agents as Record<string, any>)) {
      mapped[k] = {
        name: v.name ?? k,
        status: v.status ?? 'STALE',
        confidence: v.confidence ?? 0,
        latency_ms: v.latency_ms ?? 0,
        uptime_s: v.uptime_s ?? 0,
        last_seen: v.last_seen ?? new Date().toISOString(),
      };
    }
    store.setAgents(mapped);
  }

  if (missions) {
    const list = Array.isArray(missions) ? missions : missions.missions ?? [];
    store.setMissions(
      list.map((m: any): MissionData => ({
        id: m.id ?? m.mission_id ?? genEventId(),
        name: m.name ?? m.type ?? 'Mission',
        stage: m.stage ?? m.status ?? 'unknown',
        status: m.status === 'DONE' ? 'completed' : m.status?.toLowerCase() ?? 'pending',
        created_at: m.created_at ?? new Date().toISOString(),
        updated_at: m.updated_at ?? new Date().toISOString(),
      }))
    );
  }

  if (paper) {
    const openPos = paper.open_position ?? paper.positions?.[0] ?? null;
    store.setPaper({
      total_trades: paper.total_trades ?? 0,
      win_rate: paper.win_rate ?? 0,
      total_pnl: paper.total_pnl ?? 0,
      open_position: openPos
        ? {
            side: openPos.side,
            size: openPos.size ?? openPos.qty ?? 0,
            entry_price: openPos.entry_price ?? 0,
            unrealized_pnl: openPos.unrealized_pnl ?? 0,
            timestamp: openPos.timestamp ?? new Date().toISOString(),
          }
        : null,
      drawdown: paper.max_drawdown ?? 0,
    });
  }
}

// ── WebSocket connections ─────────────────────────────────────────────────────

function openWs(
  path: string,
  onMessage: (data: any) => void,
): WebSocket {
  const ws = new WebSocket(`${wsBase()}${path}`);

  ws.onopen = () => {
    useWorldStore.getState().setWsConnected(true);
  };

  ws.onmessage = (ev) => {
    try {
      const parsed = JSON.parse(ev.data);
      onMessage(parsed);
    } catch {
      /* ignore malformed messages */
    }
  };

  ws.onerror = () => {
    useWorldStore.getState().setWsConnected(false);
  };

  ws.onclose = () => {
    if (!_destroyed) {
      useWorldStore.getState().setWsConnected(false);
      scheduleReconnect();
    }
  };

  return ws;
}

function scheduleReconnect(): void {
  if (_reconnectTimer) return;
  _reconnectTimer = setTimeout(() => {
    _reconnectTimer = null;
    if (!_destroyed) connectWebSockets();
  }, 3000);
}

function connectWebSockets(): void {
  const store = useWorldStore.getState();

  // Decision stream
  _wsDecision = openWs('/ws/decision', (msg) => {
    if (msg.type === 'decision' && msg.data) {
      const d = msg.data;
      store.setDecision({
        signal: d.signal ?? d.action ?? 'UNKNOWN',
        confidence: d.confidence ?? 0,
        reasoning: d.reasoning ?? '',
        timestamp: msg.timestamp ?? new Date().toISOString(),
        scores: d.scores,
      });
    }
  });

  // Agent telemetry stream
  _wsAgents = openWs('/ws/agents', (msg) => {
    if (msg.type === 'telemetry' && msg.data?.agents) {
      const mapped: Record<string, AgentTelemetry> = {};
      for (const [k, v] of Object.entries(msg.data.agents as Record<string, any>)) {
        mapped[k] = {
          name: v.name ?? k,
          status: v.status ?? 'STALE',
          confidence: v.confidence ?? 0,
          latency_ms: v.latency_ms ?? 0,
          uptime_s: v.uptime_s ?? 0,
          last_seen: v.last_seen ?? new Date().toISOString(),
        };
      }
      store.setAgents(mapped);
    }
  });

  // Mission stream
  _wsMissions = openWs('/ws/missions', (msg) => {
    if (msg.type === 'missions' && Array.isArray(msg.data)) {
      store.setMissions(
        msg.data.map((m: any): MissionData => ({
          id: m.id ?? genEventId(),
          name: m.name ?? 'Mission',
          stage: m.stage ?? 'unknown',
          status: m.status === 'DONE' ? 'completed' : m.status?.toLowerCase() ?? 'pending',
          created_at: m.created_at ?? new Date().toISOString(),
          updated_at: m.updated_at ?? new Date().toISOString(),
        }))
      );
    }
  });

  // Event bus stream
  _wsEvents = openWs('/ws/events', (msg) => {
    if (msg.type === 'event' && msg.data) {
      const e = msg.data;
      store.addEvent({
        id: genEventId(),
        event: e.event ?? 'EVENT',
        message: e.message ?? JSON.stringify(e),
        timestamp: e.timestamp ?? new Date().toISOString(),
        level: toSeverity(e.level ?? 'INFO'),
      });
    }
  });
}

// ── Slow-poll for endpoints without WS ────────────────────────────────────────
async function slowPoll(): Promise<void> {
  const store = useWorldStore.getState();

  const [health, paper] = await Promise.all([
    fetchJSON<any>('/api/system/health'),
    fetchJSON<any>('/api/paper'),
  ]);

  if (health) store.setSystemHealth(health as SystemHealthData);

  if (paper) {
    const openPos = paper.open_position ?? null;
    store.setPaper({
      total_trades: paper.total_trades ?? 0,
      win_rate: paper.win_rate ?? 0,
      total_pnl: paper.total_pnl ?? 0,
      open_position: openPos
        ? {
            side: openPos.side,
            size: openPos.size ?? 0,
            entry_price: openPos.entry_price ?? 0,
            unrealized_pnl: openPos.unrealized_pnl ?? 0,
            timestamp: openPos.timestamp ?? new Date().toISOString(),
          }
        : null,
      drawdown: paper.max_drawdown ?? 0,
    });
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/** Start all API connections. Call once on World HQ mount. */
export async function startWorldApi(): Promise<void> {
  _destroyed = false;

  // Initial REST hydration
  await hydrateAll();

  // Realtime WebSocket streams
  connectWebSockets();

  // Slow poll every 10s for endpoints without WebSocket
  _pollInterval = setInterval(slowPoll, 10_000);
}

/** Stop all connections and timers. Call on World HQ unmount. */
export function stopWorldApi(): void {
  _destroyed = true;

  if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }

  for (const ws of [_wsDecision, _wsAgents, _wsMissions, _wsEvents]) {
    if (ws) {
      ws.onclose = null; // prevent reconnect loop
      ws.close();
    }
  }
  _wsDecision = _wsAgents = _wsMissions = _wsEvents = null;

  useWorldStore.getState().setWsConnected(false);
}

/** Fetch data for a specific room interaction modal */
export async function fetchRoomData(endpoint: string): Promise<any> {
  return fetchJSON(endpoint);
}

/** Send a Commander command */
export async function sendCommand(command: string): Promise<any> {
  try {
    const res = await fetch(`${apiBase()}/api/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    });
    const body = await res.json();
    return body.data ?? body;
  } catch (err) {
    return { success: false, message: String(err) };
  }
}

/** Chat with a specific agent */
export async function chatWithAgent(agent: string, question: string): Promise<any> {
  try {
    const res = await fetch(`${apiBase()}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent, question }),
    });
    const body = await res.json();
    return body.data ?? body;
  } catch (err) {
    return { answer: 'Agent unavailable.', error: String(err) };
  }
}
