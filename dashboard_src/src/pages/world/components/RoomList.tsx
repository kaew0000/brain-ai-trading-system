// dashboard_src/src/pages/world/components/RoomList.tsx
import type { RoomActivity } from '../types'
import { activityColorHex, activityLabel } from '../sceneMapping'

interface RoomListProps {
  rooms: RoomActivity[]
  selectedRoomId: string | null
  onSelect: (roomId: string) => void
}

export default function RoomList({ rooms, selectedRoomId, onSelect }: RoomListProps) {
  return (
    <ul className="space-y-1" data-testid="room-list">
      {rooms.map((room) => (
        <li key={room.roomId}>
          <button
            type="button"
            onClick={() => onSelect(room.roomId)}
            data-testid={`room-item-${room.roomId}`}
            className={`w-full flex items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
              room.roomId === selectedRoomId
                ? 'bg-slate-700 text-white'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: activityColorHex(room.activity) }}
              />
              {room.roomId}
            </span>
            <span className="text-xs text-slate-400">
              {activityLabel(room.activity)} · {room.occupantCount}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
