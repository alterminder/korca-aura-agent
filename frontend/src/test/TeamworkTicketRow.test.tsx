import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TicketRow } from '../components/teamwork/TicketRow'
import type { Ticket } from '../types'

function renderRow(ticket: Partial<Ticket>) {
  return render(
    <TicketRow
      ticket={{
        id: '123',
        subject: 'Website update',
        status: 'Active',
        client_name: null,
        client_display_name: null,
        ...ticket,
      } as Ticket}
      expertNameByEmail={new Map()}
      onSelect={vi.fn()}
    />,
  )
}

describe('TicketRow', () => {
  it('keeps Active status text but uses the neutral open-ticket badge', () => {
    renderRow({ status: 'Active' })

    const status = screen.getByText('Active')
    expect(status).toBeInTheDocument()
    expect(status).toHaveClass('bg-app-nav-hover')
    expect(status).not.toHaveClass('bg-blue-900/30')
  })

  it('shows derived client display name when explicit client name is missing', () => {
    renderRow({ client_display_name: 'Example Staffing' })

    expect(screen.getByText('Example Staffing')).toBeInTheDocument()
  })
})
