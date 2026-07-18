import { useHealth, useML } from '@/stores'
import { Panel, StatCard, DataTable, Empty, ConfBar } from '@/components/common'
import clsx from 'clsx'

function SRow({name,s}:{name:string;s:any}){
  const sc=s.status==='ALIVE'?'text-accent-green':s.status==='STALE'?'text-accent-gold':'text-accent-red'
  const dc=s.status==='ALIVE'?'bg-accent-green shadow-[0_0_6px_rgba(16,185,129,0.8)]':s.status==='STALE'?'bg-accent-gold shadow-[0_0_6px_rgba(251,191,36,0.8)]':'bg-accent-red shadow-[0_0_6px_rgba(239,68,68,0.8)]'
  return(
    <div className="flex items-center gap-3 py-2 border-b border-border/50 last:border-0">
      <div className={clsx('w-2 h-2 rounded-full shrink-0',dc)}/>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-mono text-text-primary">{name.replace(/_/g,' ')}</div>
        <div className="text-[10px] text-text-muted">{s.last_beat?`Last: ${new Date(s.last_beat).toLocaleTimeString()}`:'Never beaten'}{s.age_s!=null&&` · ${s.age_s.toFixed(0)}s ago`}</div>
      </div>
      <div className="text-right shrink-0"><div className={clsx('text-xs font-mono font-bold',sc)}>{s.status}</div><div className="text-[10px] text-text-muted">/{s.interval_s}s</div></div>
    </div>
  )
}

