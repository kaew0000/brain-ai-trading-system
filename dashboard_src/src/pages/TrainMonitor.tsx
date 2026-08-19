/**
 * V16 — Train Monitor tab.
 *
 * Dedicated view for "is the system still training normally, and what
 * did training actually produce" — requested directly (Command Center
 * screenshot had no way to answer either question without reading raw
 * JSON). Reuses existing, already-live infrastructure only:
 *
 *  - useML() (status/performance) — already globally polled every 15s
 *    by useMLData() (hooks/useData.ts), backed by GET /api/ml/status +
 *    GET /api/ml/performance. Nothing new fetched here for these.
 *  - GET /api/ml/models (api.mlModels(), lib/api.ts — already existed,
 *    just never called from any page) — polled locally, same
 *    page-local useEffect+setInterval pattern already used by
 *    TradeReplay.tsx / DebateRoom.tsx / Memory.tsx for page-specific
 *    data that doesn't need to live in the global store.
 *
 * No new backend routes. No existing export touched.
 *
 * "Still training normally" is answered with facts, not a guessed
 * verdict: last_prediction recency (raw timestamp — this page doesn't
 * know the real trading-cycle cadence well enough to assert
 * ALIVE/STALE the way system_health's watchdog does, so it isn't
 * invented here) and a dataset-row counter that is compared against
 * its own first-observed value for this page session, so a flat
 * count while the page is open is visible as `+0`, not asserted as
 * "stuck" — the person judges that against how long they've had the
 * tab open.
 */
import { useState, useEffect, useRef } from 'react'
import { useML } from '@/stores'
import { Panel, StatCard, DataTable, Empty, Loading, ConfBar, fmtPct, timeAgo } from '@/components/common'
import { MiniChart } from '@/components/common/MiniChart'
import { api } from '@/lib/api'
import { computeRowsGrowth } from '@/lib/trainMonitor'
import type { MLModelsData, ModelInfo, MLStatus, PortfolioHistoryEntry } from '@/types/api'
import clsx from 'clsx'

const MODEL_TYPES = [
  { key: 'meta_label',            label: 'Meta Label',        activeKey: 'meta_label_active' },
  { key: 'confidence_calibrator', label: 'Calibrator',        activeKey: 'calibrator_active' },
  { key: 'outcome_predictor',     label: 'Outcome Predictor', activeKey: 'outcome_predictor_active' },
] as const satisfies ReadonlyArray<{ key: keyof MLModelsData & string; label: string; activeKey: keyof MLStatus & string }>

