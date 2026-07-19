import { Routes, Route } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import Layout from '@/components/layout/Layout'
import { useAllData } from '@/hooks/useData'
import PageLoader from '@/components/common/PageLoader'

const Overview      = lazy(() => import('@/pages/Overview'))
const AgentFloor    = lazy(() => import('@/pages/AgentFloor'))
const DebateRoom    = lazy(() => import('@/pages/DebateRoom'))
const MissionBoard  = lazy(() => import('@/pages/MissionBoard'))
const Portfolio     = lazy(() => import('@/pages/Portfolio'))
const Intelligence  = lazy(() => import('@/pages/Intelligence'))
const Memory        = lazy(() => import('@/pages/Memory'))
const TradeReplay   = lazy(() => import('@/pages/TradeReplay'))
const Commander     = lazy(() => import('@/pages/Commander'))
const SystemHealth  = lazy(() => import('@/pages/SystemHealth'))
const WorldPage     = lazy(() => import('@/pages/world/WorldPage'))

function DataBootstrap() { useAllData(); return null }

export default function App() {
  return (
    <>
      <DataBootstrap />
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index             element={<Overview />} />
            <Route path="agents"     element={<AgentFloor />} />
            <Route path="debate"     element={<DebateRoom />} />
            <Route path="missions"   element={<MissionBoard />} />
            <Route path="portfolio"  element={<Portfolio />} />
            <Route path="intelligence" element={<Intelligence />} />
            <Route path="memory"     element={<Memory />} />
            <Route path="replay"     element={<TradeReplay />} />
            <Route path="commander"  element={<Commander />} />
            <Route path="health"     element={<SystemHealth />} />
            <Route path="world"      element={<WorldPage />} />
          </Route>
        </Routes>
      </Suspense>
    </>
  )
}
