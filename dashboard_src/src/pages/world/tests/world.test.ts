// ============================================================
// Brain Bot V15 — World HQ Unit Tests (Vitest)
// Tests: map generation, store, NPC mood, teleport,
// tile walkability, room detection, API helpers.
// Run: npm run test  (from dashboard/)
// ============================================================

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// ── Mock Phaser (not available in Node) ──────────────────────

vi.mock('phaser', () => ({
  default: { AUTO: 1, Scale: { RESIZE: 1, CENTER_BOTH: 1 }, Game: vi.fn() },
  Scene: class MockScene {},
}));

// ── Map generation ─────────────────────────────────────────────

describe('MapLoader', () => {
  let buildWorldMap: typeof import('../MapLoader').buildWorldMap;
  let isWalkable:   typeof import('../MapLoader').isWalkable;
  let isBlocking:   typeof import('../MapLoader').isBlocking;
  let getRoomAtTile: typeof import('../MapLoader').getRoomAtTile;
  let tileToPx:     typeof import('../MapLoader').tileToPx;
  let pxToTile:     typeof import('../MapLoader').pxToTile;

  beforeEach(async () => {
    const mod = await import('../MapLoader');
    buildWorldMap  = mod.buildWorldMap;
    isWalkable     = mod.isWalkable;
    isBlocking     = mod.isBlocking;
    getRoomAtTile  = mod.getRoomAtTile;
    tileToPx       = mod.tileToPx;
    pxToTile       = mod.pxToTile;
  });

  it('builds a world map with correct dimensions', () => {
    const map = buildWorldMap();
    expect(map.cols).toBe(120);
    expect(map.rows).toBe(72);
    expect(map.tiles.length).toBe(72);
    expect(map.tiles[0].length).toBe(120);
  });

  it('places CEO room floor tiles at correct position', () => {
    const map = buildWorldMap();
    // CEO Room: tx=2, ty=2, tw=18, th=14 → interior starts at (3,3)
    expect(map.tiles[3][3]).toBe('floor_ceo');
  });

  it('places wall tiles at room borders', () => {
    const map = buildWorldMap();
    // Top wall of CEO room
    expect(map.tiles[2][2]).toBe('wall');
    expect(map.tiles[2][10]).toBe('wall');
  });

  it('generates path tiles between rooms', () => {
    const map = buildWorldMap();
    // There must be at least one path tile in the map
    let foundPath = false;
    for (let ty = 0; ty < map.rows && !foundPath; ty++) {
      for (let tx = 0; tx < map.cols; tx++) {
        if (map.tiles[ty][tx] === 'path') { foundPath = true; break; }
      }
    }
    expect(foundPath).toBe(true);
  });

  it('places water border tiles at edges', () => {
    const map = buildWorldMap();
    expect(map.tiles[0][5]).toBe('water');
    expect(map.tiles[map.rows - 1][5]).toBe('water');
    expect(map.tiles[5][0]).toBe('water');
    expect(map.tiles[5][map.cols - 1]).toBe('water');
  });

  it('isWalkable returns true for floor and path tiles', () => {
    expect(isWalkable('floor_ceo')).toBe(true);
    expect(isWalkable('floor_ml')).toBe(true);
    expect(isWalkable('path')).toBe(true);
    expect(isWalkable('grass')).toBe(false);
    expect(isWalkable('water')).toBe(false);
    expect(isWalkable('wall')).toBe(false);
  });

  it('isBlocking returns true for wall, water, void', () => {
    expect(isBlocking('wall')).toBe(true);
    expect(isBlocking('water')).toBe(true);
    expect(isBlocking('void')).toBe(true);
    expect(isBlocking('path')).toBe(false);
    expect(isBlocking('floor_ceo')).toBe(false);
  });

  it('getRoomAtTile returns correct room for interior tiles', async () => {
    const { ROOM_DEFINITIONS } = await import('../Room');
    // Interior of CEO room (tx=5, ty=5 is inside tx:2,ty:2,tw:18,th:14)
    const room = getRoomAtTile(5, 5, ROOM_DEFINITIONS);
    expect(room?.id).toBe('ceo');
  });

  it('getRoomAtTile returns null for grass tiles', async () => {
    const { ROOM_DEFINITIONS } = await import('../Room');
    // Far grass tile unlikely to be in any room
    const room = getRoomAtTile(60, 34, ROOM_DEFINITIONS);
    expect(room).toBeNull();
  });

  it('tileToPx converts correctly', () => {
    const { x, y } = tileToPx(0, 0);
    expect(x).toBe(8); // TILE_SIZE/2 = 8
    expect(y).toBe(8);
  });

  it('pxToTile converts correctly', () => {
    const { tx, ty } = pxToTile(16, 16);
    expect(tx).toBe(1);
    expect(ty).toBe(1);
  });

  it('tileToPx and pxToTile are inverse operations', () => {
    const { x, y }   = tileToPx(10, 5);
    const { tx, ty } = pxToTile(x, y);
    expect(tx).toBe(10);
    expect(ty).toBe(5);
  });

  it('includes all 16 rooms in the map', () => {
    const map = buildWorldMap();
    expect(map.rooms.length).toBe(16);
  });

  it('includes all 10 NPCs', () => {
    const map = buildWorldMap();
    expect(map.npcs.length).toBe(10);
  });
});

