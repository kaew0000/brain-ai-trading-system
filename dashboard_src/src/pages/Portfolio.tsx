import { MockPortfolioProvider } from '@/components/mock/MockDataProvider'
import PortfolioDashboard from './portfolio/PortfolioDashboard'

export default function Portfolio() {
  return (
    <MockPortfolioProvider>
      <PortfolioDashboard />
    </MockPortfolioProvider>
  )
}
