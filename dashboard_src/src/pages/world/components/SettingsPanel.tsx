// dashboard_src/src/pages/world/components/SettingsPanel.tsx
// Phase W10 — World-scoped preferences only (simulation speed, default
// camera focus). Broader dashboard-wide settings are out of this
// phase's scope — see world/docs/LIVE_COMMAND_CENTER.md's scoping note.
import { useState } from 'react'
import { worldApi } from '../api'

const SPEED_KEY = 'world.settings.simulationSpeed'

function loadSpeed(): number {
  const raw = window.localStorage.getItem(SPEED_KEY)
  const parsed = raw ? Number(raw) : 1
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1
}

interface SettingsPanelProps {
  rooms: string[]
}

export default function SettingsPanel({ rooms }: SettingsPanelProps) {
  const [speed, setSpeed] = useState(loadSpeed)
  const [applied, setApplied] = useState(false)

  const applySpeed = (value: number) => {
    setSpeed(value)
    window.localStorage.setItem(SPEED_KEY, String(value))
    worldApi
      .setSimulationSpeed(value)
      .then(() => setApplied(true))
      .catch(() => setApplied(false))
  }

  return (
    <div data-testid="settings-panel" className="space-y-4 text-sm">
      <div>
        <label className="block text-slate-400 mb-1" htmlFor="sim-speed">
          Simulation speed
        </label>
        <input
          id="sim-speed"
          type="range"
          min={0.25}
          max={4}
          step={0.25}
          value={speed}
          data-testid="settings-speed"
          onChange={(e) => applySpeed(Number(e.target.value))}
          className="w-full"
        />
        <div className="text-slate-300">{speed.toFixed(2)}× {applied && '(applied)'}</div>
      </div>

      <div>
        <label className="block text-slate-400 mb-1">Focus camera on room</label>
        <select
          data-testid="settings-focus-room"
          onChange={(e) => e.target.value && worldApi.focusRoom(e.target.value)}
          defaultValue=""
          className="w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-slate-200"
        >
          <option value="" disabled>
            Choose a room…
          </option>
          {rooms.map((roomId) => (
            <option key={roomId} value={roomId}>
              {roomId}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
