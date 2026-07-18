import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Panel, Empty, Loading } from '@/components/common'
import { api } from '@/lib/api'
import clsx from 'clsx'

const AGENTS=['CEO','SMC_ANALYST','FUTURES_ANALYST','RISK_MANAGER','TRADER']

export default function Memory(){
  const[selected,setSelected]=useState(AGENTS[0])
  const[memory,setMemory]=useState<any>(null)
  const[journal,setJournal]=useState<any>(null)
  const[loading,setLoading]=useState(false)

  useEffect(()=>{
    const load=async()=>{
      setLoading(true)
      try{const[m,j]=await Promise.all([api.agentMemory(selected).catch(()=>null),api.journal()]);setMemory(m);setJournal(j)}catch{}
      setLoading(false)
    }
    load()
  },[selected])

  const explanations=(journal as any)?.explanations??[]
  const agentMsgs=(journal as any)?.agent_messages??[]

  return(
    <div className="h-full grid grid-cols-12 gap-3 min-h-0">
      <div className="col-span-12 md:col-span-2">
        <Panel title="Agents" icon="⬡" accent="text-accent-purple" className="h-full">
          <div className="space-y-1">
            {AGENTS.map(a=>(
              <button key={a} onClick={()=>setSelected(a)}
                className={clsx('w-full text-left px-2 py-1.5 rounded text-xs font-mono transition-all',
                  selected===a?'bg-accent-purple/20 text-accent-purple border border-accent-purple/30':'text-text-secondary hover:bg-surface-2')}>
                {a.replace('_',' ')}
              </button>
            ))}
          </div>
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Panel title={`${selected} Memory`} icon="◉" accent="text-accent-gold" className="h-full">
          {loading?<Loading/>:!memory?<Empty text="No memory data for this agent"/>:(
            <pre className="text-xs font-mono text-text-secondary whitespace-pre-wrap overflow-auto max-h-full">{JSON.stringify(memory,null,2)}</pre>
          )}
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-4 flex flex-col gap-3">
        <Panel title="AI Explanations" icon="◆" accent="text-accent-cyan" className="flex-1 overflow-auto">
          {explanations.length===0?<Empty text="No explanations yet"/>:(
            <div className="space-y-2">
              {explanations.slice(0,20).map((e:any,i:number)=>(
                <motion.div key={i} initial={{opacity:0}} animate={{opacity:1}} className="bg-surface-2 rounded p-2 text-xs">
                  <div className="flex justify-between mb-1">
                    <span className="text-accent-cyan font-mono">{e.action??'—'}</span>
                    <span className="text-text-muted">{(e.timestamp??'').slice(11,19)}</span>
                  </div>
                  {e.summary&&<div className="text-text-secondary">{e.summary}</div>}
                </motion.div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Agent Messages" icon="⚡" accent="text-accent-blue" className="flex-1 overflow-auto" noPad>
          <div className="p-2 space-y-0">
            {agentMsgs.length===0?<Empty text="No agent messages"/>:(
              agentMsgs.slice(0,30).map((m:any,i:number)=>(
                <div key={i} className="terminal-line flex gap-2 py-0.5 border-b border-border/30">
                  <span className="text-text-muted w-16 shrink-0">{(m.timestamp??'').slice(11,19)}</span>
                  <span className="text-accent-blue w-20 shrink-0 truncate">{m.agent}</span>
                  <span className="text-text-secondary flex-1 truncate">{m.message}</span>
                </div>
              ))
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}
