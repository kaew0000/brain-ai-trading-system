import { useState, useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useUI, useDecision, useHealth } from '@/stores'
import { StatusDot, ActionBadge } from '@/components/common'
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
  const loc=useLocation()
  const sig=decision?.signal
  const overall=health?.overall_status??'UNKNOWN'
  const ovColor=overall==='ALIVE'?'text-accent-green':overall==='DEGRADED'?'text-accent-gold':'text-accent-red'

  return(
    <div className="flex h-screen overflow-hidden bg-surface bg-grid bg-grid">
      <aside className="flex flex-col w-14 xl:w-52 shrink-0 border-r border-border bg-surface-1">
        <div className="px-3 py-3 border-b border-border flex items-center gap-2">
          <div className="w-7 h-7 rounded bg-accent-blue/20 border border-accent-blue/50 flex items-center justify-center text-accent-blue text-sm font-bold shrink-0">B</div>
          <div className="hidden xl:block overflow-hidden">
            <div className="text-xs font-mono font-bold text-text-primary leading-none">BRAIN BOT</div>
            <div className="text-[9px] text-text-muted tracking-widest mt-0.5">V14 · COMMAND OFFICE</div>
          </div>
        </div>
        <nav className="flex-1 py-2 px-1.5 space-y-0.5 overflow-y-auto">
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
              </>
            ):<span className="text-xs text-text-muted animate-pulse">Waiting for first cycle…</span>}
          </div>
          <div className="flex items-center gap-4">
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
    </div>
  )
}
