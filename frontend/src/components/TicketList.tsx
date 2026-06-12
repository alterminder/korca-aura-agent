import { formatDistanceToNow } from 'date-fns'
import type { Ticket } from '../types'

const STATUS_STYLE: Record<string, string> = {
  solved:   'bg-slate-500 text-white border-transparent',
  closed:   'bg-slate-500 text-white border-transparent',
  resolved: 'bg-slate-500 text-white border-transparent',
  open:     'bg-blue-900/30 text-blue-400 border-transparent',
  new:      'bg-blue-900/30 text-blue-400 border-transparent',
  pending:  'bg-yellow-900/30 text-yellow-400 border-transparent',
  hold:     'bg-app-nav-hover text-app-nav-text border-transparent',
}

export function TicketList({ tickets }: { tickets: Ticket[] }) {
  if (tickets.length === 0) {
    return (
      <div className="text-center py-12 text-app-nav-text">
        No tickets yet. Import from Integrations to get started.
      </div>
    )
  }

  return (
    <ul className="divide-y divide-app-border bg-app-panel rounded-lg border border-app-border">
      {tickets.map((ticket) => (
        <li key={ticket.id} className="p-4">
          <div className="flex items-center justify-between">
            <p className="font-medium text-slate-950 truncate">{ticket.subject}</p>
            <span className={`ml-2 text-[10px] px-2 py-0.5 rounded-full border font-normal shrink-0 ${STATUS_STYLE[ticket.status?.toLowerCase()] ?? 'bg-app-nav-hover text-app-nav-text border-transparent'}`}>
              {ticket.status}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-4 text-sm text-app-nav-text flex-wrap">
            {(ticket.client_display_name || ticket.client_name) && (
              <span className="text-app-accent">{ticket.client_display_name || ticket.client_name}</span>
            )}
            {ticket.agent_name && <span>→ {ticket.agent_name}</span>}
            {ticket.ticket_type && (
              <span className="text-xs bg-app-accent-bg text-slate-600 px-2 py-0.5 rounded">{ticket.ticket_type}</span>
            )}
            {ticket.inbox_name && (
              <span className="text-xs bg-app-nav-hover text-app-nav-text px-2 py-0.5 rounded">{ticket.inbox_name}</span>
            )}
            {ticket.created_at && (
              <span>{formatDistanceToNow(new Date(ticket.created_at), { addSuffix: true })}</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}
