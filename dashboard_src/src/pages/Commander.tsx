import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useCommander } from '@/stores'
import { Panel, Empty } from '@/components/common'
import { api } from '@/lib/api'
import clsx from 'clsx'

const CMDS=[
  {cmd:'status',label:'System Status',desc:'Get current bot status'},
  {cmd:'pause',label:'Pause Trading',desc:'Pause the trading loop'},
  {cmd:'resume',label:'Resume Trading',desc:'Resume the trading loop'},
  {cmd:'paper',label:'Force Paper Mode',desc:'Enable paper-only safety override'},
  {cmd:'retrain',label:'Trigger Retrain',desc:'Run nightly ML retrain now'},
  {cmd:'reconcile',label:'Reconcile',desc:'Run position reconciliation now'},
]

export default function Commander(){
  const{state,chatHistory,setState,addMessage}=useCommander()
  const[input,setInput]=useState('')
  const[sending,setSending]=useState(false)
  const[cmdSent,setCmdSent]=useState<string|null>(null)
  const endRef=useRef<HTMLDivElement>(null)

  useEffect(()=>{endRef.current?.scrollIntoView({behavior:'smooth'})},[chatHistory])

  const sendChat=async()=>{
    const msg=input.trim();if(!msg||sending)return
    setInput('');setSending(true);addMessage('user',msg)
    try{const res:any=await api.chat(msg);addMessage('assistant',res?.reply??res?.message??JSON.stringify(res))}
    catch(e){addMessage('assistant',`[Error: ${String(e)}]`)}
    setSending(false)
  }

  const sendCmd=async(cmd:string)=>{
    setCmdSent(cmd)
    try{const res:any=await api.sendCommand(cmd);if(res?.state)setState(res.state);addMessage('assistant',`Command '${cmd}' → ${JSON.stringify(res?.message??res)}`)}
    catch(e){addMessage('assistant',`[Error: ${String(e)}]`)}
    setCmdSent(null)
  }

  return(
    <div className="h-full grid grid-cols-12 gap-3 min-h-0">
      <div className="col-span-12 md:col-span-3 flex flex-col gap-3">
        <Panel title="Command Center" icon="⌘" accent="text-accent-gold" className="flex-1">
          <div className="space-y-2">
            {CMDS.map(c=>(
              <button key={c.cmd} onClick={()=>sendCmd(c.cmd)} disabled={cmdSent===c.cmd}
                className={clsx('w-full text-left p-2.5 rounded border transition-all text-xs font-mono',
                  cmdSent===c.cmd?'bg-accent-blue/20 border-accent-blue/50 text-accent-blue animate-pulse':'bg-surface-2 border-border hover:border-border-bright hover:bg-surface-3 text-text-secondary')}>
                <div className="font-bold text-text-primary">{c.label}</div>
                <div className="text-text-muted text-[10px] mt-0.5">{c.desc}</div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Control State" icon="◈" accent="text-accent-cyan">
          {!state?<Empty text="No state data"/>:(
            <div className="space-y-2 text-xs">
              <div className="flex justify-between"><span className="text-text-muted">Trading</span><span className={state.paused?'text-accent-red':'text-accent-green'}>{state.paused?'⏸ PAUSED':'▶ ACTIVE'}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Paper Override</span><span className={state.paper_mode_forced?'text-accent-gold':'text-text-muted'}>{state.paper_mode_forced?'✓ ON':'✗ OFF'}</span></div>
              {state.updated_at&&<div className="flex justify-between"><span className="text-text-muted">Updated</span><span className="font-mono text-text-secondary">{state.updated_at.slice(11,19)}</span></div>}
            </div>
          )}
        </Panel>
      </div>
      <div className="col-span-12 md:col-span-9">
        <Panel title="AI Commander Chat" icon="⚡" accent="text-accent-blue" className="h-full" noPad>
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-auto p-3 space-y-2">
              {chatHistory.length===0?(
                <div className="flex items-center justify-center h-full text-text-muted text-xs">
                  <div className="text-center"><div className="text-3xl mb-2">⌘</div><div>Ask the AI Commander anything about the trading system</div><div className="mt-1 text-text-muted opacity-60">e.g. "What is the current regime?" · "Why did the bot wait?"</div></div>
                </div>
              ):(
                <AnimatePresence initial={false}>
                  {chatHistory.map((m,i)=>(
                    <motion.div key={i} initial={{opacity:0,y:4}} animate={{opacity:1,y:0}} className={clsx('flex',m.role==='user'?'justify-end':'justify-start')}>
                      <div className={clsx('max-w-[80%] px-3 py-2 rounded-lg text-xs font-mono',m.role==='user'?'bg-accent-blue/20 text-accent-blue border border-accent-blue/30 ml-8':'bg-surface-2 text-text-primary border border-border mr-8')}>
                        <div className="text-[10px] text-text-muted mb-1">{m.role==='user'?'You':'⌘ Commander'} · {m.ts.slice(11,19)}</div>
                        <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              )}
              <div ref={endRef}/>
            </div>
            <div className="border-t border-border p-3 flex gap-2">
              <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==='Enter'&&!e.shiftKey&&sendChat()}
                placeholder="Ask the Commander… (Enter to send)"
                className="flex-1 bg-surface-2 border border-border rounded px-3 py-2 text-xs font-mono text-text-primary placeholder:text-text-muted outline-none focus:border-accent-blue transition-colors"/>
              <button onClick={sendChat} disabled={sending||!input.trim()}
                className={clsx('px-4 py-2 rounded text-xs font-mono font-bold transition-all',sending||!input.trim()?'bg-surface-3 text-text-muted cursor-not-allowed':'bg-accent-blue/20 text-accent-blue border border-accent-blue/50 hover:bg-accent-blue/30')}>
                {sending?'…':'Send'}
              </button>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  )
}
