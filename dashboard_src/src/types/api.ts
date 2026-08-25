// src/types/api.ts
export interface ApiResponse<T> { ok: boolean; data: T }
export interface HealthData { status:string; version:string; symbol:string; leverage:number; testnet:boolean; uptime_s:number; mode?:string }
export interface SubsystemHealth { status:'ALIVE'|'STALE'|'DEAD'; last_beat:string|null; age_s:number|null; interval_s:number; meta:Record<string,unknown>|null }
export interface SystemHealthData { subsystems:Record<string,SubsystemHealth>; overall_status:'ALIVE'|'DEGRADED'|'CRITICAL'|'UNKNOWN'; timestamp:string }
export interface ReconciliationEvent { id:string; timestamp:string; mismatch_type:string; severity:string; detail:string; recovery_attempted:boolean; recovery_result:string|null }
export interface ReconciliationData { status:{last_run:string|null;last_result:string|null;event_count:number;suppressed_repeat_count?:number}; events:ReconciliationEvent[]; recovery_log:Array<{timestamp:string;action:string;target:string;result:string}>; timestamp:string }
export interface ConfidenceBreakdown { smc?:number; volume?:number; oi?:number; funding?:number; regime?:number }
export interface DecisionSignal { action:'LONG'|'SHORT'|'WAIT'; direction:string; confidence:number; score:number; regime:string; mtf_aligned:boolean; blocked:boolean; block_reasons:string[]; entry_price:number; stop_loss:number; take_profit:number; confidence_breakdown:ConfidenceBreakdown }
export interface DecisionData { signal?:DecisionSignal; decision?:Record<string,unknown>; explanation?:Record<string,unknown>; regime?:{regime:string;confidence:number;trend_bias:string}; message?:string; timestamp:string }
export type MissionStage = 'SIGNAL_FOUND'|'VALIDATION'|'RISK_CHECK'|'EXECUTION'|'MONITORING'|'CLOSED'
export interface Mission { id:string; symbol:string; direction:'LONG'|'SHORT'; stage:MissionStage; confidence:number; created_at:string; updated_at:string; history:Array<{stage:string;note?:string;timestamp:string}>; meta:Record<string,unknown> }
export interface MissionsData { missions:Mission[]; mission_count:number; stages:MissionStage[]; timestamp:string }
export interface AgentData { name:string; role:string; status:string; confidence?:number; last_action?:string; last_updated?:string; signals?:Record<string,unknown> }
export interface AgentsData { agents:Record<string,AgentData>; ceo_decision:Record<string,unknown>; agent_count:number; timestamp:string }
export interface TelemetryEntry { agent:string; action:string; confidence?:number; duration_ms?:number; timestamp:string; meta?:Record<string,unknown> }
export interface TelemetryData { telemetry:Record<string,TelemetryEntry[]>; agent_count:number; timestamp:string }
export interface FundingData { rate:number; annualised:number; extreme:boolean; bias:string }
export interface OIData { delta_pct:number; trend:string; pressure:string }
export interface LiquidationData { detected:boolean; type:string; severity:string }
export interface FearGreedData { value:number|null; classification:string; timestamp:string; available:boolean }
export interface IntelligenceData { funding:FundingData; open_interest:OIData; liquidations:LiquidationData; fear_greed:FearGreedData; economic_calendar:{events:unknown[];available:boolean}; timestamp:string }
export interface FuturesSnapshot { oi_delta:number; funding_rate:number; mark_price:number; futures_signal:string; futures_condition:string; futures_detail:Record<string,unknown> }
export interface FuturesData { symbol:string; oi_history:Array<{timestamp:string;symbol:string;oi_delta:number;mark_price:number}>; funding_history:Array<{timestamp:string;symbol:string;funding_rate:number;mark_price:number}>; snapshot:FuturesSnapshot }
export interface RegimeCurrent { regime:string; confidence:number; trend_bias:string; trend_strength:string; trend_data:Record<string,unknown> }
export interface RegimeData { symbol:string; current:RegimeCurrent; count:number; history:Array<{regime:string;confidence:number;timestamp:string}> }
export interface TradeRecord { id:number; timestamp:string; direction:'LONG'|'SHORT'; entry_price:number; stop_loss:number; take_profit:number; quantity:number; result:string; pnl:number; confidence:number }
export interface JournalPerformance { total_trades:number; message?:string; win_rate?:number; profit_factor?:number; total_pnl?:number }
export interface JournalData { symbol:string; performance:JournalPerformance; daily:Record<string,unknown>; open_trades:TradeRecord[]; explanations:unknown[]; agent_messages:unknown[] }
export interface MLStatus { meta_label_active:boolean; calibrator_active:boolean; outcome_predictor_active:boolean; last_prediction:{timestamp:string;original_action:string;label:string;outcome_probability:number;raw_confidence:number;calibrated_confidence:number}|null; timestamp:string }
export interface ModelInfo { id:number; created_at:string; model_type:string; version:string; active:number; algorithm:string; training_rows:number; win_rate:number; profit_factor:number; max_drawdown:number; notes:string }
export interface MLPerformance { active_models:{meta_label:ModelInfo|null;confidence_calibrator:ModelInfo|null;outcome_predictor:ModelInfo|null}; dataset:{total_rows:number;labelled_rows:number}; timestamp:string }
// V16 — Train Monitor tab. Mirrors GET /api/ml/models exactly (api/app.py
// ml_models()): one version-history list per model type, newest first
// (ml/model_registry.py::list_models() → ORDER BY id DESC).
export interface MLModelsData { meta_label:ModelInfo[]; confidence_calibrator:ModelInfo[]; outcome_predictor:ModelInfo[]; timestamp:string }

