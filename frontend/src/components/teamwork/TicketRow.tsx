import { ArrowPathIcon, ArrowsRightLeftIcon, ArrowsUpDownIcon, EyeIcon } from '@heroicons/react/24/outline'
import type { Ticket } from '../../types'

function relativeTime(dateStr: string | null): string | null {
  if (!dateStr) return null
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return null
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  const diffSec = Math.round((date.getTime() - Date.now()) / 1000)
  const abs = Math.abs(diffSec)
  if (abs < 60) return rtf.format(diffSec, 'second')
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour')
  if (abs < 604800) return rtf.format(Math.round(diffSec / 86400), 'day')
  if (abs < 2592000) return rtf.format(Math.round(diffSec / 604800), 'week')
  return rtf.format(Math.round(diffSec / 2592000), 'month')
}

function compactAuraRoutingStatus(ticket: Ticket): { label: string; className: string } | null {
  switch (ticket.routing_status) {
    case 'queued':
      return { label: 'routing queued', className: 'bg-sky-500/10 text-sky-500 border-sky-500/30' }
    case 'running':
      return { label: 'routing', className: 'bg-blue-500/10 text-blue-500 border-blue-500/30' }
    case 'no_recommendation':
      return { label: 'no recommendation', className: 'bg-amber-500/10 text-amber-500 border-amber-500/30' }
    case 'failed':
      return { label: 'routing failed', className: 'bg-red-500/10 text-red-500 border-red-500/30' }
    default:
      return null
  }
}

function auraSuggestionDisplay(
  ticket: Ticket,
  expertNameByEmail: Map<string, string>,
): { label: string; tone: 'correct' | 'wrong' | 'unknown' } | null {
  if (!ticket.latest_routing_event_id || !ticket.latest_aura_suggestion_email) return null
  const email = ticket.latest_aura_suggestion_email
  if (!email) return null
  const assignedEmail = ticket.assigned_to_email || ticket.agent_email
  const label = ticket.latest_aura_suggestion_name || expertNameByEmail.get(email.toLowerCase()) || email
  if (!assignedEmail) return { label, tone: 'unknown' }
  return {
    label,
    tone: email.toLowerCase() === assignedEmail.toLowerCase() ? 'correct' : 'wrong',
  }
}

const PILL = 'text-[10px] font-normal px-2 py-0.5 rounded-full border'

function RoutingMatchIcon({ tone }: { readonly tone: 'correct' | 'wrong' | 'unknown' }) {
  if (tone === 'correct') {
    return (
      <div className="w-4 h-4 rounded-full border border-emerald-500/50 flex items-center justify-center" title="Routed correctly">
        <span className="text-emerald-600 text-[8px] font-bold leading-none">✓</span>
      </div>
    )
  }
  if (tone === 'wrong') {
    return (
      <div className="w-4 h-4 rounded-full border border-red-500/50 flex items-center justify-center" title="Routed incorrectly">
        <span className="text-red-600 text-[8px] font-bold leading-none">✕</span>
      </div>
    )
  }
  return null
}

interface TicketListHeaderProps {
  readonly sortByStatus: boolean
  readonly onSortToggle: () => void
  readonly ticketCount?: number
  readonly importing: boolean
  readonly syncing: boolean
  readonly syncInitialized: boolean
  readonly onSyncNow: () => void
}

