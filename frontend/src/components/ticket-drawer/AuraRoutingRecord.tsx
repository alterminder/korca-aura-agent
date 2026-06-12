import type { Ticket, User } from '../../types'

interface AuraRoutingRecordProps {
  ticket: Ticket
  allExperts: User[] | undefined
  confidenceLabel: string | null
}

function MatchIcon({ outcome }: { readonly outcome: string | null | undefined }) {
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
  return null
}

export function AuraRoutingRecord({ ticket, allExperts, confidenceLabel }: AuraRoutingRecordProps) {
  const hasEvent = Boolean(ticket.latest_routing_event_id && ticket.latest_aura_suggestion_email)
  if (!hasEvent) return null

  const storedEmail = ticket.latest_aura_suggestion_email ?? null
  if (!storedEmail) return null
  const storedName = ticket.latest_aura_suggestion_name ?? null

  const expertName = storedName || allExperts?.find(e => e.email === storedEmail)?.name || storedEmail

  return (
    <div className="rounded-lg border border-app-border bg-app-nav-hover px-4 py-3 space-y-1.5">
      <p className="text-xs font-medium text-app-nav-text mb-2">Routing record</p>
      <div className="flex items-center justify-between">
        <span className="text-xs text-app-nav-text">Aura agent suggested</span>
        <div className="flex items-center gap-1.5">
          <MatchIcon outcome={ticket.latest_routing_event_outcome} />
          <span className="text-xs text-slate-950">
            {expertName}
            {confidenceLabel && (
              <span className="ml-1 opacity-60">({confidenceLabel})</span>
            )}
          </span>
        </div>
      </div>
    </div>
  )
}