// ── V16 Track W14-1 Item 12: Train Monitor — scanner decision log ──────────
// One entry of GET /api/portfolio/history. This is PortfolioManager's
// decision-cycle log (which candidates it evaluated/selected this cycle),
// NOT the real executed account state — that's api.accountState() /
// GET /api/account/state. api/portfolio_serializers.py deliberately marks
// every payload here `live:false` for exactly this reason; PortfolioHistoryEntry
// mirrors serialize_history_entry()'s condensed shape field-for-field, no
// new backend endpoint required.
// V16 training-lane-visibility phase — Track C background paper-training
// lane status (GET /api/training-lane/status). Entirely separate account
// from PortfolioHistoryEntry below: this is the isolated $100 paper
// account training_lane/training_lane_runner.py drives 24/7, independent
// of the live scanner/CEO cycle and the real circuit breaker. `enabled:
// false` is a normal, expected state (flag off, or startup failed) — not
// an error — so callers should render a plain "not running" state for it
// rather than treating it as a fetch failure.
// Field names mirror paper/paper_position.py's PaperPosition.to_dict()
// and ClosedTrade.to_dict() exactly (both reused as-is, unmodified, by
// TrainingLaneRunner.status() — see that method's own doc comment).
export interface TrainingLanePosition {
  symbol: string
  direction: string // LONG | SHORT
  entry_price: number
  mark_price: number
  stop_loss: number | null
  take_profit: number | null
  quantity: number
  leverage: number
  unrealised_pnl: number
  unrealised_pct: number
  notional: number
  opened_at: string
  bars_open: number
}
export interface TrainingLaneClosedTrade {
  symbol: string
  direction: string // LONG | SHORT
  entry_price: number
  exit_price: number
  quantity: number
  stop_loss: number | null
  take_profit: number | null
  pnl: number
  pnl_pct: number
  rr: number
  result: string // WIN | LOSS | BREAKEVEN
  opened_at: string
  closed_at: string
  duration_s: number
  close_reason: string // SL | TP | MANUAL | TIMEOUT
}
export interface TrainingLaneStatus {
  enabled: boolean
  reason?: string
  is_running?: boolean
  symbol?: string
  execution_lane?: string
  starting_balance?: number
  balance?: number
  bust_count?: number
  closed_trade_count?: number
  open_position?: TrainingLanePosition | null
  last_closed_trade?: TrainingLaneClosedTrade | null
  poll_interval_seconds?: number
}

