import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { InformationCircleIcon, TrashIcon, XMarkIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../api/client'
import type { User } from '../../types'
import { MAX_SKILLS, SkillPills } from './SkillPills'
import { DrawerFormField, DrawerManagerSelect } from './ExpertDrawerShared'

interface EditState {
  title: string
  department: string
  manager_email: string
  skills: string[]
}

export function ExpertEditDrawer({ user, allUsers, onClose }: { user: User; allUsers: User[]; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [skillInput, setSkillInput] = useState('')
  const [form, setForm] = useState<EditState>({
    title: user.title ?? '',
    department: user.department ?? '',
    manager_email: user.manager_email ?? '',
    skills: user.skills ?? [],
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

  async function handleGenerate() {
    setGenerating(true)
    try {
      const res = await api.users.generateSkills(user.id)
      const merged = [...form.skills]
      for (const s of res.skills) {
        if (!merged.includes(s) && merged.length < MAX_SKILLS) merged.push(s)
      }
      setForm(f => ({ ...f, skills: merged }))
    } finally {
      setGenerating(false)
    }
  }

  async function handleDelete() {
    if (!confirm(`Remove ${user.name || user.email} from the knowledge graph?\n\nThis only removes them from Korca — their account in Teamwork Desk is not affected.`)) return
    setDeleting(true)
    await api.users.delete(user.id)
    queryClient.invalidateQueries({ queryKey: ['users'] })
    onClose()
  }

  async function handleSave() {
    const pending = skillInput.trim().toLowerCase()
    const finalSkills = pending && !form.skills.includes(pending)
      ? [...form.skills, pending]
      : form.skills
    setSaving(true)
    try {
      await api.users.updateProfile(user.id, {
        title: form.title,
        department: form.department,
        manager_email: form.manager_email,
        skills: finalSkills,
      })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save expert')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <button type="button" aria-label="Close drawer" className="fixed inset-0 bg-black/50 z-40 cursor-default" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 w-full max-w-md bg-app-drawer border-l border-app-border shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-app-border shrink-0">
          <h2 className="text-sm font-semibold text-slate-950">Edit — {user.name || user.email}</h2>
          <button onClick={onClose} className="text-app-nav-text hover:text-slate-950">
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <p className="text-xs text-app-nav-text">{user.email}</p>

          <DrawerFormField id="title" label="Title" placeholder="e.g. Senior Support Engineer" value={form.title} onChange={v => setForm(f => ({ ...f, title: v }))} />
          <DrawerFormField id="department" label="Department" placeholder="e.g. Support" value={form.department} onChange={v => setForm(f => ({ ...f, department: v }))} />
          <DrawerManagerSelect value={form.manager_email} allUsers={allUsers} excludeId={user.id} onChange={v => setForm(f => ({ ...f, manager_email: v }))} />

          <SkillPills
            skills={form.skills}
            skillInput={skillInput}
            onSkillInputChange={setSkillInput}
            onSkillInputKeyDown={handleSkillKeyDown}
            onRemove={i => setForm(f => ({ ...f, skills: f.skills.filter((_, idx) => idx !== i) }))}
            generating={generating}
            onGenerate={handleGenerate}
            showGenerate={true}
          />

          <button
            onClick={handleSave}
            disabled={saving || deleting}
            className="w-full inline-flex items-center justify-center px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>

        <div className="px-6 py-4 border-t border-app-border shrink-0 space-y-3">
          <div className="flex items-start gap-2 text-xs text-app-nav-text">
            <InformationCircleIcon className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <p>
              <span className="font-medium text-slate-950">Delete</span> removes this expert from Korca and detaches them from all ticket assignments.{' '}
              Korca <span className="font-bold text-slate-950">never</span> deletes experts from Teamwork Desk.
            </p>
          </div>
          <button
            onClick={handleDelete}
            disabled={saving || deleting}
            className="w-full inline-flex items-center justify-center gap-1.5 px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <TrashIcon className="w-3.5 h-3.5" />
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </>
  )
}
