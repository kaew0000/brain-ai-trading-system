/**
 * V16 Track W14-1 Item 4/5 — Real Portfolio Dashboard
 *
 * Replaces the previous MockPortfolioProvider-driven view (fake
 * $124,500.75 equity, fake BTC/ETH/SOL/XRP positions, fake Sharpe/
 * drawdown/win-rate) with data read from the real GET /api/account/state
 * endpoint (api/account_api.py), via the useAccount() store
 * (src/stores/index.ts) populated by useAccountData() (src/hooks/
 * useData.ts).
 *
 * Fields this page does NOT show, and why:
 *   - Sharpe ratio / Max Drawdown: no calculation for either exists
 *     anywhere in the backend today (checked journal/journal_v2.py,
 *     analytics/trade_journal.py — neither computes them). Inventing a
 *     new stats engine is out of this phase's scope (dashboard/
 *     telemetry/auth/launcher only) and would itself be exactly the
 *     kind of fabricated number this phase exists to remove. Omitted
 *     rather than faked.
 *   - Intraday equity curve: no time-series balance-snapshot store
 *     exists (portfolio/portfolio_history.py persists decision cycles,
 *     not balance snapshots). Omitted rather than faked.
 * Fields that ARE real:
 *   - Equity/balance/margin/PnL, positions, SL/TP: exchange_state's C1
 *     ExchangeStateManager, via /api/account/state.
 *   - Sector allocation: computed server-side from live position
 *     notional via the existing portfolio/sector_engine.py.
 *   - Win rate / Profit factor / realized PnL: journal/journal_v2.py's
 *     existing get_performance_summary()/get_today_pnl().
 */
import { Panel, StatCard } from '@/components/common'
import { useAccount } from '@/stores'
import { motion } from 'framer-motion'
import clsx from 'clsx'
import type { AccountPosition, SectorAllocationEntry } from '@/types/api'

const STATUS_LABEL: Record<string, string> = {
  NO_DATA_YET: 'Waiting for first account snapshot…',
  STALE:       'Data slightly delayed',
  OFFLINE:     'Exchange connection lost — showing last known data',
  ERROR:       'Telemetry error — showing last known data',
}

function FreshnessBanner({ status, ageSeconds }: { status: string; ageSeconds: number | null }) {
  if (status === 'LIVE') return null
  const color = status === 'NO_DATA_YET' ? 'text-text-muted' : status === 'STALE' ? 'text-accent-gold' : 'text-accent-red'
  const age = ageSeconds != null ? ` (${Math.round(ageSeconds)}s old)` : ''
  return (
    <div className={clsx('text-xs font-mono px-3 py-1.5 rounded bg-surface-2 border border-border', color)}>
      {STATUS_LABEL[status] ?? status}{status !== 'NO_DATA_YET' ? age : ''}
    </div>
  )
}

function AllocationBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary font-medium">{label}</span>
        <span className="font-mono text-text-primary">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-surface-3 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      </div>
    </div>
  )
}

// Stable-ish color per sector name so re-renders/re-sorts don't flicker
// colors — a small fixed palette cycled by string hash, not per-symbol
// branding data from anywhere (there is none), so this is presentation
// only, never mistaken for a data field.
const SECTOR_COLORS = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899']
function colorFor(sector: string): string {
  let h = 0
  for (let i = 0; i < sector.length; i++) h = (h * 31 + sector.charCodeAt(i)) >>> 0
  return SECTOR_COLORS[h % SECTOR_COLORS.length]
}

function PositionRow({ pos, i }: { pos: AccountPosition; i: number }) {
  const isProfit = pos.unrealized_pnl >= 0
  return (
    <motion.div
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
          {pos.quantity} @ ${pos.entry_price.toLocaleString()}
        </span>
        <span className="text-text-secondary">→</span>
        <span className="text-text-muted">${pos.mark_price.toLocaleString()}</span>
        <span className={clsx('font-semibold', isProfit ? 'text-accent-green' : 'text-accent-red')}>
          {isProfit ? '+' : ''}${pos.unrealized_pnl.toLocaleString()}
          {pos.roi_pct != null ? ` (${pos.roi_pct.toFixed(2)}%)` : ''}
        </span>
      </div>
    </motion.div>
  )
}

