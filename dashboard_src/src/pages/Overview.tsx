import { useDecision, useHealth, useMissions, useMarket, useEventLog } from '@/stores'
import { Panel, StatCard, ActionBadge, BreakdownBars, ConfBar, fmtTime } from '@/components/common'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'

const SEV: Record<string,string> = {critical:'text-accent-red',warning:'text-accent-gold',info:'text-text-secondary'}

function Row({label,value,color='text-text-primary'}:{label:string;value:string;color?:string}){
  return <div className="flex justify-between items-center"><span className="text-text-muted text-xs">{label}</span><span className={clsx('font-mono font-medium text-xs',color)}>{value}</span></div>
}

export default function Overview(){
  const dec=useDecision(s=>s.data); const health=useHealth(s=>s.data)
  const{data:missions}=useMissions(); const market=useMarket()
  const events=useEventLog(s=>s.events); const sig=dec?.signal
  const bd=sig?.confidence_breakdown??{}
  const bdRows=[
    {label:'SMC',value:bd.smc??0,max:30,color:'bg-accent-green'},
    {label:'Volume',value:bd.volume??0,max:20,color:'bg-accent-blue'},
    {label:'OI',value:bd.oi??0,max:20,color:'bg-accent-cyan'},
    {label:'Funding',value:bd.funding??0,max:10,color:'bg-accent-purple'},
    {label:'Regime',value:bd.regime??0,max:20,color:'bg-accent-gold'},
  ]
  const total=bdRows.reduce((s,r)=>s+r.value,0)
  const intel=market.intelligence; const fut=market.futures?.snapshot; const regime=market.regime?.current
  const activeMissions=missions?.missions?.filter(m=>m.stage!=='CLOSED').length??0

  return(
    <div className="h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard label="Action" value={sig?.action??'—'} icon="🎯"
          color={sig?.action==='LONG'?'text-accent-green':sig?.action==='SHORT'?'text-accent-red':'text-text-muted'}/>
        <StatCard label="Score" value={sig?`${sig.score}/9`:'—'} sub="confidence score" color="text-accent-gold"/>
        <StatCard label="Confidence" value={sig?`${sig.confidence.toFixed(1)}%`:'—'}
          color={sig&&sig.confidence>=70?'text-accent-green':'text-text-secondary'}/>
        <StatCard label="Regime" value={regime?.regime??'—'} sub={regime?`${(regime.confidence*100).toFixed(0)}% conf`:undefined}/>
        <StatCard label="Active Missions" value={activeMissions} color={activeMissions>0?'text-accent-blue':'text-text-muted'}/>
        <StatCard label="System" value={health?.overall_status??'—'}
          color={health?.overall_status==='ALIVE'?'text-accent-green':health?.overall_status==='DEGRADED'?'text-accent-gold':'text-accent-red'}/>
      </div>
      <div className="grid grid-cols-12 gap-3 min-h-0">
        <div className="col-span-12 md:col-span-5 xl:col-span-4">
          <Panel title="CEO Decision Engine" icon="◈" accent="text-accent-gold" className="h-full">
            {sig?(
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <ActionBadge action={sig.action}/>
                  <span className="text-xs text-text-muted">{fmtTime(dec?.timestamp)}</span>
                </div>
                <div>
                  <div className="flex justify-between mb-1.5"><span className="text-xs text-text-muted">Confidence</span><span className="text-xs font-mono text-accent-gold">{sig.confidence.toFixed(2)}%</span></div>
                  <ConfBar value={sig.confidence} color="bg-accent-gold"/>
                </div>
                <div><div className="text-xs text-text-muted mb-2">Score Breakdown ({total}/100)</div><BreakdownBars rows={bdRows}/></div>
                {sig.blocked&&(sig.block_reasons??[]).length>0&&(
                  <div className="bg-accent-red/10 border border-accent-red/30 rounded p-2">
                    <div className="text-xs text-accent-red font-bold mb-1">BLOCKED</div>
                    {(sig.block_reasons??[]).map((r,i)=><div key={i} className="text-xs text-accent-red/80">• {r}</div>)}
                  </div>
                )}
                <div className="grid grid-cols-3 gap-2">
                  {[['Entry',sig.entry_price??0],['SL',sig.stop_loss??0],['TP',sig.take_profit??0]].map(([l,v])=>(
                    <div key={l as string} className="bg-surface-2 rounded p-1.5 text-center">
                      <div className="text-[10px] text-text-muted">{l}</div>
                      <div className="text-xs font-mono font-bold">{(v as number)>0?`$${(v as number).toLocaleString(undefined,{maximumFractionDigits:0})}`:'—'}</div>
                    </div>
                  ))}
                </div>
                <span className={clsx('text-xs font-mono',sig.mtf_aligned?'text-accent-green':'text-text-muted')}>
                  {sig.mtf_aligned?'✓ MTF Aligned':'✗ MTF Diverged'}
                </span>
              </div>
            ):<div className="flex items-center justify-center h-full text-text-muted text-xs">No decision yet</div>}
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-3 xl:col-span-3">
          <Panel title="Market Intel" icon="◬" accent="text-accent-cyan" className="h-full">
            {intel?(
              <div className="space-y-2">
                <Row label="Funding" value={`${(intel.funding.rate*100).toFixed(4)}%`} color={intel.funding.extreme?'text-accent-red':'text-accent-green'}/>
                <Row label="OI Trend" value={intel.open_interest.trend}/>
                <Row label="OI Pressure" value={intel.open_interest.pressure}/>
                <Row label="Liquidations" value={intel.liquidations.detected?intel.liquidations.type:'None'} color={intel.liquidations.detected?'text-accent-red':'text-text-muted'}/>
                <Row label="Fear/Greed" value={intel.fear_greed.available?`${intel.fear_greed.value} · ${intel.fear_greed.classification}`:'N/A'}/>
                {fut&&<><div className="border-t border-border pt-2"/><Row label="Mark Price" value={(fut.mark_price??0)>0?`$${(fut.mark_price as number).toLocaleString(undefined,{maximumFractionDigits:0})}`:'—'}/><Row label="Signal" value={fut.futures_signal||'—'}/></>}
              </div>
            ):<div className="flex items-center justify-center h-full text-text-muted text-xs">No data</div>}
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-4 xl:col-span-5">
          <Panel title="Live Event Stream" icon="⚡" accent="text-accent-blue" className="h-full" noPad>
            <div className="p-2 overflow-auto h-full">
              {events.length===0?<div className="flex items-center justify-center h-full text-text-muted text-xs">Waiting for events…</div>:(
                <AnimatePresence initial={false}>
                  {events.slice(0,50).map((e,i)=>(
                    <motion.div key={`${e.seq??i}-${e.timestamp}`} initial={{opacity:0,x:-6}} animate={{opacity:1,x:0}}
                      className="terminal-line flex gap-2 py-0.5 border-b border-border/30">
                      <span className="text-text-muted w-20 shrink-0 tabular-nums">{e.timestamp.slice(11,19)}</span>
                      <span className="w-24 shrink-0 font-bold truncate" style={{color:e.agent==='RISK_MANAGER'?'#ef4444':e.agent==='CONFIDENCE_ENGINE'?'#fbbf24':'#3b82f6'}}>{e.agent.slice(0,12)}</span>
                      <span className={clsx('flex-1 truncate',SEV[e.severity]??'text-text-secondary')}>{e.event}: {e.message}</span>
                    </motion.div>
                  ))}
                </AnimatePresence>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}