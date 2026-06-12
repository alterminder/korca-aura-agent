import type { KeyboardEvent } from 'react'

export const MAX_SKILLS = 27

export function SkillPills({
  skills,
  skillInput,
  onSkillInputChange,
  onSkillInputKeyDown,
  onRemove,
  generating,
  onGenerate,
  showGenerate,
}: {
  skills: string[]
  skillInput: string
  onSkillInputChange: (v: string) => void
  onSkillInputKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void
  onRemove: (i: number) => void
  generating: boolean
  onGenerate: () => void
  showGenerate: boolean
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label htmlFor="skill-input" className="block text-xs text-app-nav-text">Skills</label>
        <span className="text-xs text-app-nav-text">{skills.length}/{MAX_SKILLS}</span>
      </div>
      <div className="min-h-[42px] w-full border border-app-border rounded-lg px-2 py-1.5 flex flex-wrap gap-1 focus-within:ring-2 focus-within:ring-app-accent bg-app-bg">
        {skills.map((skill, i) => (
          <span key={i} className="inline-flex items-center gap-1 text-xs bg-app-accent-bg text-slate-600 px-3 py-1 rounded-full">
            {skill}
            <button type="button" onClick={() => onRemove(i)} className="text-slate-400 hover:text-slate-600 leading-none">&times;</button>
          </span>
        ))}
        {skills.length < MAX_SKILLS && (
          <input
            id="skill-input"
            type="text"
            value={skillInput}
            onChange={e => onSkillInputChange(e.target.value)}
            onKeyDown={onSkillInputKeyDown}
            placeholder={skills.length === 0 ? 'Type skill, press Space or ,' : ''}
            className="flex-1 min-w-[120px] text-sm outline-none bg-transparent py-0.5 text-slate-950 placeholder-app-nav-text"
          />
        )}
      </div>
      <div className="flex items-center justify-between mt-1">
        <p className="text-xs text-app-nav-text">Space or , to add</p>
        {showGenerate && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="text-xs text-app-accent hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? 'Generating…' : '✦ Generate skill cloud'}
          </button>
        )}
      </div>
    </div>
  )
}
