/**
 * Brain Bot — MockDataProvider
 * Wraps frontend components with realistic-looking mock data when
 * backend endpoints are not yet implemented.
 *
 * Claude replaces this provider with real data adapters later.
 */
import { createContext, useContext, ReactNode } from 'react'

export interface MockPortfolioData {
  totalEquity: number
  dayPnl: number
  dayPnlPct: number
  positions: Array<{
    symbol: string
    side: 'LONG' | 'SHORT'
    size: number
    entryPrice: number
    markPrice: number
    pnl: number
    pnlPct: number
    margin: number
    leverage: number
  }>
  allocation: Array<{ sector: string; value: number; target: number; color: string }>
  history: Array<{ time: string; equity: number }>
  metrics: {
    sharpe: number
    maxDrawdown: number
    winRate: number
    profitFactor: number
  }
}

const MockPortfolioContext = createContext<MockPortfolioData | null>(null)

export function MockPortfolioProvider({ children }: { children: ReactNode }) {
  const value: MockPortfolioData = {
    totalEquity: 124_500.75,
    dayPnl: 2_340.50,
    dayPnlPct: 1.91,
    positions: [
      { symbol: 'BTCUSDT', side: 'LONG', size: 0.45, entryPrice: 64200, markPrice: 65123, pnl: 415.35, pnlPct: 1.44, margin: 15000, leverage: 4 },
      { symbol: 'ETHUSDT', side: 'SHORT', size: 2.5, entryPrice: 3450, markPrice: 3380, pnl: 175.00, pnlPct: 2.03, margin: 8000, leverage: 3 },
      { symbol: 'SOLUSDT', side: 'LONG', size: 15, entryPrice: 145.20, markPrice: 148.50, pnl: 49.50, pnlPct: 2.27, margin: 2000, leverage: 5 },
      { symbol: 'XRPUSDT', side: 'SHORT', size: 500, entryPrice: 0.62, markPrice: 0.598, pnl: 11.00, pnlPct: 3.55, margin: 300, leverage: 2 },
    ],
    allocation: [
      { sector: 'Crypto Majors', value: 65, target: 60, color: '#3b82f6' },
      { sector: 'Altcoins', value: 20, target: 25, color: '#8b5cf6' },
      { sector: 'Cash', value: 15, target: 15, color: '#10b981' },
    ],
    history: Array.from({ length: 24 }, (_, i) => ({
      time: `${i.toString().padStart(2, '0')}:00`,
      equity: 120000 + Math.sin(i / 3) * 2000 + i * 150 + (Math.random() * 400 - 200),
    })),
    metrics: {
      sharpe: 1.84,
      maxDrawdown: -8.2,
      winRate: 62.5,
      profitFactor: 1.73,
    },
  }

  return (
    <MockPortfolioContext.Provider value={value}>
      {children}
    </MockPortfolioContext.Provider>
  )
}

export const useMockPortfolio = (): MockPortfolioData => {
  const ctx = useContext(MockPortfolioContext)
  if (!ctx) throw new Error('useMockPortfolio must be used within MockPortfolioProvider')
  return ctx
}
