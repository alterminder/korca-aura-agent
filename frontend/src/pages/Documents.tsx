import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CloudArrowUpIcon } from '@heroicons/react/24/outline'
import { useDocuments, useStats } from '../hooks/useDocuments'
import { useSearch } from '../hooks/useSearch'
import { DocumentList } from '../components/DocumentList'
import { PDFUploader } from '../components/PDFUploader'
import { SearchBar } from '../components/SearchBar'
import { Link } from 'react-router-dom'

const LIMIT = 20

function rawId(id: string) {
  return id.includes(':') ? id.split(':')[1] : id
}

export function Documents() {
  const [page, setPage] = useState(0)
  const [showUploader, setShowUploader] = useState(false)
  const queryClient = useQueryClient()
  const { data: documents, isLoading } = useDocuments(page * LIMIT, LIMIT)
  const { data: stats } = useStats()
  const { results, answer, loading, answerLoading, error, search } = useSearch()

  function handleUploaded() {
    queryClient.invalidateQueries({ queryKey: ['documents'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-950">Documents</h1>
          {stats?.documents != null && (
            <span className="text-sm font-medium px-2.5 py-0.5 rounded-full bg-app-nav-hover text-app-nav-text font-mono">
              {stats.documents}
            </span>
          )}
        </div>
        <button
          onClick={() => setShowUploader((v) => !v)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-normal border border-slate-950/30 text-slate-950 bg-transparent rounded-full hover:bg-slate-950/5 transition-colors"
        >
          <CloudArrowUpIcon className="w-4 h-4" />
          Upload
        </button>
      </div>

      {/* Uploader panel */}
      {showUploader && (
        <div className="bg-app-panel rounded-lg border border-app-border p-5">
          <p className="text-sm text-app-nav-text mb-4">
            Upload PDFs to extract, index, and make their content searchable.
          </p>
          <PDFUploader onUploaded={handleUploaded} />
        </div>
      )}

      {/* Document list */}
      {isLoading ? (
        <div className="text-center py-12 text-app-nav-text">Loading...</div>
      ) : (
        <>
          <DocumentList documents={documents ?? []} />
          <div className="flex justify-between">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="text-sm text-app-accent disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={(documents?.length ?? 0) < LIMIT}
              className="text-sm text-app-accent disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </>
      )}

      <section className="pt-4 border-t border-app-border space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Search Documents</h2>
          <p className="text-sm text-app-nav-text mt-1">
            Search PDF chunks and generate an answer from indexed document content.
          </p>
        </div>

        <div className="w-1/2">
          <SearchBar onSearch={search} loading={loading} placeholder="Search or ask a question..." />
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}

        {(answerLoading || answer) && (
          <div className="bg-app-accent-bg border border-app-accent/30 rounded-lg p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-sm font-semibold text-app-accent">AI Answer</span>
              {answerLoading && (
                <span className="text-xs text-app-nav-text animate-pulse">Generating...</span>
              )}
            </div>
            {answerLoading ? (
              <div className="space-y-2">
                <div className="h-4 bg-app-nav-hover rounded animate-pulse w-3/4" />
                <div className="h-4 bg-app-nav-hover rounded animate-pulse w-full" />
                <div className="h-4 bg-app-nav-hover rounded animate-pulse w-2/3" />
              </div>
            ) : answer ? (
              <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{answer.answer}</p>
            ) : null}
          </div>
        )}

        {results && (
          <div className="space-y-4">
            <p className="text-sm text-app-nav-text">
              {results.total} result{results.total !== 1 ? 's' : ''} for &ldquo;{results.query}&rdquo;
            </p>
            {results.results.map((r) => (
              <div key={r.chunk_id} className="bg-app-panel rounded-lg border border-app-border p-4">
                <div className="flex items-center justify-between mb-2">
                  <Link
                    to={`/documents/${rawId(r.document_id)}`}
                    className="text-sm font-medium text-app-accent hover:opacity-80"
                  >
                    View document
                  </Link>
                  <span className="text-xs text-app-nav-text">
                    {(r.score * 100).toFixed(1)}% match
                  </span>
                </div>
                <p className="text-sm text-slate-700 line-clamp-4">{r.content}</p>
              </div>
            ))}
            {results.results.length === 0 && (
              <p className="text-center text-app-nav-text py-8">No results found. Try a different query.</p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
