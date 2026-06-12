import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  CheckCircleIcon,
  CloudArrowUpIcon,
  DocumentIcon,
  ExclamationCircleIcon,
} from '@heroicons/react/24/outline'
import { useBatchUpload, type BatchUploadItem, type BatchUploadItemStatus } from '../hooks/useBatchUpload'

const STATUS_COLORS = {
  queued:     'text-app-nav-text',
  uploading:  'text-blue-400',
  processing: 'text-yellow-400',
  completed:  'text-green-400',
  failed:     'text-red-400',
} as const

const STATUS_LABELS = {
  queued:     'Queued',
  uploading:  'Uploading...',
  processing: 'Processing document...',
  completed:  'Document processed!',
  failed:     'Processing failed',
} as const

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function batchSummary(items: BatchUploadItem[]) {
  const completed = items.filter((item) => item.status === 'completed').length
  const failed = items.filter((item) => item.status === 'failed').length
  if (items.length === 0) return ''
  if (completed + failed === items.length) {
    return `${completed} completed${failed ? `, ${failed} failed` : ''}`
  }
  return `${completed} of ${items.length} completed`
}

function statusIcon(status: BatchUploadItemStatus) {
  if (status === 'completed') return <CheckCircleIcon className="h-5 w-5 text-green-400" />
  if (status === 'failed') return <ExclamationCircleIcon className="h-5 w-5 text-red-400" />
  return <DocumentIcon className="h-5 w-5 text-app-nav-text" />
}

export function PDFUploader({ onUploaded }: { onUploaded?: () => void } = {}) {
  const { state, uploadFiles, reset } = useBatchUpload({ onFileCompleted: onUploaded })

  const onDrop = useCallback(
    (files: File[]) => { void uploadFiles(files) },
    [uploadFiles]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    maxFiles: 20,
    maxSize: 50 * 1024 * 1024,
    disabled: state.status === 'running',
  })

  if (state.status !== 'idle') {
    return (
      <div className="border border-app-border rounded-lg bg-app-panel">
        <div className="flex items-center justify-between gap-4 border-b border-app-border px-4 py-3">
          <div>
            <p className="text-sm font-semibold text-slate-950">Upload batch</p>
            <p className="mt-0.5 text-xs text-app-nav-text">{batchSummary(state.items)}</p>
          </div>
          {state.status === 'completed' && (
            <button
              onClick={reset}
              className="text-sm font-medium text-app-accent hover:opacity-80"
            >
              Upload another batch
            </button>
          )}
        </div>

        <div className="divide-y divide-app-border">
          {state.items.map((item) => (
            <div key={item.id} className="px-4 py-3">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-5 w-5 shrink-0">{statusIcon(item.status)}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <p className="truncate text-sm font-medium text-slate-950">{item.fileName}</p>
                    <span className={`text-xs font-medium ${STATUS_COLORS[item.status]}`}>
                      {STATUS_LABELS[item.status]}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-app-nav-text">
                    <span>{formatFileSize(item.fileSize)}</span>
                    {item.message && <span className="min-w-0 truncate">{item.message}</span>}
                  </div>
                  {(item.status === 'uploading' || item.status === 'processing') && (
                    <div className="mt-3 h-2 w-full rounded-full bg-app-nav-hover">
                      <div
                        className="h-2 rounded-full bg-app-accent transition-all duration-500"
                        style={{ width: `${item.progress}%` }}
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        {state.status === 'running' && (
          <p className="border-t border-app-border px-4 py-3 text-xs text-app-nav-text">
            Files are uploaded one at a time so OCR and Gemini processing stay stable.
          </p>
        )}
      </div>
    )
  }

  return (
    <div
      {...getRootProps()}
      className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-colors bg-app-panel ${
        isDragActive ? 'border-app-accent bg-app-accent-bg' : 'border-app-border hover:border-app-accent/50'
      }`}
    >
      <input {...getInputProps()} />
      <CloudArrowUpIcon className="mx-auto h-12 w-12 text-app-nav-text" />
      <p className="mt-2 text-sm text-slate-600">
        {isDragActive ? 'Drop PDFs here...' : 'Drop PDFs here or click to browse'}
      </p>
      <p className="mt-1 text-xs text-app-nav-text">Up to 20 PDFs, 50MB each</p>
    </div>
  )
}
