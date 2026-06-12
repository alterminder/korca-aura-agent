import type { Ticket } from '../types'

export function auraRoutingStatusDisplay(ticket: Ticket): { label: string; className: string } | null {
  switch (ticket.routing_status) {
    case 'queued':
      return { label: 'Routing queued', className: 'bg-sky-500/10 text-sky-500 border-sky-500/30' }
    case 'running':
      return { label: 'Routing in progress', className: 'bg-blue-500/10 text-blue-500 border-blue-500/30' }
    case 'no_recommendation':
      return { label: 'No Aura recommendation', className: 'bg-amber-500/10 text-amber-500 border-amber-500/30' }
    case 'failed':
      return { label: 'Aura routing failed', className: 'bg-red-500/10 text-red-500 border-red-500/30' }
    default:
      return null
  }
}

export function hasActiveAuraRouting(ticket?: Ticket | null): boolean {
  return ticket?.routing_status === 'queued' || ticket?.routing_status === 'running'
}