// ── Store ──────────────────────────────────────────────────────

describe('worldStore', () => {
  let useWorldStore: any;
  let selectCeoMood: any;
  let selectSystemSeverity: any;
  let selectNpcMood: any;

  beforeEach(async () => {
    vi.resetModules();
    const mod = await import('../worldStore');
    useWorldStore       = mod.useWorldStore;
    selectCeoMood       = mod.selectCeoMood;
    selectSystemSeverity = mod.selectSystemSeverity;
    selectNpcMood       = mod.selectNpcMood;
  });

  it('has correct initial state', () => {
    const state = useWorldStore.getState();
    expect(state.wsConnected).toBe(false);
    expect(state.decision).toBeNull();
    expect(state.missions).toEqual([]);
    expect(state.theme).toBe('cyberpunk');
  });

  it('setDecision updates decision state', () => {
    const store = useWorldStore.getState();
    store.setDecision({ signal: 'LONG', confidence: 0.85, reasoning: 'test', timestamp: '2024-01-01' });
    expect(useWorldStore.getState().decision?.signal).toBe('LONG');
    expect(useWorldStore.getState().decision?.confidence).toBe(0.85);
  });

  it('addEvent prepends to recentEvents and caps at 50', () => {
    const store = useWorldStore.getState();
    for (let i = 0; i < 55; i++) {
      store.addEvent({ id: `ev_${i}`, event: 'TEST', message: 'msg', timestamp: '', level: 'info' });
    }
    expect(useWorldStore.getState().recentEvents.length).toBe(50);
    // Most recent first
    expect(useWorldStore.getState().recentEvents[0].id).toBe('ev_54');
  });

  it('openModal sets all modal state', () => {
    const store = useWorldStore.getState();
    store.openModal('ceo', 'ceo', 'ceo_agent');
    const s = useWorldStore.getState();
    expect(s.activeModal).toBe('ceo');
    expect(s.activeRoomId).toBe('ceo');
    expect(s.activeNpcId).toBe('ceo_agent');
  });

  it('closeModal clears modal state', () => {
    const store = useWorldStore.getState();
    store.openModal('ceo', 'ceo');
    store.closeModal();
    const s = useWorldStore.getState();
    expect(s.activeModal).toBe('none');
    expect(s.activeRoomId).toBeNull();
  });

  it('setTheme changes theme', () => {
    useWorldStore.getState().setTheme('retro');
    expect(useWorldStore.getState().theme).toBe('retro');
  });

  it('toggleAudio toggles audioEnabled', () => {
    const store = useWorldStore.getState();
    expect(store.audioEnabled).toBe(false);
    store.toggleAudio();
    expect(useWorldStore.getState().audioEnabled).toBe(true);
    store.toggleAudio();
    expect(useWorldStore.getState().audioEnabled).toBe(false);
  });
});