export default function TrainMonitor() {
  const status = useML(s => s.status)
  const performance = useML(s => s.performance)
  const [models, setModels] = useState<MLModelsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<typeof MODEL_TYPES[number]['key']>('meta_label')

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await api.mlModels()
        if (!cancelled) setModels(data as unknown as MLModelsData)
      } catch { /* keep last-known-good, same posture as every other poll in this app */ }
      if (!cancelled) setLoading(false)
    }
    load()
    const id = setInterval(load, 20000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // V16 Track W14-1 Item 12 — scanner/CEO decision-cycle log. Explicitly
  // NOT real account state (see PortfolioHistoryEntry doc comment in
  // types/api.ts and the warning banner rendered below it) — surfaces
  // multi-symbol scanning activity (SCANNER_ENABLED/SCHEDULER_ENABLED/
  // CEO_MULTI_SYMBOL_ENABLED) for training visibility without risking it
  // being mistaken for the live portfolio shown elsewhere (Commander /
  // api.accountState()).
  const [portfolioHistory, setPortfolioHistory] = useState<PortfolioHistoryEntry[]>([])
  const [portfolioHistoryLoading, setPortfolioHistoryLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const page = await api.portfolioHistory(30)
        if (!cancelled) setPortfolioHistory((page as any)?.entries ?? [])
      } catch { /* keep last-known-good */ }
      if (!cancelled) setPortfolioHistoryLoading(false)
    }
    load()
    const id = setInterval(load, 20000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Dataset growth observed since this page was opened — see file header.
  const firstTotalRows = useRef<number | null>(null)
  const totalRows = performance?.dataset?.total_rows
  if (firstTotalRows.current === null && typeof totalRows === 'number') {
    firstTotalRows.current = totalRows
  }
  const rowsGrowth = computeRowsGrowth(firstTotalRows.current, totalRows)

  const rows: ModelInfo[] = (models?.[tab] as ModelInfo[] | undefined) ?? []
  const activeModel = performance?.active_models?.[tab === 'meta_label' ? 'meta_label' : tab === 'confidence_calibrator' ? 'confidence_calibrator' : 'outcome_predictor'] ?? null

  const cols = [
    { key: 'version',       label: 'Version' },
    { key: 'created_at',    label: 'Created', render: (r: any) => <span className="text-text-muted">{new Date(r.created_at).toLocaleString()}</span> },
    { key: 'algorithm',     label: 'Algorithm', render: (r: any) => <span className="text-text-secondary">{r.algorithm || '—'}</span> },
    { key: 'training_rows', label: 'Rows', right: true },
    { key: 'win_rate',      label: 'Win Rate', right: true, render: (r: any) => <span className={r.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red'}>{fmtPct(r.win_rate, 1)}</span> },
    { key: 'profit_factor', label: 'PF', right: true, render: (r: any) => <span className={r.profit_factor >= 1 ? 'text-accent-green' : 'text-accent-red'}>{Number(r.profit_factor).toFixed(2)}</span> },
    { key: 'max_drawdown',  label: 'Max DD', right: true, render: (r: any) => <span className="text-text-muted">{Number(r.max_drawdown).toFixed(2)}</span> },
    { key: 'active',        label: 'Status', render: (r: any) => r.active ? <span className="badge-green">ACTIVE</span> : <span className="text-text-muted text-[10px]">retired</span> },
    { key: 'notes',         label: 'Notes', render: (r: any) => <span className="text-text-muted text-[10px] truncate max-w-[180px] block" title={r.notes || undefined}>{r.notes || '—'}</span> },
  ]

  return (
    <div className="h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {MODEL_TYPES.map(m => (
          <StatCard
            key={m.key}
            label={m.label}
            value={status?.[m.activeKey] ? 'ACTIVE' : 'NONE'}
            color={status?.[m.activeKey] ? 'text-accent-green' : 'text-text-muted'}
          />
        ))}
        <StatCard label="Dataset Rows" value={performance?.dataset?.total_rows ?? '—'} sub={`${performance?.dataset?.labelled_rows ?? '—'} labelled`} />
        <StatCard
          label="Growth (this session)"
          value={rowsGrowth == null ? '—' : rowsGrowth > 0 ? `+${rowsGrowth}` : rowsGrowth}
          color={rowsGrowth != null && rowsGrowth > 0 ? 'text-accent-green' : 'text-text-muted'}
          sub="rows since tab opened"
        />
      </div>

      <div className="grid grid-cols-12 gap-3 min-h-0">
        <div className="col-span-12 xl:col-span-8 flex flex-col min-h-0">
          <Panel
            title="Model Training History"
            icon="◇"
            accent="text-accent-purple"
            className="h-full"
            noPad
            action={
              <div className="flex gap-1">
                {MODEL_TYPES.map(m => (
                  <button
                    key={m.key}
                    onClick={() => setTab(m.key)}
                    className={clsx(
                      'px-2 py-1 rounded text-[10px] font-mono transition-all border',
                      tab === m.key
                        ? 'bg-accent-purple/20 text-accent-purple border-accent-purple/30'
                        : 'text-text-secondary border-transparent hover:bg-surface-2',
                    )}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            }
          >
            <div className="p-3 overflow-auto h-full">
              {loading ? <Loading /> : rows.length === 0
                ? <Empty text="No training runs recorded yet for this model type" />
                : <DataTable cols={cols} rows={rows} rowKey={(r: any, i) => String(r.id ?? i)} />}
            </div>
          </Panel>
        </div>

        <div className="col-span-12 xl:col-span-4 flex flex-col gap-3 min-h-0">
          <Panel title="Currently Active" icon="●" accent="text-accent-green">
            {!activeModel ? <Empty text="No active model for this type" /> : (
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between"><span className="text-text-muted">Version</span><span className="font-mono text-text-primary">{activeModel.version}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Created</span><span className="font-mono text-text-secondary">{new Date(activeModel.created_at).toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Algorithm</span><span className="font-mono text-text-secondary">{activeModel.algorithm || '—'}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Training Rows</span><span className="font-mono text-text-secondary">{activeModel.training_rows}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Win Rate</span><span className="font-mono text-accent-green">{fmtPct(activeModel.win_rate, 1)}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Profit Factor</span><span className="font-mono text-text-secondary">{Number(activeModel.profit_factor).toFixed(2)}</span></div>
                {activeModel.notes && <div className="pt-1.5 border-t border-border text-text-muted text-[10px]">{activeModel.notes}</div>}
              </div>
            )}
          </Panel>

          <Panel title="Last Prediction" icon="◆" accent="text-accent-gold" className="flex-1">
            {!status?.last_prediction ? <Empty text="No prediction recorded yet" /> : (
              <div className="space-y-2 text-xs">
                <div className="flex justify-between items-center">
                  <span className="text-text-muted">When</span>
                  <span className="font-mono text-text-secondary" title={status.last_prediction.timestamp}>{timeAgo(status.last_prediction.timestamp)}</span>
                </div>
                <div className="flex justify-between"><span className="text-text-muted">Original Action</span><span className="font-mono">{status.last_prediction.original_action}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Label</span><span className={clsx('font-mono', status.last_prediction.label === 'TRADE' ? 'text-accent-green' : 'text-accent-red')}>{status.last_prediction.label}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Raw Confidence</span><span className="font-mono">{status.last_prediction.raw_confidence.toFixed(1)}%</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Calibrated</span><span className="font-mono text-accent-gold">{status.last_prediction.calibrated_confidence.toFixed(1)}%</span></div>
                <div>
                  <div className="flex justify-between mb-1"><span className="text-text-muted">Outcome Probability</span><span className="font-mono">{status.last_prediction.outcome_probability.toFixed(1)}%</span></div>
                  <ConfBar value={status.last_prediction.outcome_probability} color="bg-accent-purple" />
                </div>
              </div>
            )}
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3 min-h-0">
        <div className="col-span-12 xl:col-span-8 flex flex-col min-h-0">
          <Panel
            title="Scanner Decision Log — Not Real Positions"
            icon="⚠"
            accent="text-accent-gold"
            className="h-full"
            noPad
          >
            <div className="px-3 pt-2 pb-1 text-[10px] text-accent-gold/90 border-b border-border bg-accent-gold/5">
              แสดง decision cycle ของ scanner/CEO (เหรียญที่ประเมิน/เลือกต่อรอบ)
              ไม่ใช่พอร์ตเงินจริงที่กำลังถือ — ดูสถานะบัญชีจริงที่หน้า Commander
            </div>
            <div className="p-3 overflow-auto h-full">
              {portfolioHistoryLoading ? <Loading /> : portfolioHistory.length === 0
                ? <Empty text="No decision cycles persisted yet" />
                : <DataTable
                    cols={[
                      { key: 'timestamp', label: 'Cycle', render: (r: PortfolioHistoryEntry) => <span className="text-text-muted">{timeAgo(r.timestamp)}</span> },
                      { key: 'symbols', label: 'Symbols', render: (r: PortfolioHistoryEntry) => <span className="text-text-secondary">{r.symbols.length ? r.symbols.join(', ') : '—'}</span> },
                      { key: 'selected_count', label: 'Selected', right: true },
                      { key: 'rejected_count', label: 'Rejected', right: true },
                      { key: 'blocked', label: 'Blocked', render: (r: PortfolioHistoryEntry) => r.blocked ? <span className="badge-red" title={r.block_reason ?? undefined}>BLOCKED</span> : <span className="text-text-muted text-[10px]">—</span> },
                      { key: 'portfolio_score', label: 'Score', right: true, render: (r: PortfolioHistoryEntry) => <span className="font-mono">{r.portfolio_score.toFixed(1)}</span> },
                    ]}
                    rows={portfolioHistory}
                    rowKey={(r: PortfolioHistoryEntry, i) => r.decided_at ?? String(i)}
                  />}
            </div>
          </Panel>
        </div>

        <div className="col-span-12 xl:col-span-4 flex flex-col min-h-0">
          <Panel title="Decision History Trend" icon="◈" accent="text-accent-blue" className="flex-1">
            {portfolioHistoryLoading ? <Loading /> : portfolioHistory.length < 2
              ? <Empty text="Not enough decision cycles yet for a trend" />
              : <MiniChart
                  series={[
                    { label: 'Selected symbols/cycle', color: '#60a5fa', values: [...portfolioHistory].reverse().map(r => r.selected_count) },
                    { label: 'Portfolio score', color: '#c084fc', values: [...portfolioHistory].reverse().map(r => r.portfolio_score) },
                  ]}
                  height={160}
                />}
          </Panel>
        </div>
      </div>
    </div>
  )
}
