import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cog6ToothIcon } from '@heroicons/react/24/outline'
import { api, type TeamworkImportProgress } from '../api/client'
import { TicketDrawer } from '../components/TicketDrawer'
import { FiltersBar } from '../components/teamwork/FiltersBar'
import { EMPTY_FILTERS, type ImportTeamworkFilters } from '../components/teamwork/filters'
import { SettingsDrawer } from '../components/teamwork/TeamworkSettingsDrawer'
import { TicketListHeader, TicketRow } from '../components/teamwork/TicketRow'
import type { Ticket } from '../types'

const TEAMWORK_IMPORT_PROGRESS_URL = '/api/import/teamwork/progress'

function hasActiveAuraRouting(ticket?: Ticket | null): boolean {
  return ticket?.routing_status === 'queued' || ticket?.routing_status === 'running'
}

function isTerminalImportStatus(status: string): boolean {
  return status === 'completed' || status === 'error' || status === 'idle'
}

function isVisibleImportProgress(progress?: TeamworkImportProgress | null): boolean {
  return Boolean(progress && progress.status !== 'idle')
}

function ticketRefetchInterval(query: { state: { data: unknown } }): number | false {
  const tickets = query.state.data as Ticket[] | undefined
  return tickets?.some(hasActiveAuraRouting) ? 2000 : false
}

function EmptyTicketState({ hasExisting, importing, onImport }: {
  readonly hasExisting: boolean
  readonly importing: boolean
  readonly onImport: () => void
}) {
  if (hasExisting) {
    return (
      <div className="py-16 text-center space-y-2">
        <p className="text-sm font-medium text-slate-950">No matching tickets</p>
        <p className="text-xs text-app-nav-text">Try adjusting your filters</p>
      </div>
    )
  }
  return (
    <div className="py-16 text-center space-y-3">
      <p className="text-sm font-medium text-slate-950">No tickets yet</p>
      <p className="text-xs text-app-nav-text">Import your Teamwork Desk ticket history to get started</p>
      <button
        onClick={onImport}
        disabled={importing}
        className="mt-2 px-5 py-2 text-sm bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {importing ? 'Importing…' : 'Import tickets'}
      </button>
    </div>
  )
}