// ── NPC mood selectors ─────────────────────────────────────────

describe('NPC mood selectors', () => {
  let useWorldStore: any;
  let selectCeoMood: any;
  let selectSystemSeverity: any;
  let selectNpcMood: any;

  beforeEach(async () => {
    vi.resetModules();
    const mod = await import('../worldStore');
    useWorldStore        = mod.useWorldStore;
    selectCeoMood        = mod.selectCeoMood;
    selectSystemSeverity = mod.selectSystemSeverity;
    selectNpcMood        = mod.selectNpcMood;
  });

  it('selectCeoMood returns happy when confidence >= 0.8', () => {
    const store = useWorldStore.getState();
    store.setWsConnected(true);
    store.setDecision({ signal: 'LONG', confidence: 0.9, reasoning: '', timestamp: '' });
    expect(selectCeoMood(useWorldStore.getState())).toBe('happy');
  });

  it('selectCeoMood returns worried when confidence < 0.4', () => {
    const store = useWorldStore.getState();
    store.setWsConnected(true);
    store.setDecision({ signal: 'WAIT', confidence: 0.3, reasoning: '', timestamp: '' });
    expect(selectCeoMood(useWorldStore.getState())).toBe('worried');
  });

  it('selectCeoMood returns worried when WS disconnected', () => {
    useWorldStore.getState().setWsConnected(false);
    expect(selectCeoMood(useWorldStore.getState())).toBe('worried');
  });

  it('selectSystemSeverity is critical when WS disconnected', () => {
    useWorldStore.getState().setWsConnected(false);
    expect(selectSystemSeverity(useWorldStore.getState())).toBe('critical');
  });

  it('selectSystemSeverity is ok when connected and alive', () => {
    const store = useWorldStore.getState();
    store.setWsConnected(true);
    store.setSystemHealth({ overall_status: 'ALIVE', subsystems: {}, timestamp: '' });
    expect(selectSystemSeverity(useWorldStore.getState())).toBe('ok');
  });

  it('selectNpcMood is happy when agent confidence > 0.8', () => {
    const store = useWorldStore.getState();
    store.setAgents({ risk: { name: 'Risk', status: 'ALIVE', confidence: 0.9, latency_ms: 10, uptime_s: 3600, last_seen: '' } });
    expect(selectNpcMood('risk_agent')(useWorldStore.getState())).toBe('happy');
  });

  it('selectNpcMood is critical when agent status is DEAD', () => {
    const store = useWorldStore.getState();
    store.setAgents({ smc: { name: 'SMC', status: 'DEAD', confidence: 0, latency_ms: 0, uptime_s: 0, last_seen: '' } });
    expect(selectNpcMood('smc_agent')(useWorldStore.getState())).toBe('critical');
  });
});

// ── Room definitions ────────────────────────────────────────────

describe('Room definitions', () => {
  it('all rooms have unique IDs', async () => {
    const { ROOM_DEFINITIONS } = await import('../Room');
    const ids = ROOM_DEFINITIONS.map((r) => r.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(ids.length);
  });

  it('all NPCs reference valid room IDs', async () => {
    const { NPC_DEFINITIONS, ROOM_DEFINITIONS } = await import('../Room');
    const roomIds = new Set(ROOM_DEFINITIONS.map((r) => r.id));
    for (const npc of NPC_DEFINITIONS) {
      expect(roomIds.has(npc.roomId)).toBe(true);
    }
  });

  it('all rooms have apiEndpoint or null', async () => {
    const { ROOM_DEFINITIONS } = await import('../Room');
    for (const room of ROOM_DEFINITIONS) {
      expect(room.apiEndpoint === null || room.apiEndpoint.startsWith('/')).toBe(true);
    }
  });

  it('all rooms have non-zero dimensions', async () => {
    const { ROOM_DEFINITIONS } = await import('../Room');
    for (const room of ROOM_DEFINITIONS) {
      expect(room.tw).toBeGreaterThan(0);
      expect(room.th).toBeGreaterThan(0);
    }
  });
});
