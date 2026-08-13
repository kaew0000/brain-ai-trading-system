import { useState, useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useUI, useDecision, useHealth, useCommander } from '@/stores'
import { StatusDot, ActionBadge } from '@/components/common'
import LifecycleControl from '@/components/commander/LifecycleControl'
import LoginModal from '@/components/auth/LoginModal'
import clsx from 'clsx'

const NAV = [
  {to:'/',icon:'◈',label:'Overview',short:'OVR'},
  {to:'/agents',icon:'◉',label:'Agent Floor',short:'AGT'},
  {to:'/debate',icon:'⚡',label:'Debate Room',short:'DBT'},
  {to:'/missions',icon:'⊞',label:'Mission Board',short:'MSN'},
  {to:'/portfolio',icon:'◎',label:'Portfolio',short:'PRT'},
  {to:'/intelligence',icon:'◬',label:'Market Intel',short:'MKT'},
  {to:'/memory',icon:'⬡',label:'AI Memory',short:'MEM'},
  {to:'/replay',icon:'▷',label:'Trade Replay',short:'RPL'},
  {to:'/commander',icon:'⌘',label:'Commander',short:'CMD'},
  {to:'/health',icon:'♥',label:'System Health',short:'SYS'},
  {to:'/world',icon:'⌂',label:'Office World',short:'WLD'},
]

function Clock(){
  const[t,setT]=useState(()=>new Date().toISOString().slice(11,19))
  useEffect(()=>{const id=setInterval(()=>setT(new Date().toISOString().slice(11,19)),1000);return()=>clearInterval(id)},[])
  return <span className="text-text-muted tabular-nums font-mono text-xs">{t} UTC</span>
}

export default function Layout(){
  const connected=useUI(s=>s.connected)
  const decision=useDecision(s=>s.data)
  const health=useHealth(s=>s.data)
  const commanderState=useCommander(s=>s.state)
  const loc=useLocation()
  const sig=decision?.signal
  const overall=health?.overall_status??'UNKNOWN'
  const ovColor=overall==='ALIVE'?'text-accent-green':overall==='DEGRADED'?'text-accent-gold':'text-accent-red'
  // V16 Track W14-1 Item 5 — "Waiting for first cycle" fix. `sig` itself
  // is never cleared/reset (useDecisionData()'s poll only ever updates it
  // on success, keeping last-known-good on failure — see useData.ts —
  // and the backend's /api/decision also never clears latest_decision on
  // stop, see api/app.py). What WAS missing: any signal that the shown
  // decision might be stale because the bot isn't currently RUNNING.
  // lifecycle_state undefined (older backend / not yet polled) is
  // treated as "unknown", not as "definitely running" — never implies
  // freshness it can't confirm.
  const lifecycleState=commanderState?.lifecycle_state
  const isLive=lifecycleState==='RUNNING'
  const [showLogin,setShowLogin]=useState(false)

  return(
    <div className="flex h-screen overflow-hidden bg-surface bg-grid bg-grid">
      <aside className="flex flex-col w-14 xl:w-52 shrink-0 border-r border-border bg-surface-1" role="navigation" aria-label="Primary">
        <div className="px-3 py-3 border-b border-border flex items-center gap-2">
          <div className="w-7 h-7 rounded bg-accent-blue/20 border border-accent-blue/50 flex items-center justify-center text-accent-blue text-sm font-bold shrink-0">B</div>
          <div className="hidden xl:block overflow-hidden">
            <div className="text-xs font-mono font-bold text-text-primary leading-none">BRAIN BOT</div>
            <div className="text-[9px] text-text-muted tracking-widest mt-0.5">V16 · COMMAND OFFICE</div>
          </div>
        </div>
        <nav className="flex-1 py-2 px-1.5 space-y-0.5 overflow-y-auto" role="menubar">
          {NAV.map(n=>(
            <NavLink key={n.to} to={n.to} end={n.to==='/'}
              className={({isActive})=>clsx('nav-item',isActive&&'active')}>
              <span className="text-base w-5 text-center shrink-0">{n.icon}</span>
              <span className="hidden xl:block flex-1 truncate">{n.label}</span>
              <span className="xl:hidden text-[10px] text-text-muted">{n.short}</span>
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-2 border-t border-border">
          <div className="flex items-center gap-2">
            <StatusDot status={connected?'ALIVE':'DEAD'}/>
            <span className="hidden xl:block text-[10px] text-text-muted font-mono">{connected?'CONNECTED':'OFFLINE'}</span>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="h-10 shrink-0 border-b border-border bg-surface-1 px-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="text-text-muted">BTCUSDT</span>
            {(sig?.entry_price??0)>0?<span className="text-accent-gold font-bold tabular-nums">${(sig.entry_price as number).toLocaleString(undefined,{minimumFractionDigits:2})}</span>:null}
          </div>
          <div className="flex items-center gap-3">
            {sig?(
              <>
                <ActionBadge action={sig.action}/>
                <div className="flex items-center gap-1.5">
                  <div className="w-20 h-1 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full bg-accent-blue rounded-full transition-all duration-500" style={{width:`${sig.confidence}%`}}/>
                  </div>
                  <span className="text-xs font-mono text-text-secondary tabular-nums">{sig.confidence.toFixed(1)}%</span>
                </div>
                <span className="text-xs text-text-muted hidden md:block">{sig.regime}</span>
                {!isLive&&lifecycleState&&(
                  <span
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent-gold/15 text-accent-gold"
                    title="Bot is not RUNNING — showing the last decision from before it stopped, not a live signal"
                  >
                    {lifecycleState==='STOPPED'?'STOPPED · last signal':lifecycleState}
                  </span>
                )}
              </>
            ):<span className="text-xs text-text-muted animate-pulse">Waiting for first cycle…</span>}
          </div>
          <div className="flex items-center gap-4">
            <LifecycleControl onRequireLogin={()=>setShowLogin(true)}/>
            <span className={clsx('hidden sm:block text-xs font-mono font-medium',ovColor)}>{overall}</span>
            <Clock/>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-3">
          <motion.div key={loc.pathname} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:0.15}} className="h-full">
            <Outlet/>
          </motion.div>
        </main>
      </div>
      {showLogin&&<LoginModal onClose={()=>setShowLogin(false)}/>}
    </div>
  )
}
