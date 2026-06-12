import { useState } from 'react'
import { ArrowUturnLeftIcon } from '@heroicons/react/24/outline'
import { EMPTY_FILTERS, type ImportTeamworkFilters } from './filters'

interface FiltersBarProps {
  filters: ImportTeamworkFilters
  onFiltersChange: (next: ImportTeamworkFilters) => void
  filterOptions?: { clients: string[]; agents: string[]; inboxes: string[] }
}

export function FiltersBar({ filters, onFiltersChange, filterOptions }: FiltersBarProps) {
  const [searchInput, setSearchInput] = useState(filters.search)

  const hasActiveFilter =
    Boolean(filters.client)
    || Boolean(filters.agent)
    || Boolean(filters.inbox)
    || Boolean(filters.search)
    || filters.mismatch_only
    || filters.unrouted_only

  const selectClass = (hasValue: boolean) =>
    `text-sm px-3 py-2 border border-app-border rounded-full focus:outline-none focus:border-slate-950/30 bg-app-panel ${hasValue ? 'text-slate-950' : 'text-app-nav-text'}`

  function reset() {
    onFiltersChange(EMPTY_FILTERS)
    setSearchInput('')
  }

  return (
    <div className="flex gap-4 mb-4">
      {/* Left half — four dropdowns */}
      <div className="flex gap-2 shrink-0">
        {([
          { key: 'client', label: 'All clients', options: filterOptions?.clients ?? [] },
          { key: 'agent',  label: 'All experts', options: filterOptions?.agents  ?? [] },
          { key: 'inbox',  label: 'All inboxes', options: filterOptions?.inboxes ?? [] },
        ] as const).map(({ key, label, options }) => (
          <select
            key={key}
            value={filters[key]}
            onChange={(e) => onFiltersChange({ ...filters, [key]: e.target.value })}
            className={selectClass(Boolean(filters[key]))}
          >
            <option value="">{label}</option>
            {options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        ))}
        <select
          value={filters.mismatch_only ? 'mismatch' : filters.unrouted_only ? 'unrouted' : ''}
          onChange={(e) =>
            onFiltersChange({
              ...filters,
              mismatch_only: e.target.value === 'mismatch',
              unrouted_only: e.target.value === 'unrouted',
            })
          }
          className={selectClass(filters.mismatch_only || filters.unrouted_only)}
        >
          <option value="">All routing</option>
          <option value="unrouted">Unrouted</option>
          <option value="mismatch">Wrong routing</option>
        </select>
      </div>

      {/* Right half — search + actions */}
      <form
        className="flex-1 flex items-center gap-2 min-w-0"
        onSubmit={(e) => {
          e.preventDefault()
          onFiltersChange({ ...filters, search: searchInput })
        }}
      >
        <input
          type="text"
          value={searchInput}
          onChange={(e) => {
            setSearchInput(e.target.value)
            if (e.target.value === '') onFiltersChange({ ...filters, search: '' })
          }}
          placeholder="Search by subject..."
          className="flex-1 text-sm px-4 py-2 border border-app-border rounded-full focus:outline-none focus:border-slate-950/30 text-slate-950 bg-app-panel placeholder-app-nav-text"
        />
        <button
          type="submit"
          className="shrink-0 px-6 py-2 text-sm bg-neutral-950 text-white rounded-full hover:bg-neutral-800 transition-colors"
        >
          Search
        </button>
        <button
          type="button"
          onClick={reset}
          disabled={!hasActiveFilter}
          title="Reset filters"
          className="shrink-0 p-2 border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ArrowUturnLeftIcon className="w-4 h-4" />
        </button>
      </form>
    </div>
  )
}
