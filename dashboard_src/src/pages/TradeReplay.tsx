import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Panel, Empty, Loading, fmtPrice, fmtTime } from '@/components/common'
import { api } from '@/lib/api'
import clsx from 'clsx'

export default function TradeReplay(){
  const[journal,setJournal]=useState<any>(null)
  const[forward,setForward]=useState<any>(null)
  const[loading,setLoading]=useState(true)
  const[selected,setSelected]=useState<any>(null)

  useEffect(()=>{
    const load=async()=>{
      try{const[j,f]=await Promise.all([api.journal(),api.forwardTest().catch(()=>null)]);setJournal(j);setForward(f)}catch{}
      setLoading(false)
    }
    load();const id=setInterval(load,15000);return()=>clearInterval(id)
  },[])

  const openTrades=(journal as any)?.open_trades??[]
  const perf=(journal as any)?.performance??{}
  const fwdData=(forward as any)??{}

  return(
    <div className="h-full grid grid-cols-12 gap-3 min-h-0">
      <div className="col-span-12 md:col-span-4">
        <Panel title="Open Trades" icon="▷" accent="text-accent-green" className="h-full" noPad>
          <div className="p-2 overflow-auto h-full">
            {loading?<Loading/>:openTrades.length===0?<Empty text="No open trades"/>:(
              <div className="space-y-2">
                <AnimatePresence>
                  {openTrades.map((t:any)=>(
                    <motion.div key={t.id} layout initial={{opacity:0}} animate={{opacity:1}}
                      onClick={()=>setSelected(selected?.id===t.id?null:t)}
                      className={clsx('bg-surface-2 rounded-lg p-2.5 cursor-pointer border transition-all',selected?.id===t.id?'border-accent-blue':'border-border hover:border-border-bright')}>
                      <div className="flex justify-between mb-1.5">
                        <span className={clsx('text-xs font-mono font-bold',t.direction==='LONG'?'text-accent-green':'text-accent-red')}>{t.direction==='LONG'?'▲':'▼'} {t.direction}</span>
                        <span className="text-[10px] text-text-muted">#{t.id}</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1 text-[10px]">
                        <div><div className="text-text-muted">Entry</div><div className="font-mono">${fmtPrice(t.entry_price)}</div></div>
                        <div><div className="text-text-muted">SL</div><div className="font-mono text-accent-red">${fmtPrice(t.stop_loss)}</div></div>
                        <div><div className="text-text-muted">TP</div><div className="font-mono text-accent-green">${fmtPrice(t.take_profit)}</div></div>
                      </div>
                      <div className="flex justify-between mt-1.5 text-[10px]">
                        <span className="text-text-muted">Qty: <span className="text-text-secondary">{t.quantity?.toFixed(4)}</span></span>
                        <span className="text-text-muted">{fmtTime(t.timestamp)}</span>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            )}
          </div>
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-5 flex flex-col gap-3">
        <Panel title="Trade Replay" icon="◈" accent="text-accent-gold" className="flex-1">
          {!selected?<Empty text="Select a trade to replay its lifecycle"/>:(
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className={clsx('text-xl font-mono font-bold',selected.direction==='LONG'?'text-accent-green':'text-accent-red')}>{selected.direction}</span>
                <span className="text-xs text-text-muted">Trade #{selected.id}</span>
              </div>
              <div className="relative bg-surface-2 rounded p-3">
                <div className="text-[10px] text-text-muted mb-2">Price Levels</div>
                {[{label:'Take Profit',price:selected.take_profit,color:'bg-accent-green',tc:'text-accent-green'},{label:'Entry',price:selected.entry_price,color:'bg-accent-gold',tc:'text-accent-gold'},{label:'Stop Loss',price:selected.stop_loss,color:'bg-accent-red',tc:'text-accent-red'}].map(l=>(
                  <div key={l.label} className="flex items-center gap-2 mb-2">
                    <div className={clsx('w-2 h-2 rounded-full',l.color)}/>
                    <span className="text-xs text-text-muted w-24">{l.label}</span>
                    <div className="flex-1 h-px bg-border"/>
                    <span className={clsx('text-xs font-mono font-bold',l.tc)}>${fmtPrice(l.price)}</span>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {[['RR Ratio',selected.take_profit&&selected.stop_loss&&selected.entry_price?((selected.take_profit-selected.entry_price)/(selected.entry_price-selected.stop_loss)).toFixed(2)+':1':'—'],['Confidence',selected.confidence!=null?`${selected.confidence.toFixed(1)}%`:'—'],['Regime',selected.regime??'—'],['Status',selected.result||'OPEN']].map(([k,v])=>(
                  <div key={k} className="bg-surface-2 rounded p-2"><div className="text-text-muted text-[10px]">{k}</div><div className="font-mono text-text-primary">{v}</div></div>
                ))}
              </div>
            </div>
          )}
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-3">
        <Panel title="Forward Test" icon="◎" accent="text-accent-purple" className="h-full">
          {loading?<Loading/>:!fwdData||Object.keys(fwdData).length===0?<Empty text="No forward test data"/>:(
            <div className="space-y-2 text-xs">
              {Object.entries(fwdData).filter(([k])=>k!=='timestamp').map(([k,v])=>(
                <div key={k} className="flex justify-between"><span className="text-text-muted capitalize">{k.replace(/_/g,' ')}</span><span className="font-mono text-text-secondary">{typeof v==='number'?(v as number).toFixed(4):String(v)}</span></div>
              ))}
            </div>
          )}
          {perf&&(
            <div className="mt-3 pt-3 border-t border-border space-y-2 text-xs">
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Performance</div>
              <div className="flex justify-between"><span className="text-text-muted">Total Trades</span><span className="font-mono">{perf.total_trades??'—'}</span></div>
              {perf.win_rate!=null&&<div className="flex justify-between"><span className="text-text-muted">Win Rate</span><span className="font-mono text-accent-green">{(perf.win_rate*100).toFixed(1)}%</span></div>}
              {perf.profit_factor!=null&&<div className="flex justify-between"><span className="text-text-muted">Profit Factor</span><span className="font-mono text-accent-gold">{perf.profit_factor.toFixed(2)}</span></div>}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
