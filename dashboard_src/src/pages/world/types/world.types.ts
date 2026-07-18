// ============================================================
// Brain Bot V15 — World HQ Types
// ============================================================

export type WorldTheme = 'dark' | 'cyberpunk' | 'retro' | 'light';

export type NPCMood = 'happy' | 'neutral' | 'worried' | 'critical';

export type AgentStatus = 'ALIVE' | 'STALE' | 'DEAD';

export type TileType =
  | 'void'
  | 'grass'
  | 'path'
  | 'water'
  | 'wall'
  | 'floor_ceo'
  | 'floor_mission'
  | 'floor_risk'
  | 'floor_intelligence'
  | 'floor_futures'
  | 'floor_ml'
  | 'floor_command'
  | 'floor_portfolio'
  | 'floor_replay'
  | 'floor_server'
  | 'floor_data'
  | 'floor_training'
  | 'floor_meeting'
  | 'floor_emergency'
  | 'floor_teleport'
  | 'floor_plaza';

// ------------------------------------
// Room definitions
// ------------------------------------
export interface RoomDefinition {
  id: string;
  name: string;
  /** Tile coordinates */
  tx: number;
  ty: number;
  tw: number;
  th: number;
  /** Visual */
  floorTile: TileType;
  wallColor: number;
  floorColor: number;
  accentColor: number;
  labelColor: string;
  /** Which agent NPC lives here (matches agent key) */
  npcId: string | null;
  /** Which API endpoint to call on interaction */
  apiEndpoint: string | null;
  /** Modal type to open */
  modalType: ModalType;
  /** Short description */
  description: string;
}

// ------------------------------------
// NPC definitions
// ------------------------------------
export interface NPCDefinition {
  id: string;
  name: string;
  role: string;
  roomId: string;
  /** Base color (head/body) */
  bodyColor: number;
  headColor: number;
  /** Starting tile position (within room) */
  startTx: number;
  startTy: number;
  /** Icon character to show above NPC */
  icon: string;
}

// ------------------------------------
// Modal types
// ------------------------------------
export type ModalType =
  | 'ceo'
  | 'mission_board'
  | 'risk_center'
  | 'portfolio_vault'
  | 'replay_theater'
  | 'ml_lab'
  | 'intelligence_lab'
  | 'futures_lab'
  | 'command_center'
  | 'server_room'
  | 'data_center'
  | 'training_room'
  | 'meeting_room'
  | 'emergency_room'
  | 'teleport_hub'
  | 'central_plaza'
  | 'none';

// ------------------------------------
// Live trading data
// ------------------------------------
export interface DecisionData {
  signal: 'LONG' | 'SHORT' | 'WAIT' | 'UNKNOWN';
  confidence: number;
  reasoning: string;
  timestamp: string;
  scores?: Record<string, number>;
}

export interface AgentTelemetry {
  name: string;
  status: AgentStatus;
  confidence: number;
  latency_ms: number;
  uptime_s: number;
  last_seen: string;
  mood?: NPCMood;
}

export interface MissionData {
  id: string;
  name: string;
  stage: string;
  status: 'active' | 'completed' | 'failed' | 'pending';
  created_at: string;
  updated_at: string;
}

export interface PaperData {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  open_position: OpenPosition | null;
  drawdown: number;
}

export interface OpenPosition {
  side: 'LONG' | 'SHORT';
  size: number;
  entry_price: number;
  unrealized_pnl: number;
  timestamp: string;
}

export interface IntelligenceData {
  sentiment: string;
  funding_rate: number;
  open_interest: number;
  long_short_ratio: number;
}

export interface SystemHealthData {
  overall_status: AgentStatus;
  subsystems: Record<string, { status: AgentStatus; last_beat: string }>;
  timestamp: string;
}

// ------------------------------------
// Zustand store shape
// ------------------------------------
export interface WorldStore {
  // Connection
  wsConnected: boolean;
  apiBase: string;

  // Trading data
  decision: DecisionData | null;
  agents: Record<string, AgentTelemetry>;
  missions: MissionData[];
  paper: PaperData | null;
  intelligence: IntelligenceData | null;
  systemHealth: SystemHealthData | null;
  recentEvents: EventItem[];

  // World state
  activeModal: ModalType;
  activeRoomId: string | null;
  activeNpcId: string | null;
  playerTileX: number;
  playerTileY: number;
  theme: WorldTheme;
  audioEnabled: boolean;

  // Actions
  setWsConnected: (v: boolean) => void;
  setDecision: (d: DecisionData) => void;
  setAgents: (a: Record<string, AgentTelemetry>) => void;
  setMissions: (m: MissionData[]) => void;
  setPaper: (p: PaperData) => void;
  setIntelligence: (i: IntelligenceData) => void;
  setSystemHealth: (h: SystemHealthData) => void;
  addEvent: (e: EventItem) => void;
  openModal: (type: ModalType, roomId?: string, npcId?: string) => void;
  closeModal: () => void;
  setPlayerPos: (tx: number, ty: number) => void;
  setTheme: (t: WorldTheme) => void;
  toggleAudio: () => void;
}

export interface EventItem {
  id: string;
  event: string;
  message: string;
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'success';
}

// ------------------------------------
// Phaser scene bridge
// ------------------------------------
export interface PhaserBridge {
  teleportToRoom: (roomId: string) => void;
  teleportToNpc: (npcId: string) => void;
  setTheme: (theme: WorldTheme) => void;
  onInteract: (cb: (type: ModalType, roomId: string, npcId?: string) => void) => void;
  onPlayerMove: (cb: (tx: number, ty: number) => void) => void;
  getNpcPositions: () => Array<{ id: string; tx: number; ty: number }>;
}

// ------------------------------------
// Map structure
// ------------------------------------
export interface WorldMap {
  cols: number;
  rows: number;
  tileSize: number;
  tiles: TileType[][];
  rooms: RoomDefinition[];
  npcs: NPCDefinition[];
}
