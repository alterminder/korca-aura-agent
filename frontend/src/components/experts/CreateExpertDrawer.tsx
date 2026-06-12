import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { XMarkIcon } from '@heroicons/react/24/outline'
import { api } from '../../api/client'
import type { User } from '../../types'
import { MAX_SKILLS, SkillPills } from './SkillPills'
import { DrawerFormField, DrawerManagerSelect } from './ExpertDrawerShared'

export function CreateExpertDrawer({ allUsers, onClose }: { allUsers: User[]; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [skillInput, setSkillInput] = useState('')
  const [form, setForm] = useState({
    name: '',
    email: '',
    title: '',
    department: '',
    manager_email: '',
    skills: [] as string[],
  })

  function addSkill(raw: string) {
    const val = raw.trim().toLowerCase()
    if (!val || form.skills.includes(val) || form.skills.length >= MAX_SKILLS) return
    setForm(f => ({ ...f, skills: [...f.skills, val] }))
  }

  function handleSkillKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === ',' || e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      addSkill(skillInput)
      setSkillInput('')
    } else if (e.key === 'Backspace' && skillInput === '' && form.skills.length > 0) {
      setForm(f => ({ ...f, skills: f.skills.slice(0, -1) }))
    }
  }

  async function handleCreate() {
    if (!form.name.trim() || !form.email.trim()) {
      setError('Name and email are required.')
      return
    }
    const pending = skillInput.trim().toLowerCase()
    const finalSkills = pending && !form.skills.includes(pending)
      ? [...form.skills, pending]
      : form.skills
    setSaving(true)
    setError(null)
    try {
      await api.users.create({
        name: form.name.trim(),
        email: form.email.trim(),
        title: form.title || undefined,
        department: form.department || undefined,
        skills: finalSkills,
      })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create expert')
      setSaving(false)
    }
  }

  return (
    <>
      <button type="button" aria-label="Close drawer" className="fixed inset-0 bg-black/50 z-40 cursor-default" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 w-full max-w-md bg-app-drawer border-l border-app-border shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-app-border shrink-0">
          <h2 className="text-sm font-semibold text-slate-950">Add Expert</h2>
          <button onClick={onClose} className="text-app-nav-text hover:text-slate-950">
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-900/20 border border-red-900/50 px-3 py-2 text-sm text-red-400">{error}</div>
          )}
          <DrawerFormField id="name" label="Name *" placeholder="e.g. Jane Smith" value={form.name} onChange={v => setForm(f => ({ ...f, name: v }))} />
          <DrawerFormField id="email" label="Email *" type="email" placeholder="jane@example.com" value={form.email} onChange={v => setForm(f => ({ ...f, email: v }))} />
          <DrawerFormField id="title" label="Title" placeholder="e.g. Senior Support Engineer" value={form.title} onChange={v => setForm(f => ({ ...f, title: v }))} />
          <DrawerFormField id="department" label="Department" placeholder="e.g. Support" value={form.department} onChange={v => setForm(f => ({ ...f, department: v }))} />
          <DrawerManagerSelect value={form.manager_email} allUsers={allUsers} onChange={v => setForm(f => ({ ...f, manager_email: v }))} />

          <SkillPills
            skills={form.skills}
            skillInput={skillInput}
            onSkillInputChange={setSkillInput}
            onSkillInputKeyDown={handleSkillKeyDown}
            onRemove={i => setForm(f => ({ ...f, skills: f.skills.filter((_, idx) => idx !== i) }))}
            generating={false}
            onGenerate={() => {}}
            showGenerate={false}
          />
        </div>

        <div className="px-6 py-4 border-t border-app-border shrink-0">
          <button
            onClick={handleCreate}
            disabled={saving}
            className="w-full inline-flex items-center justify-center px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? 'Creating...' : 'Create Expert'}
          </button>
        </div>
      </div>
    </>
  )
}
