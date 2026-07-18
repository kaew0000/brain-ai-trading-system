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
export interface PaperMetricsValues { total_trades:number; wins:number; losses:number; win_rate:number; profit_factor:number; sharpe_ratio:number; expectancy:number; max_drawdown:number; max_drawdown_pct:number; total_pnl:number; avg_pnl:number; avg_win:number; avg_loss:number; avg_rr:number; best_trade:number; worst_trade:number; account?:{balance:number;equity:number;day_pnl:number;day_pnl_pct:number;total_pnl:number;win_rate:number} }
export interface PaperMetrics { enabled:boolean; metrics:PaperMetricsValues|null; reason:string|null }
export interface Signal { id:number; timestamp:string; action:string; confidence:number; regime:string; entry_price:number }
export interface SignalsData { symbol:string; count:number; signals:Signal[] }
export interface CommandState { paused:boolean; paper_mode_forced:boolean; updated_at:string|null }
export interface BusEvent { agent:string; event:string; message:string; severity:'info'|'warning'|'critical'; payload:Record<string,unknown>; timestamp:string; seq?:number }
