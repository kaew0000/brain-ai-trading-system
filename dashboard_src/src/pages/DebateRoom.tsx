import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Panel, Empty, Loading } from '@/components/common'
import { api } from '@/lib/api'
import clsx from 'clsx'

const COLORS: Record<string,string>={CEO:'#fbbf24',SMC:'#10b981',FUTURES:'#06b6d4',VOLUME:'#3b82f6',REGIME:'#8b5cf6',RISK:'#ef4444',TRADER:'#f97316'}
function gc(a:string){const k=Object.keys(COLORS).find(k=>a.toUpperCase().includes(k));return k?COLORS[k]:'#94a3b8'}

export default function DebateRoom(){
  const[reasoning,setReasoning]=useState<any[]>([])
  const[graph,setGraph]=useState<any>(null)
  const[loading,setLoading]=useState(true)
  useEffect(()=>{
    const load=async()=>{
      try{const[r,g]=await Promise.all([api.reasoning(),api.agentGraph()]);setReasoning((r as any).reasoning??[]);setGraph(g)}catch{}
      setLoading(false)
    }
    load();const id=setInterval(load,8000);return()=>clearInterval(id)
  },[])
  const nodes=graph?.nodes??[]; const edges=graph?.edges??[]

  return(
    <div className="h-full grid grid-cols-12 gap-3 min-h-0">
      <div className="col-span-12 md:col-span-7">
        <Panel title="Agent Reasoning Stream" icon="⚡" accent="text-accent-blue" className="h-full" noPad>
          <div className="p-3 overflow-auto h-full">
            {loading?<Loading/>:reasoning.length===0?<Empty text="No reasoning entries yet"/>:(
              <AnimatePresence initial={false}>
                {reasoning.map((r:any,i:number)=>(
                  <motion.div key={i} initial={{opacity:0,y:-4}} animate={{opacity:1,y:0}}
                    className="mb-3 p-2.5 bg-surface-2 rounded-lg border-l-2" style={{borderColor:gc(r.agent??'')}}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold font-mono" style={{color:gc(r.agent??'')}}>{r.agent??'UNKNOWN'}</span>
                      <span className="text-[10px] text-text-muted">{(r.timestamp??'').slice(11,19)}</span>
                    </div>
                    <div className="text-xs text-text-secondary leading-relaxed">{r.thought}</div>
                    {r.confidence!=null&&<div className="mt-1 text-[10px] text-text-muted">conf: <span className="text-accent-gold">{r.confidence.toFixed(1)}%</span></div>}
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
          </div>
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-5">
        <Panel title="Agent Relationship Graph" icon="◉" accent="text-accent-gold" className="h-full">
          {loading?<Loading/>:nodes.length===0?<Empty text="No graph data"/>:(
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2">
                {nodes.map((n:any)=>(
                  <div key={n.id} className="flex items-center gap-2 p-2 bg-surface-2 rounded border border-border">
                    <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{backgroundColor:gc(n.id),boxShadow:`0 0 6px ${gc(n.id)}`}}/>
                    <div><div className="text-[10px] font-mono font-bold text-text-primary">{n.label||n.id}</div><div className="text-[9px] text-text-muted">{n.status??n.type}</div></div>
                  </div>
                ))}
              </div>
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider mb-2">Connections ({edges.length})</div>
                <div className="space-y-1.5">
                  {edges.slice(0,10).map((e:any,i:number)=>(
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="font-mono text-text-secondary w-20 truncate">{e.source}</span>
                      <span className="text-text-muted">→</span>
                      <span className="font-mono text-text-secondary flex-1 truncate">{e.target}</span>
                      <span className="text-accent-gold tabular-nums">{(e.weight??0).toFixed(2)}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 pt-2 border-t border-border text-xs text-text-muted">
                  Total weight: <span className="text-accent-gold">{graph?.weights_sum?.toFixed(2)??'—'}</span>
                </div>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}