import { useJournal, useMarket } from '@/stores'
import { Panel, StatCard, DataTable, Empty, fmtPrice, fmtTime } from '@/components/common'
import type { TradeRecord } from '@/types/api'
import clsx from 'clsx'

export default function Portfolio(){
  const journal=useJournal(s=>s.journal); const paper=useJournal(s=>s.paper)
  const signals=useMarket(s=>s.signals)
  const perf=journal?.performance; const open=journal?.open_trades??[]
  const paperEnabled = paper?.enabled === true
  const acct = paperEnabled ? paper?.metrics?.account : undefined

  const tc=[
    {key:'direction',label:'Dir',render:(r:TradeRecord)=><span className={r.direction==='LONG'?'text-accent-green':'text-accent-red'}>{r.direction==='LONG'?'▲':'▼'} {r.direction}</span>},
    {key:'entry_price',label:'Entry',right:true,render:(r:TradeRecord)=><span className="tabular-nums">${fmtPrice(r.entry_price)}</span>},
    {key:'quantity',label:'Qty',right:true,render:(r:TradeRecord)=><span className="tabular-nums">{r.quantity?.toFixed(4)}</span>},
    {key:'confidence',label:'Conf',right:true,render:(r:TradeRecord)=><span className="text-accent-gold">{r.confidence?.toFixed(1)}%</span>},
    {key:'result',label:'Result',render:(r:TradeRecord)=><span className={r.result==='WIN'?'text-accent-green':r.result==='LOSS'?'text-accent-red':'text-text-muted'}>{r.result||'OPEN'}</span>},
    {key:'pnl',label:'PnL',right:true,render:(r:TradeRecord)=><span className={clsx('tabular-nums',(r.pnl??0)>=0?'text-accent-green':'text-accent-red')}>{(r.pnl??0)>=0?'+':''}{fmtPrice(r.pnl??0)}</span>},
    {key:'timestamp',label:'Time',render:(r:TradeRecord)=><span className="text-text-muted">{fmtTime(r.timestamp)}</span>},
  ]
  const sc=[
    {key:'action',label:'Action',render:(s:any)=><span className={s.action==='LONG'?'text-accent-green':s.action==='SHORT'?'text-accent-red':'text-text-muted'}>{s.action}</span>},
    {key:'confidence',label:'Conf',right:true,render:(s:any)=><span className="text-accent-gold">{s.confidence?.toFixed(1)}%</span>},
    {key:'regime',label:'Regime'},
    {key:'entry_price',label:'Price',right:true,render:(s:any)=><span className="tabular-nums">${fmtPrice(s.entry_price)}</span>},
    {key:'timestamp',label:'Time',render:(s:any)=><span className="text-text-muted">{fmtTime(s.timestamp)}</span>},
  ]

  return(
    <div className="h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard label="Balance" icon="◎" value={acct?`$${fmtPrice(acct.balance)}`:(perf?`${perf.total_trades} trades`:'—')} color="text-accent-gold"/>
        <StatCard label="Day PnL" value={acct?`$${fmtPrice(acct.day_pnl)}`:'—'} color={(acct?.day_pnl??0)>=0?'text-accent-green':'text-accent-red'}/>
        <StatCard label="Win Rate" value={acct?.win_rate!=null?`${(acct.win_rate*100).toFixed(1)}%`:(perf?.win_rate!=null?`${(perf.win_rate*100).toFixed(1)}%`:'—')}/>
        <StatCard label="Total PnL" value={acct?`$${fmtPrice(acct.total_pnl)}`:'—'} color={(acct?.total_pnl??0)>=0?'text-accent-green':'text-accent-red'}/>
        <StatCard label="Open Trades" value={open.length} color="text-accent-blue"/>
        <StatCard label="Signals" value={signals?.count??'—'}/>
      </div>
      <div className="grid grid-cols-12 gap-3 min-h-0">
        <div className="col-span-12 xl:col-span-5 flex flex-col gap-3">
          <Panel title="Open Positions" icon="▷" accent="text-accent-green" className="flex-1" noPad>
            <div className="p-3 overflow-auto">
              {open.length===0?<Empty text="No open positions"/>:<DataTable cols={tc} rows={open} rowKey={r=>String(r.id)}/>}
            </div>
          </Panel>
          {acct?(
            <Panel title="Account Metrics" icon="◎" accent="text-accent-gold">
              <div className="space-y-2">
                {[['Balance',`$${fmtPrice(acct.balance)}`],['Equity',`$${fmtPrice(acct.equity)}`],['Day PnL%',`${(acct.day_pnl_pct*100).toFixed(2)}%`]].map(([k,v])=>(
                  <div key={k} className="flex justify-between text-xs"><span className="text-text-muted">{k}</span><span className="font-mono">{v}</span></div>
                ))}
              </div>
            </Panel>
          ):paper&&!paperEnabled&&(
            <Panel title="Account Metrics" icon="◎" accent="text-text-muted">
              <Empty text={`Paper Trading Disabled${paper.reason?` — ${paper.reason}`:''}`}/>
            </Panel>
          )}
        </div>
        <div className="col-span-12 xl:col-span-7">
          <Panel title={`Signal History (${signals?.count??0})`} icon="◈" accent="text-accent-blue" className="h-full" noPad>
            <div className="p-3 overflow-auto h-full">
              {!signals?.signals?.length?<Empty text="No signal history"/>:<DataTable cols={sc} rows={signals.signals} rowKey={r=>String(r.id)}/>}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
