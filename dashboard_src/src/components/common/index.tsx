import React, { useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'

export function StatusDot({status}:{status:string}){
  const c=status==='ALIVE'||status==='online'?'dot-green':status==='STALE'?'dot-gold':'dot-red'
  return <span className={clsx('dot animate-pulse-slow',c)}/>
}

export function Panel({title,icon,action,className,children,accent,noPad}:{
  title:string;icon?:React.ReactNode;action?:React.ReactNode;className?:string;children:React.ReactNode;accent?:string;noPad?:boolean
}){
  return(
    <div className={clsx('panel flex flex-col',className)}>
      <div className="panel-header">
        <div className="flex items-center gap-2">
          {icon&&<span className={clsx('text-sm',accent||'text-accent-blue')}>{icon}</span>}
          <span className="panel-title">{title}</span>
        </div>
        {action&&<div>{action}</div>}
      </div>
      <div className={clsx('flex-1 overflow-auto',!noPad&&'p-3')}>{children}</div>
    </div>
  )
}

export function StatCard({label,value,sub,color='text-text-primary',icon,blink}:{
  label:string;value:string|number;sub?:string;color?:string;icon?:string;blink?:boolean
}){
  return(
    <div className="bg-surface-2 border border-border rounded-lg p-3 flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="stat-label">{label}</span>
        {icon&&<span className="text-base">{icon}</span>}
      </div>
      <div className={clsx('stat-value',color,blink&&'animate-blink')}>{value}</div>
      {sub&&<div className="text-xs text-text-muted">{sub}</div>}
    </div>
  )
}

export function ActionBadge({action}:{action:string}){
  if(action==='LONG')  return <span className="badge-green">▲ LONG</span>
  if(action==='SHORT') return <span className="badge-red">▼ SHORT</span>
  return <span className="badge-gray">◆ WAIT</span>
}

/**
 * FIX BUG-BLINK-01: ConfBar กระพริบเพราะ initial={{width:0}} reset ทุก re-render
 * แก้: ใช้ useRef เก็บ pct ล่าสุด → ครั้งแรก initial=0, หลังจากนั้น initial=prevPct
 * ผล: bar ไม่ reset กลับ 0 ทุกครั้ง poll เปลี่ยน data
 */
export function ConfBar({value,max=100,color='bg-accent-blue'}:{value:number;max?:number;color?:string}){
  const pct=Math.max(0,Math.min(100,(value/max)*100))
  const prevPct=useRef(0)
  const from=prevPct.current
  prevPct.current=pct
  return(
    <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden">
      <motion.div className={clsx('h-full rounded-full',color)}
        initial={{width:`${from}%`}}
        animate={{width:`${pct}%`}}
        transition={{duration:0.4,ease:'easeOut'}}/>
    </div>
  )
}

export function BreakdownBars({rows}:{rows:Array<{label:string;value:number;max:number;color:string}>}){
  return(
    <div className="space-y-2">
      {rows.map(r=>(
        <div key={r.label} className="flex items-center gap-2">
          <span className="text-xs text-text-muted w-16 shrink-0">{r.label}</span>
          <div className="flex-1"><ConfBar value={r.value} max={r.max} color={r.color}/></div>
          <span className="text-xs font-mono text-text-secondary w-10 text-right">{r.value}/{r.max}</span>
        </div>
      ))}
    </div>
  )
}

export function Timeline({items}:{items:Array<{label:string;note?:string;time?:string;done:boolean}>}){
  return(
    <ol className="relative border-l border-border ml-2 space-y-3">
      {items.map((item,i)=>(
        <li key={i} className="ml-4">
          <div className={clsx('absolute -left-1.5 w-3 h-3 rounded-full border-2',
            item.done?'bg-accent-green border-accent-green':'bg-surface-3 border-border-bright')}
            style={{top:`${i*2.2+0.3}rem`}}/>
          <div className="flex items-baseline gap-2">
            <span className={clsx('text-xs font-mono',item.done?'text-accent-green':'text-text-muted')}>{item.label}</span>
            {item.note&&<span className="text-xs text-text-muted">{item.note}</span>}
            {item.time&&<span className="text-xs text-text-muted ml-auto">{item.time.slice(11,19)}</span>}
          </div>
        </li>
      ))}
    </ol>
  )
}

export function DataTable<T>({cols,rows,rowKey}:{
  cols:Array<{key:keyof T|string;label:string;render?:(row:T)=>React.ReactNode;right?:boolean}>;
  rows:T[];rowKey:(row:T,i:number)=>string
}){
  return(
    <table className="w-full text-xs font-mono">
      <thead><tr className="border-b border-border">
        {cols.map(c=><th key={String(c.key)} className={clsx('pb-1.5 text-text-muted font-medium',c.right?'text-right':'text-left')}>{c.label}</th>)}
      </tr></thead>
      <tbody>
        <AnimatePresence initial={false}>
          {rows.map((row,i)=>(
            <motion.tr key={rowKey(row,i)} initial={{opacity:0,y:-4}} animate={{opacity:1,y:0}} exit={{opacity:0}}
              className="border-b border-border/50 hover:bg-surface-2 transition-colors">
              {cols.map(c=>(
                <td key={String(c.key)} className={clsx('py-1.5 pr-3',c.right&&'text-right')}>
                  {c.render?c.render(row):String((row as any)[c.key]??'—')}
                </td>
              ))}
            </motion.tr>
          ))}
        </AnimatePresence>
      </tbody>
    </table>
  )
}

export function Loading({text='Loading…'}:{text?:string}){
  return <div className="flex items-center justify-center h-full text-text-muted text-xs gap-2"><span className="animate-pulse">⟳</span>{text}</div>
}

export function Empty({text='No data yet'}:{text?:string}){
  return <div className="flex items-center justify-center h-full text-text-muted text-xs">{text}</div>
}

export const fmtPct=(v:number|null|undefined,d=4)=>v==null?'—':`${(v*100).toFixed(d)}%`
export const fmtPrice=(v:number|null|undefined)=>v==null?'—':v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})
export const fmtTime=(iso:string|null|undefined)=>iso?new Date(iso).toLocaleTimeString():'—'
export const timeAgo=(iso:string|null|undefined)=>{
  if(!iso)return'—'
  const s=Math.floor((Date.now()-new Date(iso).getTime())/1000)
  if(s<60)return`${s}s ago`;if(s<3600)return`${Math.floor(s/60)}m ago`;return`${Math.floor(s/3600)}h ago`
}

// ── New in V16: Suspense fallback ────────────────────────────────────────────

export function PageLoader() {
  return (
    <div className="h-screen flex items-center justify-center bg-surface">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-accent-blue/30 border-t-accent-blue rounded-full animate-spin" />
        <span className="text-xs text-text-muted font-mono tracking-wider">LOADING MODULE…</span>
      </div>
    </div>
  )
}

export function Skeleton({ className, lines = 1 }: { className?: string; lines?: number }) {
  return (
    <div className={`space-y-2 animate-pulse ${className ?? ''}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-2 bg-surface-3 rounded" style={{ width: `${70 + (i % 3) * 10}%` }} />
      ))}
    </div>
  )
}
