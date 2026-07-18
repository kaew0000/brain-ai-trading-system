import { useMarket } from '@/stores'
import { Panel, StatCard, DataTable, Empty, ConfBar, fmtPrice } from '@/components/common'
import clsx from 'clsx'

function FGMeter({value}:{value:number|null}){
  if(value==null)return <span className="text-text-muted text-xs">Unavailable</span>
  const color=value<25?'bg-accent-red':value<45?'bg-accent-orange':value<55?'bg-accent-gold':value<75?'bg-accent-cyan':'bg-accent-green'
  const tc=color.replace('bg-','text-')
  const label=value<25?'Extreme Fear':value<45?'Fear':value<55?'Neutral':value<75?'Greed':'Extreme Greed'
  return(
    <div className="space-y-2">
      <div className="flex justify-between text-xs"><span className="text-text-muted">Fear / Greed</span><span className={clsx('font-mono font-bold',tc)}>{value} — {label}</span></div>
      <div className="h-3 bg-surface-3 rounded-full overflow-hidden"><div className={clsx('h-full rounded-full transition-all duration-700',color)} style={{width:`${value}%`}}/></div>
      <div className="flex justify-between text-[10px] text-text-muted"><span>0 · Fear</span><span>100 · Greed</span></div>
    </div>
  )
}

export default function Intelligence(){
  const intel=useMarket(s=>s.intelligence); const futures=useMarket(s=>s.futures)
  const regime=useMarket(s=>s.regime); const snap=futures?.snapshot
  const oiRows=(futures?.oi_history??[]).slice(0,30); const frRows=(futures?.funding_history??[]).slice(0,30)

  const hc=[
    {key:'timestamp',label:'Time',render:(r:any)=><span className="text-text-muted">{(r.timestamp??'').slice(11,19)}</span>},
    {key:'oi_delta',label:'OI Δ',right:true,render:(r:any)=><span className={clsx('tabular-nums',(r.oi_delta??0)>=0?'text-accent-green':'text-accent-red')}>{((r.oi_delta??0)*100).toFixed(4)}%</span>},
    {key:'mark_price',label:'Price',right:true,render:(r:any)=><span className="tabular-nums">${fmtPrice(r.mark_price)}</span>},
  ]
  const fc=[
    {key:'timestamp',label:'Time',render:(r:any)=><span className="text-text-muted">{(r.timestamp??'').slice(11,19)}</span>},
    {key:'funding_rate',label:'Rate',right:true,render:(r:any)=><span className={clsx('tabular-nums',Math.abs(r.funding_rate??0)>0.0005?'text-accent-red':'text-accent-green')}>{((r.funding_rate??0)*100).toFixed(4)}%</span>},
    {key:'mark_price',label:'Price',right:true,render:(r:any)=><span className="tabular-nums">${fmtPrice(r.mark_price)}</span>},
  ]

  return(
    <div className="h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard label="Funding Rate" value={intel?`${((intel.funding.rate??0)*100).toFixed(4)}%`:'—'} color={intel?.funding.extreme?'text-accent-red':'text-accent-green'} sub={intel?.funding.bias}/>
        <StatCard label="OI Delta" value={intel?`${((intel.open_interest.delta_pct??0)*100).toFixed(2)}%`:'—'} sub={intel?.open_interest.trend}/>
        <StatCard label="OI Pressure" value={intel?.open_interest.pressure??'—'}/>
        <StatCard label="Liquidations" value={intel?.liquidations.detected?intel.liquidations.type:'None'} color={intel?.liquidations.detected?'text-accent-red':'text-text-muted'}/>
        <StatCard label="Regime" value={regime?.current.regime??'—'} sub={regime?.current.trend_bias}/>
        <StatCard label="Mark Price" value={snap?`$${fmtPrice(snap.mark_price)}`:'—'} color="text-accent-gold"/>
      </div>
      <div className="grid grid-cols-12 gap-3 min-h-0">
        <div className="col-span-12 md:col-span-4 flex flex-col gap-3">
          <Panel title="Fear & Greed" icon="◬" accent="text-accent-cyan" className="flex-1">
            {intel?(
              <div className="space-y-4">
                <FGMeter value={intel.fear_greed.value}/>
                <div className="space-y-2 text-xs">
                  {[['Funding Bias',intel.funding.bias],['Funding Extreme',intel.funding.extreme?'YES':'No'],['OI Trend',intel.open_interest.trend],['OI Pressure',intel.open_interest.pressure],['Liquidation',intel.liquidations.detected?`${intel.liquidations.type} (${intel.liquidations.severity})`:'None']].map(([k,v])=>(
                    <div key={k} className="flex justify-between"><span className="text-text-muted">{k}</span><span className="font-mono text-text-secondary">{v}</span></div>
                  ))}
                </div>
              </div>
            ):<Empty/>}
          </Panel>
          <Panel title="Regime" icon="⬡" accent="text-accent-purple" className="flex-1">
            {regime?.current?(
              <div className="space-y-3">
                <div className="text-2xl font-mono font-bold text-accent-purple">{regime.current.regime}</div>
                <div>
                  <div className="flex justify-between text-xs mb-1"><span className="text-text-muted">Confidence</span><span className="text-accent-gold">{(regime.current.confidence*100).toFixed(1)}%</span></div>
                  <ConfBar value={regime.current.confidence*100} color="bg-accent-purple"/>
                </div>
                <div className="space-y-1.5 text-xs">
                  {[['Trend Bias',regime.current.trend_bias],['Trend Strength',regime.current.trend_strength],['History',String(regime.count)]].map(([k,v])=>(
                    <div key={k} className="flex justify-between"><span className="text-text-muted">{k}</span><span className="font-mono text-text-secondary">{v}</span></div>
                  ))}
                </div>
              </div>
            ):<Empty/>}
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-4">
          <Panel title="OI History" icon="▲" accent="text-accent-green" className="h-full" noPad>
            <div className="p-3 overflow-auto h-full">
              {oiRows.length===0?<Empty text="No OI data"/>:<DataTable cols={hc} rows={oiRows} rowKey={(_,i)=>String(i)}/>}
            </div>
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-4">
          <Panel title="Funding History" icon="◎" accent="text-accent-cyan" className="h-full" noPad>
            <div className="p-3 overflow-auto h-full">
              {frRows.length===0?<Empty text="No funding data"/>:<DataTable cols={fc} rows={frRows} rowKey={(_,i)=>String(i)}/>}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
