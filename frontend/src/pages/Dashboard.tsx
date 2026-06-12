import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useStats } from '../hooks/useDocuments'
import { api } from '../api/client'
import {
  BuildingOfficeIcon,
  CheckCircleIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
  TicketIcon,
  UserGroupIcon,
} from '@heroicons/react/24/outline'

export function Dashboard() {
  const { data: stats } = useStats()

  const { data: aiAccuracy } = useQuery({
    queryKey: ['ai-accuracy'],
    queryFn: () => api.import.aiAccuracy(),
    refetchInterval: 60_000,
  })

  const { data: expertLoad } = useQuery({
    queryKey: ['expert-load'],
    queryFn: () => api.health.expertLoad(),
    refetchInterval: 60_000,
  })

  const { data: clientLoad } = useQuery({
    queryKey: ['client-load'],
    queryFn: () => api.health.clientLoad(),
    refetchInterval: 60_000,
  })

  const { data: recentActivity } = useQuery({
    queryKey: ['recent-activity'],
    queryFn: () => api.health.recentActivity(),
    refetchInterval: 60_000,
  })

  const { data: reviewData } = useQuery({
    queryKey: ['needs-review'],
    queryFn: () => api.health.needsReview(),
    refetchInterval: 30_000,
  })

  const stagedCount = reviewData?.staged ?? 0
  const allClear = stagedCount === 0
  const maxExpertTickets = expertLoad ? Math.max(...expertLoad.map((e) => e.ticket_count), 1) : 1
  const maxClientTickets = clientLoad ? Math.max(...clientLoad.map((c) => c.ticket_count), 1) : 1

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-950">Dashboard</h1>
      </div>

      {/* Row 1 — stat cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-app-border bg-app-drawer p-3.5 text-app-nav-text">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-mono font-normal">Documents</p>
            <DocumentTextIcon className="h-5 w-5 shrink-0" />
          </div>
          <p className="mt-2 text-3xl font-bold font-mono">{stats?.documents ?? 0}</p>
        </div>
        <div className="rounded-lg border border-app-border bg-app-drawer p-3.5 text-app-nav-text">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-mono font-normal">Tickets</p>
            <TicketIcon className="h-5 w-5 shrink-0" />
          </div>
          <p className="mt-2 text-3xl font-bold font-mono">{stats?.tickets ?? 0}</p>
        </div>
        <div className="rounded-lg border border-app-border bg-app-drawer p-3.5 text-app-nav-text">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-mono font-normal">Experts</p>
            <UserGroupIcon className="h-5 w-5 shrink-0" />
          </div>
          <p className="mt-2 text-3xl font-bold font-mono">{stats?.users ?? 0}</p>
        </div>
        <div className="rounded-lg border border-app-border bg-app-drawer p-3.5 text-app-nav-text">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-mono font-normal">Clients</p>
            <BuildingOfficeIcon className="h-5 w-5 shrink-0" />
          </div>
          <p className="mt-2 text-3xl font-bold font-mono">{stats?.clients ?? 0}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <StagedTicketsCard stagedCount={stagedCount} allClear={allClear} />

        <div className="space-y-6">
          <div className="rounded-lg border border-app-border bg-app-panel p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-950">Routing Accuracy</h2>
              <span className="text-xs text-app-nav-text">
                {aiAccuracy?.evaluated ?? 0} evaluated tickets
              </span>
            </div>
            <AccuracyBar
              pct={aiAccuracy?.accuracy_pct ?? null}
            />
          </div>

          <RecentRoutingActivity items={recentActivity ?? []} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <LoadCard
          title="Top Experts by Ticket Load"
          viewAllHref="/experts"
          items={(expertLoad ?? []).map(expert => ({
            key: expert.email,
            label: expert.name || expert.email,
            count: expert.ticket_count,
          }))}
          max={maxExpertTickets}
        />
        <LoadCard
          title="Top Clients by Ticket Load"
          viewAllHref="/clients"
          items={(clientLoad ?? []).map(client => ({
            key: client.domain || client.name || 'unknown',
            label: client.name || client.domain || 'Unknown client',
            count: client.ticket_count,
          }))}
          max={maxClientTickets}
        />
      </div>
    </div>
  )
}

function StagedTicketsCard({
  stagedCount,
  allClear,
}: {
  stagedCount: number
  allClear: boolean
}) {
  return (
    <div className="rounded-lg border border-app-border bg-app-panel p-4 flex flex-col min-h-64">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-950 flex items-center gap-1.5">
          <ExclamationTriangleIcon className="w-4 h-4 text-yellow-400" />
          Staged Tickets
        </h2>
        <Link to="/review-queue" className="text-xs text-app-accent hover:opacity-80">
          Open staged tickets →
        </Link>
      </div>
      <div className="flex-1 flex items-center justify-center py-4">
        {allClear ? (
          <div className="text-center">
            <CheckCircleIcon className="w-10 h-10 text-green-400 mx-auto mb-2" />
            <p className="text-sm text-app-nav-text">All caught up</p>
          </div>
        ) : (
          <div className="w-full space-y-3">
            {stagedCount > 0 && (
              <div className="flex items-center justify-between rounded-md bg-yellow-500/10 border border-yellow-500/20 px-4 py-3">
                <div>
                  <p className="text-2xl font-bold font-mono text-yellow-400">{stagedCount}</p>
                  <p className="text-xs text-app-nav-text">staged - not historical knowledge</p>
                </div>
                <Link
                  to="/review-queue"
                  className="text-xs text-yellow-400 border border-yellow-500/30 rounded-full px-3 py-1.5 hover:bg-yellow-500/20 transition-colors"
                >
                  Open →
                </Link>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(months / 12)}y ago`
}

function RoutingOutcomeIcon({ outcome }: { readonly outcome: string }) {
  if (outcome === 'correct') {
    return (
      <div className="w-4 h-4 rounded-full border border-emerald-500/50 flex items-center justify-center" title="Routed correctly">
        <span className="text-emerald-600 text-[8px] font-bold leading-none">✓</span>
      </div>
    )
  }
  if (outcome === 'wrong') {
    return (
      <div className="w-4 h-4 rounded-full border border-red-500/50 flex items-center justify-center" title="Routed incorrectly">
        <span className="text-red-600 text-[8px] font-bold leading-none">✕</span>
      </div>
    )
  }
  return (
    <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[11px] bg-app-nav-hover text-app-nav-text border border-transparent">
      unassigned
    </span>
  )
}

function RecentRoutingActivity({
  items,
}: {
  items: Array<{
    subject: string | null
    ticket_id: string | number
    expert_name: string | null
    expert_email: string | null
    routed_at: string | null
    client_name: string | null
    outcome: string | null
    confirmed: boolean
  }>
}) {
  return (
    <div className="rounded-lg border border-app-border bg-app-panel p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-950">Recent Routing Activity</h2>
        <Link to="/integrations/teamwork" className="text-xs text-app-accent hover:opacity-80">
          View tickets →
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="py-6 text-center text-sm text-app-nav-text">No Aura routing events yet</p>
      ) : (
        <div className="space-y-3">
          {items.slice(0, 5).map(item => {
            const outcome = item.outcome || (item.confirmed ? 'correct' : 'wrong')
            return (
              <div key={`${item.ticket_id}-${item.routed_at ?? ''}`} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-700">{item.subject || `Ticket #${item.ticket_id}`}</p>
                  <p className="mt-0.5 truncate text-xs text-app-nav-text">
                    <span className="text-app-accent">{item.client_name || 'No client'}</span> · Routed to {item.expert_name || item.expert_email || 'No expert'}
                  </p>
                  {item.routed_at && (
                    <p className="mt-0.5 text-[11px] text-app-nav-text/70">{timeAgo(item.routed_at)}</p>
                  )}
                </div>
                <RoutingOutcomeIcon outcome={outcome} />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function LoadCard({
  title,
  viewAllHref,
  items,
  max,
}: {
  title: string
  viewAllHref: string
  items: Array<{ key: string; label: string; count: number }>
  max: number
}) {
  return (
    <div className="rounded-lg border border-app-border bg-app-panel p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-950">{title}</h2>
        <Link to={viewAllHref} className="text-xs text-app-accent hover:opacity-80">
          View all →
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="py-6 text-center text-sm text-app-nav-text">No ticket load yet</p>
      ) : (
        <div className="space-y-2">
          {items.map(item => (
            <div key={item.key} className="flex items-center gap-3">
              <span className="text-sm text-slate-600 w-40 truncate shrink-0">
                {item.label}
              </span>
              <div className="flex-1 bg-app-nav-hover rounded-full h-2 overflow-hidden">
                <div
                  className="h-full bg-app-accent rounded-full transition-all"
                  style={{ width: `${(item.count / max) * 100}%` }}
                />
              </div>
              <span className="text-xs font-mono text-app-nav-text w-8 text-right shrink-0">
                {item.count}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function accuracyColor(pct: number | null): string {
  if (pct === null) return 'bg-gray-600'
  if (pct >= 95) return 'bg-purple-600'
  if (pct >= 90) return 'bg-purple-500'
  if (pct >= 85) return 'bg-violet-500'
  if (pct >= 80) return 'bg-violet-400'
  if (pct >= 73) return 'bg-yellow-500'
  if (pct >= 67) return 'bg-yellow-400'
  if (pct >= 60) return 'bg-yellow-300'
  return 'bg-red-500'
}

function AccuracyBar({
  pct,
}: {
  pct: number | null
}) {
  const value = pct ?? 0
  const color = accuracyColor(pct)
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-slate-950">
          {pct !== null ? `${value.toFixed(1)}%` : '—'}
        </span>
      </div>
      <div className="h-2 bg-app-nav-hover rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all`}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  )
}
