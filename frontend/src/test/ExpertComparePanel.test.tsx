import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExpertComparePanel } from '../components/experts/ExpertComparePanel'
import type { ExpertComparison } from '../types'

const BASE: ExpertComparison = {
  expert_a: { id: '1', name: 'Alice Smith', email: 'alice@example.com' },
  expert_b: { id: '2', name: 'Bob Jones', email: 'bob@example.com' },
  shared_clients: [],
  only_a_clients: [],
  only_b_clients: [],
  shared_skills: [],
  only_a_skills: [],
  only_b_skills: [],
}

describe('ExpertComparePanel', () => {
  it('renders both expert names in the header', () => {
    render(<ExpertComparePanel data={BASE} onClose={vi.fn()} />)
    expect(screen.getByText('Alice Smith')).toBeInTheDocument()
    expect(screen.getByText('Bob Jones')).toBeInTheDocument()
  })

  it('calls onClose when the × button is clicked', async () => {
    const onClose = vi.fn()
    render(<ExpertComparePanel data={BASE} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows shared clients', () => {
    const data: ExpertComparison = {
      ...BASE,
      shared_clients: [{ name: 'Acme Corp', count_a: 3, count_b: 5 }],
    }
    render(<ExpertComparePanel data={data} onClose={vi.fn()} />)
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('Shared clients (1)')).toBeInTheDocument()
  })

  it('shows only-A and only-B exclusive clients under the correct column', () => {
    const data: ExpertComparison = {
      ...BASE,
      only_a_clients: [{ name: 'Alpha Co', count: 2 }],
      only_b_clients: [{ name: 'Beta Ltd', count: 4 }],
    }
    render(<ExpertComparePanel data={data} onClose={vi.fn()} />)
    expect(screen.getByText('Alpha Co')).toBeInTheDocument()
    expect(screen.getByText('Beta Ltd')).toBeInTheDocument()
  })

  it('shows a fallback for clients without a name', () => {
    const data: ExpertComparison = {
      ...BASE,
      shared_clients: [{ name: null, count_a: 3, count_b: 5 }],
      only_a_clients: [{ name: null, count: 2 }],
      only_b_clients: [{ name: null, count: 4 }],
    }
    render(<ExpertComparePanel data={data} onClose={vi.fn()} />)
    expect(screen.getAllByText('Unknown client')).toHaveLength(3)
  })

  it('renders the skills section when skills are present', () => {
    const data: ExpertComparison = {
      ...BASE,
      only_a_skills: ['neo4j'],
      shared_skills: ['python'],
      only_b_skills: ['java'],
    }
    render(<ExpertComparePanel data={data} onClose={vi.fn()} />)
    expect(screen.getByText('Skills')).toBeInTheDocument()
    expect(screen.getByText('neo4j')).toBeInTheDocument()
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(screen.getByText('java')).toBeInTheDocument()
  })

  it('hides the skills section when there are no skills', () => {
    render(<ExpertComparePanel data={BASE} onClose={vi.fn()} />)
    expect(screen.queryByText('Skills')).not.toBeInTheDocument()
  })

  it('shows column header with first name of each expert', () => {
    render(<ExpertComparePanel data={BASE} onClose={vi.fn()} />)
    expect(screen.getByText('Only Alice (0)')).toBeInTheDocument()
    expect(screen.getByText('Only Bob (0)')).toBeInTheDocument()
  })
})