export function TicketListHeader({
  sortByStatus,
  onSortToggle,
  ticketCount,
  importing,
  syncing,
  syncInitialized,
  onSyncNow,
}: TicketListHeaderProps) {
  const col = 'text-xs font-normal uppercase tracking-wide'
  const color = 'text-slate-500'
  return (
    <div className="px-5 pt-5 pb-4 flex items-center border-b border-app-border gap-4">
      <div className="flex-1 min-w-0 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-950">Imported Tickets</h2>
        {ticketCount !== undefined && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-app-nav-hover text-app-nav-text">
            {ticketCount}
          </span>
        )}
        <button
          onClick={onSyncNow}
          disabled={importing || syncing || !syncInitialized}
          className="text-slate-950 bg-transparent rounded-full p-1 hover:bg-slate-950/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title={syncInitialized ? 'Sync Teamwork updates' : 'Bootstrap sync in Settings first'}
        >
          <ArrowPathIcon className={`w-3 h-3 ${syncing ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className={`w-36 shrink-0 ${col} ${color}`}>Assigned To</div>
      <div className="w-10 shrink-0 flex items-center">
        <ArrowsRightLeftIcon className="w-3.5 h-3.5 text-slate-500" />
      </div>
      <div className={`w-44 shrink-0 ${col} ${color}`}>Routed To</div>
      <div className="w-32 shrink-0 flex items-center justify-end gap-1">
        <span className={`${col} ${color}`}>Status</span>
        <button
          onClick={onSortToggle}
          title={sortByStatus ? 'Sort by date' : 'Sort: open first'}
          className={`transition-colors ${sortByStatus ? 'text-slate-950' : 'text-slate-500 hover:text-slate-950'}`}
        >
          <ArrowsUpDownIcon className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="w-4 shrink-0" />
    </div>
  )
}

interface TicketRowProps {
  readonly ticket: Ticket
  readonly expertNameByEmail: Map<string, string>
  readonly onSelect: (ticketId: string) => void
}

export function TicketRow({ ticket, expertNameByEmail, onSelect }: TicketRowProps) {
  const auraSuggestion = auraSuggestionDisplay(ticket, expertNameByEmail)
  const auraRoutingStatus = compactAuraRoutingStatus(ticket)
  const assignedName = ticket.assigned_to_name || ticket.agent_name
  const clientDisplayName = ticket.client_display_name || ticket.client_name
  const when = relativeTime(ticket.created_at)
  const s = ticket.status?.toLowerCase()
  let statusPillColor = 'bg-app-nav-hover text-app-nav-text border-transparent'
  if (s === 'closed' || s === 'solved' || s === 'resolved') statusPillColor = 'bg-slate-500 text-white border-transparent'

  return (
    <div className="px-5 py-3 flex items-center gap-4 hover:bg-app-nav-hover transition-colors">

      {/* Col 1 — ticket info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-950 truncate">{ticket.subject}</p>
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          {clientDisplayName && (
            <span className="text-xs text-app-accent">{clientDisplayName}</span>
          )}
          {ticket.ticket_type && (
            <span className={`${PILL} bg-app-nav-hover text-app-nav-text border-transparent`}>{ticket.ticket_type}</span>
          )}
          {ticket.inbox_name && (
            <span className={`${PILL} bg-app-nav-hover text-app-nav-text border-transparent`}>{ticket.inbox_name}</span>
          )}
          {(ticket.tags ?? []).map((tag) => (
            <span key={tag} className={`${PILL} bg-app-nav-hover text-app-nav-text border-transparent`}>{tag}</span>
          ))}
        </div>
        {when && <p className="text-xs text-app-nav-text mt-1">{when}</p>}
      </div>

      {/* Col 2 — Assigned To */}
      <div className="w-36 shrink-0">
        {assignedName
          ? <p className="text-xs text-slate-950">{assignedName}</p>
          : <p className="text-xs text-app-nav-text">—</p>
        }
      </div>

      {/* Col 3 — Match indicator */}
      <div className="w-10 shrink-0 flex items-center">
        {auraSuggestion && <RoutingMatchIcon tone={auraSuggestion.tone} />}
      </div>

      {/* Col 4 — Routed To */}
      <div className="w-44 shrink-0 space-y-1">
        {auraRoutingStatus && (
          <span
            className={`${PILL} ${auraRoutingStatus.className}`}
            title={ticket.aura_routing_error || undefined}
          >
            {auraRoutingStatus.label}
          </span>
        )}
        {auraSuggestion && (
          <p
            className="text-xs text-slate-950"
            title={`Aura suggested: ${auraSuggestion.label} · Assigned: ${ticket.assigned_to_name || ticket.assigned_to_email || ticket.agent_name || ticket.agent_email || 'none'}`}
          >
            {auraSuggestion.label}
          </p>
        )}
        {!auraRoutingStatus && !auraSuggestion && (
          <p className="text-xs text-app-nav-text">—</p>
        )}
      </div>

      {/* Col 5 — Status */}
      <div className="w-32 shrink-0 space-y-1 flex flex-col items-end">
        <span className={`${PILL} ${statusPillColor}`}>
          {ticket.status}
        </span>
      </div>

      {/* Eye */}
      <button
        onClick={() => onSelect(String(ticket.id))}
        className="w-4 shrink-0 text-app-nav-text hover:text-app-accent transition-colors"
        title="View ticket"
      >
        <EyeIcon className="w-4 h-4" />
      </button>
    </div>
  )
}