export function ImportTeamwork() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const es = new EventSource('/api/events/tickets')
    es.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets-count'] })
      queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
    }
    return () => es.close()
  }, [queryClient])

  const [progress, setProgress] = useState<TeamworkImportProgress | null>(null)
  const [importing, setImporting] = useState(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [purging, setPurging] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [page, setPage] = useState(0)
  const [sortByStatus, setSortByStatus] = useState(false)
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [filters, setFilters] = useState<ImportTeamworkFilters>(EMPTY_FILTERS)
  const esRef = useRef<EventSource | null>(null)
  const terminalProgressRef = useRef(false)

  const LIMIT = 20

  function applyFilters(next: ImportTeamworkFilters) {
    setFilters(next)
    setPage(0)
  }

  const { data: filterOptions } = useQuery({
    queryKey: ['import-teamwork-filters'],
    queryFn: api.import.teamworkFilterOptions,
  })

  const { data: allExperts } = useQuery({
    queryKey: ['users'],
    queryFn: api.users.list,
  })

  const expertNameByEmail = new Map(
    (allExperts ?? [])
      .filter(expert => expert.email && expert.name)
      .map(expert => [expert.email.toLowerCase(), expert.name])
  )

  const { data: status } = useQuery({
    queryKey: ['import-teamwork-status'],
    queryFn: api.import.teamworkStatus,
    refetchInterval: importing ? 3000 : false,
  })

  const { data: syncState } = useQuery({
    queryKey: ['teamwork-sync-state'],
    queryFn: api.import.teamworkSyncState,
  })

  const { data: autoSync } = useQuery({
    queryKey: ['teamwork-auto-sync'],
    queryFn: api.import.teamworkAutoSync,
  })

  const { data: aiAccuracy } = useQuery({
    queryKey: ['ai-accuracy'],
    queryFn: api.import.aiAccuracy,
  })

  const { data: tickets, isLoading: ticketsLoading } = useQuery<Ticket[]>({
    queryKey: ['import-teamwork-tickets', page, filters, sortByStatus],
    queryFn: () => api.import.listTickets(page * LIMIT, LIMIT, { ...filters, sort_by_status: sortByStatus }),
    refetchInterval: ticketRefetchInterval,
  })

  const { data: ticketCount } = useQuery({
    queryKey: ['import-teamwork-tickets-count', filters],
    queryFn: () => api.import.countTickets(filters),
  })

  const refreshImportData = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets-count'] })
    queryClient.invalidateQueries({ queryKey: ['teamwork-sync-state'] })
    queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }, [queryClient])

  const closeProgressStream = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
  }, [])

  const handleImportProgress = useCallback((data: TeamworkImportProgress) => {
    if (isVisibleImportProgress(data)) {
      setProgress(data)
    } else {
      setProgress(null)
    }

    if (!isTerminalImportStatus(data.status)) return

    terminalProgressRef.current = true
    closeProgressStream()
    setImporting(false)
    refreshImportData()
  }, [closeProgressStream, refreshImportData])

  const openProgressStream = useCallback(() => {
    if (esRef.current) return

    terminalProgressRef.current = false
    const es = new EventSource(TEAMWORK_IMPORT_PROGRESS_URL, { withCredentials: false })
    esRef.current = es

    es.onmessage = (e) => {
      handleImportProgress(JSON.parse(e.data) as TeamworkImportProgress)
    }

    es.onerror = () => {
      if (terminalProgressRef.current) return
      closeProgressStream()
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
    }
  }, [closeProgressStream, handleImportProgress, queryClient])

  const saveAutoSync = useMutation({
    mutationFn: api.import.setTeamworkAutoSync,
    onSuccess: (data) => {
      queryClient.setQueryData(['teamwork-auto-sync'], data)
    },
  })

  const syncNow = useMutation({
    mutationFn: api.import.syncTeamworkNow,
    onSuccess: (result) => {
      setSyncMessage(`${result.processed} checked · ${result.imported} imported · ${result.updated} updated · ${result.protected_skipped} protected`)
      queryClient.invalidateQueries({ queryKey: ['teamwork-sync-state'] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets-count'] })
      queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err) => {
      setSyncMessage(String(err instanceof Error ? err.message : err))
    },
  })

  useEffect(() => {
    return () => {
      closeProgressStream()
    }
  }, [closeProgressStream])

  useEffect(() => {
    const currentProgress = status?.progress
    if (currentProgress && isVisibleImportProgress(currentProgress)) {
      setProgress(currentProgress)
    } else if (currentProgress?.status === 'idle') {
      setProgress(null)
    }

    if (status?.import_running) {
      setImporting(true)
      openProgressStream()
      return
    }

    if (status) {
      setImporting(false)
    }
  }, [openProgressStream, status])

  async function purgeBlocked(prefix?: string, block = false) {
    if (purging) return
    setPurging(true)
    try {
      const res = await api.import.purgeBlockedTickets(prefix, block)
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets-count'] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
      queryClient.invalidateQueries({ queryKey: ['staged-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      alert(`Removed ${res.deleted} blocked ticket${res.deleted !== 1 ? 's' : ''}.`)
    } finally {
      setPurging(false)
    }
  }

  async function clearTickets() {
    if (importing) return
    await api.import.clearTeamworkTickets()
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
    queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }

  function startSyncNow() {
    if (syncNow.isPending || importing) return
    setSyncMessage('Syncing Teamwork updates…')
    syncNow.mutate()
  }

  async function startImport() {
    if (importing) return
    setImporting(true)
    setProgress({ status: 'queued', message: 'Import queued...' })

    try {
      const result = await api.import.startTeamworkImport()
      if (result.status === 'already_running') {
        setProgress({ status: 'running', message: 'Import already running...' })
      }
      openProgressStream()
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
    } catch (err) {
      setProgress({
        status: 'error',
        message: err instanceof Error ? err.message : 'Could not start import',
        error: String(err),
      })
      setImporting(false)
    }
  }

  const processed = progress
    ? progress.processed ?? ((progress.imported ?? 0) + (progress.skipped ?? 0) + (progress.failed ?? 0))
    : 0

  const pct = progress?.total
    ? Math.round(processed / progress.total * 100)
    : 0

  const lastUpdated = syncState?.state?.last_run_at
    ? new Date(syncState.state.last_run_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div>
      <TicketDrawer
        ticketId={selectedTicketId}
        onClose={() => setSelectedTicketId(null)}
        onDeleted={() => {
          queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
          queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets-count'] })
          queryClient.invalidateQueries({ queryKey: ['import-teamwork-status'] })
        }}
      />

      {showSettings && (
        <SettingsDrawer
          onClose={() => setShowSettings(false)}
          importing={importing}
          syncing={syncNow.isPending}
          syncState={syncState?.state}
          autoSync={autoSync}
          onSaveAutoSync={(settings) => saveAutoSync.mutate(settings)}
          savingAutoSync={saveAutoSync.isPending}
          onPurgeBlocked={purgeBlocked}
          onClear={clearTickets}
        />
      )}

      {/* Page header */}
      <div className="flex items-center justify-between gap-4 mb-8">
        <div className="flex items-center gap-4">
          <img src="/teamwork-desk.svg" alt="Teamwork Desk" className="h-10 object-contain" />
          <h1 className="text-2xl font-bold text-slate-950">Teamwork Desk</h1>
        </div>
        <button
          onClick={() => setShowSettings(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors"
          title="Teamwork import and routing settings"
        >
          <Cog6ToothIcon className="w-4 h-4" />
          Settings
        </button>
      </div>

      {/* Stats */}
      <div className="bg-app-panel rounded-lg border border-app-border p-5 mb-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm text-app-nav-text">Tickets in graph</p>
            <p className="text-3xl font-bold text-slate-950 font-mono">{status?.tickets_in_graph ?? '—'}</p>
            {lastUpdated && (
              <p className="text-xs text-app-nav-text mt-1">Last updated {lastUpdated}</p>
            )}
            {syncMessage && (
              <p className={`text-xs mt-1 ${syncNow.isError ? 'text-red-400' : 'text-app-accent'}`}>{syncMessage}</p>
            )}
          </div>
          {(aiAccuracy?.evaluated ?? 0) > 0 && (
            <div className="flex gap-6 text-right">
              <div>
                <p className="text-sm text-app-nav-text">✦ Aura accuracy</p>
                <p className={`text-3xl font-bold font-mono ${(aiAccuracy!.accuracy_pct ?? 0) >= 80 ? 'text-purple-400' : 'text-amber-400'}`}>
                  {aiAccuracy!.accuracy_pct}%
                </p>
                <p className="text-xs text-app-nav-text mt-0.5 font-mono font-normal">{aiAccuracy!.correct}/{aiAccuracy!.evaluated} verified</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Progress */}
      {progress && (
        <div className="bg-app-panel rounded-lg border border-app-border p-5 mb-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-slate-950">{progress.message}</span>
            {progress.total && (
              <span className="text-sm text-app-nav-text">{pct}%</span>
            )}
          </div>
          {progress.total && (
            <div className="w-full bg-app-nav-hover rounded-full h-2 mb-3">
              <div
                className={`h-2 rounded-full transition-all ${progress.status === 'error' ? 'bg-red-500' : progress.status === 'completed' ? 'bg-green-500' : 'bg-app-accent'}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          )}
          {progress.total && (
            <div className="flex gap-6 text-xs text-app-nav-text">
              <span className="text-green-400">{progress.imported ?? 0} imported</span>
              <span className="text-app-nav-text">{progress.skipped ?? 0} skipped</span>
              {(progress.failed ?? 0) > 0 && (
                <span className="text-red-400">{progress.failed} failed</span>
              )}
              <span>{progress.total} total</span>
            </div>
          )}
        </div>
      )}

      {/* Initial Import Banner */}
      {syncState && !syncState.initialized && !importing && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-5 mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <p className="text-sm font-semibold text-slate-950">Initial import incomplete</p>
            <p className="text-xs text-app-nav-text">
              {status?.tickets_in_graph
                ? `Only ${status.tickets_in_graph} tickets have been imported. Resume the import to get all historical data and set up automatic syncing.`
                : 'Import your Teamwork Desk ticket history to get started.'}
            </p>
          </div>
          <button
            onClick={startImport}
            className="px-4 py-2 text-xs font-semibold bg-slate-950 text-white rounded-full hover:bg-slate-800 transition-colors shrink-0 self-start sm:self-auto"
          >
            {status?.tickets_in_graph ? 'Continue Import' : 'Import Tickets'}
          </button>
        </div>
      )}

      <FiltersBar filters={filters} onFiltersChange={applyFilters} filterOptions={filterOptions} />

      {/* Ticket list */}
      <div className="bg-app-panel rounded-lg">
        {ticketsLoading ? (
          <div className="py-12 text-center text-app-nav-text text-sm">Loading...</div>
        ) : !tickets?.length ? (
          <EmptyTicketState
            hasExisting={(status?.tickets_in_graph ?? 0) > 0}
            importing={importing}
            onImport={startImport}
          />
        ) : (
          <>
            <TicketListHeader
              sortByStatus={sortByStatus}
              onSortToggle={() => setSortByStatus(s => !s)}
              ticketCount={ticketCount?.count}
              importing={importing}
              syncing={syncNow.isPending}
              syncInitialized={Boolean(syncState?.initialized)}
              onSyncNow={startSyncNow}
            />
            <div className="divide-y divide-app-border">
              {tickets.map((ticket) => (
                <TicketRow
                  key={ticket.id}
                  ticket={ticket}
                  expertNameByEmail={expertNameByEmail}
                  onSelect={setSelectedTicketId}
                />
              ))}
            </div>
            <div className="px-5 py-3 border-t border-app-border flex items-center justify-between">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="text-sm text-app-accent disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <span className="text-xs text-app-nav-text">
                Page {page + 1}{ticketCount === undefined ? '' : ` of ${Math.max(1, Math.ceil(ticketCount.count / LIMIT))}`}
              </span>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={(tickets?.length ?? 0) < LIMIT}
                className="text-sm text-app-accent disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
