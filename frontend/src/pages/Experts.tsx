import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PencilSquareIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { ExpertComparePanel } from '../components/experts/ExpertComparePanel'
import { ExpertEditDrawer } from '../components/experts/ExpertEditDrawer'
import { CreateExpertDrawer } from '../components/experts/CreateExpertDrawer'
import type { ExpertComparison, User } from '../types'

export function Experts() {
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [creating, setCreating] = useState(false)
  const [compareMode, setCompareMode] = useState(false)
  const [selected, setSelected] = useState<string[]>([])

  const { data: experts, isLoading } = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: api.users.list,
  })

  const { data: compareData, isFetching: comparing } = useQuery<ExpertComparison>({
    queryKey: ['users', 'compare', selected[0], selected[1]],
    queryFn: () => api.users.compare(selected[0], selected[1]),
    enabled: selected.length === 2,
  })

  function toggleCompareMode() {
    setCompareMode(v => !v)
    setSelected([])
  }

  function toggleSelect(id: string) {
    setSelected(prev => {
      if (prev.includes(id)) return prev.filter(x => x !== id)
      if (prev.length >= 2) return [prev[1], id]
      return [...prev, id]
    })
  }

  return (
    <>
      <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-950">Experts</h1>
          <p className="text-app-nav-text mt-1">People mapped in the knowledge graph. Click the edit icon to add title, department, and skills.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleCompareMode}
            className="px-4 py-2 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors"
          >
            {compareMode ? 'Exit Compare' : 'Compare'}
          </button>
          {!compareMode && (
            <button
              onClick={() => setCreating(true)}
              className="px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 transition-colors"
            >
              + Add Expert
            </button>
          )}
        </div>
      </div>

      {compareMode && (
        <p className="text-xs text-app-nav-text -mt-2">
          {selected.length === 0 && 'Select two experts to compare.'}
          {selected.length === 1 && 'Select one more expert.'}
          {selected.length === 2 && comparing && 'Loading comparison…'}
        </p>
      )}

      {isLoading ? (
        <div className="text-center py-12 text-app-nav-text">Loading...</div>
      ) : !experts?.length ? (
        <div className="text-center py-12 text-app-nav-text">
          No experts yet. Import tickets to start building the knowledge graph.
        </div>
      ) : (
        <div className="bg-app-panel rounded-lg border border-app-border divide-y divide-app-border">
          {experts.map((expert) => {
            const isSelected = selected.includes(expert.id)
            const expertInfo = (
              <>
                <div className="flex items-start gap-3 min-w-0 flex-1">
                  {compareMode && (
                    <div className={`mt-0.5 w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                      isSelected ? 'bg-app-accent border-app-accent' : 'border-app-border'
                    }`}>
                      {isSelected && <span className="text-app-bg text-xs leading-none">✓</span>}
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className={`text-sm font-medium ${isSelected ? 'text-app-accent' : 'text-slate-950'}`}>
                        {expert.name || <span className="text-app-nav-text italic">Unknown</span>}
                      </p>
                      {expert.department && (
                        <span className="text-xs bg-app-accent-bg text-slate-600 px-1.5 py-0.5 rounded">{expert.department}</span>
                      )}
                    </div>
                    <p className="text-xs text-app-nav-text mt-0.5">{expert.email}</p>
                    {expert.title && (
                      <p className="text-xs text-slate-500 mt-0.5 italic">{expert.title}</p>
                    )}
                    {(expert.skills ?? []).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {(expert.skills ?? []).map((skill: string) => (
                          <span key={skill} className="text-xs bg-app-accent-bg text-slate-600 px-3 py-1 rounded-full">
                            {skill}
                          </span>
                        ))}
                      </div>
                    )}
                    {(expert.topics ?? []).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {(expert.topics ?? []).slice(0, 6).map((topic: string) => (
                          <span key={topic} className="text-xs bg-app-nav-hover text-app-nav-text px-1.5 py-0.5 rounded">
                            {topic}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-2xl font-bold text-app-accent">{expert.tickets_resolved ?? 0}</p>
                  <p className="text-xs text-app-nav-text">tickets resolved</p>
                </div>
              </>
            )

            return compareMode ? (
              <button
                key={expert.id ?? expert.email}
                type="button"
                className={`w-full text-left px-5 py-4 flex items-start justify-between gap-4 cursor-pointer hover:bg-app-nav-hover/30 ${isSelected ? 'bg-app-nav-hover/40' : ''}`}
                onClick={() => toggleSelect(expert.id)}
              >
                {expertInfo}
              </button>
            ) : (
              <div
                key={expert.id ?? expert.email}
                className="px-5 py-4 flex items-start justify-between gap-4"
              >
                {expertInfo}
                <button
                  type="button"
                  onClick={() => setEditingUser(expert)}
                  className="mt-1 shrink-0 text-app-nav-text hover:text-app-accent transition-colors"
                  title="Edit profile"
                >
                  <PencilSquareIcon className="w-4 h-4" />
                </button>
              </div>
            )
          })}
        </div>
      )}

      {compareMode && compareData && selected.length === 2 && (
        <ExpertComparePanel
          data={compareData}
          onClose={() => setSelected([])}
        />
      )}
    </div>

      {editingUser && (
        <ExpertEditDrawer user={editingUser} allUsers={experts ?? []} onClose={() => setEditingUser(null)} />
      )}
      {creating && (
        <CreateExpertDrawer allUsers={experts ?? []} onClose={() => setCreating(false)} />
      )}
    </>
  )
}
