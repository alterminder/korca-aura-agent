import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { TrashIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { TicketDrawer } from '../components/TicketDrawer'
import type { Ticket } from '../types'

const REASON_LABELS: Record<string, string> = {
  missing_content: 'No content',
  missing_assignee: 'No assignee',
  missing_client: 'No client',
  low_content_quality: 'Low quality content',
  not_closed: 'Open ticket',
}

const LIMIT = 25

function isClosedStatus(status?: string | null): boolean {
  return ['closed', 'solved', 'resolved'].includes((status ?? '').toLowerCase())
}

function StagedReasons({ reasons }: Readonly<{ reasons?: string[] | null }>) {
  if (!reasons?.length) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {reasons.map(r => (
        <span key={r} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-normal bg-amber-50 text-amber-700 border border-amber-200">
          {REASON_LABELS[r] ?? r}
        </span>
      ))}
    </div>
  )
}

export function ReviewQueue() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [promoting, setPromoting] = useState<string | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)

  function openTicket(id: string) {
    queryClient.removeQueries({ queryKey: ['ticket', id] })
    setSelectedTicketId(id)
  }

  const { data, isLoading } = useQuery({
    queryKey: ['staged-tickets', page],
    queryFn: () => api.import.listStaged(page * LIMIT, LIMIT),
  })

  const tickets: Ticket[] = data?.tickets ?? []
  const total: number = data?.total ?? 0
  const totalPages = Math.ceil(total / LIMIT)

  async function handleBulkDelete() {
    if (!checked.size || deleting) return
    if (!confirm(`Delete ${checked.size} ticket${checked.size !== 1 ? 's' : ''} from the graph? They will be blocklisted and never re-imported.`)) return
    setDeleting(true)
    try {
      const res = await api.import.bulkDeleteTickets(Array.from(checked))
      toast.success(`Deleted ${res.deleted} ticket${res.deleted !== 1 ? 's' : ''}`)
      setChecked(new Set())
      queryClient.invalidateQueries({ queryKey: ['staged-tickets'] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  async function handlePromote(ticketId: string) {
    setPromoting(ticketId)
    try {
      await api.import.promoteTicket(ticketId)
      toast.success('Ticket promoted to graph')
      queryClient.invalidateQueries({ queryKey: ['staged-tickets'] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Promote failed')
    } finally {
      setPromoting(null)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-950">Staged Tickets</h1>
        <p className="mt-1 text-sm text-app-nav-text">
          Tickets that are not part of historical knowledge yet. Correct the issue in Teamwork or promote manually.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-app-nav-text">{total} staged ticket{total !== 1 ? 's' : ''}</span>
        {checked.size > 0 && (
          <button
            onClick={handleBulkDelete}
            disabled={deleting}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <TrashIcon className="h-4 w-4" />
            {deleting ? 'Deleting…' : `Delete ${checked.size} selected`}
          </button>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-16 bg-app-nav-hover rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && tickets.length === 0 && (
        <div className="text-center py-16 text-app-nav-text">
          <p className="text-lg font-medium text-slate-950">No staged tickets</p>
          <p className="text-sm mt-1">All eligible tickets are historical knowledge.</p>
        </div>
      )}

      {tickets.length > 0 && (
        <div className="border border-app-border rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-app-border">
            <thead className="bg-app-nav-hover">
              <tr>
                <th className="px-4 py-3 w-8">
                  <input
                    type="checkbox"
                    checked={tickets.length > 0 && tickets.every(t => checked.has(String(t.id)))}
                    onChange={e => {
                      if (e.target.checked) setChecked(new Set(tickets.map(t => String(t.id))))
                      else setChecked(new Set())
                    }}
                    className="rounded border-app-border"
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-app-nav-text uppercase tracking-wider">Ticket</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-app-nav-text uppercase tracking-wider">Reasons</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-app-nav-text uppercase tracking-wider">Client</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-app-nav-text uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-app-panel divide-y divide-app-border">
              {tickets.map(ticket => (
                <tr
                  key={ticket.id}
                  className={`hover:bg-app-nav-hover cursor-pointer transition-colors ${checked.has(String(ticket.id)) ? 'bg-red-900/10' : ''}`}
                  onClick={() => openTicket(String(ticket.id))}
                >
                  <td className="px-4 py-3 w-8" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={checked.has(String(ticket.id))}
                      onChange={e => {
                        const id = String(ticket.id)
                        setChecked(prev => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(id)
                          else next.delete(id)
                          return next
                        })
                      }}
                      className="rounded border-app-border"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-sm font-medium text-slate-950 truncate max-w-xs">{ticket.subject || '(no subject)'}</p>
                    <p className="text-xs text-app-nav-text mt-0.5">
                      #{ticket.id} · {ticket.source_system} · {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString() : '—'}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <StagedReasons reasons={ticket.staged_reasons} />
                  </td>
                  <td className="px-4 py-3 text-sm text-app-nav-text">
                    {ticket.client_display_name || ticket.client_name || ticket.client_domain || <span className="text-app-nav-text/40">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    {ticket.agent_email && isClosedStatus(ticket.status) ? (
                      <button
                        onClick={() => handlePromote(String(ticket.id))}
                        disabled={promoting === String(ticket.id)}
                        className="px-2.5 py-1 text-xs font-medium text-app-accent border border-app-accent/30 rounded hover:bg-app-accent-bg disabled:opacity-50"
                      >
                        {promoting === String(ticket.id) ? '…' : 'Promote'}
                      </button>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-normal bg-amber-50 text-amber-700 border border-amber-200">
                        {ticket.agent_email ? 'Open ticket' : 'No assignee'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-3 py-1.5 text-sm border border-app-border rounded hover:bg-app-nav-hover disabled:opacity-40 text-slate-600"
          >
            Previous
          </button>
          <span className="text-sm text-app-nav-text">Page {page + 1} of {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-3 py-1.5 text-sm border border-app-border rounded hover:bg-app-nav-hover disabled:opacity-40 text-slate-600"
          >
            Next
          </button>
        </div>
      )}

      <TicketDrawer
        ticketId={selectedTicketId}
        onClose={() => setSelectedTicketId(null)}
        onDeleted={() => {
          setSelectedTicketId(null)
          queryClient.invalidateQueries({ queryKey: ['staged-tickets'] })
        }}
      />
    </div>
  )
}
