import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useDocument } from '../hooks/useDocuments'
import type { Notification } from '../types'
import {
  HomeIcon,
  ArrowsRightLeftIcon,
  DocumentTextIcon,
  UserGroupIcon,
  BuildingOfficeIcon,
  ClipboardDocumentListIcon,
  BeakerIcon,
  CpuChipIcon,
  UserIcon,
  BellIcon,
  ChevronRightIcon,
} from '@heroicons/react/24/outline'

const NAV = [
  { to: '/', label: 'Dashboard', icon: HomeIcon },
  { to: '/integrations', label: 'Integrations', icon: ArrowsRightLeftIcon },
  { to: '/aura-agent', label: 'Aura Agent', icon: CpuChipIcon },
  { to: '/documents', label: 'Documents', icon: DocumentTextIcon },
  { to: '/experts', label: 'Experts', icon: UserGroupIcon },
  { to: '/clients', label: 'Clients', icon: BuildingOfficeIcon },
  { to: '/review-queue', label: 'Staged Tickets', icon: ClipboardDocumentListIcon },
  { to: '/routing', label: 'Sandbox', icon: BeakerIcon },
]

interface Crumb {
  label: string
  to: string
}

const STATUS_DOT: Record<string, string> = {
  success: 'bg-emerald-400',
  error: 'bg-red-400',
  warning: 'bg-yellow-400',
  info: 'bg-slate-400',
}

function getCrumbs(pathname: string): Crumb[] {
  if (pathname === '/') return []
  if (pathname === '/integrations') return [{ label: 'Integrations', to: '/integrations' }]
  if (pathname.startsWith('/integrations/teamwork')) return [
    { label: 'Integrations', to: '/integrations' },
    { label: 'Teamwork Desk', to: '/integrations/teamwork' },
  ]
  if (pathname.startsWith('/integrations')) return [{ label: 'Integrations', to: '/integrations' }]
  if (pathname === '/aura-agent') return [{ label: 'Aura Agent', to: '/aura-agent' }]
  if (pathname === '/documents') return [{ label: 'Documents', to: '/documents' }]
  if (pathname.startsWith('/documents/')) return [
    { label: 'Documents', to: '/documents' },
    { label: 'Document', to: pathname },
  ]
  if (pathname === '/experts') return [{ label: 'Experts', to: '/experts' }]
  if (pathname === '/clients') return [{ label: 'Clients', to: '/clients' }]
  if (pathname === '/review-queue') return [{ label: 'Staged Tickets', to: '/review-queue' }]
  if (pathname === '/routing') return [{ label: 'Sandbox', to: '/routing' }]
  if (pathname === '/activity-log') return [{ label: 'Activity Log', to: '/activity-log' }]
  return []
}

