// dashboard_src/src/pages/world/components/NotificationsPanel.tsx
import { useEffect, useState } from 'react'
import { worldApi } from '../api'
import type { NotificationItem } from '../types'

const SEVERITY_COLOR: Record<NotificationItem['severity'], string> = {
  info: 'text-sky-400',
  success: 'text-green-400',
  warning: 'text-amber-400',
  critical: 'text-red-400',
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
          <div className={`text-xs font-semibold uppercase ${SEVERITY_COLOR[item.severity]}`}>
            {item.severity}
          </div>
          <div className="text-slate-200">{item.message}</div>
          <div className="text-xs text-slate-500">{item.timestamp}</div>
        </li>
      ))}
    </ul>
  )
}
