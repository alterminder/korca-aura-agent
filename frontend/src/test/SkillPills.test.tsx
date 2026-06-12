import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MAX_SKILLS, SkillPills } from '../components/experts/SkillPills'

function renderSkillPills(overrides: Partial<Parameters<typeof SkillPills>[0]> = {}) {
  const props = {
    skills: [],
    skillInput: '',
    onSkillInputChange: vi.fn(),
    onSkillInputKeyDown: vi.fn(),
    onRemove: vi.fn(),
    generating: false,
    onGenerate: vi.fn(),
    showGenerate: false,
    ...overrides,
  }
  return { ...render(<SkillPills {...props} />), props }
}

describe('SkillPills', () => {
  it('renders each skill as a pill', () => {
    renderSkillPills({ skills: ['react', 'typescript', 'neo4j'] })
    expect(screen.getByText('react')).toBeInTheDocument()
    expect(screen.getByText('typescript')).toBeInTheDocument()
    expect(screen.getByText('neo4j')).toBeInTheDocument()
  })

  it('shows skill count', () => {
    renderSkillPills({ skills: ['react', 'typescript'] })
    expect(screen.getByText(`2/${MAX_SKILLS}`)).toBeInTheDocument()
  })

  it('calls onRemove with the correct index when × is clicked', async () => {
    const onRemove = vi.fn()
    renderSkillPills({ skills: ['react', 'typescript'], onRemove })
    const removeButtons = screen.getAllByText('×')
    await userEvent.click(removeButtons[0])
    expect(onRemove).toHaveBeenCalledWith(0)
  })

  it('shows the text input when skills is below MAX_SKILLS', () => {
    renderSkillPills({ skills: ['react'] })
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('hides the text input when skills equals MAX_SKILLS', () => {
    const fullSkills = Array.from({ length: MAX_SKILLS }, (_, i) => `skill${i}`)
    renderSkillPills({ skills: fullSkills })
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('shows generate button when showGenerate is true', () => {
    renderSkillPills({ showGenerate: true })
    expect(screen.getByText('✦ Generate skill cloud')).toBeInTheDocument()
  })

  it('hides generate button when showGenerate is false', () => {
    renderSkillPills({ showGenerate: false })
    expect(screen.queryByText('✦ Generate skill cloud')).not.toBeInTheDocument()
  })

  it('shows loading label while generating', () => {
    renderSkillPills({ showGenerate: true, generating: true })
    expect(screen.getByText('Generating…')).toBeInTheDocument()
  })

  it('calls onGenerate when the generate button is clicked', async () => {
    const onGenerate = vi.fn()
    renderSkillPills({ showGenerate: true, onGenerate })
    await userEvent.click(screen.getByText('✦ Generate skill cloud'))
    expect(onGenerate).toHaveBeenCalledOnce()
  })

  it('calls onSkillInputChange when the input changes', async () => {
    const onSkillInputChange = vi.fn()
    renderSkillPills({ onSkillInputChange })
    await userEvent.type(screen.getByRole('textbox'), 'a')
    expect(onSkillInputChange).toHaveBeenCalled()
  })
})
