import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useMissions } from '@/stores'
import { Panel, Timeline, Empty } from '@/components/common'
import type { Mission, MissionStage } from '@/types/api'
import clsx from 'clsx'

const STAGES: MissionStage[]=['SIGNAL_FOUND','VALIDATION','RISK_CHECK','EXECUTION','MONITORING','CLOSED']
const STC: Record<MissionStage,string>={SIGNAL_FOUND:'text-accent-blue',VALIDATION:'text-accent-cyan',RISK_CHECK:'text-accent-gold',EXECUTION:'text-accent-orange',MONITORING:'text-accent-green',CLOSED:'text-text-muted'}
const STB: Record<MissionStage,string>={SIGNAL_FOUND:'bg-accent-blue/20 border-accent-blue/30',VALIDATION:'bg-accent-cyan/20 border-accent-cyan/30',RISK_CHECK:'bg-accent-gold/20 border-accent-gold/30',EXECUTION:'bg-accent-orange/20 border-accent-orange/30',MONITORING:'bg-accent-green/20 border-accent-green/30',CLOSED:'bg-surface-3 border-border'}

function MCard({m,selected,onClick}:{m:Mission;selected:boolean;onClick:()=>void}){
  const sIdx=STAGES.indexOf(m.stage)
  return(
    <motion.div layout onClick={onClick} className={clsx('panel p-3 cursor-pointer',selected&&'ring-1 ring-accent-blue')}>
      <div className="flex items-center justify-between mb-2">
        <span className={clsx('text-xs font-mono font-bold',m.direction==='LONG'?'text-accent-green':'text-accent-red')}>{m.direction==='LONG'?'▲':'▼'} {m.direction}</span>
        <span className={clsx('text-[10px] px-1.5 py-0.5 rounded border',STB[m.stage])}>{m.stage}</span>
      </div>
      <div className="flex gap-1">{STAGES.map((s,i)=><div key={s} className={clsx('flex-1 h-1 rounded-full',i<sIdx?'bg-accent-green':i===sIdx?'bg-accent-blue':'bg-surface-3')}/>)}</div>
      <div className="flex justify-between mt-1.5 text-[10px] text-text-muted">
        <span>conf: <span className="text-accent-gold">{m.confidence.toFixed(1)}%</span></span>
        <span>{new Date(m.updated_at).toLocaleTimeString()}</span>
      </div>
    </motion.div>
  )
}

export default function MissionBoard(){
  const{data}=useMissions(); const[selected,setSelected]=useState<string|null>(null)
  const missions=data?.missions??[]; const active=missions.filter(m=>m.stage!=='CLOSED')
  const closed=missions.filter(m=>m.stage==='CLOSED'); const selM=missions.find(m=>m.id===selected)
  const sc=STAGES.reduce((a,s)=>{a[s]=missions.filter(m=>m.stage===s).length;return a},{} as Record<string,number>)

  return(
    <div className="h-full grid grid-cols-12 gap-3 min-h-0">
      <div className="col-span-12">
        <div className="grid grid-cols-6 gap-2">
          {STAGES.map(s=>(
            <div key={s} className={clsx('panel p-2 text-center',sc[s]>0&&'ring-1 ring-border-bright')}>
              <div className={clsx('text-lg font-mono font-bold',STC[s])}>{sc[s]}</div>
              <div className="text-[9px] text-text-muted uppercase tracking-wider">{s.replace('_',' ')}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="col-span-12 md:col-span-5 xl:col-span-4 flex flex-col gap-2 overflow-auto">
        <Panel title={`Active (${active.length})`} icon="⊞" accent="text-accent-blue">
          {active.length===0?<Empty text="No active missions"/>:(
            <div className="space-y-2"><AnimatePresence>{active.map(m=><MCard key={m.id} m={m} selected={selected===m.id} onClick={()=>setSelected(selected===m.id?null:m.id)}/>)}</AnimatePresence></div>
          )}
        </Panel>
        {closed.length>0&&(
          <Panel title={`Closed (${closed.length})`} icon="✓" accent="text-text-muted">
            <div className="space-y-1">{closed.slice(0,10).map(m=>(
              <div key={m.id} className="flex justify-between text-xs py-1 border-b border-border/50">
                <span className={clsx('font-mono',m.direction==='LONG'?'text-accent-green':'text-accent-red')}>{m.direction}</span>
                <span className="text-text-muted">{m.id.slice(0,8)}</span>
                <span className="text-text-muted">{new Date(m.updated_at).toLocaleTimeString()}</span>
              </div>
            ))}</div>
          </Panel>
        )}
      </div>
      <div className="col-span-12 md:col-span-7 xl:col-span-8">
        <Panel title="Mission Detail" icon="◆" accent="text-accent-gold" className="h-full">
          {!selM?<Empty text="Select a mission to view lifecycle"/>:(
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2 text-xs">
                {[['ID',selM.id],['Symbol',selM.symbol],['Direction',selM.direction],['Stage',selM.stage],['Confidence',`${selM.confidence.toFixed(2)}%`],['Created',new Date(selM.created_at).toLocaleString()],['Updated',new Date(selM.updated_at).toLocaleString()]].map(([k,v])=>(
                  <div key={k} className="flex justify-between"><span className="text-text-muted">{k}</span>
                  <span className={clsx('font-mono',k==='Direction'?(v==='LONG'?'text-accent-green':'text-accent-red'):'text-text-primary')}>{v}</span></div>
                ))}
                {Object.keys(selM.meta).filter(k=>k!=='market_context_snapshot').map(k=>(
                  <div key={k} className="flex justify-between"><span className="text-text-muted">{k}</span>
                  <span className="font-mono text-text-secondary">{typeof selM.meta[k]==='number'?Number(selM.meta[k]).toLocaleString(undefined,{maximumFractionDigits:4}):String(selM.meta[k]??'—')}</span></div>
                ))}
              </div>
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider mb-2">Lifecycle</div>
                <Timeline items={selM.history.map(h=>({label:h.stage,note:h.note,time:h.timestamp,done:true}))}/>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}