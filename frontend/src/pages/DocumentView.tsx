import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { TrashIcon } from '@heroicons/react/24/outline'
import { useDocument, useDeleteDocument } from '../hooks/useDocuments'
import { DocumentDetail } from '../components/DocumentDetail'

export function DocumentView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: document, isLoading, error } = useDocument(id ?? '')
  const deleteMutation = useDeleteDocument()

  const handleDelete = async () => {
    if (!id || !window.confirm('Delete this document?')) return
    await deleteMutation.mutateAsync(id)
    toast.success('Document deleted')
    navigate('/documents')
  }

  if (isLoading) {
    return <div className="text-center py-12 text-app-nav-text">Loading...</div>
  }
  if (error || !document) {
    return <div className="text-center py-12 text-red-400">Document not found</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-app-nav-text hover:text-slate-950"
        >
          ← Back
        </button>
        <button
          onClick={handleDelete}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-normal bg-neutral-950 text-white rounded-full hover:bg-neutral-800 disabled:opacity-50 transition-colors"
          disabled={deleteMutation.isPending}
        >
          <TrashIcon className="h-4 w-4" />
          Delete document
        </button>
      </div>
      <DocumentDetail document={document} />
    </div>
  )
}
