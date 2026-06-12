import { describe, expect, it } from 'vitest'
import { auraRoutingStatusDisplay, hasActiveAuraRouting } from '../components/ticketRoutingHelpers'
import type { Ticket } from '../types'

function ticket(routing_status: Ticket['routing_status']): Ticket {
  return { routing_status } as Ticket
}

describe('hasActiveAuraRouting', () => {
  it('returns true for queued', () => {
    expect(hasActiveAuraRouting(ticket('queued'))).toBe(true)
  })

  it('returns true for running', () => {
    expect(hasActiveAuraRouting(ticket('running'))).toBe(true)
  })

  it('returns false for non-active statuses', () => {
    expect(hasActiveAuraRouting(ticket('confirmed'))).toBe(false)
    expect(hasActiveAuraRouting(ticket('no_recommendation'))).toBe(false)
    expect(hasActiveAuraRouting(ticket('failed'))).toBe(false)
    expect(hasActiveAuraRouting(ticket('unrouted'))).toBe(false)
  })

  it('returns false for null/undefined', () => {
    expect(hasActiveAuraRouting(null)).toBe(false)
    expect(hasActiveAuraRouting(undefined)).toBe(false)
  })
})

describe('auraRoutingStatusDisplay', () => {
  it('returns queued badge for queued', () => {
    const result = auraRoutingStatusDisplay(ticket('queued'))
    expect(result).not.toBeNull()
    expect(result!.label).toContain('queued')
    expect(result!.className).toContain('sky')
  })

  it('returns in-progress badge for running', () => {
    const result = auraRoutingStatusDisplay(ticket('running'))
    expect(result).not.toBeNull()
    expect(result!.label).toContain('progress')
    expect(result!.className).toContain('blue')
  })

  it('returns no-recommendation badge', () => {
    const result = auraRoutingStatusDisplay(ticket('no_recommendation'))
    expect(result).not.toBeNull()
    expect(result!.label).toContain('recommendation')
    expect(result!.className).toContain('amber')
  })

  it('returns failed badge', () => {
    const result = auraRoutingStatusDisplay(ticket('failed'))
    expect(result).not.toBeNull()
    expect(result!.label).toContain('failed')
    expect(result!.className).toContain('red')
  })

  it('returns null for statuses without a badge', () => {
    expect(auraRoutingStatusDisplay(ticket('confirmed'))).toBeNull()
    expect(auraRoutingStatusDisplay(ticket('suggested'))).toBeNull()
    expect(auraRoutingStatusDisplay(ticket('unrouted'))).toBeNull()
    expect(auraRoutingStatusDisplay({} as Ticket)).toBeNull()
  })
})
