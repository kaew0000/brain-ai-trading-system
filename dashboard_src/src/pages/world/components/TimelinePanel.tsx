// dashboard_src/src/pages/world/components/TimelinePanel.tsx
import { useEffect, useState } from 'react'
import { worldApi } from '../api'
import type { TimelineStatus } from '../types'

export default function TimelinePanel() {
  const [status, setStatus] = useState<TimelineStatus | null>(null)

  const refresh = () => {
    worldApi.getTimeline().then(setStatus).catch(() => setStatus(null))
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [])

  const currentTick = status?.current?.tick.tickNumber ?? 0

  return (
    <div data-testid="timeline-panel" className="space-y-3 text-sm">
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="timeline-play"
          onClick={() => worldApi.timelinePlay().then(refresh)}
          className="rounded bg-slate-700 px-3 py-1.5 text-white hover:bg-slate-600"
        >
          Play
        </button>
        <button
          type="button"
          data-testid="timeline-pause"
          onClick={() => worldApi.timelinePause().then(refresh)}
          className="rounded bg-slate-700 px-3 py-1.5 text-white hover:bg-slate-600"
        >
          Pause
        </button>
        <button
          type="button"
          data-testid="timeline-resume"
          onClick={() => worldApi.timelineResume().then(refresh)}
          className="rounded bg-slate-700 px-3 py-1.5 text-white hover:bg-slate-600"
        >
          Resume
        </button>
      </div>
      <div className="text-slate-300">
        Tick <span className="font-mono">{currentTick}</span> · History length{' '}
        <span className="font-mono">{status?.length ?? 0}</span> ·{' '}
        {status?.isPlaying ? 'Playing' : 'Paused'}
      </div>
      <input
        type="range"
        min={0}
        max={Math.max(status?.length ?? 0 - 1, 0)}
        value={currentTick}
        data-testid="timeline-seek"
        onChange={(e) => worldApi.timelineSeek(Number(e.target.value)).then(refresh)}
        className="w-full"
      />
    </div>
  )
}
