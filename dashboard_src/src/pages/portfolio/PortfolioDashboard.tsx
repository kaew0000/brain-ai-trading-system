import { Panel, StatCard } from '@/components/common'
import { useMockPortfolio } from '@/components/mock/MockDataProvider'
import { motion } from 'framer-motion'
import clsx from 'clsx'

function AllocationBar({ label, value, target, color }: { label: string; value: number; target: number; color: string }) {
  const diff = value - target
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary font-medium">{label}</span>
        <span className="font-mono text-text-primary">{value}%</span>
      </div>
      <div className="h-2 bg-surface-3 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
          initial={{ width: 0 }}
          animate={{ width: `${value}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-text-muted font-mono">
        <span>Target {target}%</span>
        <span className={clsx(diff > 0 ? 'text-accent-green' : diff < 0 ? 'text-accent-red' : '')}>
          {diff > 0 ? '+' : ''}{diff.toFixed(1)}%
        </span>
      </div>
    </div>
  )
}

function EquitySparkline({ data }: { data: Array<{ time: string; equity: number }> }) {
  const values = data.map(d => d.equity)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * 100
    const y = 100 - ((d.equity - min) / range) * 100
    return `${x},${Math.max(2, Math.min(98, y))}`
  }).join(' ')

  return (
    <div className="h-32 w-full">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
        <defs>
          <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon points={`0,100 ${points} 100,100`} fill="url(#equityGrad)" />
        <polyline points={points} fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="flex justify-between text-[10px] text-text-muted font-mono mt-1">
        <span>00:00</span>
        <span>23:00</span>
      </div>
    </div>
  )
}

export default function PortfolioDashboard() {
  const p = useMockPortfolio()
  const isProfit = p.dayPnl >= 0

  return (
    <div className="h-full grid grid-rows-[auto_1fr] gap-3">
      {/* Top stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total Equity" value={`$${p.totalEquity.toLocaleString()}`} color="text-accent-gold" icon="◎" />
        <StatCard
          label="Day P&L"
          value={`${isProfit ? '+' : ''}$${p.dayPnl.toLocaleString()}`}
          color={isProfit ? 'text-accent-green' : 'text-accent-red'}
          icon="◈"
        />
        <StatCard label="Day %" value={`${isProfit ? '+' : ''}${p.dayPnlPct.toFixed(2)}%`} color={isProfit ? 'text-accent-green' : 'text-accent-red'} />
        <StatCard label="Positions" value={p.positions.length} color="text-accent-blue" />
      </div>

      <div className="grid grid-cols-12 gap-3 min-h-0">
        {/* Positions table */}
        <div className="col-span-12 lg:col-span-8 space-y-3 overflow-auto">
          <Panel title="Open Positions" icon="◎" className="h-full">
            <div className="space-y-2">
              {p.positions.map((pos, i) => (
                <motion.div
                  key={pos.symbol}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05, duration: 0.25 }}
                  className="flex items-center justify-between p-2.5 rounded bg-surface-2 border border-border hover:border-border-bright transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={clsx(
                        'text-[10px] font-bold px-1.5 py-0.5 rounded',
                        pos.side === 'LONG' ? 'bg-accent-green/20 text-accent-green' : 'bg-accent-red/20 text-accent-red'
                      )}
                    >
                      {pos.side}
                    </span>
                    <span className="text-sm font-mono font-semibold text-text-primary">{pos.symbol}</span>
                    <span className="text-[10px] text-text-muted font-mono">{pos.leverage}x</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs font-mono">
                    <span className="text-text-muted">
                      {pos.size} @ ${pos.entryPrice.toLocaleString()}
                    </span>
                    <span className="text-text-secondary">→</span>
                    <span className="text-text-muted">${pos.markPrice.toLocaleString()}</span>
                    <span className={clsx('font-semibold', pos.pnl >= 0 ? 'text-accent-green' : 'text-accent-red')}>
                      {pos.pnl >= 0 ? '+' : ''}${pos.pnl.toLocaleString()} ({pos.pnlPct.toFixed(2)}%)
                    </span>
                  </div>
                </motion.div>
              ))}
            </div>
          </Panel>
        </div>

        {/* Right column: allocation + equity + metrics */}
        <div className="col-span-12 lg:col-span-4 space-y-3">
          <Panel title="Allocation" icon="◬">
            <div className="space-y-4">
              {p.allocation.map(a => (
                <AllocationBar key={a.sector} label={a.sector} value={a.value} target={a.target} color={a.color} />
              ))}
            </div>
          </Panel>

          <Panel title="Equity Curve (24h)" icon="◈">
            <EquitySparkline data={p.history} />
          </Panel>

          <Panel title="Performance Metrics" icon="◉">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-surface-2 rounded p-2 text-center border border-border">
                <div className="text-lg font-mono font-bold text-accent-gold">{p.metrics.sharpe.toFixed(2)}</div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Sharpe</div>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center border border-border">
                <div className="text-lg font-mono font-bold text-accent-red">{p.metrics.maxDrawdown.toFixed(1)}%</div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Max DD</div>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center border border-border">
                <div className="text-lg font-mono font-bold text-accent-green">{p.metrics.winRate.toFixed(1)}%</div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Win Rate</div>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center border border-border">
                <div className="text-lg font-mono font-bold text-accent-blue">{p.metrics.profitFactor.toFixed(2)}</div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Profit Factor</div>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
