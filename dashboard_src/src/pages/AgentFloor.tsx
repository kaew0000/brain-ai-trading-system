import { useState } from 'react'
import { motion } from 'framer-motion'
import { useAgents } from '@/stores'
import { Panel, ConfBar, Empty, fmtTime, timeAgo } from '@/components/common'
import clsx from 'clsx'

const AC: Record<string,string>={CEO:'text-accent-gold',SMC:'text-accent-green',FUTURES:'text-accent-cyan',VOLUME:'text-accent-blue',REGIME:'text-accent-purple',RISK:'text-accent-red',TRADER:'text-accent-orange'}
const AI: Record<string,string>={CEO:'◈',SMC:'◆',FUTURES:'◎',VOLUME:'▲',REGIME:'⬡',RISK:'⊗',TRADER:'▷'}

function AgentCard({name,agent,selected,onClick}:{name:string;agent:any;selected:boolean;onClick:()=>void}){
  const ck=Object.keys(AC).find(k=>name.toUpperCase().includes(k))??'CEO'
  const color=AC[ck]; const icon=AI[ck]??'◉'; const conf=agent?.confidence??0
  return(
    <motion.div layout onClick={onClick} whileHover={{scale:1.01}}
      className={clsx('panel cursor-pointer p-3 space-y-2',selected&&'ring-1 ring-accent-blue')}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={clsx('text-lg',color)}>{icon}</span>
          <div><div className={clsx('text-xs font-mono font-bold',color)}>{name}</div><div className="text-[10px] text-text-muted">{agent?.role??'Agent'}</div></div>
        </div>
        <span className={clsx('text-[10px] px-1.5 py-0.5 rounded border',agent?.status==='active'?'text-accent-green border-accent-green/30 bg-accent-green/10':'text-text-muted border-border bg-surface-3')}>
          {agent?.status??'idle'}
        </span>
      </div>
      {conf>0&&<div><div className="flex justify-between text-[10px] text-text-muted mb-1"><span>Confidence</span><span>{conf.toFixed(1)}%</span></div><ConfBar value={conf} color={color.replace('text-','bg-')}/></div>}
      {agent?.last_action&&<div className="text-[10px] text-text-muted truncate">↳ {agent.last_action}</div>}
      {agent?.last_updated&&<div className="text-[10px] text-text-muted">{timeAgo(agent.last_updated)}</div>}
    </motion.div>
  )
}

export default function AgentFloor(){
  const agentsData=useAgents(s=>s.agents); const telData=useAgents(s=>s.telemetry)
  const[selected,setSelected]=useState<string|null>(null)
  const agents=agentsData?.agents??{}; const names=Object.keys(agents)
  const selAgent=selected?agents[selected]:null
  const selTel=selected?(telData?.telemetry?.[selected]??[]):[]

  return(
    <div className="h-full grid grid-cols-12 gap-3 min-h-0">
      <div className="col-span-12 md:col-span-8">
        <Panel title={`Agent Operations Floor — ${names.length} Agents`} icon="◉" accent="text-accent-blue" className="h-full">
          {names.length===0?<Empty text="No agent data — bot not running"/>:(
            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
              {names.map(name=><AgentCard key={name} name={name} agent={agents[name]} selected={selected===name} onClick={()=>setSelected(selected===name?null:name)}/>)}
            </div>
          )}
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-4 flex flex-col gap-3">
        <Panel title="Agent Detail" icon="◆" accent="text-accent-gold" className="flex-1">
          {!selected?<Empty text="Click an agent to inspect"/>:selAgent?(
            <div className="space-y-3">
              <div className="space-y-2 text-xs">
                {[['Name',selected],['Role',selAgent.role??'—'],['Status',selAgent.status??'—'],['Conf',selAgent.confidence!=null?`${selAgent.confidence.toFixed(2)}%`:'—'],['Updated',fmtTime(selAgent.last_updated)]].map(([k,v])=>(
                  <div key={k} className="flex justify-between"><span className="text-text-muted">{k}</span><span className="font-mono text-text-primary">{v}</span></div>
                ))}
              </div>
              {selAgent.signals&&Object.keys(selAgent.signals).length>0&&(
                <pre className="text-[10px] text-text-secondary bg-surface-2 rounded p-2 overflow-auto max-h-32">{JSON.stringify(selAgent.signals,null,2)}</pre>
              )}
            </div>
          ):null}
        </Panel>
        <Panel title="Telemetry" icon="⚡" accent="text-accent-cyan" className="flex-1" noPad>
          <div className="overflow-auto max-h-52 p-2">
            {selTel.length===0?<Empty text={selected?'No telemetry':'Select an agent'}/>:(
              <div className="space-y-1">
                {(selTel as any[]).slice(0,30).map((t,i)=>(
                  <div key={i} className="terminal-line flex gap-2">
                    <span className="text-text-muted w-16 shrink-0">{(t.timestamp??'').slice(11,19)}</span>
                    <span className="text-accent-blue flex-1 truncate">{t.action}</span>
                    {t.duration_ms!=null&&<span className="text-text-muted">{t.duration_ms}ms</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}