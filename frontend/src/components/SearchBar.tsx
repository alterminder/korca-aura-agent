import { useState, type FormEvent } from 'react'

interface Props {
  onSearch: (query: string) => void
  loading?: boolean
  placeholder?: string
}

export function SearchBar({ onSearch, loading = false, placeholder = 'Search documents...' }: Props) {
  const [value, setValue] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (value.trim()) onSearch(value.trim())
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        className="flex-1 rounded-full border border-app-border bg-app-panel text-slate-950 placeholder-app-nav-text px-4 py-2 text-sm focus:outline-none focus:border-slate-950/30"
      />
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className="shrink-0 px-6 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? 'Searching...' : 'Search'}
      </button>
    </form>
  )
}
