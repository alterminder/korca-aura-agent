import type { Ticket, User } from '../../types'

interface TicketMetaProps {
  ticket: Ticket
  allExperts: User[] | undefined
  showReassign: boolean
  reassignEmail: string
  reassigning: boolean
  onToggleReassign: () => void
  onReassignEmailChange: (email: string) => void
  onReassign: () => void
}

export function TicketMeta({
  ticket,
  allExperts,
  showReassign,
  reassignEmail,
  reassigning,
  onToggleReassign,
  onReassignEmailChange,
  onReassign,
}: TicketMetaProps) {
  return (
    <>
      {/* Meta row */}
      <div className="flex flex-wrap gap-2 items-center">
        {(() => {
          const pill = 'text-[10px] font-normal px-2 py-0.5 rounded-full border'
          const s = ticket.status?.toLowerCase()
          let color = 'bg-app-nav-hover text-app-nav-text border-transparent'
          if (s === 'closed' || s === 'solved' || s === 'resolved') color = 'bg-slate-500 text-white border-transparent'
          return <span className={`${pill} ${color}`}>{ticket.status}</span>
        })()}
        {ticket.source_system && (
          <span className="text-[10px] font-normal px-2 py-0.5 rounded-full border bg-app-nav-hover text-app-nav-text border-transparent">
            {ticket.source_system}
          </span>
        )}
        {ticket.source && (
          <span className="text-[10px] font-normal px-2 py-0.5 rounded-full border bg-app-nav-hover text-app-nav-text border-transparent">
            via {ticket.source}
          </span>
        )}
      </div>

      {/* People & Client */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-xs text-app-nav-text">Assigned to</p>
            <button
              onClick={onToggleReassign}
              className="text-xs text-app-accent hover:opacity-80"
            >
              {showReassign ? 'cancel' : 'reassign'}
            </button>
          </div>
          {showReassign ? (
            <div className="flex gap-1 mt-1">
              <select
                value={reassignEmail}
                onChange={e => onReassignEmailChange(e.target.value)}
                className="flex-1 text-xs px-2 py-1 border border-app-border rounded focus:outline-none focus:ring-1 focus:ring-app-accent text-slate-950 bg-app-bg"
              >
                <option value="">Pick expert...</option>
                {allExperts?.map(u => (
                  <option key={u.email} value={u.email}>{u.name || u.email}</option>
                ))}
              </select>
              <button
                onClick={onReassign}
                disabled={!reassignEmail || reassigning}
                className="text-xs px-2 py-1 bg-app-accent text-app-bg rounded hover:opacity-90 disabled:opacity-50"
              >
                {reassigning ? '...' : 'Save'}
              </button>
            </div>
          ) : (
            <>
              <p className="text-slate-950 font-medium">{ticket.agent_name || '—'}</p>
              {ticket.agent_email && (
                <p className="text-xs text-app-nav-text">{ticket.agent_email}</p>
              )}
            </>
          )}
        </div>
        <div>
          <p className="text-xs text-app-nav-text mb-0.5">Client</p>
          <p className="text-slate-950 font-medium">{ticket.client_display_name || ticket.client_name || '—'}</p>
          {ticket.client_domain && (
            <p className="text-xs text-app-nav-text">{ticket.client_domain}</p>
          )}
        </div>
        <div>
          <p className="text-xs text-app-nav-text mb-0.5">Created</p>
          <p className="text-slate-600">
            {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString() : '—'}
          </p>
        </div>
      </div>
    </>
  )
}
