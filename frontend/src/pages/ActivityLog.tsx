import { useEffect, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { api } from '../api/client'
import type { Notification } from '../types'

const STATUS_DOT: Record<string, string> = {
  success: 'bg-emerald-400',
  error: 'bg-red-400',
  warning: 'bg-yellow-400',
  info: 'bg-slate-400',
}

const STATUS_LABEL: Record<string, string> = {
  success: 'text-emerald-600',
  error: 'text-red-600',
  warning: 'text-yellow-600',
  info: 'text-slate-500',
}

export function ActivityLog() {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.notifications
      .list(100)
      .then((data) => {
        if (Array.isArray(data)) setNotifications(data)
      })
      .catch(() => { /* ignore fetch errors */ })
      .finally(() => setLoading(false))
  }, [])

  // Live updates via SSE
  useEffect(() => {
    const es = new EventSource('/api/events/notifications')
    es.onmessage = (e) => {
      try {
        const n: Notification = JSON.parse(e.data)
        setNotifications((prev) => [n, ...prev].slice(0, 100))
      } catch { /* ignore malformed SSE data */ }
    }
    return () => es.close()
  }, [])

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-slate-950 mb-6">Activity Log</h1>
      {loading ? (
        <p className="text-sm text-app-nav-text">Loading…</p>
      ) : notifications.length === 0 ? (
        <p className="text-sm text-app-nav-text">No activity yet.</p>
      ) : (
        <ol className="relative border-l border-app-border space-y-0">
          {notifications.map((n, i) => (
            <li key={i} className="ml-4 pb-6">
              <span className={`absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-white ${STATUS_DOT[n.status] ?? STATUS_DOT.info}`} />
              <p className="text-sm text-slate-950 leading-snug">{n.message}</p>
              <p className={`mt-0.5 text-xs font-medium ${STATUS_LABEL[n.status] ?? STATUS_LABEL.info}`}>
                {n.status}
                <span className="ml-2 font-normal text-app-nav-text">
                  {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                </span>
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
