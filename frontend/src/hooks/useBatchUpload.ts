import { useCallback, useState } from 'react'
import { api } from '../api/client'
import type { DocumentStatusEvent } from '../types'

export type BatchUploadItemStatus = 'queued' | 'uploading' | 'processing' | 'completed' | 'failed'
export type BatchUploadStatus = 'idle' | 'running' | 'completed'

export interface BatchUploadItem {
  id: string
  fileName: string
  fileSize: number
  status: BatchUploadItemStatus
  progress: number
  message: string | null
  documentId: string | null
}

export interface BatchUploadState {
  status: BatchUploadStatus
  items: BatchUploadItem[]
}

function itemId(file: File, index: number) {
  return `${file.name}-${file.size}-${file.lastModified}-${index}`
}

function rawId(id: string) {
  return id.includes(':') ? id.split(':')[1] : id
}

function waitForDocumentStatus(documentId: string, onEvent: (event: DocumentStatusEvent) => void) {
  return new Promise<DocumentStatusEvent>((resolve) => {
    const es = new EventSource(`/api/documents/${rawId(documentId)}/status`)

    es.onmessage = (e: MessageEvent<string>) => {
      const event = JSON.parse(e.data) as DocumentStatusEvent
      onEvent(event)
      if (event.status === 'completed' || event.status === 'failed') {
        es.close()
        resolve(event)
      }
    }

    es.onerror = () => {
      es.close()
      resolve({
        id: documentId,
        status: 'failed',
        progress: 0,
        message: 'Connection lost while waiting for processing status',
      })
    }
  })
}

export function useBatchUpload({ onFileCompleted }: { onFileCompleted?: () => void } = {}) {
  const [state, setState] = useState<BatchUploadState>({ status: 'idle', items: [] })

  const updateItem = useCallback((id: string, patch: Partial<BatchUploadItem>) => {
    setState((current) => ({
      ...current,
      items: current.items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    }))
  }, [])

  const uploadFiles = useCallback(
    async (files: File[], authorEmail?: string, tags?: string) => {
      if (files.length === 0) return

      const items = files.map((file, index) => ({
        id: itemId(file, index),
        fileName: file.name,
        fileSize: file.size,
        status: 'queued' as const,
        progress: 0,
        message: null,
        documentId: null,
      }))
      setState({ status: 'running', items })

      for (const [index, file] of files.entries()) {
        const id = items[index].id
        updateItem(id, { status: 'uploading', progress: 5, message: 'Uploading...' })

        try {
          const data = await api.documents.upload(file, authorEmail, tags)
          updateItem(id, {
            status: data.status === 'completed' || data.status === 'failed' ? data.status : 'processing',
            progress: data.status === 'completed' ? 100 : data.status === 'failed' ? 0 : 10,
            message: data.message,
            documentId: data.id,
          })

          if (data.status === 'completed' || data.status === 'failed') {
            if (data.status === 'completed') onFileCompleted?.()
            continue
          }

          const event = await waitForDocumentStatus(data.id, (evt) => {
            updateItem(id, {
              status: evt.status === 'pending' ? 'processing' : evt.status,
              progress: evt.progress,
              message: evt.message,
              documentId: data.id,
            })
          })
          if (event.status === 'completed') onFileCompleted?.()
        } catch (err) {
          updateItem(id, {
            status: 'failed',
            progress: 0,
            message: err instanceof Error ? err.message : 'Upload failed',
          })
        }
      }

      setState((current) => ({ ...current, status: 'completed' }))
    },
    [onFileCompleted, updateItem]
  )

  const reset = useCallback(() => {
    setState({ status: 'idle', items: [] })
  }, [])

  return { state, uploadFiles, reset }
}
