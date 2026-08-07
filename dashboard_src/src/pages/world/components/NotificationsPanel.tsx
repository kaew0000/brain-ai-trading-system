// dashboard_src/src/pages/world/components/NotificationsPanel.tsx
// Phase W10 (fixed in Phase W12): the real backend shape is
// InteractionNotification (id/category/roomId/tickNumber/message/agentId)
// — no timestamp/severity/read at that layer. This was wrong before
// (assumed a shape that doesn't exist) and is corrected here.
import { useEffect, useState } from 'react'
import { worldApi } from '../api'
import type { NotificationItem } from '../types'

const CATEGORY_COLOR: Record<NotificationItem['category'], string> = {
  emergency: 'text-red-400',
  alert: 'text-amber-400',
  meeting: 'text-purple-400',
  mission: 'text-sky-400',
  celebration: 'text-yellow-400',
  system_status: 'text-slate-400',
}

export default function NotificationsPanel() {
  const [items, setItems] = useState<NotificationItem[]>([])

  useEffect(() => {
    const refresh = () => worldApi.getNotifications().then(setItems).catch(() => setItems([]))
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [])

  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No alerts.</p>
  }

  return (
    <ul data-testid="notifications-panel" className="space-y-2 text-sm">
      {items.map((item) => (
        <li key={item.id} className="rounded-md border border-slate-700 px-3 py-2">
          <div className={`text-xs font-semibold uppercase ${CATEGORY_COLOR[item.category]}`}>
            {item.category.replace('_', ' ')}
          </div>
          <div className="text-slate-200">{item.message}</div>
          <div className="text-xs text-slate-500">
            {item.roomId} · tick {item.tickNumber}
          </div>
        </li>
      ))}
    </ul>
  )
}
