import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import type { Document } from '../types'

const STATUS_STYLE: Record<Document['status'], string> = {
  pending:    'bg-app-nav-hover text-slate-600',
  processing: 'bg-yellow-900/30 text-yellow-400',
  completed:  'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  failed:     'bg-red-900/30 text-red-400',
}

function rawId(id: string) {
  return id.includes(':') ? id.split(':')[1] : id
}

export function DocumentList({ documents }: { documents: Document[] }) {
  if (documents.length === 0) {
    return (
      <div className="text-center py-12 text-app-nav-text">
        No documents yet. Upload a PDF to get started.
      </div>
    )
  }

  return (
    <ul className="grid grid-cols-6 gap-5">
      {documents.map((doc) => (
        <li key={doc.id} className="bg-app-panel rounded-lg border border-app-border hover:bg-app-nav-hover transition-colors">
          <Link to={`/documents/${rawId(doc.id)}`} className="block p-4">
            <div className="flex items-start justify-between gap-1 mb-2">
              <p className="text-sm font-medium text-slate-950 line-clamp-2 leading-snug">{doc.title}</p>
              {doc.status !== 'completed' && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-normal shrink-0 ${STATUS_STYLE[doc.status]}`}>
                  {doc.status}
                </span>
              )}
            </div>
            <p className="text-xs text-app-nav-text">{formatDistanceToNow(new Date(doc.created_at), { addSuffix: true })}</p>
            {(doc.experts ?? []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {(doc.experts ?? []).map((expert) => (
                  <span key={expert.email} className="text-xs text-app-nav-text bg-app-accent-bg px-1.5 py-0.5 rounded-full">
                    {expert.name}
                  </span>
                ))}
              </div>
            )}
          </Link>
        </li>
      ))}
    </ul>
  )
}
