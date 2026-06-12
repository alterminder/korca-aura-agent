import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { SparklesIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import type { Ticket } from '../types'
import { auraRoutingStatusDisplay, hasActiveAuraRouting } from './ticketRoutingHelpers'

export function RoutingSection({ ticket }: { ticket: Ticket }) {
  const queryClient = useQueryClient()
  const ticketId = String(ticket.id)

  const [auraRouting, setAuraRouting] = useState(false)
  const [auraExpert, setAuraExpert] = useState<{ name: string | null; email: string | null } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [teamworkAction, setTeamworkAction] = useState<string | null>(null)
  const [teamworkActionPending, setTeamworkActionPending] = useState<'post' | 'assign' | 'post-staging' | 'assign-staging' | null>(null)

  // Sync with fresh ticket data whenever the query refetches
  useEffect(() => {
    setAuraExpert(null)
  }, [ticket.routing_suggestions])

  const { data: allExperts } = useQuery({
    queryKey: ['users'],
    queryFn: api.users.list,
    enabled: !!ticket.latest_aura_suggestion_email || !!ticket.aura_suggestion_email,
  })

  // Staging actions are only usable when a staging expert email is configured
  // (the backend gates post/assign-staging-expert on it). Hide the block otherwise.
  const { data: routingMode } = useQuery({
    queryKey: ['teamwork-routing-mode'],
    queryFn: api.import.teamworkRoutingMode,
  })
  const stagingConfigured = routingMode?.staging_expert_configured ?? false

  async function handleAuraRoute() {
    setAuraRouting(true)
    setAuraExpert(null)
    setError(null)
    queryClient.setQueryData<Ticket>(['ticket', ticketId], (current) =>
      current ? { ...current, routing_status: 'running', aura_routing_error: null } : current,
    )
    queryClient.setQueriesData<Ticket[]>({ queryKey: ['import-teamwork-tickets'] }, (current) =>
      current?.map((row) =>
        String(row.id) === ticketId
          ? { ...row, routing_status: 'running', aura_routing_error: null }
          : row,
      ),
    )
    try {
      const res = await api.import.routeTicketAura(ticketId)
      setAuraExpert({ name: res.expert_name, email: res.expert_email })
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Aura routing failed')
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
    } finally {
      setAuraRouting(false)
    }
  }

  async function handlePostAuraSuggestion() {
    setTeamworkActionPending('post')
    setTeamworkAction(null)
    setError(null)
    try {
      await api.import.postAuraSuggestion(ticketId)
      setTeamworkAction('Posted private note to Teamwork.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not post private note')
    } finally {
      setTeamworkActionPending(null)
    }
  }

  async function handleAssignAuraSuggestion() {
    setTeamworkActionPending('assign')
    setTeamworkAction(null)
    setError(null)
    try {
      await api.import.assignAuraSuggestion(ticketId)
      setTeamworkAction('Assignment sent to Teamwork.')
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not assign expert')
    } finally {
      setTeamworkActionPending(null)
    }
  }

  async function handlePostStagingExpert() {
    setTeamworkActionPending('post-staging')
    setTeamworkAction(null)
    setError(null)
    try {
      await api.import.postStagingExpert(ticketId)
      setTeamworkAction('Posted staging private note to Teamwork.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not post staging private note')
    } finally {
      setTeamworkActionPending(null)
    }
  }

  async function handleAssignStagingExpert() {
    setTeamworkActionPending('assign-staging')
    setTeamworkAction(null)
    setError(null)
    try {
      await api.import.assignStagingExpert(ticketId)
      setTeamworkAction('Staging assignment sent to Teamwork.')
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
      queryClient.invalidateQueries({ queryKey: ['import-teamwork-tickets'] })
      queryClient.invalidateQueries({ queryKey: ['ai-accuracy'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not assign staging expert')
    } finally {
      setTeamworkActionPending(null)
    }
  }

  const hasAuraRoutingEvent = Boolean(ticket.latest_routing_event_id && ticket.latest_aura_suggestion_email)
  const storedAuraEmail = hasAuraRoutingEvent ? ticket.latest_aura_suggestion_email : null
  const storedAuraName = ticket.latest_aura_suggestion_name
  const storedAuraExpert = storedAuraEmail
    ? {
        email: storedAuraEmail,
        name: storedAuraName ?? allExperts?.find(e => e.email === storedAuraEmail)?.name ?? null,
      }
    : null
  const currentAuraExpert = auraExpert ?? storedAuraExpert
  const auraRoutingStatus = auraRoutingStatusDisplay(ticket)
  const graphRoutingActive = hasActiveAuraRouting(ticket)
  const routingActive = auraRouting || graphRoutingActive
  const routeLabel = routingActive
    ? 'Routing...'
    : currentAuraExpert
    ? 'Reroute'
    : 'Find Expert'

  return (
    <div className="border border-app-border rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-app-nav-text uppercase tracking-wide">Routing Suggestion</p>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAuraRoute}
            disabled={routingActive}
            className="text-xs text-app-accent hover:opacity-80 disabled:opacity-50 font-medium"
            title="Use Neo4j Aura agent to recommend an expert"
          >
            {routeLabel}
          </button>
        </div>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}
      {teamworkAction && <p className="text-xs text-green-400">{teamworkAction}</p>}

      {routingActive && (
        <div className="space-y-2">
          {[1, 2, 3].map(i => <div key={i} className="h-8 bg-app-nav-hover rounded animate-pulse" />)}
        </div>
      )}

      {!auraRouting && auraRoutingStatus && (graphRoutingActive || !currentAuraExpert) && (
        <div className={`rounded-lg border px-3 py-2 text-xs font-medium ${auraRoutingStatus.className}`}>
          {auraRoutingStatus.label}
          {ticket.aura_routing_error && (
            <p className="mt-1 font-normal opacity-80">{ticket.aura_routing_error}</p>
          )}
        </div>
      )}

      {ticket.teamwork_action_error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          <span className="font-medium">Teamwork action failed</span>
          <p className="mt-0.5 font-normal">{ticket.teamwork_action_error}</p>
        </div>
      )}

      {/* Aura result card */}
      {currentAuraExpert && !routingActive && (
        <div className="rounded-lg border border-app-border bg-app-nav-hover px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-purple-400 flex items-center gap-1"><SparklesIcon className="w-3 h-3" /> Aura agent recommends</span>
            {currentAuraExpert.name || currentAuraExpert.email
              ? <span className="text-xs font-bold text-slate-950">{currentAuraExpert.name || currentAuraExpert.email}</span>
              : <span className="text-xs text-app-nav-text italic">No recommendation</span>
            }
          </div>
          {currentAuraExpert.email && (
            <div className="space-y-2 mt-3">
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handlePostAuraSuggestion}
                  disabled={teamworkActionPending !== null}
                  className="px-3 py-1.5 text-xs font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {teamworkActionPending === 'post' ? 'Posting...' : 'Post a note'}
                </button>
                <button
                  onClick={handleAssignAuraSuggestion}
                  disabled={teamworkActionPending !== null}
                  className="px-3 py-1.5 text-xs font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {teamworkActionPending === 'assign' ? 'Assigning...' : 'Assign expert'}
                </button>
              </div>
              {stagingConfigured && (
                <div className="border-t border-app-border pt-2">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-app-nav-text">Staging</p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={handlePostStagingExpert}
                      disabled={teamworkActionPending !== null}
                      className="px-3 py-1.5 text-xs font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {teamworkActionPending === 'post-staging' ? 'Posting...' : 'Post a note'}
                    </button>
                    <button
                      onClick={handleAssignStagingExpert}
                      disabled={teamworkActionPending !== null}
                      className="px-3 py-1.5 text-xs font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {teamworkActionPending === 'assign-staging' ? 'Assigning...' : 'Assign expert'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

    </div>
  )
}
