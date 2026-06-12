import { XMarkIcon } from '@heroicons/react/24/outline'
import type { ExpertComparison } from '../../types'

function ClientBar({ count, max, color }: { count: number; max: number; color: 'a' | 'b' }) {
  const pct = max > 0 ? Math.max(4, Math.round((count / max) * 100)) : 4
  return (
    <div className="flex items-center gap-1.5">
      <div
        className={`h-2 rounded-full ${color === 'a' ? 'bg-app-accent' : 'bg-purple-500'}`}
        style={{ width: `${pct}%`, minWidth: '4px', maxWidth: '80px' }}
      />
      <span className="text-xs text-app-nav-text tabular-nums">{count}</span>
    </div>
  )
}

function clientName(name: string | null) {
  return name || 'Unknown client'
}

export function ExpertComparePanel({ data, onClose }: { data: ExpertComparison; onClose: () => void }) {
  const maxShared = Math.max(...data.shared_clients.map(c => Math.max(c.count_a, c.count_b)), 1)
  const maxA = Math.max(...data.only_a_clients.map(c => c.count), 1)
  const maxB = Math.max(...data.only_b_clients.map(c => c.count), 1)

  const hasSkills = data.shared_skills.length + data.only_a_skills.length + data.only_b_skills.length > 0

  return (
    <div className="bg-app-panel border border-app-border rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-app-border">
        <div className="flex items-center gap-3 text-sm font-medium">
          <span className="text-app-accent">{data.expert_a.name}</span>
          <span className="text-app-nav-text">vs</span>
          <span className="text-purple-400">{data.expert_b.name}</span>
        </div>
        <button onClick={onClose} className="text-app-nav-text hover:text-slate-950">
          <XMarkIcon className="w-4 h-4" />
        </button>
      </div>

      {/* Three-column client grid */}
      <div className="grid grid-cols-3 divide-x divide-app-border">
        {/* Only A */}
        <div className="px-4 py-3">
          <p className="text-xs font-medium text-app-accent mb-2">
            Only {data.expert_a.name.split(' ')[0]} ({data.only_a_clients.length})
          </p>
          {data.only_a_clients.length === 0 ? (
            <p className="text-xs text-app-nav-text italic">None</p>
          ) : (
            <div className="space-y-1.5">
              {data.only_a_clients.map((c, index) => (
                <div key={`${clientName(c.name)}-${index}`} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-slate-950 truncate">{clientName(c.name)}</span>
                  <ClientBar count={c.count} max={maxA} color="a" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Shared */}
        <div className="px-4 py-3">
          <p className="text-xs font-medium text-slate-950 mb-2">
            Shared clients ({data.shared_clients.length})
          </p>
          {data.shared_clients.length === 0 ? (
            <p className="text-xs text-app-nav-text italic">No shared clients</p>
          ) : (
            <div className="space-y-2">
              {data.shared_clients.map((c, index) => (
                <div key={`${clientName(c.name)}-${index}`}>
                  <p className="text-xs text-slate-950 truncate mb-0.5">{clientName(c.name)}</p>
                  <div className="space-y-0.5">
                    <ClientBar count={c.count_a} max={maxShared} color="a" />
                    <ClientBar count={c.count_b} max={maxShared} color="b" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Only B */}
        <div className="px-4 py-3">
          <p className="text-xs font-medium text-purple-400 mb-2">
            Only {data.expert_b.name.split(' ')[0]} ({data.only_b_clients.length})
          </p>
          {data.only_b_clients.length === 0 ? (
            <p className="text-xs text-app-nav-text italic">None</p>
          ) : (
            <div className="space-y-1.5">
              {data.only_b_clients.map((c, index) => (
                <div key={`${clientName(c.name)}-${index}`} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-slate-950 truncate">{clientName(c.name)}</span>
                  <ClientBar count={c.count} max={maxB} color="b" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Skills */}
      {hasSkills && (
        <div className="px-5 py-3 border-t border-app-border">
          <p className="text-xs font-medium text-app-nav-text mb-2">Skills</p>
          <div className="flex flex-wrap gap-1.5">
            {data.only_a_skills.map(s => (
              <span key={s} className="text-xs bg-white text-app-accent border border-app-accent px-2 py-0.5 rounded-full">
                {s}
              </span>
            ))}
            {data.shared_skills.map(s => (
              <span key={s} className="text-xs bg-white text-emerald-500 border border-emerald-500 px-2 py-0.5 rounded-full">
                {s}
              </span>
            ))}
            {data.only_b_skills.map(s => (
              <span key={s} className="text-xs bg-white text-purple-500 border border-purple-500 px-2 py-0.5 rounded-full">
                {s}
              </span>
            ))}
          </div>
          <div className="flex gap-4 mt-2">
            <span className="text-xs text-app-nav-text">
              <span className="inline-block w-2 h-2 rounded-full bg-app-accent mr-1" />{data.expert_a.name.split(' ')[0]} only
            </span>
            <span className="text-xs text-app-nav-text">
              <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1" />shared
            </span>
            <span className="text-xs text-app-nav-text">
              <span className="inline-block w-2 h-2 rounded-full bg-purple-500 mr-1" />{data.expert_b.name.split(' ')[0]} only
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