export default function PortfolioDashboard() {
  const { account: data } = useAccount()

  // useAccountData() polls on mount, so on the very first render(s) the
  // store can still be null — that's the same "no data yet" state as an
  // explicit NO_DATA_YET status, never treated as an error.
  const status = data?.status ?? 'NO_DATA_YET'
  const acct = data?.account ?? null
  const positions = data?.positions ?? []
  const sectors: SectorAllocationEntry[] = data?.sector_allocation ?? []
  const perf = data?.performance

  const dayPnl = data?.realized_pnl_today
  const isProfit = (dayPnl ?? 0) >= 0

  return (
    <div className="h-full grid grid-rows-[auto_auto_1fr] gap-3">
      <FreshnessBanner status={status} ageSeconds={data?.age_seconds ?? null} />

      {/* Top stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="Wallet Balance"
          value={acct ? `$${acct.wallet_balance.toLocaleString()}` : '—'}
          color="text-accent-gold" icon="◎"
        />
        <StatCard
          label="Realized P&L (today)"
          value={dayPnl != null ? `${isProfit ? '+' : ''}$${dayPnl.toLocaleString()}` : '—'}
          color={dayPnl != null ? (isProfit ? 'text-accent-green' : 'text-accent-red') : undefined}
          icon="◈"
        />
        <StatCard
          label="Unrealized P&L"
          value={acct ? `${acct.unrealized_pnl >= 0 ? '+' : ''}$${acct.unrealized_pnl.toLocaleString()}` : '—'}
          color={acct ? (acct.unrealized_pnl >= 0 ? 'text-accent-green' : 'text-accent-red') : undefined}
        />
        <StatCard label="Positions" value={positions.length} color="text-accent-blue" />
      </div>

      <div className="grid grid-cols-12 gap-3 min-h-0">
        {/* Positions table */}
        <div className="col-span-12 lg:col-span-8 space-y-3 overflow-auto">
          <Panel title="Open Positions" icon="◎" className="h-full">
            {positions.length === 0 ? (
              <div className="text-xs text-text-muted p-4 text-center">
                {status === 'NO_DATA_YET' ? 'Waiting for account data…' : 'No open positions'}
              </div>
            ) : (
              <div className="space-y-2">
                {positions.map((pos, i) => <PositionRow key={pos.symbol} pos={pos} i={i} />)}
              </div>
            )}
          </Panel>
        </div>

        {/* Right column: sector allocation + performance (real data only) */}
        <div className="col-span-12 lg:col-span-4 space-y-3">
          <Panel title="Sector Allocation" icon="◬">
            {sectors.length === 0 ? (
              <div className="text-xs text-text-muted p-2">No open exposure</div>
            ) : (
              <div className="space-y-4">
                {sectors.map(s => (
                  <AllocationBar key={s.sector} label={s.sector} pct={s.pct} color={colorFor(s.sector)} />
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Performance" icon="◉">
            {/* Sharpe ratio and max drawdown are intentionally not shown
                here — no backend calculation for either exists yet (see
                this file's module docstring). Showing a number would
                mean fabricating one. */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-surface-2 rounded p-2 text-center border border-border">
                <div className="text-lg font-mono font-bold text-accent-green">
                  {perf?.win_rate != null ? `${(perf.win_rate * 100).toFixed(1)}%` : '—'}
                </div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Win Rate</div>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center border border-border">
                <div className="text-lg font-mono font-bold text-accent-blue">
                  {perf?.profit_factor != null ? perf.profit_factor.toFixed(2) : '—'}
                </div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Profit Factor</div>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center border border-border col-span-2">
                <div className="text-lg font-mono font-bold text-accent-gold">
                  {perf?.total_trades ?? 0}
                </div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider">Closed Trades</div>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