export function Layout({ children, onLogout }: { children: React.ReactNode; onLogout: () => void }) {
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [bellOpen, setBellOpen] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const bellRef = useRef<HTMLDivElement>(null)

  const docIdMatch = pathname.match(/^\/documents\/(.+)$/)
  const docId = docIdMatch ? docIdMatch[1] : ''
  const { data: currentDoc } = useDocument(docId)

  const crumbs = getCrumbs(pathname).map((crumb, i, arr) =>
    i === arr.length - 1 && docId && currentDoc
      ? { ...crumb, label: currentDoc.title }
      : crumb,
  )

  // Load initial notifications (live updates arrive via SSE below)
  useEffect(() => {
    api.notifications
      .list()
      .then((data) => {
        if (Array.isArray(data)) setNotifications(data)
      })
      .catch(() => { /* ignore fetch errors */ })
  }, [])

  // SSE subscription
  useEffect(() => {
    const es = new EventSource('/api/events/notifications')
    es.onmessage = (e) => {
      try {
        const n: Notification = JSON.parse(e.data)
        setNotifications((prev) => [n, ...prev].slice(0, 100))
        setUnread((u) => u + 1)
      } catch { /* ignore malformed SSE data */ }
    }
    return () => es.close()
  }, [])

  // Aura agent status — read from the shared ['aura-agents'] query so toggling
  // status on the Aura Agent page updates this badge instantly (that page writes
  // the same cache key). The interval is only a fallback for out-of-band changes.
  const { data: auraAgents, isError: auraAgentsError } = useQuery({
    queryKey: ['aura-agents'],
    queryFn: api.aura.listAgents,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
  let agentOnline: boolean | null = null
  if (auraAgentsError) {
    agentOnline = false
  } else if (auraAgents) {
    agentOnline = auraAgents[0]?.is_private === false
  }

  // Click-outside to close bell dropdown
  useEffect(() => {
    if (!bellOpen) return
    const handler = (e: MouseEvent) => {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) {
        setBellOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [bellOpen])

  function openBell() {
    setBellOpen((o) => !o)
    setUnread(0)
  }

  return (
    <div className="min-h-screen flex bg-slate-100">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-transparent flex flex-col">
        <div className="h-16 flex items-center px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <img src="/favicon.png" alt="Korca" className="h-7 w-7 object-contain" />
            <span className="text-xl font-bold text-slate-950 tracking-wide">Korca</span>
          </Link>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${pathname.startsWith(to) && (to !== '/' || pathname === '/')
                  ? 'text-app-accent bg-white'
                  : 'text-app-nav-text hover:text-slate-950 hover:bg-white'
                }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </Link>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        <main className="flex flex-1 min-w-0 flex-col pt-5 pr-5 pb-10">
          <div className="relative mb-3 flex h-10 w-full items-center gap-2">
            {/* Bar with breadcrumbs */}
            <div className="flex-1 h-full rounded-[20px] border border-app-border bg-white flex items-center px-4 gap-1.5 min-w-0">
              <Link to="/" className="shrink-0 text-app-nav-text hover:text-slate-950 transition-colors">
                <HomeIcon className="h-4 w-4" />
              </Link>
              {crumbs.map((crumb, i) => (
                <span key={crumb.to} className="flex items-center gap-1.5 min-w-0">
                  <ChevronRightIcon className="h-3 w-3 shrink-0 text-slate-500" />
                  {i === crumbs.length - 1 ? (
                    <span className="text-sm text-slate-950 truncate">{crumb.label}</span>
                  ) : (
                    <Link to={crumb.to} className="text-sm text-app-nav-text hover:text-slate-950 transition-colors truncate">
                      {crumb.label}
                    </Link>
                  )}
                </span>
              ))}
            </div>

            {/* Aura Agent Status */}
            {agentOnline !== null && (
              <div className="flex h-10 shrink-0 items-center gap-2 rounded-full border border-app-border bg-white px-4 text-sm text-slate-950">
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${agentOnline ? 'bg-emerald-500' : 'bg-red-500'}`} />
                {agentOnline ? 'Aura Agent Online' : 'Aura Agent Offline'}
              </div>
            )}

            {/* Bell */}
            <div ref={bellRef} className="relative shrink-0">
              <button
                type="button"
                onClick={openBell}
                className="relative flex h-10 w-10 items-center justify-center rounded-full border border-app-border bg-white text-app-nav-text transition-colors hover:bg-app-nav-hover hover:text-slate-950"
                aria-label="Notifications"
              >
                <BellIcon className="h-4 w-4" />
                {unread > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-neutral-950 text-[9px] font-bold text-white">
                    {unread > 9 ? '9+' : unread}
                  </span>
                )}
              </button>
              {bellOpen && (
                <div className="absolute right-0 top-12 z-20 w-80 rounded-2xl border border-app-border bg-white shadow-lg overflow-hidden">
                  <div className="px-4 py-3 border-b border-app-border">
                    <span className="text-sm font-medium text-slate-950">Notifications</span>
                  </div>
                  <div className="max-h-72 overflow-y-auto divide-y divide-app-border">
                    {notifications.length === 0 ? (
                      <p className="px-4 py-6 text-center text-sm text-app-nav-text">No notifications yet.</p>
                    ) : (
                      notifications.slice(0, 10).map((n, i) => (
                        <div key={i} className="flex items-start gap-3 px-4 py-3">
                          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[n.status] ?? STATUS_DOT.info}`} />
                          <div className="min-w-0">
                            <p className="text-sm text-slate-950 leading-snug">{n.message}</p>
                            <p className="mt-0.5 text-xs text-app-nav-text">
                              {new Date(n.created_at).toLocaleString()}
                            </p>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                  <div className="border-t border-app-border px-4 py-2">
                    <Link
                      to="/activity-log"
                      onClick={() => setBellOpen(false)}
                      className="text-xs text-app-accent hover:opacity-80 font-medium"
                    >
                      View all activity →
                    </Link>
                  </div>
                </div>
              )}
            </div>

            {/* User menu */}
            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => setMenuOpen((open) => !open)}
                className="flex h-10 w-10 items-center justify-center rounded-full border border-app-border bg-white text-app-nav-text transition-colors hover:bg-app-nav-hover hover:text-slate-950"
                aria-label="Open user menu"
                aria-expanded={menuOpen}
              >
                <UserIcon className="h-4 w-4" />
              </button>
              {menuOpen && (
                <div className="absolute right-0 top-12 z-20 w-36 rounded-md border border-app-border bg-white py-1 shadow-lg">
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false)
                      onLogout()
                    }}
                    className="w-full px-3 py-2 text-left text-sm text-app-nav-text hover:bg-app-nav-hover hover:text-slate-950"
                  >
                    Logout
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="min-h-0 flex-1 w-full rounded-[20px] border border-app-border bg-white px-8 py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
