interface AgentPromptEditorProps {
  value: string
  onChange: (value: string) => void
  canSave: boolean
  isSaving: boolean
  onSave: () => void
}

export function AgentPromptEditor({ value, onChange, canSave, isSaving, onSave }: AgentPromptEditorProps) {
  return (
    <section className="bg-app-panel border border-app-border rounded-lg p-5">
      <h3 className="text-base font-semibold text-slate-950 mb-3">Main Prompt</h3>
      <textarea
        value={value}
        onChange={event => onChange(event.target.value)}
        className="w-full min-h-[32rem] resize-y rounded-md bg-slate-50 border border-app-border p-4 text-xs leading-5 text-slate-700 whitespace-pre-wrap outline-none focus:border-app-accent"
        spellCheck={false}
      />
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            canSave
              ? 'bg-app-accent text-white hover:bg-app-accent/90'
              : 'bg-app-nav-hover text-app-nav-text cursor-not-allowed'
          }`}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </section>
  )
}
