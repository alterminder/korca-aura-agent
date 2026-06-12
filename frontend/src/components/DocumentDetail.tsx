import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Document, User } from '../types'

function rawId(id: string) {
  return id.includes(':') ? id.split(':')[1] : id
}

export function DocumentDetail({ document: doc }: { document: Document }) {
  const docId = rawId(doc.id)
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const expertsQuery = useQuery({
    queryKey: ['document-experts', docId],
    queryFn: () => api.documents.experts(docId),
  })
  const experts = expertsQuery.data ?? []

  // Users are only needed once the assign dropdown opens; shares the ['users'] cache.
  const usersQuery = useQuery({
    queryKey: ['users'],
    queryFn: api.users.list,
    enabled: dropdownOpen,
  })
  const allUsers: User[] = usersQuery.data ?? []

  const invalidateExperts = () => {
    queryClient.invalidateQueries({ queryKey: ['document-experts', docId] })
    queryClient.invalidateQueries({ queryKey: ['documents'] })
  }

  const assignMutation = useMutation({
    mutationFn: (email: string) => api.documents.addExpert(docId, email),
    onSuccess: invalidateExperts,
  })
  const removeMutation = useMutation({
    mutationFn: (email: string) => api.documents.removeExpert(docId, email),
    onSuccess: invalidateExperts,
  })

  useEffect(() => {
    if (!dropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [dropdownOpen])

  const openDropdown = () => {
    setDropdownOpen(true)
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  const assign = (email: string) => {
    assignMutation.mutate(email)
    setSearch('')
    setDropdownOpen(false)
  }

  const remove = (email: string) => {
    removeMutation.mutate(email)
  }

  const assignedEmails = new Set(experts.map(e => e.email))
  const filtered = allUsers.filter(
    u =>
      !assignedEmails.has(u.email) &&
      (u.name.toLowerCase().includes(search.toLowerCase()) ||
        u.email.toLowerCase().includes(search.toLowerCase())),
  )

  return (
    <div className="space-y-6">
      <div className="bg-app-panel rounded-lg border border-app-border p-6">
        <h1 className="text-2xl font-bold text-slate-950">{doc.title}</h1>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div><dt className="font-medium text-app-nav-text">File</dt><dd className="text-slate-950">{doc.filename}</dd></div>
          <div><dt className="font-medium text-app-nav-text">Pages</dt><dd className="text-slate-950">{doc.page_count}</dd></div>
          <div><dt className="font-medium text-app-nav-text">Chunks</dt><dd className="text-slate-950">{doc.chunk_count}</dd></div>
          <div>
            <dt className="font-medium text-app-nav-text">Uploaded</dt>
            <dd className="text-slate-950">{formatDistanceToNow(new Date(doc.created_at), { addSuffix: true })}</dd>
          </div>
          {doc.author_email && (
            <div><dt className="font-medium text-app-nav-text">Author</dt><dd className="text-slate-950">{doc.author_email}</dd></div>
          )}
        </dl>
        {(doc.tags ?? []).length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1">
            {(doc.tags ?? []).map((tag) => (
              <span key={tag} className="text-xs bg-app-accent-bg text-slate-600 px-3 py-1 rounded-full">
                {tag}
              </span>
            ))}
          </div>
        )}
        <div className="mt-4">
          <a
            href={`/api/documents/${rawId(doc.id)}/download`}
            className="text-sm text-app-accent hover:opacity-80 font-medium"
          >
            Download original PDF
          </a>
        </div>
      </div>

      <div className="bg-app-panel rounded-lg border border-app-border p-6">
        <h2 className="text-lg font-semibold text-slate-950 mb-3">Designated Experts</h2>

        <div className="flex flex-wrap items-center gap-2">
          {experts.map(expert => (
            <span
              key={expert.email}
              className="inline-flex items-center gap-1.5 rounded-full border border-app-border px-3 py-2 bg-app-accent-bg text-sm"
            >
              <span className="font-normal text-slate-950">{expert.name}</span>
              <button
                onClick={() => remove(expert.email)}
                className="text-app-nav-text hover:text-slate-950 leading-none"
                aria-label={`Remove ${expert.name}`}
              >
                ×
              </button>
            </span>
          ))}

          <div className="relative" ref={dropdownRef}>
            {dropdownOpen ? (
              <div>
                <input
                  ref={searchRef}
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  onKeyDown={e => e.key === 'Escape' && (setDropdownOpen(false), setSearch(''))}
                  placeholder="Search by name or email…"
                  className="rounded-full border border-slate-950/30 px-4 py-1.5 text-sm text-slate-950 bg-white focus:outline-none focus:ring-1 focus:ring-slate-950/30 w-56"
                />
                {filtered.length > 0 && (
                  <div className="absolute z-10 mt-1 left-0 w-64 bg-app-panel border border-app-border rounded-2xl shadow-lg overflow-hidden">
                    {filtered.slice(0, 8).map(user => (
                      <button
                        key={user.email}
                        onClick={() => assign(user.email)}
                        className="w-full text-left px-4 py-2.5 hover:bg-app-accent-bg transition-colors"
                      >
                        <p className="text-sm font-medium text-slate-950">{user.name}</p>
                        <p className="text-xs text-app-nav-text">{user.email}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={openDropdown}
                className="rounded-full bg-neutral-950 text-white hover:bg-neutral-800 transition-colors duration-150 px-3 py-2 text-sm font-normal"
              >
                + Assign Expert
              </button>
            )}
          </div>
        </div>
      </div>

      {doc.chunks && doc.chunks.length > 0 && (
        <div className="bg-app-panel rounded-lg border border-app-border p-6">
          <h2 className="text-lg font-semibold text-slate-950 mb-4">
            Content Chunks ({doc.chunks.length})
          </h2>
          <div className="space-y-3">
            {doc.chunks.slice(0, 10).map((chunk) => (
              <div key={chunk.id} className="border border-app-border rounded p-3">
                <p className="text-xs text-app-nav-text mb-1">Chunk {chunk.chunk_index + 1}</p>
                <p className="text-sm text-slate-700 line-clamp-3">{chunk.content}</p>
              </div>
            ))}
            {doc.chunks.length > 10 && (
              <p className="text-sm text-app-nav-text text-center">
                +{doc.chunks.length - 10} more chunks
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
