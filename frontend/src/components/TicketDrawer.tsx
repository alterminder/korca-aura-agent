import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { ArrowPathIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { RoutingSection } from './TicketRoutingSection'
import { hasActiveAuraRouting } from './ticketRoutingHelpers'
import { AuraRoutingRecord } from './ticket-drawer/AuraRoutingRecord'
import { TicketContentViewer } from './ticket-drawer/TicketContentViewer'
import { TicketDrawerFooter } from './ticket-drawer/TicketDrawerFooter'
import { TicketMeta } from './ticket-drawer/TicketMeta'
import type { Ticket } from '../types'

interface Props {
  ticketId: string | null
  onClose: () => void
  onDeleted?: (id: string) => void
}

function visibleConfidence(confidence?: string | null): string | null {
  return confidence && ['high', 'medium', 'low'].includes(confidence) ? confidence : null
}

export function TicketDrawer({ ticketId, onClose, onDeleted }: Props) {
  const queryClient = useQueryClient()
  const [deleting, setDeleting] = useState(false)
  const [spamming, setSpamming] = useState(false)
  const [reimporting, setReimporting] = useState(false)
  const [contentView, setContentView] = useState<'summary' | 'request' | 'raw'>('summary')
  const [showReassign, setShowReassign] = useState(false)
  const [reassigning, setReassigning] = useState(false)
  const [reassignEmail, setReassignEmail] = useState('')
  const overlayRef = useRef<HTMLButtonElement>(null)

  const { data: ticket, isLoading } = useQuery<Ticket>({
    queryKey: ['ticket', ticketId],
    queryFn: () => api.import.getTicket(ticketId!),
    enabled: !!ticketId,
    refetchInterval: (query) => hasActiveAuraRouting(query.state.data) ? 2000 : false,
    staleTime: 0,   // always refetch on drawer open
    gcTime: 0,      // drop cache immediately on close — prevents stale flash on reopen
  })

  const { data: allExperts } = useQuery({
    queryKey: ['users'],
    queryFn: api.users.list,
    enabled: showReassign || !!ticket?.latest_aura_suggestion_email,
  })
  const confidenceLabel = visibleConfidence(ticket?.aura_suggestion_confidence)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handleReassign() {
    if (!reassignEmail || !ticket || reassigning) return
    setReassigning(true)
    try {
      const expert = allExperts?.find(u => u.email === reassignEmail)
      await api.import.reassignResolver(String(ticket.id), reassignEmail, expert?.name ?? '')
      setShowReassign(false)
      setReassignEmail('')
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
      queryClient.invalidateQueries({ queryKey: ['staged-tickets'] })
    } finally {
      setReassigning(false)
    }
  }

  async function handleSync() {
    if (!ticket || reimporting) return
    setReimporting(true)
    try {
      await api.import.syncTicket(String(ticket.id))
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['staged-tickets'] })
    } finally {
      setReimporting(false)
    }
  }

  async function handleDelete() {
    if (!ticket || deleting) return
    if (!confirm(`Remove "${ticket.subject}" from the knowledge graph?\n\nThis only removes it from Korca — the ticket in Teamwork Desk is not affected.`)) return
    setDeleting(true)
    await api.import.deleteTicket(String(ticket.id))
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
    setDeleting(false)
    onDeleted?.(String(ticket.id))
    onClose()
  }

  async function handleSpam() {
    if (!ticket || spamming) return
    if (!confirm(`Mark "${ticket.subject}" as spam?\n\nThis removes it from Korca and blocks it from being re-imported.`)) return
    setSpamming(true)
    await api.import.spamTicket(String(ticket.id))
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
    setSpamming(false)
    onDeleted?.(String(ticket.id))
    onClose()
  }

  if (!ticketId) return null

  return (
    <>
      <button
        ref={overlayRef}
        type="button"
        aria-label="Close drawer"
        className="fixed inset-0 bg-black/50 z-40 cursor-default"
        onClick={onClose}
      />

      <div className="fixed top-0 right-0 h-full w-full max-w-xl bg-app-drawer border-l border-app-border shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-app-border shrink-0">
          <div className="flex items-center gap-2 min-w-0 pr-4">
            <h2 className="text-sm font-semibold text-slate-950 truncate">
              {isLoading ? 'Loading...' : ticket?.subject ?? 'Ticket'}
            </h2>
            {ticket?.id && (
              <span className="text-xs text-app-nav-text shrink-0">#{ticket.id}</span>
            )}
            {ticket?.source_system === 'teamwork' && (
              <button
                onClick={handleSync}
                disabled={reimporting}
                title="Sync from Teamwork"
                className="shrink-0 text-slate-950 bg-transparent rounded-full p-1 hover:bg-slate-950/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ArrowPathIcon className={`w-3 h-3 ${reimporting ? 'animate-spin' : ''}`} />
              </button>
            )}
          </div>
          <button onClick={onClose} className="shrink-0 text-app-nav-text hover:text-slate-950">
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-app-nav-text text-sm">Loading...</div>
        ) : !ticket ? (
          <div className="flex-1 flex items-center justify-center text-app-nav-text text-sm">Ticket not found</div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              <TicketMeta
                ticket={ticket}
                allExperts={allExperts}
                showReassign={showReassign}
                reassignEmail={reassignEmail}
                reassigning={reassigning}
                onToggleReassign={() => { setShowReassign(v => !v); setReassignEmail('') }}
                onReassignEmailChange={setReassignEmail}
                onReassign={handleReassign}
              />

              {(ticket.tags ?? []).length > 0 && (
                <div>
                  <p className="text-xs text-app-nav-text mb-1.5">Tags</p>
                  <div className="flex flex-wrap gap-1.5">
                    {ticket.tags.map((tag) => (
                      <span key={tag} className="text-xs bg-app-accent-bg text-slate-600 px-2 py-0.5 rounded">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <TicketContentViewer
                ticket={ticket}
                contentView={contentView}
                onContentViewChange={setContentView}
              />

              <AuraRoutingRecord
                ticket={ticket}
                allExperts={allExperts}
                confidenceLabel={confidenceLabel}
              />

              <RoutingSection ticket={ticket} />
            </div>

            <TicketDrawerFooter
              deleting={deleting}
              spamming={spamming}
              onDelete={handleDelete}
              onSpam={handleSpam}
            />
          </>
        )}
      </div>
    </>
  )
}
