import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { XMarkIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { useStats } from '../hooks/useDocuments'
import { TicketDrawer } from '../components/TicketDrawer'
import type { Client } from '../types'


function ClientDetail({ domain, onClose }: { domain: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [linkingParent, setLinkingParent] = useState(false)
  const [selectedParent, setSelectedParent] = useState('')
  const [saving, setSaving] = useState(false)

  const { data: client, isLoading } = useQuery<Client>({
    queryKey: ['client', domain],
    queryFn: () => api.clients.get(domain),
  })

  const { data: allClients } = useQuery<Client[]>({
    queryKey: ['clients'],
    queryFn: () => api.clients.list(0, 200),
  })

  async function handleLink() {
    if (!selectedParent) return
    setSaving(true)
    await api.clients.link(domain, selectedParent)
    queryClient.invalidateQueries({ queryKey: ['client', domain] })
    queryClient.invalidateQueries({ queryKey: ['clients'] })
    setLinkingParent(false)
    setSelectedParent('')
    setSaving(false)
  }

  async function handleUnlink() {
    await api.clients.unlink(domain)
    queryClient.invalidateQueries({ queryKey: ['client', domain] })
    queryClient.invalidateQueries({ queryKey: ['clients'] })
  }

  return (
    <>
      <button type="button" aria-label="Close drawer" className="fixed inset-0 bg-black/50 z-40 cursor-default" onClick={onClose} />
      <div className="fixed top-0 right-0 h-full w-full max-w-xl bg-app-drawer border-l border-app-border shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-app-border shrink-0">
          <h2 className="text-sm font-semibold text-slate-950 truncate pr-4">
            {isLoading ? 'Loading...' : client ? client.display_name : domain}
          </h2>
          <button onClick={onClose} className="text-app-nav-text hover:text-slate-950 shrink-0">
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-app-nav-text text-sm">Loading...</div>
        ) : !client ? (
          <div className="flex-1 flex items-center justify-center text-app-nav-text text-sm">Not found</div>
        ) : (
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs text-app-nav-text mb-0.5">Company</p>
                <p className="text-slate-950 font-medium">{client.display_name}</p>
              </div>
              <div>
                <p className="text-xs text-app-nav-text mb-0.5">Domain</p>
                <p className="text-slate-950 font-medium">{client.domain || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-app-nav-text mb-0.5">Total tickets</p>
                <p className="text-2xl font-bold text-app-accent">{client.ticket_count}</p>
              </div>
              <div>
                <p className="text-xs text-app-nav-text mb-0.5">Handled by</p>
                <p className="text-slate-600 text-xs">{(client.agents ?? []).filter(Boolean).join(', ') || '—'}</p>
              </div>
            </div>

            {/* Parent client link */}
            <div className="border border-app-border rounded-lg p-4 space-y-2">
              <p className="text-xs font-medium text-app-nav-text uppercase tracking-wide">Works for</p>
              {client.parent_domain ? (
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-950">
                      {client.parent_name || client.parent_domain}
                    </p>
                    <p className="text-xs text-app-nav-text">{client.parent_domain}</p>
                  </div>
                  <button
                    onClick={handleUnlink}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    Unlink
                  </button>
                </div>
              ) : linkingParent ? (
                <div className="flex items-center gap-2">
                  <select
                    value={selectedParent}
                    onChange={e => setSelectedParent(e.target.value)}
                    className="flex-1 text-sm border border-app-border rounded-lg px-2 py-1.5 bg-app-bg text-slate-950 focus:outline-none focus:ring-2 focus:ring-app-accent"
                  >
                    <option value="">Select client…</option>
                    {(allClients ?? [])
                      .filter(c => c.domain !== domain && !c.parent_domain)
                      .map(c => (
                        <option key={c.domain} value={c.domain}>
                          {c.display_name} ({c.domain})
                        </option>
                      ))}
                  </select>
                  <button
                    onClick={handleLink}
                    disabled={!selectedParent || saving}
                    className="px-3 py-1.5 text-xs bg-app-accent text-app-bg rounded-lg hover:opacity-90 disabled:opacity-50"
                  >
                    {saving ? 'Saving…' : 'Link'}
                  </button>
                  <button
                    onClick={() => { setLinkingParent(false); setSelectedParent('') }}
                    className="text-xs text-app-nav-text hover:text-slate-950"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setLinkingParent(true)}
                  className="text-xs text-app-accent hover:opacity-80"
                >
                  + Link to parent client
                </button>
              )}
            </div>

            {(client.tickets ?? []).length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs text-app-nav-text">Tickets</p>
                  {(client.ticket_count ?? 0) > 50 && (
                    <p className="text-xs text-app-nav-text">Showing 50 of {client.ticket_count}</p>
                  )}
                </div>
                <div className="space-y-1">
                  {(client.tickets ?? []).map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      className="w-full text-left flex items-center justify-between text-xs py-1.5 border-b border-app-border cursor-pointer hover:bg-app-nav-hover -mx-2 px-2 rounded"
                      onClick={() => setSelectedTicketId(String(t.id))}
                    >
                      <span className="text-slate-600 truncate pr-2">{t.subject}</span>
                      <span className={`shrink-0 text-[10px] px-2 py-0.5 rounded-full border font-normal ${{
                        solved:  'bg-slate-500 text-white border-transparent',
                        closed:  'bg-slate-500 text-white border-transparent',
                        resolved: 'bg-slate-500 text-white border-transparent',
                        open:    'bg-blue-900/30 text-blue-400 border-transparent',
                        new:     'bg-blue-900/30 text-blue-400 border-transparent',
                        pending: 'bg-yellow-900/30 text-yellow-400 border-transparent',
                        hold:    'bg-app-nav-hover text-app-nav-text border-transparent',
                        active:  'bg-blue-900/30 text-blue-400 border-transparent',
                      }[t.status?.toLowerCase()] ?? 'bg-app-nav-hover text-app-nav-text border-transparent'}`}>{t.status}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      <TicketDrawer
        ticketId={selectedTicketId}
        onClose={() => setSelectedTicketId(null)}
      />
    </>
  )
}

export function Clients() {
  const [search, setSearch] = useState('')
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null)

  const { data: clients, isLoading } = useQuery<Client[]>({
    queryKey: ['clients', search],
    queryFn: () => api.clients.list(0, 50, search || undefined),
  })
  const { data: stats } = useStats()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-950">Clients</h1>
            {stats?.clients != null && (
              <span className="text-sm font-medium px-2.5 py-0.5 rounded-full bg-app-nav-hover text-app-nav-text font-mono">
                {stats.clients}
              </span>
            )}
          </div>
          <p className="text-app-nav-text mt-1">Companies derived from imported tickets.</p>
        </div>
        <input
          type="text"
          placeholder="Search by name or domain…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="text-sm border border-app-border rounded-full px-4 py-2 w-64 bg-app-panel text-slate-950 placeholder-app-nav-text focus:outline-none focus:border-slate-950/30"
        />
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-app-nav-text">Loading...</div>
      ) : !clients?.length ? (
        <div className="text-center py-12 text-app-nav-text">
          {search ? 'No clients match your search.' : 'No clients yet. Import tickets to populate this list.'}
        </div>
      ) : (
        <div className="bg-app-panel rounded-lg border border-app-border divide-y divide-app-border">
          {clients.map((client) => (
            <button
              key={client.domain || client.name}
              type="button"
              className="w-full text-left px-5 py-4 flex items-center justify-between gap-4 hover:bg-app-nav-hover cursor-pointer transition-colors"
              onClick={() => setSelectedDomain(client.domain)}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-slate-950">{client.display_name}</p>
                  {client.parent_domain && (
                    <span className="text-xs bg-app-accent-bg text-app-accent px-1.5 py-0.5 rounded shrink-0">
                      → {client.parent_name || client.parent_domain}
                    </span>
                  )}
                </div>
                <p className="text-xs text-app-nav-text mt-0.5">{client.domain}</p>
              </div>
              <div className="text-right shrink-0">
                <p className="text-2xl font-bold text-app-accent">{client.ticket_count}</p>
                <p className="text-xs text-app-nav-text">tickets</p>
              </div>
            </button>
          ))}
        </div>
      )}

      {selectedDomain && (
        <ClientDetail domain={selectedDomain} onClose={() => setSelectedDomain(null)} />
      )}
    </div>
  )
}
