import PortfolioDashboard from './portfolio/PortfolioDashboard'

// V16 Track W14-1 Item 4: this page previously wrapped PortfolioDashboard
// in MockPortfolioProvider (fake equity/positions/Sharpe/drawdown/win
// rate — see src/components/mock/MockDataProvider.tsx). PortfolioDashboard
// now reads real data from useAccount() (src/stores/index.ts), populated
// by GET /api/account/state — no mock wrapper needed in the production
// render path. MockDataProvider.tsx itself is left in place (test-only;
// no longer imported by any production page).
export default function Portfolio() {
  return <PortfolioDashboard />
}
