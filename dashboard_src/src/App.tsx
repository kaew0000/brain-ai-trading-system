import { Routes, Route } from 'react-router-dom'
import Layout from '@/components/layout/Layout'
import { useAllData } from '@/hooks/useData'
import Overview      from '@/pages/Overview'
import AgentFloor    from '@/pages/AgentFloor'
import DebateRoom    from '@/pages/DebateRoom'
import MissionBoard  from '@/pages/MissionBoard'
import Portfolio     from '@/pages/Portfolio'
import Intelligence  from '@/pages/Intelligence'
import Memory        from '@/pages/Memory'
import TradeReplay   from '@/pages/TradeReplay'
import Commander     from '@/pages/Commander'
import SystemHealth  from '@/pages/SystemHealth'

function DataBootstrap(){ useAllData(); return null }

export default function App(){
  return (
    <>
      <DataBootstrap />
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
        </Route>
      </Routes>
    </>
  )
}