export interface PortfolioHistoryEntry {
  decided_at: string
  timestamp: string
  blocked: boolean
  block_reason: string | null
  selected_count: number
  rejected_count: number
  replacement_count: number
  total_capital_allocated: number
  total_risk_allocated: number
  diversification_score: number
  portfolio_score: number
  symbols: string[]
}
export interface PortfolioHistoryPage {
  entries: PortfolioHistoryEntry[]
  pagination: { limit:number; offset:number; returned:number; total:number|null; has_more:boolean }
  source: string
  live: boolean
  as_of: string | null
  note: string | null
}
export interface PaperMetricsValues { total_trades:number; wins:number; losses:number; win_rate:number; profit_factor:number; sharpe_ratio:number; expectancy:number; max_drawdown:number; max_drawdown_pct:number; total_pnl:number; avg_pnl:number; avg_win:number; avg_loss:number; avg_rr:number; best_trade:number; worst_trade:number; account?:{balance:number;equity:number;day_pnl:number;day_pnl_pct:number;total_pnl:number;win_rate:number} }
export interface PaperMetrics { enabled:boolean; metrics:PaperMetricsValues|null; reason:string|null }
export interface Signal { id:number; timestamp:string; action:string; confidence:number; regime:string; entry_price:number }
export interface SignalsData { symbol:string; count:number; signals:Signal[] }
export interface CommandState {
  paused: boolean
  paper_mode_forced: boolean
  updated_at: string | null
  // W14-0 — was already returned by GET /api/command/state
  // (get_control_state().snapshot()) but never modeled on the frontend
  // until Track W14-1. One of STOPPED/STARTING/RUNNING/STOPPING/FAILED —
  // see commander/control_state.py.
  lifecycle_state?: 'STOPPED' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'FAILED'
}

// V16 Track W14-1 Item 4/5 — real account telemetry (api/account_api.py).
// Mirrors that endpoint's response exactly; every field can genuinely be
// null/empty (see account_api.py's own "never fabricate a 0" rule) —
// consumers must render an explicit "no data yet" state, not a 0.
export interface AccountPosition {
  symbol: string; side: 'LONG' | 'SHORT'; quantity: number
  entry_price: number; mark_price: number; liquidation_price: number
  leverage: number; margin_type: string; unrealized_pnl: number
  notional: number; roi_pct: number | null
  sl_price: number | null; tp_price: number | null; version: number
}
export interface AccountOrder {
  symbol: string; order_id: number | string; client_order_id: string
  side: string; type: string; status: string; stop_price: number | null
  orig_qty: number; executed_qty: number; reduce_only: boolean
  is_sl: boolean; is_tp: boolean
}
export interface SectorAllocationEntry { sector: string; notional: number; pct: number }
export interface AccountPerformance {
  total_trades: number; win_rate: number | null
  profit_factor: number | null; avg_rr: number | null
}
export interface AccountStateData {
  status: 'NO_DATA_YET' | 'LIVE' | 'STALE' | 'OFFLINE' | 'ERROR'
  mode: string
  account: {
    wallet_balance: number; available_balance: number; unrealized_pnl: number
    total_margin_balance: number; maintenance_margin: number; initial_margin: number
    margin_ratio: number | null
  } | null
  positions: AccountPosition[]
  orders: AccountOrder[]
  sector_allocation: SectorAllocationEntry[]
  realized_pnl_total: number | null
  realized_pnl_today: number | null
  performance: AccountPerformance
  revision: number | null
  fetched_at: number | null
  age_seconds: number | null
  degraded?: boolean
  stale_reason?: string | null
  health_score?: number
}
export interface BusEvent { agent:string; event:string; message:string; severity:'info'|'warning'|'critical'; payload:Record<string,unknown>; timestamp:string; seq?:number }