export default function SystemHealth(){
  const hd=useHealth(s=>s.data); const rd=useHealth(s=>s.recon)
  const mlp=useML(s=>s.performance); const mls=useML(s=>s.status)
  const sub=hd?.subsystems??{}; const overall=hd?.overall_status??'UNKNOWN'
  const alive=Object.values(sub).filter((s:any)=>s.status==='ALIVE').length
  const dead=Object.values(sub).filter((s:any)=>s.status==='DEAD').length
  const stale=Object.values(sub).filter((s:any)=>s.status==='STALE').length
  const ev=rd?.events??[]; const rl=rd?.recovery_log??[]; const rs=rd?.status

  const ec=[
    {key:'timestamp',label:'Time',render:(r:any)=><span className="text-text-muted">{r.timestamp.slice(11,19)}</span>},
    {key:'mismatch_type',label:'Type',render:(r:any)=><span className="font-mono text-accent-red text-[10px]">{r.mismatch_type}</span>},
    {key:'severity',label:'Sev',render:(r:any)=><span className={r.severity==='critical'?'text-accent-red':r.severity==='warning'?'text-accent-gold':'text-text-muted'}>{r.severity}</span>},
    {key:'recovery_result',label:'Recovery',render:(r:any)=><span className="text-text-muted text-[10px] truncate max-w-[100px] block">{r.recovery_result??'—'}</span>},
  ]
  const rc=[
    {key:'timestamp',label:'Time',render:(r:any)=><span className="text-text-muted">{r.timestamp.slice(11,19)}</span>},
    {key:'action',label:'Action',render:(r:any)=><span className="text-accent-cyan">{r.action}</span>},
    {key:'result',label:'Result',render:(r:any)=><span className={r.result==='ok'?'text-accent-green':r.result.startsWith('skip')?'text-text-muted':'text-accent-red'}>{r.result}</span>},
  ]

  return(
    <div className="h-full grid grid-rows-[auto_1fr] gap-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-3">
        <StatCard label="Overall" value={overall} color={overall==='ALIVE'?'text-accent-green':overall==='DEGRADED'?'text-accent-gold':'text-accent-red'}/>
        <StatCard label="Alive" value={alive} color="text-accent-green" icon="♥"/>
        <StatCard label="Stale" value={stale} color="text-accent-gold"/>
        <StatCard label="Dead" value={dead} color="text-accent-red"/>
        <StatCard label="Recon Events" value={ev.length} color={ev.length>0?'text-accent-red':'text-text-muted'}/>
        <StatCard label="ML Meta Label" value={mls?.meta_label_active?'ACTIVE':'NONE'} color={mls?.meta_label_active?'text-accent-green':'text-text-muted'}/>
        <StatCard label="Dataset Rows" value={mlp?.dataset?.labelled_rows??'—'} sub={`/ ${mlp?.dataset?.total_rows??'—'} total`}/>
      </div>
      <div className="grid grid-cols-12 gap-3 min-h-0">
        <div className="col-span-12 md:col-span-3">
          <Panel title="Subsystem Watchdog" icon="♥" accent="text-accent-green" className="h-full" noPad>
            <div className="p-3 overflow-auto h-full">
              {Object.keys(sub).length===0?<Empty text="No heartbeat data — bot not running"/>:Object.entries(sub).map(([n,s])=><SRow key={n} name={n} s={s}/>)}
            </div>
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-6 flex flex-col gap-3">
          <Panel title={`Reconciliation Events (${ev.length})`} icon="◈" accent="text-accent-red" className="flex-1" noPad>
            <div className="p-3 overflow-auto h-full">
              {rs&&<div className="mb-2 p-2 bg-surface-2 rounded text-xs flex gap-4"><span className="text-text-muted">Last run: <span className="text-text-secondary">{rs.last_run?rs.last_run.slice(11,19):'Never'}</span></span><span className={rs.last_result==='OK'?'text-accent-green':'text-accent-red'}>{rs.last_result??'—'}</span>{rs.suppressed_repeat_count>0&&<span className="text-text-muted">Repeats suppressed: <span className="text-accent-gold">{rs.suppressed_repeat_count}</span></span>}</div>}
              {ev.length===0?<Empty text="No reconciliation events — all positions agree ✓"/>:<DataTable cols={ec} rows={ev} rowKey={r=>r.id}/>}
            </div>
          </Panel>
          <Panel title={`Recovery Log (${rl.length})`} icon="◎" accent="text-accent-cyan" className="flex-1" noPad>
            <div className="p-3 overflow-auto h-full">
              {rl.length===0?<Empty text="No recovery actions"/>:<DataTable cols={rc} rows={rl} rowKey={(_,i)=>String(i)}/>}
            </div>
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-3 flex flex-col gap-3">
          <Panel title="ML Advisor" icon="⬡" accent="text-accent-purple" className="flex-1">
            {!mls?<Empty text="No ML data"/>:(
              <div className="space-y-3">
                {[{label:'Meta Label',active:mls.meta_label_active},{label:'Calibrator',active:mls.calibrator_active},{label:'Outcome Pred',active:mls.outcome_predictor_active}].map(m=>(
                  <div key={m.label} className="flex items-center justify-between text-xs"><span className="text-text-muted">{m.label}</span><span className={m.active?'text-accent-green':'text-text-muted'}>{m.active?'● ACTIVE':'○ NONE'}</span></div>
                ))}
                {mls.last_prediction&&(
                  <div className="mt-2 pt-2 border-t border-border space-y-1.5 text-xs">
                    <div className="text-[10px] text-text-muted uppercase tracking-wider">Last Prediction</div>
                    <div className="flex justify-between"><span className="text-text-muted">Label</span><span className={mls.last_prediction.label==='TRADE'?'text-accent-green':'text-accent-red'}>{mls.last_prediction.label}</span></div>
                    <div className="flex justify-between"><span className="text-text-muted">Raw</span><span className="font-mono">{mls.last_prediction.raw_confidence.toFixed(1)}%</span></div>
                    <div className="flex justify-between"><span className="text-text-muted">Cal</span><span className="font-mono text-accent-gold">{mls.last_prediction.calibrated_confidence.toFixed(1)}%</span></div>
                    <div>
                      <div className="flex justify-between mb-1"><span className="text-text-muted">Outcome</span><span className="font-mono">{mls.last_prediction.outcome_probability.toFixed(1)}%</span></div>
                      <ConfBar value={mls.last_prediction.outcome_probability} color="bg-accent-purple"/>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Panel>
          <Panel title="ML Performance" icon="◆" accent="text-accent-gold">
            {!mlp?<Empty text="No ML data"/>:(
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-surface-2 rounded p-2 text-center"><div className="text-text-muted text-[10px]">Total</div><div className="text-accent-blue font-mono font-bold">{mlp.dataset?.total_rows??0}</div></div>
                  <div className="bg-surface-2 rounded p-2 text-center"><div className="text-text-muted text-[10px]">Labelled</div><div className="text-accent-green font-mono font-bold">{mlp.dataset?.labelled_rows??0}</div></div>
                </div>
                {mlp.active_models?.meta_label&&(
                  <div className="space-y-1 text-xs pt-1">
                    <div className="text-[10px] text-text-muted uppercase">Active Meta-Label</div>
                    {[['Win Rate',`${(mlp.active_models.meta_label.win_rate*100).toFixed(1)}%`],['PF',mlp.active_models.meta_label.profit_factor.toFixed(2)],['Rows',String(mlp.active_models.meta_label.training_rows)]].map(([k,v])=>(
                      <div key={k} className="flex justify-between"><span className="text-text-muted">{k}</span><span className="font-mono text-text-secondary">{v}</span></div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}
